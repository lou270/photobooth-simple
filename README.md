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
- **WiFi Sharing:** Share photos via WiFi network (QR code generation)
- **Phone as a Remote Camera:** Guests photograph anywhere at the event from their own phone and print it at the booth

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
                        │   Review    │                 │
                        │   Screen    │                 │
                        └──┬────┬───┬─┘                 │
                           │    │   │                   │
                      Print│    │   │Share              │
                           ▼    │   ▼                   │
                    ┌──────────┐│┌──────────┐           │
                    │  Print   │││ QR Code  │           │
                    │  Popup   │││  Popup   │           │
                    └────┬─────┘│└────┬─────┘           │
                         │Close │Close│                 │
                         └──────┴─────┘                 │
                                │ Home                  │
                                ▼                       │
                         ┌─────────────┐                │
                         │   Collect   │────────────────┘
                         │ (if printed)│                │
                         └─────────────┘                │
                                                        │
                          Home without printing ────────┘
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

- **Start Screen:** Initial screen with "Press to begin" prompt
- **Select Format Screen:** Choose between different photo layouts/formats. Skipped when a single template is installed, since there is nothing to choose
- **Countdown Screen:** Live camera preview with countdown timer before capture. The first shot waits to be asked; the following ones start on their own, and the button under the preview cancels
- **Confirm Capture Screen:** Review and validate the captured photo. Keeping it is what happens on its own after a few seconds, shown by the ring around the confirm button and restarted by any touch; retaking is the button press. The chosen filter is kept for the rest of the session
- **Processing Screen:** Collage generation in progress
- **Review Screen:** Final saved-collage screen with available actions: print, share, or go home
- **Print Popup:** Shows print progress and reports print errors while keeping the saved photo available
- **QR Code Popup:** Shows the sharing QR code without leaving the review screen
- **Remote Gallery Screen:** Photos guests sent from their phone, waiting to be printed (see [Phone as a remote camera](#phone-as-a-remote-camera))
- **Collect Screen:** Shown only after a print was sent: tells the guest their photo is on its way out of the printer, and frees the booth on a touch or after a few seconds
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

# Run automated installation (recommended)
chmod +x install.sh
./install.sh

# Or install manually
pip3 install -r requirements.txt --break-system-packages

# Run the application
python3 photoboothapp.py
```

## Customization

### Configuration File

You can edit `config.ini` to change various parameters such as:
 - **FULLSCREEN:** Full screen window mode
 - **SHARE:** Enable/disable share buttons using a QRCode
 - **REMOTE_CAPTURE:** Let guests send photos taken with their own phone (see [Phone as a remote camera](#phone-as-a-remote-camera))
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
- **Multiple Formats:** Support for various print formats (10x15 cm, 5x15 cm strips, custom sizes)
- **Duplication Support:** Automatically duplicate templates horizontally or vertically for strip printing
- **Import/Export:** Save templates as JSON files and import existing templates
- **Live Preview:** Real-time preview with scaling and duplication visualization

![Template Editor](doc/template_editor.png)

## Phone as a remote camera

The booth only sees what stands in front of it. With `REMOTE_CAPTURE = True`, every guest phone
becomes a second camera: someone photographs the speeches at the far end of the room, sends the
photo to the booth, walks over and prints it.

### What a guest does

1. Taps the QR button at the bottom right of the welcome screen, which shows two codes.
2. Scans the first: it carries the booth's WiFi credentials, so the phone joins the access point.
   The capture page usually opens by itself at that point, through the captive portal.
3. Scans the second only if it did not: that code carries the booth's address.
4. Takes a photo, checks it, sends it. The page then lists everything that phone has sent, with what
   became of it, and lets the guest take a photo back before anyone prints it.
5. Walks to the booth. The welcome screen shows a button with the number of photos waiting; tapping
   it opens the wall of photos, and tapping one prints it exactly like a photo taken at the booth.

It takes two codes because no phone reads a payload that both joins a network and opens a page. The
second one carries a literal address rather than a name: phones do not reliably send their lookups
to this network's resolver, and an address needs none. That address is `/`, so the capture page is
what the booth serves at its root while the feature is on; the gallery stays at `/gallery`.

The capture itself is done by the phone's own camera application, through a file input, rather than
by the browser. That is deliberate: `getUserMedia` is refused outside a secure context, and a booth
serving plain HTTP from its own access point has no way to offer one. Where the page *is* served
over HTTPS, it additionally offers a live viewfinder inside the page.

### What the booth does with it

Incoming photos are re-encoded before anything else. That bounds what a 12 MP phone leaves on the
disk, and it drops the EXIF block on the way, so the GPS coordinates of whoever pressed the shutter
never reach the booth or the gallery.

A photo picked at the booth is copied into the working directory as an ordinary capture, assembled
with the first single-photo template, then printed, shared and saved like any other session. It
appears in the gallery and in the USB export with the rest of the evening.

### The network, and why it is a captive portal

The booth's access point has no uplink to share, and that shapes everything. A phone joining it
decides for itself whether the network is worth staying on, and it decides by fetching a known URL
and comparing the answer byte for byte.

Handing out **no default route** was tried first, on the theory that iOS and Android read a
route-less network as local only, keep the cellular radio for the internet and use the WiFi for the
booth alone. Both vendors describe that behaviour, and the first half works. The second half does
not: with mobile data active, phones send the local traffic to the cellular interface as well, and
the booth's own address simply times out in the browser. Apple's developer forums carry the same
report, answered by their own engineer as "a bit like a bug", with disabling mobile data as the only
workaround; the ESP32 community hit it identically. So the booth does the opposite of clever.

`install.sh` gives the network a default route pointing at the booth, resolves every domain to it,
and answers the connectivity probes as a real portal does:

- A phone that has not been through the portal is redirected, which is what makes the sign-in sheet
  open on the capture page by itself.
- Once the guest has sent a photo — or tapped **Keep this WiFi connected** on the page — the same
  probes start answering exactly what each operating system expects: a bare 204 for Android, Apple's
  `Success` page, Microsoft's `Microsoft Connect Test`. The phone stops flagging the network and
  stops offering to leave it for mobile data.

The booth also serves the Captive Portal API of RFC 8908 at `/captive-portal/api`, advertised by the
DHCP option of RFC 8910, which iOS 14 and Android 11 read before falling back to probing. That URI
must be the API endpoint and not a web page: a phone that finds HTML there ignores the whole
mechanism.

What no configuration can fix: **while a guest is connected, they have no internet.** The booth has
none to give. The page says so after each send, and the flow is built around a short visit rather
than an evening spent connected. If a venue offers a spare ethernet port, or the Pi can carry a USB
WiFi dongle onto the venue's own network, sharing a real uplink (NAT from `wlan0`) removes the
trade-off entirely and makes the portal unnecessary.

### Upgrading a booth that is already installed

`install.sh` writes this configuration on a fresh install, and rewrites `/etc/dnsmasq.conf` whole,
so the simplest way to move an existing booth onto it is to run the installer again and answer *no*
to every step except the WiFi access point one:

```bash
./install.sh
```

Phones already connected keep their old lease, and its old routing, until it expires. Ask them to
forget the network and rejoin rather than wondering why nothing changed.

### Moderating

Anything sent by a phone shows up under **Admin → Phone photos** (`/admin/remote`). An unwanted photo
can be rejected, which takes it out of the booth queue while the guest still sees what happened to
it, or deleted outright. Deleting all sessions from the admin page also clears this queue.

### Settings

All in the `[Remote]` section of `config.ini`, and in the admin configuration form:

| Setting | Default | What it does |
| --- | --- | --- |
| `REMOTE_CAPTURE` | `False` | Turns the whole feature on. While off, the routes answer 404 and no QR code is shown. |
| `REMOTE_URL` | `None` | Address the QR code carries. Derived from the booth's own interface when left empty. |
| `REMOTE_MAX_UPLOAD_MB` | `12` | Largest upload accepted. |
| `REMOTE_MAX_IMAGE_PIXELS` | `2400` | Longest side kept when the photo is re-encoded. |
| `REMOTE_MAX_PER_SENDER` | `20` | Photos one phone may leave waiting. |
| `REMOTE_MAX_PENDING` | `200` | Photos the queue holds, all phones together. |
| `REMOTE_MIN_UPLOAD_INTERVAL` | `3` | Seconds a phone must wait between two sends. |

The last four exist so that one guest, or one script within WiFi range, cannot fill the booth's disk
on their own.

The QR code itself is built from the `[WiFi]` section, which every QR code the booth shows now uses,
the sharing one included:

| Setting | Default | What it does |
| --- | --- | --- |
| `WIFI_SSID` | `PhotoBooth` | Network name put in the code. Must match `ssid=` in `/etc/hostapd/hostapd.conf`. |
| `WIFI_PASSWORD` | *(empty)* | Empty for an open network, which is how `install.sh` configures it. |
| `WIFI_HIDDEN` | `False` | Only if hostapd is set to `ignore_broadcast_ssid`. |
| `WIFI_AP_ADDRESS` | `192.168.4.1` | The booth's address on that network, which the second code carries. |

`WIFI_AP_ADDRESS` cannot be guessed and is not optional on a booth running its own access point:
that network has no default route, so the address the system would pick for itself belongs to
whatever else the Pi is plugged into. Leave it empty only for a booth sitting on somebody else's
WiFi, where guessing is the right answer.

Nothing here configures hostapd; these values only describe it. Renaming the network on the Pi means
renaming it here too, otherwise the QR code invites guests onto a network that no longer exists.
Clearing `WIFI_SSID` says the booth has no access point of its own, and the QR codes then carry the
booth's address directly instead.

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
