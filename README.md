# Simple PhotoBooth

A simple and intuitive photobooth application designed to be easy to use, even for young children (tested with 3-5 year olds). This project provides a straightforward photo-taking experience without unnecessary complexity.

## Features

- **Multiple Camera Support:** Compatible with Raspberry Pi Camera Module 3, DSLR cameras (via gPhoto2), and USB webcams
- **Intelligent Camera Selection:** Automatically uses the best available camera (DSLR for capture, Pi Camera for preview)
- **Direct Printing:** Support for DNP DS620 and other CUPS-compatible printers
- **LED Ring Effects:** Visual feedback with WS2812 LED ring support
- **USB Photo Export:** Automatic photo dump to USB drives
- **Multiple Photo Formats:** Support for different collage layouts
- **Touch Screen Interface:** Optimized for 7" Ingcool touchscreen and above
- **Photo Sharing:** A QR code on the review screen opens the guest's own photo on their phone, ready to download
- **Phone as a Remote Camera:** Guests photograph anywhere at the event from their own phone and print it at the booth
- **Dressed for Each Event:** Welcome title, subtitle and photo set from the admin page, and the event name and date printed on every sheet
- **Idle Slideshow (optional):** The evening's photos on the welcome screen while nobody is using the booth

## Screenshots

![Waiting Screen](doc/waiting.jpeg)
![Select Format](doc/select_format.jpeg)
![Capture Screen](doc/capture.jpeg)
![Capture Screen](doc/confirm.jpeg)
![Review Screen](doc/review.jpeg)

## Screen Flow

The photobooth application follows this screen navigation flow:

```
                        ┌─────────────┐
                        │    Start    │◄────────────────┐
                        │   Screen    │                 │
                        └──────┬──────┘                 │
                               │ Touch                  │
                               ▼                        │
                        ┌─────────────┐                 │
                        │   Select    │ (skipped when   │
                        │   Format    │  one template)  │
                        └──────┬──────┘                 │
                               │ Choose                 │
                               ▼                        │
                        ┌─────────────┐                 │
           ┌───────────►│  Countdown  │◄── auto-starts  │
           │            │   Screen    │    from shot 2  │
           │            └──────┬──────┘                 │
           │ Retake            │ Capture                │
           │                   ▼                        │
           │            ┌─────────────┐                 │
           └────────────┤   Confirm   │ auto-validates  │
                        │   Capture   │ after a few s   │
                        └──────┬──────┘                 │
                               │ Validate               │
                               ▼                        │
                        ┌─────────────┐                 │
                        │ Processing  │                 │
                        │   Screen    │                 │
                        └──────┬──────┘                 │
                               │ Done                   │
                               ▼                        │
                        ┌─────────────┐                 │
                        │   Review    │ look, copies,   │
                        │   Screen    │ print, share    │
                        └──┬────┬───┬─┘                 │
                           │    │   │Share              │
                      Print│    │   ▼                   │
                           │    │ ┌──────────┐          │
                           │    │ │ QR Code  │          │
                           │    │ │  Popup   │          │
                           │    │ └────┬─────┘          │
                           │    │Home  │Close           │
                           │    └──────┴────────────────┤
                           ▼                            │
                    ┌─────────────┐                     │
                    │  Printing   │─────────────────────┘
                    │   Screen    │ (or Error)          │
                    └─────────────┘                     │
                                                        │
                                                        │
           ┌─────────────┐                              │
           │    Error    │──────────────────────────────┘
           └─────────────┘

Note: All screens have a "Home" button to return to the Start Screen

Second entry point, when REMOTE_CAPTURE is enabled: from the Start Screen, the
button counting the photos phones have sent opens the Remote Gallery, and
picking one there joins the flow at the Processing Screen.
```

### Screen Descriptions

- **Start Screen:** Initial screen with "Press to begin" prompt, under the event's own title, subtitle and photo when the operator set them. With `SLIDESHOW = True`, the evening's photos take over the screen after a while without a touch; a touch brings the welcome screen back rather than starting a session
- **Select Format Screen:** Choose between different photo layouts/formats. Skipped when a single template is installed, since there is nothing to choose
- **Countdown Screen:** Live camera preview with countdown timer before capture. The first shot waits to be asked; the following ones start on their own, and the button under the preview cancels
- **Confirm Capture Screen:** Keep the shot or take it again — nothing else. Keeping is what happens on its own after a few seconds, shown by the ring around the confirm button and restarted by any touch; retaking is the button press
- **Processing Screen:** Collage generation in progress
- **Review Screen:** The finished collage and everything still open: the filter, applied to the whole collage and previewed live; the number of copies, on a button that cycles through them and counts the photos the guest will hold rather than the sheets the printer runs; print, share, or go home. The session is written to disk when the guest prints, shares or leaves, so what is saved is what they chose, and the filter is fixed from then on. Sharing comes before printing, since printing is what ends the session
- **Printing Screen:** A sheet coming out of a printer for as long as the job takes, then back to the welcome screen on its own — pressing print ends the session, so the booth frees itself for the next guest. A failure goes to the Error screen instead, saying so, with the photo still saved
- **QR Code Popup:** Shows the sharing QR code without leaving the review screen. It opens this guest's collage, not the whole gallery (see [Guest network and QR codes](#guest-network-and-qr-codes))
- **Remote Gallery Screen:** Photos guests sent from their phone, waiting to be printed (see [Phone as a remote camera](#phone-as-a-remote-camera))
- **Error Screen:** Displayed when an error occurs during the process
- **Maintenance Screen:** Displayed for operator intervention, such as storage, camera, web server, printer, or USB export issues

## Camera Support

The application is compatible with multiple camera types:

- **Raspberry Pi Camera Module 3** (recommended)
- **DSLR cameras** via gPhoto2 (e.g., Canon EOS 2000D/Rebel T7)
- **USB webcams** via OpenCV

The application automatically selects the best available camera configuration:
- If a Pi Camera is connected, it's used for live preview
- If a DSLR is connected, it's used for high-quality photo capture
- If only one camera type is available, it's used for both preview and capture

## Compatibility

Tested on:
- macOS Sonoma/Sequoia
- Raspberry Pi 5 (8GB) with Raspberry Pi Camera Module 3
- Raspberry Pi OS (Debian-based)

## Recommended Hardware Components
| Product                              | Links                                                                                                             |
|--------------------------------------|-------------------------------------------------------------------------------------------------------------------|
| Raspberry Pi 5                       | https://www.raspberrypi.com/products/raspberry-pi-5/                                                              |
| Pi camera module 3                   | https://www.raspberrypi.com/products/camera-module-3/                                                             |
| Led Ring 5V - 12 bits                | https://www.az-delivery.de/en/products/rgb-led-ring-ws2812-mit-12-rgb-leds-5v-fuer-arduino?variant=18912609108064 |
| DNP DS620 printer                    | https://www.dnpphoto.eu/en/product-range/photo-printers/item/120-ds620                                            |
| Canon EOS 2000D (EU) / Rebel T7 (US) | https://global.canon/en/c-museum/product/dslr873.html                                                             |
| Ingcool 7" touchscreen               | http://www.ingcool.com/wiki/7DP-CAPLCD                                                                            |
| Godox Flash MS300V                   | https://store.godox.eu/en/flash-lamps/5732-godox-ms300-v-studio-flash-6952344225646.html                          |
| Godox BDR-W420 Beauty Dish 42cm      | https://store.godox.eu/en/beauty-dish/101-godox-bdr-w420-beauty-dish-420mm-white-bounce-6952344206126.html        |
| Pixel TF-321 Hot Shoe                |                                                                                                                   |

## Installation

For detailed installation instructions, please see [INSTALLATION.md](INSTALLATION.md).

### Quick Start

```bash
# Clone the repository
git clone https://github.com/IArchi/py-photobooth-simple.git
cd py-photobooth-simple

# Build the booth. Asks what hardware it has, then saves the answers.
./install.sh

# Check it is actually ready
./setup/doctor.sh

# Run the application
.venv/bin/python photoboothapp.py
```

Building a second booth costs one command, because the first run saved its answers to
`setup/booth.conf`:

```bash
./install.sh --profile setup/booth.conf --yes
```

The installer is safe to re-run: it rewrites delimited blocks and generated files rather than
appending to them, so a second pass changes nothing. Use `--dry-run` to see what it would do
first.

## Customization

### Configuration File

You can edit `config.ini` to change various parameters such as:
 - **FULLSCREEN:** Full screen window mode
 - **WINDOW_WIDTH / WINDOW_HEIGHT:** Size of the booth window in pixels, and the mode fullscreen runs at (1024 x 600 for the Ingcool 7" panel, 1920 x 1080 for a full HD monitor)
 - **ROTATION:** Quarter turn for a panel mounted on its side (0, 90, 180, 270), applied by the booth itself so no desktop or touchscreen configuration is needed
 - **SHARE:** Enable/disable the share button, whose QR code opens the guest's own photo
 - **REMOTE_CAPTURE:** Let guests send photos taken with their own phone (see [Phone as a remote camera](#phone-as-a-remote-camera))
 - **WELCOME_TITLE / WELCOME_SUBTITLE / EVENT_NAME / DATE_FORMAT:** The event's words on the welcome screen and on the prints (see [Dressing the booth for an event](#dressing-the-booth-for-an-event))
 - **SLIDESHOW:** Show the evening's photos on the welcome screen while nobody is using the booth
 - **RINGLED:** Enable/disable RingLed functionality (set to `False` if you don't have RingLed hardware)
 - **COUNTDOWN:** Countdown time before photo capture
 - **DCIM_DIRECTORY:** Directory where photos and collages are stored
 - **PRINTER:** Printer's name in CUPS
 - **CALIBRATION:** Calibration matrix for hybrid mode (DSLR + piCamera or DSLR + webcam) from `tools/calibrate_zoom.py`

### Web server

You can edit configuration file and download photos from <localip>:<WEB_PORT>.

### Template Editor

The application includes a **visual template editor** - a browser-based tool for creating and customizing photo layouts without coding.
The editor is reachable from `<localip>:<WEB_PORT>/admin/editor` after admin authentication.

- **Visual Canvas:** Interactive canvas with grid snapping for precise positioning
- **Photo Frames:** Add, move, resize, and delete photo placeholders
- **Background/Foreground Layers:** Import decorative backgrounds and overlay frames
- **Text Boxes:** Printed text with `{event}`, `{date}` and `{time}` placeholders, previewed in the booth's own font with today's values
- **Multiple Formats:** Support for various print formats (10x15 cm, 5x15 cm strips, custom sizes)
- **Duplication Support:** Automatically duplicate templates horizontally or vertically for strip printing
- **Import/Export:** Save templates as JSON files and import existing templates
- **Live Preview:** Real-time preview with scaling and duplication visualization

![Template Editor](doc/template_editor.png)

## Dressing the booth for an event

Everything here is set on site from the admin page, and applied on the next start of the booth
(**Restart app** on the same page).

### The welcome screen

- **Photo:** the *Welcome screen photo* card takes a JPEG, PNG or WebP. The booth re-encodes it as a
  JPEG no wider than 3840 pixels and keeps it in `event/welcome_background.jpg`, outside the photo
  directory, so deleting the evening's sessions leaves it in place. *Back to the booth's own photo*
  removes it.
- **Title and subtitle:** `WELCOME_TITLE` replaces "PHOTO BOOTH" when set; `WELCOME_SUBTITLE` adds a
  line under it, outlined so it stays readable on any photo.

### Text on the prints

A template can carry text boxes, added in the template editor with **+ Add Text**. The text is sized
to fill its box - a long event name shrinks instead of running off the sheet - and drawn over the
foreground layer, in Roboto, the font Kivy already ships.

| Placeholder | Prints as |
| --- | --- |
| `{event}` | `EVENT_NAME` from the `[Event]` section |
| `{date}` | the day the photo is taken, formatted by `DATE_FORMAT` (`%d/%m/%Y` by default) |
| `{time}` | the time the photo is taken, as hours:minutes |

Anything else between braces prints as written. In a template file, a box looks like this:

```json
"texts": [
  {"x": 600, "y": 1020, "width": 600, "height": 120,
   "text": "{event}\n{date}", "color": "#a0522d", "align": "center", "bold": true}
]
```

### The idle slideshow

Off by default. With `SLIDESHOW = True` in the `[Slideshow]` section, the welcome screen shows the
evening's collages, newest first, once nobody has touched it for `SLIDESHOW_IDLE_SECONDS` (60), each
for `SLIDESHOW_PHOTO_SECONDS` (6). It waits while the phone codes are open, and does not start before
the first photo of the evening exists. A touch brings the welcome screen back without starting a
session; a physical button starts one directly.

## Guest network and QR codes

Both features that reach a guest's phone - sharing a photo and sending one from a phone - work over a
network the booth **joins**, like any other machine. The booth does not create that network and
configures nothing on it: `install.sh` installs no access point, no DHCP or DNS server and no captive
portal.

### Choosing the network

- **A travel router beside the booth** (recommended). The booth joins it over ethernet or WiFi, guests
  join its WiFi. It needs no internet: everything the phones open is served by the booth itself.
- **The venue's WiFi**, when guests are on it anyway. Check that it lets two devices talk to each other:
  many public networks isolate their clients, and the phones then never reach the booth.

Either way, give the booth a stable address - a DHCP reservation on the router is the simplest - so the
codes do not change during the evening.

### What the codes carry

| Code | Shown on | Opens |
| --- | --- | --- |
| Share | the review screen, when `SHARE = True` | `/collage/<session>`: this guest's collage, with a download button |
| Send a photo | the welcome screen, when `REMOTE_CAPTURE = True` | `/remote`: the capture page |

When `WIFI_SSID` is set, each popup shows two codes side by side: the first joins that network, the
second opens the page. It takes two because no phone reads a payload that both joins a network and
opens a page. When `WIFI_SSID` is empty, only the address code is shown, for guests who are on the
network already.

The address in the codes is derived, each time a code is drawn, from the interface the booth uses to
reach its network. Set `REMOTE_URL` when that guess is wrong - a booth with both ethernet and WiFi, a
fixed hostname, a port forward.

Pressing share saves the session there and then, with the look the guest picked, so the photo their
phone opens is the one on screen. A phone quick enough to open the link while the booth is still
writing gets a page that waits and reloads until the collage is there.

### Settings

In the `[WiFi]` section of `config.ini`, and in the admin configuration form. They describe the network
for the QR code; changing them changes nothing on the network itself.

| Setting | Default | What it does |
| --- | --- | --- |
| `WIFI_SSID` | *(empty)* | Network name put in the joining code. Empty shows the address code alone. |
| `WIFI_PASSWORD` | *(empty)* | Empty for an open network. |
| `WIFI_HIDDEN` | `False` | Only for a network that does not broadcast its name. |

`REMOTE_URL`, in the `[Remote]` section, sets the address both codes carry (see below).

`./setup/doctor.sh` reports the address the codes will carry, and warns when the booth has none.

## Phone as a remote camera

The booth only sees what stands in front of it. With `REMOTE_CAPTURE = True`, every guest phone
becomes a second camera: someone photographs the speeches at the far end of the room, sends the
photo to the booth, walks over and prints it.

### What a guest does

1. Taps the QR button at the bottom right of the welcome screen.
2. Scans the codes it shows: the network one first, if there is one, then the address one (see
   [Guest network and QR codes](#guest-network-and-qr-codes)).
3. Takes a photo, checks it, sends it. The page then lists everything that phone has sent, with what
   became of it, and lets the guest take a photo back before anyone prints it.
4. Walks to the booth. The welcome screen shows a button with the number of photos waiting; tapping
   it opens the wall of photos, and tapping one prints it exactly like a photo taken at the booth.

The capture page is also what the booth serves at its root (`/`) while the feature is on; the
gallery stays at `/gallery`.

The capture itself is done by the phone's own camera application, through a file input, rather than
by the browser. That is deliberate: `getUserMedia` is refused outside a secure context, and a booth
serving plain HTTP has no way to offer one. Where the page *is* served over HTTPS, it additionally
offers a live viewfinder inside the page.

On a network with no internet, Android warns about it and may move the phone back onto mobile data,
at which point the booth stops answering. The page tells guests which option to pick in that
notification to stay connected.

### What the booth does with it

Incoming photos are re-encoded before anything else. That bounds what a 12 MP phone leaves on the
disk, and it drops the EXIF block on the way, so the GPS coordinates of whoever pressed the shutter
never reach the booth or the gallery.

A photo picked at the booth is copied into the working directory as an ordinary capture, assembled
with the first single-photo template, then printed, shared and saved like any other session. It
appears in the gallery and in the USB export with the rest of the evening.

### Moderating

Anything sent by a phone shows up under **Admin → Phone photos** (`/admin/remote`). An unwanted photo
can be rejected, which takes it out of the booth queue while the guest still sees what happened to
it, or deleted outright. Deleting all sessions from the admin page also clears this queue.

### Settings

All in the `[Remote]` section of `config.ini`, and in the admin configuration form:

| Setting | Default | What it does |
| --- | --- | --- |
| `REMOTE_CAPTURE` | `False` | Turns the whole feature on. While off, the routes answer 404 and no QR code is shown. |
| `REMOTE_URL` | `None` | Address every QR code carries, the sharing one included. Derived from the booth's own interface when left empty. |
| `REMOTE_MAX_UPLOAD_MB` | `12` | Largest upload accepted. |
| `REMOTE_MAX_IMAGE_PIXELS` | `2400` | Longest side kept when the photo is re-encoded. |
| `REMOTE_MAX_PER_SENDER` | `20` | Photos one phone may leave waiting. |
| `REMOTE_MAX_PENDING` | `200` | Photos the queue holds, all phones together. |
| `REMOTE_MIN_UPLOAD_INTERVAL` | `3` | Seconds a phone must wait between two sends. |

The last four exist so that one guest, or one script within WiFi range, cannot fill the booth's disk
on their own.

## USB Photo Export

A dedicated background thread monitors for USB drives and automatically exports all photos:

- Insert a FAT32-formatted USB drive
- The application will automatically copy all photos from the `DCIM_DIRECTORY` to the USB drive
- A progress screen is displayed during the copy process
- Safely remove thUe USB drive when the process completes

**Important:** USB drives must be formatted as FAT32 for compatibility.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is open source and available under the MIT License.

## Support

For detailed installation instructions, troubleshooting, and configuration options, please refer to [INSTALLATION.md](INSTALLATION.md).
