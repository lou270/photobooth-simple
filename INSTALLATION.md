# Installation Guide

How to turn a bare machine into a working photo booth, and how to do it again
for the next one without remembering any of this.

## What this runs on

Any Debian-based Linux. A Raspberry Pi 5 (8 GB) on Raspberry Pi OS is the
reference build, but a Pi 4 or a small x86 machine with an SSD works too: the
installer decides what to do from what the host can actually do, not from which
board it is. On a machine with no firmware config file, the device-tree steps
(Pi camera, SPI, HDMI timings) are skipped and everything else - printer,
autostart - is installed normally.

What varies per booth is described in `setup/booth.conf`, so the same repository
builds a DSLR booth with a printer and a webcam booth without one.

## Building a booth

Flash Raspberry Pi OS (or install Debian), get the machine on the network, then:

```bash
git clone https://github.com/IArchi/py-photobooth-simple.git
cd py-photobooth-simple
./install.sh
```

The installer asks what hardware this booth has, installs accordingly, and saves
your answers to `setup/booth.conf`. Run again, it shows those answers and asks
whether to reuse them or answer again. Then check it:

```bash
./setup/doctor.sh
```

### The second booth, and every one after

`setup/booth.conf` is the whole interview, written down. Copy it to the next
machine and there are no questions left to answer:

```bash
./install.sh --profile setup/booth.conf --yes
```

Start from `setup/booth.conf.example` to write one by hand; every value is
documented there.

### Seeing what it would do first

```bash
./install.sh --profile setup/booth.conf --dry-run
```

Prints every command and the full content of every file it would write, and
changes nothing.

### Re-running it

The installer is idempotent. Host files are written either as a delimited block:

```
# >>> photobooth:led-spi >>>
[all]
dtparam=spi=on
# <<< photobooth:led-spi <<<
```

or as a whole file rendered from `setup/templates/`. Running it twice rewrites
the same block instead of appending a second copy, so a re-run after changing
one answer is safe.

## What each step does

| Step | Needs | Effect |
| --- | --- | --- |
| Base packages | - | Build tools, curl, ffmpeg, `libgl1` for Kivy and OpenCV, `gettext-base` for templating |
| Python | - | Creates `.venv` and installs `requirements.txt` into it |
| Configuration | - | Creates `config.ini`, generates an admin password if none is set, sets `FULLSCREEN = True` in kiosk mode, `PRINTER = None` and `RINGLED = False` when the booth has neither |
| Kiosk | labwc or Wayfire | Hides the panel, stops the media-mount dialog; the booth hides the pointer itself in fullscreen |
| Screen | firmware config | `video=HDMI-A-1:1024x600M@60D` on the kernel command line for the Ingcool 7" panel |
| Pi camera | firmware config | `camera_auto_detect=1`, the CMA bump libcamera needs, `python3-picamera2`, and a `simplejpeg` built for the venv's numpy |
| DSLR | - | `libgphoto2` and its tools, and disables the gvfs claim on the camera |
| Printer | - | CUPS, then registers the queue named in `config.ini` using `doc/DS620.ppd` |
| LED ring | firmware config | Enables SPI, installs `python3-spidev` |
| Autostart | systemd | `photobooth.service`: the booth alone on the screen from the console, in `cage`; the desktop is no longer started; USB drives mounted for the photo dump |
| Boot splash | firmware config or GRUB | Plymouth theme from the welcome picture, quiet kernel, same picture as wallpaper |

### The boot splash

From power-on to the welcome screen, a booth goes through three things guests
would otherwise watch: kernel messages, the desktop, and the application
loading. With `BOOT_SPLASH=yes` all three show the welcome picture, dimmed:

- **Plymouth** draws it in place of the messages. The theme is built by
  `tools/boot_splash.py` from `config.ini` - the welcome photo, `WINDOW_WIDTH`
  and `WINDOW_HEIGHT`, and `ROTATION`, since Plymouth draws on the panel as it is
  mounted - and installed in `/usr/share/plymouth/themes/photobooth`.
- **The kernel** is told to stay quiet. On a Pi, `quiet splash loglevel=3
  logo.nologo vt.global_cursor_default=0 plymouth.ignore-serial-consoles` is
  added to `cmdline.txt` and `disable_splash=1` to the firmware config (block
  `photobooth:boot-splash`). On a mini PC, the same arguments and a hidden menu
  go into `/etc/default/grub.d/photobooth-splash.cfg`; hold Shift or press Esc
  during boot to reach the GRUB menu. The maker's logo before that belongs to
  the firmware: turn on its "quiet boot" option.
- **The desktop**, on a booth that still starts one (no `AUTOSTART`), gets the
  picture as wallpaper, wherever pcmanfm already has a settings file.
- **The application** then shows its own loading screen on the same picture,
  with each step it is at, until the welcome screen is ready.

The picture is copied into the initramfs, so a new welcome photo reaches the
boot splash only when the installer runs again:

```bash
./install.sh --profile setup/booth.conf --yes
```

To go back to the boot messages on a Pi, remove the `photobooth:boot-splash`
block and the arguments above from `cmdline.txt`; on a mini PC, delete the GRUB
drop-in and run `sudo update-grub`.

### Without a desktop

With `AUTOSTART=yes` the booth starts straight from the console, alone on the
screen: `photobooth.service` takes tty1 in place of the login prompt and runs
the application inside [cage](https://github.com/cage-kiosk/cage), a compositor
that shows one application fullscreen and nothing else. No taskbar, no "update
available" notice, no dialog can draw over the booth, and Raspberry Pi OS Lite
is enough.

The desktop, if the image has one, stays installed but is no longer started,
and the machine boots to `multi-user.target`. For maintenance:

- Ctrl+Alt+F2 gives a login console beside the booth, Ctrl+Alt+F1 goes back;
- `sudo systemctl stop photobooth && sudo systemctl start lightdm` brings the
  desktop back until the next boot;
- to keep the desktop for good, `sudo systemctl disable photobooth`, then
  `sudo raspi-config nonint do_boot_behaviour B4` and reboot.

Since nothing else mounts USB drives without a desktop, the installer adds a
udev rule (`/etc/udev/rules.d/99-photobooth-usb.rules`) mounting FAT32 and exFAT
drives under `/media/<user>/` for the photo dump.

To run the booth by hand from the console, stop the service first, then
`cage -- .venv/bin/python photoboothapp.py`.

### The virtual environment

Dependencies go into `.venv` rather than into the system Python. The environment
is created with `--system-site-packages`, which is required rather than
cosmetic: `picamera2`, `libcamera` and `python3-cups` are apt packages with no
usable pip equivalent, and `libs/device_utils.py` imports them by name.

Run the booth by hand from a desktop with:

```bash
.venv/bin/python photoboothapp.py
```

### The admin password

`config.ini` ships with `ADMIN_PASSWORD = None`, which leaves the admin pages
disabled. If it is still unset when the installer runs, a 16-character password
is generated and printed once. It is stored only in `config.ini` - write it
down. To choose your own, set it before running the installer, or edit
`config.ini` afterwards; it must be at least 10 characters and not a well-known
value.

### The guest network

The installer sets up no network. Guests' phones reach the booth over a network
it joins like any other machine: a travel router beside it (no internet needed)
or the venue's WiFi, provided that one lets devices talk to each other. Connect
the booth with the usual system tools, and give it a stable address, ideally a
DHCP reservation on the router.

To spare guests from typing the network's credentials, describe it in the
`[WiFi]` section of `config.ini` (`WIFI_SSID`, `WIFI_PASSWORD`, `WIFI_HIDDEN`):
the booth then shows a code that joins it before the code that opens the page.
These values describe the network, they do not configure it. See
[Guest network and QR codes](README.md#guest-network-and-qr-codes).

### Upgrading a booth that ran its own access point

Earlier versions turned the booth into an access point with a captive portal.
The application no longer answers that portal, so on a booth installed that way
the old services hand phones a network that leads nowhere, and
`./setup/doctor.sh` warns about each one still running. Remove them:

```bash
sudo systemctl disable --now photobooth-http-redirect.service photobooth-ap-network.service hostapd dnsmasq
sudo rm -f /etc/systemd/system/photobooth-http-redirect.service /etc/systemd/system/photobooth-ap-network.service
sudo rm -f /etc/systemd/system/hostapd.service.d/photobooth-ap.conf
sudo rm -f /etc/NetworkManager/conf.d/photobooth-unmanaged.conf
sudo systemctl daemon-reload
```

Stopping `photobooth-http-redirect.service` also removes its port 80 NAT rule.
On a system without NetworkManager, delete the `photobooth:ap-address` block
from `/etc/dhcpcd.conf` instead of the NetworkManager file. Then reboot, join the
booth to its network, and drop the `WIFI_*` lines from `setup/booth.conf`: the
installer no longer reads them. `sudo apt-get remove hostapd dnsmasq` is
optional once the services are disabled.

### The printer

The installer registers the queue for you, using the name from `PRINTER` in
`config.ini` (default `DS620`) and the PPD at `doc/DS620.ppd`, on the first USB
printer CUPS reports. If the printer was not plugged in at the time, plug it in
and run the installer again, or pin the device explicitly:

```bash
sudo lpinfo -v                 # find the URI
# then set PRINTER_URI in setup/booth.conf
```

CUPS's own web interface stays available at `https://<booth-ip>:631/admin/` for
anything unusual.

### DSLR support

The distribution's `libgphoto2` is used by default. A camera too recent for it
needs a build from source, which is available but opt-in, because it means
running a third-party script as root:

```ini
GPHOTO2_UPDATER=yes
GPHOTO2_UPDATER_REF=<a commit SHA from gonzalo/gphoto2-updater>
```

The commit is required rather than optional: the installer will not fetch a
moving branch and run it as root unattended.

### LED ring wiring

| WS2812 pin | Raspberry Pi pin |
| --- | --- |
| GND | 6, 9, 14, 20 or 25 |
| DIN | 19 (GPIO 10, MOSI) |
| VCC | 2 or 4 (5V) |

## Checking a booth

```bash
./setup/doctor.sh            # everything
./setup/doctor.sh --quiet    # only what is wrong
```

It reports on the Python environment and imports, `config.ini` and the admin
password, which camera backends are actually available, whether CUPS knows the
printer named in the configuration, the SPI device, free disk space, the systemd
units (and any left from the old access point), whether the web server answers,
and the address the QR codes will carry. Exit code is 1 if anything required is
missing.

What counts as required comes from `config.ini`: a booth with `PRINTER = None`
is not missing a printer, and one with `RINGLED = False` is not missing an LED
ring.

`tools/doctor.py` can be run on its own for the application-level checks only.

## Troubleshooting

**The booth does not start at boot.** `systemctl status photobooth.service`
and `/var/log/photobooth.log`. Ctrl+Alt+F2 opens a console beside the booth to
look.

**Camera not detected.** Run `./setup/doctor.sh` first: it says which backends
are present. For a Pi camera, `rpicam-still --list-cameras` after a reboot
(`libcamera-still` on older images).
For a DSLR, `gphoto2 --capture-image`; if it reports the device is busy, the
gvfs handlers are back - the installer disables them.

**DSLR preview stays black, or the log counts "Could not find the requested
device" (-52).** The booth takes the camera out of live view after a minute
with no guest, so nothing keeps the body awake any more: set its auto power off
to Disable. The booth reopens a camera that comes back on the USB bus by
itself, but a body that has switched itself off stays gone until someone
touches it.

**Printer not working.** `./setup/doctor.sh` reports whether CUPS has a queue
under the configured name and lists the ones it does have. A registered but
paused queue: `cupsenable <name>`.

**Guests scan the code but nothing loads.** Check the address the doctor reports:
it is the one the codes carry, and the phone must be on that same network. On
the venue's WiFi, client isolation is the usual cause; a travel router avoids
it. A booth connected twice (ethernet and WiFi) may pick the wrong interface:
set `REMOTE_URL` to the right address. On a network without internet, Android
may quietly move the phone back onto mobile data - the capture page tells
guests how to stay connected.

**Screen resolution wrong.** For the Ingcool panel, confirm
`video=HDMI-A-1:1024x600M@60D` is on the line in `cmdline.txt` (beside
`config.txt`); the `hdmi_cvt` lines older versions wrote there are ignored by
the KMS display driver. Other panels usually negotiate their own mode; set
`SCREEN=none`. Then set
`WINDOW_WIDTH` and `WINDOW_HEIGHT` in `config.ini` to that same mode: the booth
asks for a real fullscreen rather than a desktop-sized one, so a panel running
1920x1080 has to be named there as well.

**Panel mounted on its side.** Set `ROTATION` to 90, 180 or 270 in `config.ini`
and leave the width and height at the panel's own mode. The installer does not
rotate the host, on purpose: that would mean Wayfire, labwc, X11 and bare KMS
each needing their own mechanism, plus a calibration matrix per touchscreen,
where the booth rotating its own display and its own touch input works the same
on every install.

One exception, and it is a development one: on Windows, Kivy computes its
viewport from the rotated size instead of the panel's, and draws the interface
into a corner of the window. `ROTATION` is therefore a booth setting, verified
on the Linux path the booth runs; leave it at 0 on a Windows workstation.

## USB photo dump

Insert a FAT32-formatted USB drive and the booth copies every saved session onto
it, showing progress on screen. Wait for it to finish before removing the drive.
Controlled by `USB_EXPORT` in `config.ini`.
