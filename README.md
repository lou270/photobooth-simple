# Simple PhotoBooth

A photo booth for events, built to be used without explanation - tested with
3 to 5 year olds. A guest touches the screen, poses, keeps the shot and walks
away with a print, a link on their phone, or both. The operator sets the booth
up for the evening from a web page, without ever opening a terminal.

It runs on a Raspberry Pi 5 with a touchscreen, a camera (Pi Camera, DSLR or
webcam) and a dye-sub printer, and on any Linux, macOS or Windows workstation
with no hardware at all for development.

![Waiting Screen](doc/waiting.jpeg)

## Contents

- [Features](#features)
- [How a session works](#how-a-session-works)
- [Hardware](#hardware)
- [Installation](#installation)
- [Running the booth](#running-the-booth)
- [Configuration](#configuration)
- [Web interface](#web-interface)
- [Dressing the booth for an event](#dressing-the-booth-for-an-event)
- [Templates and the template editor](#templates-and-the-template-editor)
- [Guest network and QR codes](#guest-network-and-qr-codes)
- [Phone as a remote camera](#phone-as-a-remote-camera)
- [USB photo export](#usb-photo-export)
- [Security notes](#security-notes)
- [Development](#development)
- [Project layout](#project-layout)
- [Troubleshooting](#troubleshooting)
- [License](#license)

## Features

**For guests**

- **One button at a time:** touch to start, press to shoot, keep or retake, print.
- **Several layouts:** single photo, strips, grids - whatever the templates describe.
  The format screen is skipped when only one template is installed.
- **Filters:** colour, black and white, sepia and glam, previewed live on the
  finished collage (`FILTERS = True`).
- **Prints and copies:** one tap prints; the copies button counts the photos the
  guest will hold, not the sheets the printer runs.
- **Sharing:** a QR code on the review screen opens the guest's own photo on their
  phone, ready to download (`SHARE = True`).
- **Phone as a remote camera:** guests photograph anywhere at the event from their
  own phone and print the photo at the booth (`REMOTE_CAPTURE = True`).
- **Idle slideshow:** the evening's photos on the welcome screen while nobody is
  using the booth (`SLIDESHOW = True`).
- **English and French**, on the booth and on the web pages; a guest's phone gets
  its own language.

**For the operator**

- **Web admin:** every setting in a typed form with its default and its help text,
  logs, statistics, bulk download, moderation of phone photos, restart.
- **Template editor:** a browser-based layout designer with levels, images, shapes,
  photo slots and variable texts, sized from the printer's own driver.
- **Dressed for each event:** welcome title, subtitle, lettering, background
  colour and photo, and the event name and date printed on every sheet.
- **USB export:** plug a drive in and every saved session is copied onto it.
- **Unattended:** idle timeouts on every screen, a print quota (`MAX_PRINTS`),
  disk-space guard, camera recovery after a failed capture, log rotation.
- **Reproducible installs:** one interactive installer whose answers are saved, so
  the next booth is one command; a doctor script that checks the result.

**Hardware**

- **Cameras:** Raspberry Pi Camera Module 3, DSLRs through libgphoto2 (exposure
  settings for Canon, Nikon and Sony), USB webcams through OpenCV - or a synthetic
  camera for development.
- **Printers:** anything CUPS drives; DNP dye-sub printers (DS620, QW410) through
  Gutenprint, with their sheet cutting taken into account.
- **Lights:** a WS2812 ring light over SPI, and three rows of 12 V LED chevrons
  dimmed over PWM (from the Pi, or from an RP2040 for a steadier ambient level).
- **Screens:** any size, any orientation (`ROTATION`), touch or a physical button
  (Enter or Space).
- **Kiosk boot:** the booth alone on the screen from power-on, behind a boot splash
  made from the welcome picture.

## How a session works

![Select Format](doc/select_format.jpeg)
![Capture Screen](doc/capture.jpeg)
![Confirm Screen](doc/confirm.jpeg)
![Review Screen](doc/review.jpeg)

```
                 ┌───────────────┐                         ┌────────────────┐
      ┌─────────►│     Start     │── photos from phones ──►│ Remote gallery │
      │          └───────┬───────┘   (REMOTE_CAPTURE)      └───────┬────────┘
      │                  │ touch                                   │ pick one
      │                  ▼                                         │
      │          ┌───────────────┐                                 │
      │          │ Select format │ skipped with a single template  │
      │          └───────┬───────┘                                 │
      │                  │ choose                                  │
      │                  ▼                                         │
      │          ┌───────────────┐◄─────────┐                      │
      │          │   Countdown   │          │ retake,              │
      │          └───────┬───────┘          │ or next shot         │
      │                  │ press, shot      │                      │
      │                  ▼                  │                      │
      │          ┌───────────────┐          │                      │
      │          │    Confirm    │──────────┘                      │
      │          └───────┬───────┘                                 │
      │                  │ keep (on its own after a few seconds)   │
      │                  ▼                                         │
      │          ┌───────────────┐                                 │
      │          │  Processing   │◄────────────────────────────────┘
      │          └───────┬───────┘
      │                  ▼
      │    home  ┌───────────────┐  share  ┌───────────────┐
      ├──────────│    Review     │────────►│ QR code popup │
      │          └───────┬───────┘         └───────────────┘
      │                  │ print
      │                  ▼
      │          ┌───────────────┐ failure ┌───────────────┐
      └──────────│   Printing    │────────►│     Error     │
                 └───────────────┘         └───────────────┘
```

Every screen a guest can walk away from has a home button and an idle timeout
that bring the booth back to the start screen.

| Screen | What happens there |
| --- | --- |
| **Loading** | Shown from the end of the boot splash while the camera, templates, storage and web server come up, with the step in progress. |
| **Start** | "Touch to begin", under the event's title, subtitle and photo. With `SLIDESHOW = True` the evening's photos take over after a while; a touch brings the welcome screen back rather than starting a session. |
| **Select format** | Choose a layout. Skipped when a single template is installed. |
| **Countdown** | Live preview framed for the slot the photo goes into. Every shot waits for the guest to press the button, which then turns into cancel; the ring light and the chevrons count down with the screen. |
| **Confirm** | Keep the shot or take it again - nothing else. Keeping happens on its own after `AUTO_KEEP_SECONDS`, shown by the ring around the button and restarted by any touch. |
| **Processing** | The collage is assembled. |
| **Review** | The finished collage with everything still open: the filter, the number of copies, print, share, home. The session is written to disk when the guest prints, shares or leaves, so what is saved is what they chose. |
| **QR code popup** | The sharing code, over the review screen. It opens this guest's collage, not the whole gallery. |
| **Printing** | A sheet coming out of a printer for as long as the job takes, then back to the start screen on its own. A failure goes to the error screen, with the photo still saved. |
| **Remote gallery** | Photos guests sent from their phone, waiting to be printed. |
| **Copying** | Progress of a USB export. |
| **Error** | What went wrong, with *continue* when the guest can carry on, or *restart* when the booth needs an operator (full disk, camera that could not be recovered). |

## Hardware

### Cameras

| Backend | `CAMERA =` | Used for |
| --- | --- | --- |
| Raspberry Pi Camera Module 3 | `picamera2` | Preview and capture, or preview only next to a DSLR |
| DSLR through libgphoto2 | `gphoto2` | Capture with its own flash; live view as preview when there is no other camera |
| USB webcam through OpenCV | `opencv` | Preview and capture, or preview only next to a DSLR |
| Synthetic camera | `fake` | Development and tests, no hardware at all |

With `CAMERA = auto` (the default) the booth probes every backend and picks the
best combination: a Pi Camera or a webcam for the live preview and a DSLR for the
capture when both are present (calibrate the two fields of view with
`tools/calibrate_zoom.py`, which writes `CALIBRATION`), otherwise whichever camera
there is for both. Naming a backend skips the probing and starts faster.

A DSLR leaves live view after a minute without a guest and wakes up when a session
starts. Its exposure for live view and for the shot are set in `[DSLR_Liveview]`
and `[DSLR_Capture]`.

### Recommended components

| Product | Links |
| --- | --- |
| Raspberry Pi 5 (8 GB) | https://www.raspberrypi.com/products/raspberry-pi-5/ |
| Pi Camera Module 3 | https://www.raspberrypi.com/products/camera-module-3/ |
| LED ring 5 V, 12 WS2812 | https://www.az-delivery.de/en/products/rgb-led-ring-ws2812-mit-12-rgb-leds-5v-fuer-arduino?variant=18912609108064 |
| DNP DS620 printer | https://www.dnpphoto.eu/en/product-range/photo-printers/item/120-ds620 |
| Canon EOS 2000D (EU) / Rebel T7 (US) | https://global.canon/en/c-museum/product/dslr873.html |
| Ingcool 7" touchscreen | http://www.ingcool.com/wiki/7DP-CAPLCD |
| Godox MS300-V studio flash | https://store.godox.eu/en/flash-lamps/5732-godox-ms300-v-studio-flash-6952344225646.html |
| Godox BDR-W420 beauty dish 42 cm | https://store.godox.eu/en/beauty-dish/101-godox-bdr-w420-beauty-dish-420mm-white-bounce-6952344206126.html |
| Pixel TF-321 hot shoe | |
| Waveshare RP2040-Zero (optional, chevrons) | https://www.waveshare.com/wiki/RP2040-Zero |

Wiring of the ring light, the chevrons and the RP2040 is in
[INSTALLATION.md](INSTALLATION.md#led-ring-wiring).

### Tested on

- Raspberry Pi 5 (8 GB) with a Raspberry Pi Camera Module 3
- Raspberry Pi OS (Debian based)
- macOS Sonoma / Sequoia

## Installation

The full guide - what each step does, kiosk mode, boot splash, printer, DSLR,
wiring - is in **[INSTALLATION.md](INSTALLATION.md)**. In short, on a Raspberry Pi
OS or Debian machine connected to the network:

```bash
git clone https://github.com/lou270/photobooth-simple.git
cd photobooth-simple
./install.sh
```

The installer asks what hardware the booth has, installs accordingly, generates
an admin password (printed once - write it down) and saves the answers to
`setup/booth.conf`. Then check the result:

```bash
./setup/doctor.sh
```

The next booth needs no questions:

```bash
./install.sh --profile setup/booth.conf --yes
```

The installer is idempotent - it rewrites delimited blocks and generated files
rather than appending to them - and `--dry-run` shows everything it would do
without changing anything.

## Running the booth

With `AUTOSTART=yes`, `photobooth.service` starts the booth on boot, alone on the
screen inside the [cage](https://github.com/cage-kiosk/cage) compositor. The
service restarts it whenever it exits, which is also how **Restart** in the admin
page and the error screen work: the application quits and systemd starts it again.

To run it by hand:

```bash
.venv/bin/python photoboothapp.py
```

From a console, stop the service first, then run
`cage -- .venv/bin/python photoboothapp.py`. Run by hand, a restart only quits.

| Where | What |
| --- | --- |
| `logs/` | Application logs, one file per run, rotated (`LOG_RETENTION_DAYS`, `LOG_MAX_FILES`); also readable from the admin page |
| `/var/log/photobooth.log` | Standard output and errors of the service |
| `DCIM/save/<session>/` | Each saved session: the collage, the captures and the gallery thumbnail |
| `DCIM/remote/` | Photos sent from phones |
| `event/` | The welcome photo uploaded from the admin page |

## Configuration

Everything is in `config.ini`, created by the installer from
[`config.ini.example`](config.ini.example), where every option is documented.
The admin page edits the same file through a form that shows each option's
default and its name in the file, and keeps the comments of a hand-edited file.
Settings are read when the booth starts: **Save and restart the booth** at the
bottom of the form applies them.

A missing option takes its default, and an invalid value is logged and replaced
by its default rather than stopping the booth.

| Section | Holds |
| --- | --- |
| `[Global]` | `LANGUAGE` (`en`, `fr`), `FULLSCREEN`, `WINDOW_WIDTH` / `WINDOW_HEIGHT` (the panel's own mode, 1024 x 600 for the Ingcool 7"), `ROTATION` (0, 90, 180, 270 for a panel on its side), `SHARE`, `ADMIN_PASSWORD` |
| `[Event]` | `WELCOME_TITLE`, `WELCOME_SUBTITLE`, `WELCOME_FONT`, `BACKGROUND_COLOR`, `EVENT_NAME`, `DATE_FORMAT` - see [Dressing the booth](#dressing-the-booth-for-an-event) |
| `[Slideshow]` | `SLIDESHOW`, `SLIDESHOW_IDLE_SECONDS`, `SLIDESHOW_PHOTO_SECONDS` |
| `[Capture]` | `CAMERA`, `COUNTDOWN`, `FILTERS`, `CALIBRATION`, `DSLR_HOT_PIXEL_FILTER`, the blur behind the preview and the photos |
| `[Print]` | `PRINTER` (CUPS queue, `None` for no printer), `MAX_PRINTS` (quota for the evening), `MAX_COPIES`, `COLLAGE_DPI`, `CUT_OFFSET`, `PRINTER_WAIT_TIMEOUT` |
| `[Timing]` | Every delay a guest may notice: auto-keep, idle timeouts per screen, capture timeout, print timeouts |
| `[Lights]` | `RINGLED`, `RINGLED_PIXELS`; `CHEVRONS`, `CHEVRONS_DRIVER` (`gpio` or `serial`), `CHEVRONS_PINS`, `CHEVRONS_SERIAL_PORT`, `CHEVRONS_IDLE_PERCENT`, `CHEVRONS_PWM_FREQUENCY` |
| `[Web]` | `WEB_PORT` (80), `WEB_HOST` (0.0.0.0; 127.0.0.1 keeps the web pages on the booth) |
| `[WiFi]` | `WIFI_SSID`, `WIFI_PASSWORD`, `WIFI_HIDDEN` - the network the QR codes join, see [Guest network](#guest-network-and-qr-codes) |
| `[Remote]` | `REMOTE_CAPTURE`, `REMOTE_URL` and the upload limits, see [Phone as a remote camera](#phone-as-a-remote-camera) |
| `[Storage]` | `DCIM_DIRECTORY`, and the free-space floor below which the booth stops taking sessions (`DISK_MIN_FREE_GB`, `DISK_MAX_USED_PERCENT`) |
| `[USB]` | `USB_EXPORT`, `USB_MIN_FREE_GB` |
| `[Log]` | `LOG_RETENTION_DAYS`, `LOG_MAX_FILES` |
| `[DSLR_Liveview]`, `[DSLR_Capture]` | `SHUTTERSPEED`, `APERTURE`, `FOCUSMODE`, `ISO`, applied to the camera for live view and for the shot (Canon, Nikon and Sony profiles) |

## Web interface

The booth serves its web pages on port 80 of its own address (`WEB_PORT`).

| Page | Who | What |
| --- | --- | --- |
| `/` | Guests | The latest collage, or the capture page when `REMOTE_CAPTURE` is on |
| `/gallery` | Guests | Every collage of the evening, newest first |
| `/collage/<session>` | Guests | One collage with a download button: where the sharing QR code leads |
| `/remote` | Guests | Send a photo from a phone (when `REMOTE_CAPTURE` is on) |
| `/admin` | Operator | Settings, welcome photo, delete all sessions, restart |
| `/admin/editor` | Operator | Template editor |
| `/admin/remote` | Operator | Photos sent from phones: reject or delete |
| `/admin/logs` | Operator | Application logs |
| `/stats` | Operator | Usage statistics and print quota |
| `/download/all-photos` | Operator | Every photo of the evening as one ZIP, streamed |

The operator pages need `ADMIN_PASSWORD`: at least 10 characters and not a
well-known value, or the admin stays disabled while the booth keeps taking
photos. Five wrong attempts lock a client out for five minutes. A login lasts 30
days, and changing the password logs every other browser out.

## Dressing the booth for an event

Everything here is set on site from the admin page, in the *Event* section of the
settings, and applied on the next start of the booth.

### The welcome screen

- **Photo:** the *Welcome screen photo* card takes a JPEG, PNG or WebP. The booth
  re-encodes it as a JPEG no wider than 3840 pixels and keeps it in
  `event/welcome_background.jpg`, outside the photo directory, so deleting the
  evening's sessions leaves it in place. *Back to the booth's own photo* removes it.
- **Title and subtitle:** `WELCOME_TITLE` replaces "Photo Booth" and can be a whole
  sentence: it breaks between words onto lines of even length and is drawn as large
  as the screen allows. `WELCOME_SUBTITLE` adds a line under it, below a thin rule.
- **Lettering:** `WELCOME_FONT` is `elegant` (Playfair Display, the default),
  `script` (Great Vibes), `modern` (Montserrat) or `playful` (Fredoka).
- **Colour:** `BACKGROUND_COLOR` is the colour behind the screens without a photo.

### Text on the prints

A template can carry variable text boxes, added in the template editor with
**Variable**. The text is sized to fill its box - a long event name shrinks instead
of running off the sheet. Its font is Roboto unless the box names one of the
welcome screen's letterings in `font`: `playfair`, `great-vibes`, `montserrat` or
`fredoka` (Playfair Display and Great Vibes have no bold face).

| Placeholder | Prints as |
| --- | --- |
| `{event}` | `EVENT_NAME` from the `[Event]` section |
| `{date}` | the day the photo is taken, formatted by `DATE_FORMAT` (`%d/%m/%Y` by default) |
| `{time}` | the time the photo is taken, as hours:minutes |

Anything else between braces prints as written. In a template file:

```json
"texts": [
  {"x": 600, "y": 1020, "width": 600, "height": 120,
   "text": "{event}\n{date}", "color": "#a0522d", "align": "center", "bold": true,
   "font": "montserrat"}
]
```

### The idle slideshow

Off by default. With `SLIDESHOW = True`, the welcome screen shows the evening's
collages, newest first, once nobody has touched it for `SLIDESHOW_IDLE_SECONDS`
(60), each for `SLIDESHOW_PHOTO_SECONDS` (6). It waits while the phone codes are
open and does not start before the first photo of the evening. A touch brings the
welcome screen back without starting a session; a physical button starts one.

## Templates and the template editor

A template is a JSON file in `templates/`: the page size, the photo slots, the
images and texts drawn around them, and the print options. The booth picks up a
template saved or deleted from the editor without a restart, once the guest in
front of it has finished. A file the booth refuses is listed in the editor with
the reason, and the booth falls back to a built-in layout rather than start with
none.

The editor is at `/admin/editor`:

![Template Editor](doc/template_editor.png)

- **Levels:** a design is a stack of levels, like layers in a drawing program:
  named, reordered, hidden (a hidden level is not printed), locked, each with its
  own opacity. Decoration may sit under the photos, over part of them, or between
  two of them.
- **Elements:** PNG, JPEG or WebP images (transparency kept; from the toolbar, by
  dropping them on the page or by pasting), rectangles with rounded corners,
  ellipses, lines, fixed text in the welcome screen's letterings, photo slots and
  variable texts. Every element has a position, size, rotation and opacity; photo
  slots and variable texts are not rotated, since the booth draws those itself.
- **Canvas:** zoom (Ctrl + wheel) and pan (wheel, or Ctrl + drag), snapping to the
  page and to other elements, optional grid, multiple selection, align and
  distribute, undo and redo, copy, paste, duplicate, arrow keys to nudge.
- **Print format:** the list comes from the printer's own driver, so it offers
  what that printer can actually cut: on a DNP QW410, `2x4*3` is a 4x6 sheet cut
  into three 2x4 prints. Picking one sizes the page to one print, and the booth
  repeats it on the sheet as many times as the printer cuts it. Without a printer,
  the editor offers the QW410's sizes; a custom size is always possible.
- **Booth preview:** the booth's own assembly of the template with sample photos,
  next to the editor's drawing, to check the two agree before the evening.
- **Import / export:** a template exports as one JSON file with its images inside,
  which another booth can import.
- **Images:** a photo heavier than 12 MB or larger than 40 megapixels is scaled
  down in the browser to what the page can show at 600 dpi before it is sent.

When a design is saved, each run of decoration between two photo slots or
variable texts is flattened by the browser into one image at 600 dpi and stored in
`templates/assets/` under a name made from its content. The template keeps the
drawing order in `stack` and the editable design in `design`, so the booth only
stacks images, photos and texts and prints exactly what the editor showed. Images
no template mentions are removed from `templates/assets/` a day after they were
last used. Templates written before levels existed, with a `background` and a
`foreground`, still print as they always did and open in the editor as three
levels.

## Guest network and QR codes

Both features that reach a guest's phone - sharing a photo and sending one from a
phone - work over a network the booth **joins**, like any other machine. The booth
creates no network: `install.sh` installs no access point, DHCP, DNS or captive
portal.

### Choosing the network

- **A travel router beside the booth** (recommended). The booth joins it over
  ethernet or WiFi, guests join its WiFi. It needs no internet: everything the
  phones open is served by the booth.
- **The venue's WiFi**, when guests are on it anyway. Check that it lets two
  devices talk to each other: many public networks isolate their clients.

Either way, give the booth a stable address - a DHCP reservation on the router is
the simplest - so the codes do not change during the evening.

### What the codes carry

| Code | Shown on | Opens |
| --- | --- | --- |
| Share | the review screen, when `SHARE = True` | `/collage/<session>`: this guest's collage, with a download button |
| Send a photo | the welcome screen, when `REMOTE_CAPTURE = True` | `/remote`: the capture page |

When `WIFI_SSID` is set, each popup shows two codes side by side: the first joins
that network, the second opens the page (no phone reads a code that does both).
When it is empty, only the address code is shown.

The address is derived, each time a code is drawn, from the interface the booth
uses to reach its network. Set `REMOTE_URL` when that guess is wrong - a booth
with both ethernet and WiFi, a fixed hostname, a port forward.
`./setup/doctor.sh` reports the address the codes will carry.

Pressing share saves the session there and then, with the look the guest picked,
so the photo their phone opens is the one on screen. A phone quick enough to open
the link while the booth is still writing gets a page that waits and reloads.

### Settings

| Setting | Default | What it does |
| --- | --- | --- |
| `WIFI_SSID` | *(empty)* | Network name put in the joining code. Empty shows the address code alone. |
| `WIFI_PASSWORD` | *(empty)* | Empty for an open network. |
| `WIFI_HIDDEN` | `False` | Only for a network that does not broadcast its name. |
| `REMOTE_URL` | `None` | Address both codes carry. Derived from the booth's own interface when empty. |

These settings describe the network for the QR codes; changing them changes
nothing on the network itself.

## Phone as a remote camera

The booth only sees what stands in front of it. With `REMOTE_CAPTURE = True`,
every guest phone becomes a second camera: someone photographs the speeches at
the far end of the room, sends the photo to the booth, walks over and prints it.

### What a guest does

1. Taps the QR button at the bottom right of the welcome screen.
2. Scans the codes it shows: the network one first, if there is one, then the
   address one.
3. Takes a photo, checks it, sends it. The page then lists everything that phone
   has sent, with what became of it, and lets the guest take a photo back before
   anyone prints it.
4. Walks to the booth. The welcome screen shows a button with the number of photos
   waiting; tapping one prints it exactly like a photo taken at the booth.

The capture page is what the booth serves at `/` while the feature is on; the
gallery stays at `/gallery`.

The photo is taken by the phone's own camera application, through a file input,
rather than by the browser: `getUserMedia` is refused outside a secure context,
and a booth serving plain HTTP cannot offer one. Where the page *is* served over
HTTPS, it also offers a live viewfinder. On a network with no internet, Android
may move the phone back onto mobile data; the page tells guests which option to
pick to stay connected.

### What the booth does with it

Incoming photos are re-encoded before anything else. That bounds what a 12 MP
phone leaves on the disk, and drops the EXIF block on the way, so the GPS
coordinates of whoever pressed the shutter never reach the booth or the gallery.

A photo picked at the booth becomes an ordinary session: assembled with the first
single-photo template, then printed, shared and saved like any other. It appears
in the gallery and in the USB export with the rest of the evening.

### Moderating

Anything sent by a phone shows up under **Admin → Phone photos**
(`/admin/remote`). An unwanted photo can be rejected, which takes it out of the
booth queue while the guest still sees what happened to it, or deleted outright.
Deleting all sessions from the admin page also clears this queue.

### Settings

| Setting | Default | What it does |
| --- | --- | --- |
| `REMOTE_CAPTURE` | `False` | Turns the whole feature on. While off, the routes answer 404 and no QR code is shown. |
| `REMOTE_MAX_UPLOAD_MB` | `12` | Largest upload accepted. |
| `REMOTE_MAX_IMAGE_PIXELS` | `2400` | Longest side kept when the photo is re-encoded. |
| `REMOTE_MAX_PER_SENDER` | `20` | Photos one phone may leave waiting. |
| `REMOTE_MAX_PENDING` | `200` | Photos the queue holds, all phones together. |
| `REMOTE_MIN_UPLOAD_INTERVAL` | `3` | Seconds a phone must wait between two sends. |

`REMOTE_MAX_PENDING` is what bounds the disk space phones can use; the per-phone
limits are counted per browser and only keep a single guest from filling the
queue by accident.

## USB photo export

A background thread watches for removable drives mounted under `/media`,
`/run/media` or `/Volumes`:

- Insert a FAT32 or exFAT drive while the booth is on its welcome screen (an
  insertion during a session waits for it to end).
- The booth copies every saved session into a `photobooth/` folder on the drive,
  skipping files already there, and shows its progress on screen.
- Wait for the booth to return to the welcome screen before removing the drive.

Without a desktop, the installer adds a udev rule that mounts such drives.
`USB_EXPORT = False` turns the feature off; `USB_MIN_FREE_GB` refuses a drive with
too little room.

## Security notes

- The booth serves plain HTTP. On a shared or open WiFi, the admin password and
  the admin cookie travel in clear: administer the booth from a network guests are
  not on, or set `WEB_HOST = 127.0.0.1` to keep the web pages on the booth itself.
- `/gallery` and the collages are open to anyone on the booth's network, whatever
  `SHARE` says: `SHARE` only shows or hides the button on the review screen.
- `config.ini` holds the admin password and `.web_session_key` signs the admin
  cookie: neither is in the repository, and neither should be.
- The installer opens CUPS's administration to the network
  (`cupsctl --remote-admin --remote-any`) so the printer can be managed from
  `https://<booth-ip>:631/admin/`; it is protected by the system account's password.

## Development

The application runs without any hardware: the camera is replaced by a synthetic
one, and the printer, the ring light and the chevrons degrade to no-ops.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp config.ini.example config.ini
```

In `config.ini`, set `CAMERA = fake` (and keep `FULLSCREEN = False`), then:

```bash
.venv/bin/python photoboothapp.py
```

The web pages are then at `http://localhost/` (or set `WEB_PORT = 5000` where
port 80 needs privileges).

The test suite needs no camera, no printer and no light:

```bash
.venv/bin/python -m pytest test/
```

The tests that build Kivy screens need a display; on a headless machine run them
under Xvfb:

```bash
xvfb-run -a .venv/bin/python -m pytest test/
```

`tools/manual/` holds scripts meant to be run by hand on the booth: camera checks
per backend, the ring light's effects, every template's preview, a sheet that
shows where a printer cuts (`cut_calibration.py`), and a countdown stress test.

`ROTATION` is verified on the Linux path the booth runs; on Windows, Kivy draws a
rotated interface into a corner of the window, so leave it at 0 there.

## Project layout

```
photoboothapp.py        Application entry point: startup steps, session flow
libs/
  config.py             config.ini reader, with a fallback for every value
  core/                 Session storage (DCIM/tmp, DCIM/save) and background jobs
  screens/              One Kivy screen per step of a session
  hardware/             Camera contract and fake camera, ring light, chevrons
  device_utils.py       Camera backends (Picamera2, gPhoto2, OpenCV) and CUPS printer
  gphoto2.py            ctypes binding to libgphoto2
  template_collage.py   Assembles a template with the photos, for screen and print
  template_schema.py    Validates template files
  print_sizes.py        Page sizes and cutting read from the printer's PPD
  imaging/              Filters and DSLR hot-pixel removal
  webserver/            Flask server: gallery, admin, JSON API, remote camera
  remote_store.py       Queue of photos sent from phones
  stats_store.py        Usage statistics and print quota
  usb_transfer.py       USB export
  event.py, i18n.py,    Event texts and fonts, translations, tunable delays,
  timings.py, ...       network addresses, shared Kivy widgets
web/                    HTML pages, the template editor and its assets
locales/                en.json, fr.json
templates/              Print templates (JSON) and their images
assets/                 Backgrounds, fonts, sample photos
firmware/               MicroPython firmware for the RP2040 driving the chevrons
setup/                  Installer library, systemd/udev/PAM templates, doctor
tools/                  Doctor, boot splash builder, zoom calibration, manual checks
test/                   pytest suite
doc/                    Screenshots, Photoshop overlays, DS620 PPD
```

## Troubleshooting

Start with `./setup/doctor.sh`: it checks the Python environment, `config.ini`
and the admin password, the camera backends, the printer queue, the lights, free
disk space, the systemd units, the web server and the address the QR codes carry.
Common problems and their fixes are in
[INSTALLATION.md](INSTALLATION.md#troubleshooting).

## Contributing

Contributions are welcome: open an issue or a pull request. Please run the test
suite before submitting.

## License

This project is open source and available under the MIT License.

It ships third-party files under their own licenses: Fabric.js
(`web/assets/vendor/fabric/`, MIT), and the welcome screen fonts
(`assets/fonts/welcome/`, SIL Open Font License, whose text sits next to each font).
