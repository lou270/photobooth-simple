#!/bin/bash
# Simple PhotoBooth - installation
#
#     ./install.sh                                   interactive, then saves the answers
#     ./install.sh --profile setup/booth.conf --yes  unattended, from a saved profile
#     ./install.sh --profile setup/booth.conf --dry-run
#
# Safe to re-run: every host file is written through a delimited managed block
# or a rendered template, so a second pass changes nothing rather than
# appending a second copy of the same overlay.
#
# What gets installed is decided by setup/booth.conf, not by which board this
# is. A step is skipped only when the host genuinely cannot do it - no firmware
# config to edit, no SPI bus, no systemd - which is why a mini PC gets its
# printer and its autostart just like a Pi does.
#
# The network is not installed here: guests reach the booth over a network it
# joins, like any other machine. See INSTALLATION.md.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHOTOBOOTH_DIR="$SCRIPT_DIR"
SETUP_DIR="$SCRIPT_DIR/setup"
TEMPLATES="$SETUP_DIR/templates"
VENV_DIR="$PHOTOBOOTH_DIR/.venv"

# shellcheck source=setup/lib.sh
source "$SETUP_DIR/lib.sh"

# ---------------------------------------------------------------------------
# Profile: 'ask' means the question has not been answered yet
# ---------------------------------------------------------------------------

KIOSK=ask
SCREEN=ask
CAMERA_PICAMERA=ask
CAMERA_DSLR=ask
GPHOTO2_UPDATER=no
GPHOTO2_UPDATER_REF=""
PRINTER_SETUP=ask
PRINTER_URI=""
PRINTER_PPD="doc/DS620.ppd"
LED_RING=ask
AUTOSTART=ask
BOOT_SPLASH=ask

PROFILE=""
ASSUME_YES=false
NEED_REBOOT=false

usage() {
    sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
    case "$1" in
        --profile)
            PROFILE="${2:?--profile needs a file}"
            shift
            ;;
        --profile=*) PROFILE="${1#*=}" ;;
        -y|--yes)    ASSUME_YES=true ;;
        --dry-run)   DRY_RUN=true ;;
        -h|--help)   usage; exit 0 ;;
        *) print_error "Unknown option: $1"; usage; exit 2 ;;
    esac
    shift
done

echo ""
echo "  Simple PhotoBooth - installation"
echo ""

if [ "$(id -u)" -eq 0 ]; then
    print_error "Do not run this script as root."
    print_info "It calls sudo for the few steps that need it, and the application must not end up owned by root."
    exit 1
fi

if [ -n "$PROFILE" ]; then
    if [ ! -f "$PROFILE" ]; then
        print_error "Profile not found: $PROFILE"
        exit 1
    fi
    # shellcheck source=/dev/null
    source "$PROFILE"
    print_info "Profile: $PROFILE"
elif [ -f "$SETUP_DIR/booth.conf" ]; then
    # shellcheck source=/dev/null
    source "$SETUP_DIR/booth.conf"
    print_info "Profile: setup/booth.conf (found automatically)"
    # Loaded silently, the answers of an earlier run left a plain ./install.sh
    # with no question to ask, and no way to change one short of editing the
    # file. Run interactively, it shows them and offers to answer again; the
    # values it never asks about (PRINTER_URI, PRINTER_PPD, GPHOTO2_*) are kept.
    if [ "$ASSUME_YES" != "true" ]; then
        echo ""
        grep -E '^(KIOSK|SCREEN|CAMERA_PICAMERA|CAMERA_DSLR|PRINTER_SETUP|LED_RING|AUTOSTART|BOOT_SPLASH)=' \
            "$SETUP_DIR/booth.conf" | sed 's/^/    /'
        echo ""
        if ! ask_yes_no "Reuse these answers?"; then
            for var in KIOSK SCREEN CAMERA_PICAMERA CAMERA_DSLR PRINTER_SETUP LED_RING AUTOSTART BOOT_SPLASH; do
                printf -v "$var" 'ask'
            done
        fi
    fi
fi

is_dry_run && print_warning "Dry run: nothing will be modified."

# ---------------------------------------------------------------------------
# Questions - only the ones the profile left unanswered
# ---------------------------------------------------------------------------

resolve_unanswered() {
    local var
    for var in KIOSK SCREEN CAMERA_PICAMERA CAMERA_DSLR PRINTER_SETUP LED_RING AUTOSTART BOOT_SPLASH; do
        if [ "${!var}" = "ask" ]; then
            printf -v "$var" 'no'
        fi
    done
}

if [ "$ASSUME_YES" = "true" ]; then
    # Unanswered means "not on this booth". Anything else would install
    # hardware support nobody asked for on an unattended run.
    resolve_unanswered
else
    ask_yes_no_var KIOSK "Enable kiosk mode (hide cursor, taskbar, media dialog)?"
    if [ "$SCREEN" = "ask" ]; then
        if ask_yes_no "Are you using the Ingcool 7\" (1024x600) touchscreen?"; then
            SCREEN=ingcool7
        else
            SCREEN=none
        fi
    fi
    ask_yes_no_var CAMERA_PICAMERA "Use the Raspberry Pi Camera Module V3?"
    ask_yes_no_var CAMERA_DSLR "Use a DSLR over USB (gPhoto2)?"
    ask_yes_no_var PRINTER_SETUP "Install printer support (CUPS)?"
    ask_yes_no_var LED_RING "Use a WS2812 LED ring on SPI?"
    ask_yes_no_var AUTOSTART "Start the booth on boot, alone on the screen (the desktop is no longer started)?"
    ask_yes_no_var BOOT_SPLASH "Show the welcome picture instead of boot messages while the booth starts?"
fi

# ---------------------------------------------------------------------------
# Step 1 - base packages
# ---------------------------------------------------------------------------

print_info "Step 1/8: base system packages"

# gettext-base carries envsubst, which renders every template below. libgl1 is
# what the pip builds of Kivy and OpenCV load at import. Only names that exist
# unchanged from Bookworm to Trixie: apt_ensure stops the whole install on a
# package the release no longer has.
apt_ensure gcc make build-essential git curl \
    ffmpeg libgl1 \
    python3-pip python3-venv gettext-base

# ---------------------------------------------------------------------------
# Step 2 - Python environment
# ---------------------------------------------------------------------------

print_info "Step 2/8: Python environment"

# A virtual environment rather than pip --break-system-packages: the booth gets
# its own dependency set instead of overwriting Debian's, which is what makes
# the install repeatable and reversible. --system-site-packages is required,
# not cosmetic: picamera2, libcamera and python3-cups are apt packages with no
# working pip equivalent, and libs/device_utils.py imports them by name.
if [ ! -d "$VENV_DIR" ]; then
    run python3 -m venv --system-site-packages "$VENV_DIR"
    is_dry_run || print_success "Created .venv"
else
    print_skip ".venv already exists"
fi

VENV_PYTHON="$VENV_DIR/bin/python"
if [ -x "$VENV_PYTHON" ]; then
    PHOTOBOOTH_PYTHON="$VENV_PYTHON"
else
    # Dry run, or a venv that has not been created yet.
    PHOTOBOOTH_PYTHON="python3"
fi
export PHOTOBOOTH_PYTHON PHOTOBOOTH_DIR

run "$PHOTOBOOTH_PYTHON" -m pip install --upgrade pip
run "$PHOTOBOOTH_PYTHON" -m pip install -r "$PHOTOBOOTH_DIR/requirements.txt"

# ---------------------------------------------------------------------------
# Step 3 - config.ini
# ---------------------------------------------------------------------------

print_info "Step 3/8: application configuration"

# config.ini holds the admin password and is deliberately not in the repository.
# Without it the application refuses to start.
if [ ! -f "$PHOTOBOOTH_DIR/config.ini" ]; then
    run cp "$PHOTOBOOTH_DIR/config.ini.example" "$PHOTOBOOTH_DIR/config.ini"
    is_dry_run || print_success "Created config.ini from config.ini.example"
else
    print_skip "Keeping the existing config.ini"
fi

# An unset admin password leaves the admin pages disabled, and a booth built
# unattended would never be told. Generate one and say so, once.
if ! is_dry_run && [ -f "$PHOTOBOOTH_DIR/config.ini" ]; then
    if [ -z "$(booth_config ADMIN_PASSWORD)" ]; then
        GENERATED_PASSWORD="$(LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 16)"
        sed -i "s/^ADMIN_PASSWORD *=.*/ADMIN_PASSWORD = ${GENERATED_PASSWORD}/" "$PHOTOBOOTH_DIR/config.ini"
        print_success "Generated an admin password: ${GENERATED_PASSWORD}"
        print_warning "Write it down now - it is stored only in config.ini."
    else
        print_skip "Admin password already set"
    fi
fi

# config.ini.example describes a full booth: fullscreen off for development, a
# DS620 and a ring light expected. Left as it is, a kiosk booth came up in a
# window, and one without a printer or a ring was reported broken by the
# doctor and showed guests a print button that could only fail. The answers
# above are the truth about this hardware, so they win on these three settings
# and only in that direction: a printer added by hand is never switched off.
if enabled "$KIOSK"; then
    config_ini_set FULLSCREEN True
fi
if ! enabled "$PRINTER_SETUP"; then
    config_ini_set PRINTER None
fi
if ! enabled "$LED_RING"; then
    config_ini_set RINGLED False
fi

# ---------------------------------------------------------------------------
# Step 4 - kiosk mode
# ---------------------------------------------------------------------------

print_info "Step 4/8: kiosk mode"

if enabled "$KIOSK"; then
    if has_wayfire; then
        # Already commented out on a second run, so the match no longer fires.
        run sudo sed -i '/^[^#].*wfrespawn wf-panel-pi/ s/^/# /' /etc/wayfire/defaults.ini
        if ! sudo grep -q '^background *= *wf-background' /etc/wayfire/defaults.ini; then
            run sudo sed -i '/^\[autostart\]/a background = wf-background' /etc/wayfire/defaults.ini
        else
            print_skip "Wayfire background already configured"
        fi
        print_success "Wayfire panel hidden"
    fi
    if has_labwc; then
        # Commented rather than deleted, and already commented on a second run.
        for labwc_autostart in /etc/xdg/labwc/autostart "$HOME/.config/labwc/autostart"; do
            [ -f "$labwc_autostart" ] || continue
            as_owner=()
            case "$labwc_autostart" in
                /etc/*) as_owner=(sudo) ;;
            esac
            run "${as_owner[@]}" sed -i '/^[^#].*wf-panel-pi/ s/^/# /' "$labwc_autostart"
        done
        print_success "labwc panel hidden"
    fi
    if ! has_wayfire && ! has_labwc; then
        print_skip "Neither Wayfire nor labwc installed; leaving the desktop alone"
    fi

    if has_boot_config; then
        boot_config_block "kiosk" <<'KIOSK_BLOCK'
# Suppress the low-voltage warning overlay, which would otherwise draw over the
# booth's own fullscreen interface during an event.
avoid_warnings=1
KIOSK_BLOCK
        NEED_REBOOT=true
    fi

    if dpkg-query -W -f='${Status}' lxplug-ptbatt 2>/dev/null | grep -q '^install ok installed$'; then
        run sudo apt-get remove -y lxplug-ptbatt
    fi

    # Stop the file manager offering to open every USB stick guests plug in:
    # libs/usb_transfer.py copies to them on its own.
    for pcmanfm in /etc/xdg/pcmanfm/LXDE-pi/pcmanfm.conf /etc/xdg/pcmanfm/default/pcmanfm.conf; do
        if [ -f "$pcmanfm" ]; then
            run sudo sed -i 's/autorun=1/autorun=0/g' "$pcmanfm"
        fi
    done
else
    print_skip "Kiosk mode not requested"
fi

# ---------------------------------------------------------------------------
# Step 5 - screen
# ---------------------------------------------------------------------------

print_info "Step 5/8: screen"

if [ "$SCREEN" = "ingcool7" ]; then
    if has_boot_config; then
        BOOT_CONFIG="$(boot_config_path)"
        boot_config_block "screen-ingcool7" <<'SCREEN_BLOCK'
# Ingcool 7in 1024x600 touchscreen, powered from the Pi's USB ports. Its mode is
# set on the kernel command line (video=), see below.
max_usb_current=1
usb_max_current_enable=1
SCREEN_BLOCK
        # The panel reports no usable EDID, so the mode has to be stated. The
        # hdmi_group/hdmi_cvt lines this used to write belong to the legacy
        # firmware display stack: under the KMS driver every current Raspberry
        # Pi OS uses, and the only one a Pi 5 has, they are ignored, and the
        # panel came up in whatever mode it guessed. KMS takes the mode from
        # video=, with CVT timings (M) and the output forced on (D).
        KERNEL_CMDLINE="$(dirname "$BOOT_CONFIG")/cmdline.txt"
        if [ -f "$KERNEL_CMDLINE" ]; then
            kernel_cmdline_set "$KERNEL_CMDLINE" "video=HDMI-A-1:1024x600M@60D"
        else
            print_warning "No $KERNEL_CMDLINE; the 1024x600 mode cannot be forced."
        fi
        NEED_REBOOT=true
    else
        print_warning "No firmware config on this host; set the 1024x600 mode through the display settings instead."
    fi
else
    print_skip "No screen-specific configuration (SCREEN=$SCREEN)"
fi

# ---------------------------------------------------------------------------
# Step 6 - cameras
# ---------------------------------------------------------------------------

print_info "Step 6/8: cameras"

if enabled "$CAMERA_PICAMERA"; then
    if has_boot_config; then
        BOOT_CONFIG="$(boot_config_path)"
        # Anchored at end of line on purpose: the unanchored version appended
        # ',cma-512' again on every run, ending up with cma-512,cma-512.
        run sudo sed -i 's/^dtoverlay=vc4-kms-v3d$/dtoverlay=vc4-kms-v3d,cma-512/' "$BOOT_CONFIG"
        # Same block name as the dtoverlay=imx708,cam0 this used to write, so a
        # re-run replaces it. That overlay pinned the camera to the CAM0 port:
        # a Pi 4 has no such port, and on a Pi 5 the ribbon usually sits in the
        # other one, so the camera was never found. Auto-detection finds it on
        # whichever port it is plugged into.
        boot_config_block "camera-imx708" <<'CAMERA_BLOCK'
# Raspberry Pi Camera Module V3, on whichever camera port it is plugged into.
camera_auto_detect=1
CAMERA_BLOCK
        NEED_REBOOT=true
        print_info "After reboot: rpicam-still --list-cameras"
    else
        print_warning "No firmware config on this host; the Pi camera cannot be enabled here."
    fi
    # Preinstalled on the desktop image only: a Lite image has no picamera2,
    # and the booth fell back to another camera without saying why.
    apt_ensure python3-picamera2
    # The venv's numpy 2 shadows Debian's numpy 1.24 on Bookworm, and the apt
    # simplejpeg that picamera2 imports was built against the latter: the
    # import fails with "numpy.dtype size changed". A pip simplejpeg in the
    # venv is built against numpy 2.
    run "$PHOTOBOOTH_PYTHON" -m pip install --upgrade simplejpeg
else
    print_skip "Pi Camera not requested"
fi

if enabled "$CAMERA_DSLR"; then
    # libs/gphoto2.py binds libgphoto2.so directly through ctypes, so the shared
    # library and its udev rules are what matter here, not a Python package.
    # The library itself comes in as a dependency: it is libgphoto2-6 on
    # Bookworm and libgphoto2-6t64 on Trixie, and naming the first stopped the
    # install there. libgphoto2-dev carries the unversioned libgphoto2.so that
    # libs/gphoto2.py loads.
    apt_ensure gphoto2 libgphoto2-dev

    if enabled "$GPHOTO2_UPDATER"; then
        if [ -z "$GPHOTO2_UPDATER_REF" ]; then
            print_error "GPHOTO2_UPDATER=yes needs GPHOTO2_UPDATER_REF set to a commit SHA."
            print_info "Running a third-party installer from a moving branch as root is not something this script will do unattended."
            exit 1
        fi
        UPDATER_URL="https://raw.githubusercontent.com/gonzalo/gphoto2-updater/${GPHOTO2_UPDATER_REF}/gphoto2-updater.sh"
        print_warning "Building libgphoto2 from source via ${UPDATER_URL}"
        run bash -c "cd /tmp && curl -fsSL -o gphoto2-updater.sh '${UPDATER_URL}' && curl -fsSL -o .env 'https://raw.githubusercontent.com/gonzalo/gphoto2-updater/${GPHOTO2_UPDATER_REF}/.env' && chmod +x gphoto2-updater.sh && sudo ./gphoto2-updater.sh -s && rm -f gphoto2-updater.sh .env"
    fi

    # gvfs grabs the camera as a storage volume the moment it is plugged in, and
    # then libgphoto2 cannot claim the USB device (-53). Older releases ship the
    # handlers in /usr/lib/gvfs, Bookworm in /usr/libexec: looking only in the
    # first found nothing there and said nothing, leaving the camera unusable.
    gvfs_found=no
    for gvfs_binary in /usr/lib/gvfs/gvfs-gphoto2-volume-monitor /usr/lib/gvfs/gvfsd-gphoto2 \
                       /usr/libexec/gvfs-gphoto2-volume-monitor /usr/libexec/gvfsd-gphoto2; do
        if [ -e "$gvfs_binary" ]; then
            gvfs_found=yes
            if [ -x "$gvfs_binary" ]; then
                run sudo chmod -x "$gvfs_binary"
                print_success "Disabled $(basename "$gvfs_binary")"
            fi
        fi
    done
    if [ "$gvfs_found" = yes ]; then
        # chmod only stops the next launch; a handler already running keeps
        # holding the camera until it exits.
        run sudo pkill -f 'gvfs-gphoto2-volume-monitor|gvfsd-gphoto2' || true
    else
        print_skip "No gvfs gphoto2 handler installed"
    fi
else
    print_skip "DSLR support not requested"
fi

# ---------------------------------------------------------------------------
# Step 7 - printer
# ---------------------------------------------------------------------------

print_info "Step 7/8: printer"

if enabled "$PRINTER_SETUP"; then
    apt_ensure cups libcups2-dev python3-cups printer-driver-gutenprint

    run sudo usermod -a -G lpadmin "$(id -un)"
    run sudo systemctl enable --now cups
    run sudo cupsctl --remote-admin --remote-any

    PRINTER_NAME="$(is_dry_run && echo "DS620" || booth_config PRINTER)"

    if [ -z "$PRINTER_NAME" ]; then
        print_info "PRINTER is None in config.ini; CUPS installed but no queue registered."
    else
        if [ -z "$PRINTER_URI" ]; then
            # Pick the first USB device CUPS can see. Dye-sub booth printers are
            # USB, and a booth normally has exactly one. Through sudo: listing
            # devices is an lpadmin operation, the group added above only
            # counts from the next login, and lpinfo refused with "Forbidden" -
            # which the 2>/dev/null turned into "no USB printer detected".
            # Gutenprint's own backend first (gutenprint53+usb://dnp-ds620/...):
            # it is the one that drives a dye-sub printer, which CUPS's plain usb
            # backend often leaves out of its list - matching usb:// alone found
            # nothing at all with a DS620 plugged in and switched on.
            DEVICES="$(sudo lpinfo -v 2>/dev/null || true)"
            PRINTER_URI="$(printf '%s\n' "$DEVICES" | awk '$1 == "direct" && $2 ~ /^gutenprint[0-9]*\+usb:\/\// {print $2; exit}')"
            if [ -z "$PRINTER_URI" ]; then
                PRINTER_URI="$(printf '%s\n' "$DEVICES" | awk '$1 == "direct" && $2 ~ /^usb:\/\// {print $2; exit}')"
            fi
        fi

        if [ -z "$PRINTER_URI" ]; then
            print_warning "No USB printer detected. Switch it on, plug it in and re-run, or set PRINTER_URI in setup/booth.conf."
            print_info "Devices CUPS sees (sudo lpinfo -v):"
            printf '%s\n' "${DEVICES:-}" | sed 's/^/    /'
        else
            PPD_PATH="$PHOTOBOOTH_DIR/$PRINTER_PPD"
            if [ -f "$PPD_PATH" ]; then
                print_info "Registering '$PRINTER_NAME' on $PRINTER_URI using $PRINTER_PPD"
                run sudo lpadmin -p "$PRINTER_NAME" -v "$PRINTER_URI" -P "$PPD_PATH" -E
            else
                print_warning "PPD not found at $PPD_PATH; registering with the driverless default."
                run sudo lpadmin -p "$PRINTER_NAME" -v "$PRINTER_URI" -m everywhere -E
            fi
            run sudo cupsaccept "$PRINTER_NAME"
            run sudo cupsenable "$PRINTER_NAME"
            print_success "Printer '$PRINTER_NAME' registered"
        fi
    fi
else
    print_skip "Printer support not requested"
fi

# ---------------------------------------------------------------------------
# Step 8 - LED ring
# ---------------------------------------------------------------------------

print_info "Step 8/8: LED ring"

if enabled "$LED_RING"; then
    if has_boot_config; then
        boot_config_block "led-spi" <<'SPI_BLOCK'
# WS2812 ring light: libs/hardware/led.py bit-bangs the WS2812 timing over SPI0.
# Wiring: GND to pin 6/9/14/20/25, DIN to pin 19 (GPIO 10 / MOSI), VCC to 5V.
dtparam=spi=on
SPI_BLOCK
        NEED_REBOOT=true
    elif has_spi_device; then
        print_info "SPI device already present, no overlay needed"
    else
        print_warning "No SPI bus on this host; libs/hardware/led.py will fall back to NullLed."
    fi
    # The apt package first: spidev has no wheel on PyPI, and building it needs
    # python3-dev, which nothing installs - so the pip route failed on almost
    # every fresh image and the ring stayed dark. The venv sees the apt module
    # through --system-site-packages. A failure here must not take the whole
    # install down: libs/hardware/led.py treats a missing spidev as "no ring
    # light" and returns NullLed, so the booth still runs.
    if ! apt_ensure python3-spidev && ! run "$PHOTOBOOTH_PYTHON" -m pip install spidev; then
        print_warning "spidev did not install; the ring light will fall back to NullLed."
    fi
else
    print_skip "LED ring not requested"
fi

# ---------------------------------------------------------------------------
# Autostart
# ---------------------------------------------------------------------------

print_info "Autostart"

escape_systemd_value() {
    printf '%s' "$1" | sed 's/[[:space:]]/\\x20/g'
}

if enabled "$AUTOSTART"; then
    if has_systemd; then
        # The booth starts from the console, alone on the screen, inside cage:
        # a compositor that runs one application fullscreen and nothing else.
        # A desktop was what it used to run in, and with it came the taskbar,
        # update notices and dialogs drawn over the booth during an event - and
        # the service was started with DISPLAY set to a login session id ("c1",
        # from `loginctl show-user -p Display`), so it never opened a window
        # at all. Xwayland lets the booth's SDL window run inside cage as it
        # did on X11. A Lite image works too: no desktop is needed.
        apt_ensure cage xwayland libpam-systemd

        PHOTOBOOTH_USER="$(id -un)"
        PHOTOBOOTH_GROUP="$(id -gn)"
        PHOTOBOOTH_UID="$(id -u)"
        PHOTOBOOTH_GID="$(id -g)"
        PHOTOBOOTH_DIR_ESCAPED="$(escape_systemd_value "$PHOTOBOOTH_DIR")"
        PHOTOBOOTH_PYTHON_ESCAPED="$(escape_systemd_value "$VENV_PYTHON")"

        export PHOTOBOOTH_USER PHOTOBOOTH_GROUP PHOTOBOOTH_UID PHOTOBOOTH_GID
        export PHOTOBOOTH_DIR_ESCAPED PHOTOBOOTH_PYTHON_ESCAPED

        # The screen, the GPU and the touchscreen. Raspberry Pi OS's first user
        # already has these, a user made by hand may not.
        run sudo usermod -a -G video,render,input "$PHOTOBOOTH_USER"

        render "$TEMPLATES/photobooth.pam.tmpl" /etc/pam.d/photobooth 0644
        render "$TEMPLATES/photobooth.service.tmpl" /etc/systemd/system/photobooth.service 0644
        if [ "$ROOT_FILE_CHANGED" = true ]; then
            NEED_REBOOT=true
        fi

        # Nothing mounts a USB drive without a desktop; the USB photo dump
        # waits for one under /media.
        render "$TEMPLATES/99-photobooth-usb.rules.tmpl" /etc/udev/rules.d/99-photobooth-usb.rules 0644
        if [ "$ROOT_FILE_CHANGED" = true ]; then
            run sudo udevadm control --reload
        fi

        # The desktop would fight the booth for the screen. It stays installed:
        # `sudo systemctl start lightdm` brings it back for maintenance.
        if [ -L /etc/systemd/system/display-manager.service ]; then
            DESKTOP_MANAGER="$(basename "$(readlink -f /etc/systemd/system/display-manager.service)")"
            run sudo systemctl disable "$DESKTOP_MANAGER"
            print_success "Desktop ($DESKTOP_MANAGER) no longer started at boot"
            NEED_REBOOT=true
        fi
        if [ "$(systemctl get-default 2>/dev/null)" != multi-user.target ]; then
            run sudo systemctl set-default multi-user.target
            NEED_REBOOT=true
        fi

        run sudo touch /var/log/photobooth.log
        run sudo chown "$PHOTOBOOTH_USER:$PHOTOBOOTH_GROUP" /var/log/photobooth.log
        run sudo systemctl daemon-reload
        run sudo systemctl enable photobooth.service

        print_success "photobooth.service enabled: the booth starts from the console, without the desktop"
    else
        print_warning "No systemd here; cannot install the autostart unit."
    fi
else
    print_skip "Autostart not requested"
fi

# ---------------------------------------------------------------------------
# Boot splash
# ---------------------------------------------------------------------------

print_info "Boot splash"

# Between power-on and the welcome screen, a booth prints its kernel messages,
# shows a desktop, then loads. Plymouth replaces the messages with the welcome
# picture, the desktop gets the same picture as wallpaper, and the application
# carries on with its own loading screen over it (libs/screens/loading.py).
PLYMOUTH_THEME_DIR=/usr/share/plymouth/themes/photobooth
KERNEL_SPLASH_ARGUMENTS="quiet splash loglevel=3 logo.nologo vt.global_cursor_default=0"

if enabled "$BOOT_SPLASH"; then
    apt_ensure plymouth plymouth-themes

    # The theme is built from config.ini as it stands: the welcome photo, the
    # panel's mode and its ROTATION, none of which Plymouth knows about.
    if is_dry_run; then
        print_dry "build the Plymouth theme with tools/boot_splash.py into $PLYMOUTH_THEME_DIR"
        print_dry "sudo plymouth-set-default-theme -R photobooth"
    else
        SPLASH_BUILD="$(mktemp -d)"
        "$PHOTOBOOTH_PYTHON" "$PHOTOBOOTH_DIR/tools/boot_splash.py" "$SPLASH_BUILD" "$PLYMOUTH_THEME_DIR" > /dev/null
        SPLASH_CHANGED=false
        for splash_file in "$SPLASH_BUILD"/*; do
            write_root_file "$PLYMOUTH_THEME_DIR/$(basename "$splash_file")" 0644 < "$splash_file"
            if [ "$ROOT_FILE_CHANGED" = true ]; then
                SPLASH_CHANGED=true
            fi
        done
        rm -rf "$SPLASH_BUILD"

        # Selecting the theme rebuilds the initramfs, which is a minute on a Pi:
        # only when there is something new to put in it.
        if [ "$SPLASH_CHANGED" = true ] || [ "$(sudo plymouth-set-default-theme 2>/dev/null)" != photobooth ]; then
            if sudo plymouth-set-default-theme -R photobooth; then
                print_success "Plymouth theme 'photobooth' selected"
                NEED_REBOOT=true
            else
                print_warning "Could not select the Plymouth theme; try: sudo plymouth-set-default-theme -R photobooth"
            fi
        else
            print_skip "Plymouth theme already selected and up to date"
        fi
    fi

    if has_boot_config; then
        BOOT_CONFIG="$(boot_config_path)"
        boot_config_block "boot-splash" <<'SPLASH_BLOCK'
# No rainbow square from the firmware before the booth's own splash.
disable_splash=1
SPLASH_BLOCK
        KERNEL_CMDLINE="$(dirname "$BOOT_CONFIG")/cmdline.txt"
        if [ -f "$KERNEL_CMDLINE" ]; then
            # plymouth.ignore-serial-consoles: with a serial console on the
            # command line, as Raspberry Pi OS ships it, Plymouth shows its
            # text mode instead of the theme.
            # shellcheck disable=SC2086 # one argument per word
            kernel_cmdline_set "$KERNEL_CMDLINE" $KERNEL_SPLASH_ARGUMENTS plymouth.ignore-serial-consoles
        else
            print_warning "No $KERNEL_CMDLINE; the kernel will keep printing its messages."
        fi
        NEED_REBOOT=true
    elif has_grub; then
        # A drop-in rather than an edit of /etc/default/grub, which belongs to
        # the operator. The menu stays reachable: hold Shift, or press Esc, while
        # the machine starts.
        write_root_file /etc/default/grub.d/photobooth-splash.cfg 0644 <<GRUB_SPLASH
# Written by install.sh (BOOT_SPLASH): straight to the booth's splash, no menu
# and no kernel messages. Delete this file and run update-grub to undo.
GRUB_TIMEOUT=0
GRUB_TIMEOUT_STYLE=hidden
GRUB_RECORDFAIL_TIMEOUT=0
GRUB_CMDLINE_LINUX_DEFAULT="\$GRUB_CMDLINE_LINUX_DEFAULT $KERNEL_SPLASH_ARGUMENTS"
GRUB_SPLASH
        if [ "$ROOT_FILE_CHANGED" = true ]; then
            run sudo update-grub
            NEED_REBOOT=true
        fi
        print_info "The maker's logo before GRUB is the firmware's: turn on 'quiet boot' in its setup."
    else
        print_warning "Neither a Pi firmware config nor GRUB here; the kernel will keep printing its messages."
    fi

    # The desktop shows for a few seconds between the splash and the booth.
    # pcmanfm draws it on Raspberry Pi OS (X11, Wayfire and labwc alike): only
    # the settings files that already exist are changed, so a desktop this
    # does not know is left alone.
    SPLASH_WALLPAPER="$PLYMOUTH_THEME_DIR/splash.png"
    wallpaper_set=false
    for desktop_items in "$HOME"/.config/pcmanfm/*/desktop-items-*.conf /etc/xdg/pcmanfm/*/desktop-items-*.conf; do
        [ -f "$desktop_items" ] || continue
        as_owner=()
        case "$desktop_items" in
            /etc/*) as_owner=(sudo) ;;
        esac
        run "${as_owner[@]}" sed -i \
            -e "s|^wallpaper=.*|wallpaper=$SPLASH_WALLPAPER|" \
            -e 's|^wallpaper_mode=.*|wallpaper_mode=crop|' \
            "$desktop_items"
        wallpaper_set=true
    done
    if [ "$wallpaper_set" = true ]; then
        print_success "Desktop wallpaper set to the splash picture"
    else
        print_skip "No pcmanfm desktop settings found; wallpaper left as it is"
    fi
else
    print_skip "Boot splash not requested"
fi

# ---------------------------------------------------------------------------
# Save the profile
# ---------------------------------------------------------------------------

if [ -z "$PROFILE" ] && [ "$ASSUME_YES" != "true" ] && ! is_dry_run; then
    cat > "$SETUP_DIR/booth.conf" <<PROFILE_OUT
# Written by install.sh on $(date -Iseconds).
# Build an identical booth with:
#     ./install.sh --profile setup/booth.conf --yes
# See setup/booth.conf.example for what each value means.

KIOSK=$KIOSK
SCREEN=$SCREEN
CAMERA_PICAMERA=$CAMERA_PICAMERA
CAMERA_DSLR=$CAMERA_DSLR
GPHOTO2_UPDATER=$GPHOTO2_UPDATER
GPHOTO2_UPDATER_REF=$GPHOTO2_UPDATER_REF
PRINTER_SETUP=$PRINTER_SETUP
PRINTER_URI=$PRINTER_URI
PRINTER_PPD=$PRINTER_PPD
LED_RING=$LED_RING
AUTOSTART=$AUTOSTART
BOOT_SPLASH=$BOOT_SPLASH
PROFILE_OUT
    print_success "Saved your answers to setup/booth.conf"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

echo ""
print_success "Installation complete"
echo ""
print_info "Check the booth with:  ./setup/doctor.sh"

if [ "$NEED_REBOOT" = "true" ]; then
    echo ""
    print_warning "Firmware settings changed; a reboot is required."
    if [ "$ASSUME_YES" != "true" ] && ! is_dry_run; then
        if ask_yes_no "Reboot now?"; then
            run sudo reboot
        fi
    else
        print_info "Run: sudo reboot"
    fi
fi

echo ""
print_info "To start the booth by hand:"
echo "  cd $PHOTOBOOTH_DIR"
echo "  .venv/bin/python photoboothapp.py          (from a desktop)"
echo "  cage -- .venv/bin/python photoboothapp.py  (from the console)"
echo ""
