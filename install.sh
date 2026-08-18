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
# config to edit, no wireless interface, no SPI bus - which is why a mini PC
# gets its access point and its autostart just like a Pi does.

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
WIFI_AP=ask
WIFI_COUNTRY=FR
WIFI_CHANNEL=6
WIFI_INTERFACE=""
WIFI_LOG_QUERIES=yes
AUTOSTART=ask

PROFILE=""
ASSUME_YES=false
NEED_REBOOT=false

usage() {
    sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
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
fi

is_dry_run && print_warning "Dry run: nothing will be modified."

# ---------------------------------------------------------------------------
# Questions - only the ones the profile left unanswered
# ---------------------------------------------------------------------------

resolve_unanswered() {
    local var
    for var in KIOSK SCREEN CAMERA_PICAMERA CAMERA_DSLR PRINTER_SETUP LED_RING WIFI_AP AUTOSTART; do
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
    ask_yes_no_var WIFI_AP "Run the WiFi access point for guest phones?"
    ask_yes_no_var AUTOSTART "Start the booth automatically on boot?"
fi

# ---------------------------------------------------------------------------
# Step 1 - base packages
# ---------------------------------------------------------------------------

print_info "Step 1/9: base system packages"

# gettext-base carries envsubst, which renders every template below.
apt_ensure gcc make build-essential git scons swig \
    ffmpeg libturbojpeg0 libgl1 \
    python3-pip python3-venv gettext-base

# ---------------------------------------------------------------------------
# Step 2 - Python environment
# ---------------------------------------------------------------------------

print_info "Step 2/9: Python environment"

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

print_info "Step 3/9: application configuration"

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

# ---------------------------------------------------------------------------
# Step 4 - kiosk mode
# ---------------------------------------------------------------------------

print_info "Step 4/9: kiosk mode"

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
    else
        print_skip "Wayfire not installed; leaving the desktop alone"
    fi

    if has_boot_config; then
        managed_block "$(boot_config_path)" "kiosk" <<'KIOSK_BLOCK'
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

print_info "Step 5/9: screen"

if [ "$SCREEN" = "ingcool7" ]; then
    if has_boot_config; then
        managed_block "$(boot_config_path)" "screen-ingcool7" <<'SCREEN_BLOCK'
# Ingcool 7in 1024x600 touchscreen: it reports no usable EDID, so the mode has
# to be stated rather than negotiated.
max_usb_current=1
hdmi_group=2
hdmi_mode=87
hdmi_cvt 1024 600 60 6 0 0 0
hdmi_drive=1
SCREEN_BLOCK
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

print_info "Step 6/9: cameras"

if enabled "$CAMERA_PICAMERA"; then
    if has_boot_config; then
        BOOT_CONFIG="$(boot_config_path)"
        # Anchored at end of line on purpose: the unanchored version appended
        # ',cma-512' again on every run, ending up with cma-512,cma-512.
        run sudo sed -i 's/^dtoverlay=vc4-kms-v3d$/dtoverlay=vc4-kms-v3d,cma-512/' "$BOOT_CONFIG"
        managed_block "$BOOT_CONFIG" "camera-imx708" <<'CAMERA_BLOCK'
# Raspberry Pi Camera Module V3
dtoverlay=imx708,cam0
CAMERA_BLOCK
        NEED_REBOOT=true
        print_info "After reboot: libcamera-still --list-cameras"
    else
        print_warning "No firmware config on this host; the Pi camera cannot be enabled here."
    fi
else
    print_skip "Pi Camera not requested"
fi

if enabled "$CAMERA_DSLR"; then
    # libs/gphoto2.py binds libgphoto2.so directly through ctypes, so the shared
    # library and its udev rules are what matter here, not a Python package.
    apt_ensure gphoto2 libgphoto2-6 libgphoto2-dev

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
    # then libgphoto2 cannot claim the USB device.
    for gvfs_binary in /usr/lib/gvfs/gvfs-gphoto2-volume-monitor /usr/lib/gvfs/gvfsd-gphoto2; do
        if [ -x "$gvfs_binary" ]; then
            run sudo chmod -x "$gvfs_binary"
            print_success "Disabled $(basename "$gvfs_binary")"
        fi
    done
else
    print_skip "DSLR support not requested"
fi

# ---------------------------------------------------------------------------
# Step 7 - printer
# ---------------------------------------------------------------------------

print_info "Step 7/9: printer"

if enabled "$PRINTER_SETUP"; then
    apt_ensure cups libcups2-dev python3-cups printer-driver-gutenprint

    run sudo usermod -a -G lpadmin "$(id -un)"
    run sudo cupsctl --remote-admin --remote-any

    PRINTER_NAME="$(is_dry_run && echo "DS620" || booth_config PRINTER)"

    if [ -z "$PRINTER_NAME" ]; then
        print_info "PRINTER is None in config.ini; CUPS installed but no queue registered."
    else
        if [ -z "$PRINTER_URI" ]; then
            # Pick the first USB device CUPS can see. Dye-sub booth printers are
            # USB, and a booth normally has exactly one.
            PRINTER_URI="$(lpinfo -v 2>/dev/null | awk '/^direct usb:/ {print $2; exit}' || true)"
        fi

        if [ -z "$PRINTER_URI" ]; then
            print_warning "No USB printer detected. Plug it in and re-run, or set PRINTER_URI in setup/booth.conf."
            print_info "Available devices: lpinfo -v"
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

print_info "Step 8/9: LED ring"

if enabled "$LED_RING"; then
    if has_boot_config; then
        managed_block "$(boot_config_path)" "led-spi" <<'SPI_BLOCK'
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
    # A build failure here must not take the whole install down: libs/hardware/
    # led.py already treats a missing spidev as "no ring light" and returns
    # NullLed, so the booth still runs.
    if ! run "$PHOTOBOOTH_PYTHON" -m pip install spidev; then
        print_warning "spidev did not install; the ring light will fall back to NullLed."
    fi
else
    print_skip "LED ring not requested"
fi

# ---------------------------------------------------------------------------
# Step 9 - WiFi access point
# ---------------------------------------------------------------------------

print_info "Step 9/9: WiFi access point"

if enabled "$WIFI_AP"; then
    if has_wlan; then
        apt_ensure hostapd dnsmasq iptables rfkill

        # The access point configuration is generated from config.ini, so that
        # the SSID the booth puts in its QR code and the one hostapd broadcasts
        # can no longer drift apart. apply-wifi.sh is also runnable on its own,
        # after the network is renamed through the admin page.
        export WIFI_COUNTRY WIFI_CHANNEL WIFI_INTERFACE WIFI_LOG_QUERIES
        APPLY_WIFI_ARGS=()
        is_dry_run && APPLY_WIFI_ARGS+=(--dry-run)
        bash "$SETUP_DIR/apply-wifi.sh" "${APPLY_WIFI_ARGS[@]+"${APPLY_WIFI_ARGS[@]}"}"
        NEED_REBOOT=true
    else
        print_warning "No wireless interface found; skipping the access point."
        print_info "Set WIFI_INTERFACE in setup/booth.conf if the adapter is named differently."
    fi
else
    print_skip "Access point not requested"
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
        PHOTOBOOTH_USER="$(id -un)"
        PHOTOBOOTH_GROUP="$(id -gn)"
        PHOTOBOOTH_DIR_ESCAPED="$(escape_systemd_value "$PHOTOBOOTH_DIR")"
        PHOTOBOOTH_PYTHON_ESCAPED="$(escape_systemd_value "$VENV_PYTHON")"
        DISPLAY_TARGET="$(loginctl show-user "$PHOTOBOOTH_USER" -p Display --value 2>/dev/null || true)"
        DISPLAY_TARGET="${DISPLAY_TARGET:-:0}"

        export PHOTOBOOTH_USER PHOTOBOOTH_GROUP PHOTOBOOTH_DIR_ESCAPED
        export PHOTOBOOTH_PYTHON_ESCAPED DISPLAY_TARGET

        render "$TEMPLATES/photobooth.service.tmpl" /etc/systemd/system/photobooth.service 0644

        run sudo touch /var/log/photobooth.log
        run sudo chown "$PHOTOBOOTH_USER:$PHOTOBOOTH_GROUP" /var/log/photobooth.log
        run sudo systemctl daemon-reload
        run sudo systemctl enable photobooth.service

        print_success "photobooth.service enabled"
    else
        print_warning "No systemd here; cannot install the autostart unit."
    fi
else
    print_skip "Autostart not requested"
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
WIFI_AP=$WIFI_AP
WIFI_COUNTRY=$WIFI_COUNTRY
WIFI_CHANNEL=$WIFI_CHANNEL
WIFI_INTERFACE=$WIFI_INTERFACE
WIFI_LOG_QUERIES=$WIFI_LOG_QUERIES
AUTOSTART=$AUTOSTART
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
    print_warning "Firmware or network settings changed; a reboot is required."
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
echo "  .venv/bin/python photoboothapp.py"
echo ""
