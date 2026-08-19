# Installation Guide

How to turn a bare machine into a working photo booth, and how to do it again
for the next one without remembering any of this.

## What this runs on

Any Debian-based Linux. A Raspberry Pi 5 (8 GB) on Raspberry Pi OS is the
reference build, but a Pi 4 or a small x86 machine with an SSD works too: the
installer decides what to do from what the host can actually do, not from which
board it is. On a machine with no firmware config file, the device-tree steps
(Pi camera, SPI, HDMI timings) are skipped and everything else - access point,
printer, autostart - is installed normally.

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
your answers to `setup/booth.conf`. Then check it:

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
# >>> photobooth:screen-ingcool7 >>>
hdmi_group=2
...
# <<< photobooth:screen-ingcool7 <<<
```

or as a whole file rendered from `setup/templates/`. Running it twice rewrites
the same block instead of appending a second copy, so a re-run after changing
one answer is safe.

## What each step does

| Step | Needs | Effect |
| --- | --- | --- |
| Base packages | - | Build tools, ffmpeg, libturbojpeg, `gettext-base` for templating |
| Python | - | Creates `.venv` and installs `requirements.txt` into it |
| Configuration | - | Creates `config.ini`, generates an admin password if none is set |
| Kiosk | Wayfire | Hides the panel and the cursor, stops the media-mount dialog |
| Screen | firmware config | 1024x600 timings for the Ingcool 7" panel |
| Pi camera | firmware config | `imx708` overlay and the CMA bump libcamera needs |
| DSLR | - | `libgphoto2` and its tools, and disables the gvfs claim on the camera |
| Printer | - | CUPS, then registers the queue named in `config.ini` using `doc/DS620.ppd` |
| LED ring | firmware config | Enables SPI, installs `spidev` |
| Access point | a wireless interface | `hostapd` + `dnsmasq` + captive portal, generated from `config.ini` |
| Autostart | systemd | `photobooth.service`, restarts on crash, starts at boot |

### The virtual environment

Dependencies go into `.venv` rather than into the system Python. The environment
is created with `--system-site-packages`, which is required rather than
cosmetic: `picamera2`, `libcamera` and `python3-cups` are apt packages with no
usable pip equivalent, and `libs/device_utils.py` imports them by name.

Run the booth by hand with:

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

### The WiFi access point

The booth shows guests a QR code built from the `[WiFi]` section of
`config.ini`, and `hostapd` broadcasts a network of its own. Those used to be
two independent copies of the same name, with nothing keeping them in step.

Now `config.ini` is the source of truth and the access point is generated from
it:

```bash
./setup/apply-wifi.sh
```

Run that after changing the network name or passphrase, including when the
change was made from the admin page. `./setup/doctor.sh` compares the two and
reports a mismatch, because it is otherwise invisible until a guest scans the
code and joins a network that is not there.

For a passphrase-protected network, set `WIFI_PASSWORD` in `config.ini` to 8-63
characters and re-run `apply-wifi.sh`; leave it empty for an open network.

### The printer

The installer registers the queue for you, using the name from `PRINTER` in
`config.ini` (default `DS620`) and the PPD at `doc/DS620.ppd`, on the first USB
printer CUPS reports. If the printer was not plugged in at the time, plug it in
and run the installer again, or pin the device explicitly:

```bash
lpinfo -v                      # find the URI
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
units, the access point's address and NAT rule, and the SSID match described
above. Exit code is 1 if anything required is missing.

What counts as required comes from `config.ini`: a booth with `PRINTER = None`
is not missing a printer, and one with `RINGLED = False` is not missing an LED
ring.

`tools/doctor.py` can be run on its own for the application-level checks only.

## Troubleshooting

**Camera not detected.** Run `./setup/doctor.sh` first: it says which backends
are present. For a Pi camera, `libcamera-still --list-cameras` after a reboot.
For a DSLR, `gphoto2 --capture-image`; if it reports the device is busy, the
gvfs handlers are back - the installer disables them.

**Printer not working.** `./setup/doctor.sh` reports whether CUPS has a queue
under the configured name and lists the ones it does have. A registered but
paused queue: `cupsenable <name>`.

**Access point does not come up.** `journalctl -xeu hostapd`. The usual cause is
a wrong `WIFI_COUNTRY` in `setup/booth.conf`, which leaves the radio with no
legal channel.

**Guests join but nothing loads.** Check the NAT rule and the interface address,
both reported by the doctor. Phones hold their old DHCP lease after a
reconfiguration: ask them to forget the network and rejoin.

**Screen resolution wrong.** For the Ingcool panel, confirm the
`photobooth:screen-ingcool7` block is present in the firmware config. Other
panels usually negotiate their own mode; set `SCREEN=none`. Then set
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
