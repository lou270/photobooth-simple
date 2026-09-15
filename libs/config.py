import configparser
import ast
import logging
from datetime import datetime
from pathlib import Path

from libs import event
from libs.event import DEFAULT_DATE_FORMAT
from libs.i18n import AVAILABLE_LANGUAGES, DEFAULT_LANGUAGE
from libs import timings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / 'config.ini'

# Child of Kivy's logger so records land in the application log when Kivy is
# running, without importing Kivy here: config must stay readable headless.
Logger = logging.getLogger('kivy.photobooth')

# Capture backends accepted by CAMERA. 'auto' probes the hardware, 'fake'
# runs the whole application with a synthetic camera and no hardware at all.
CAMERA_BACKENDS = ('auto', 'gphoto2', 'picamera2', 'opencv', 'fake')

# Resolutions COLLAGE_DPI accepts. Templates are laid out at 300 dpi, which is
# what a dye-sub printer prints; 600 only makes the saved file sharper on a
# screen, at four times the pixels to assemble.
COLLAGE_DPIS = (300, 600)
DEFAULT_COLLAGE_DPI = 300

# Window size used when config.ini says nothing: the 7" Ingcool panel the booth
# is built around. Below MIN_WINDOW_SIDE the interface, sized in fractions of
# the shortest side, stops being touchable.
DEFAULT_WINDOW_SIZE = (1024, 600)
MIN_WINDOW_SIDE = 320

# Quarter turns Kivy accepts. Rotating in the application rather than in the
# host keeps one setting working on every install: Kivy reports a rotated
# Window.size to the interface and turns touch coordinates with it, where a
# host-level rotation would need a different mechanism per display stack and a
# calibration matrix per touchscreen.
WINDOW_ROTATIONS = (0, 90, 180, 270)

# Each tunable delay in libs/timings.py, the [Timing] option that sets it, and
# the shortest value accepted: below it a screen would leave before anyone could
# read it, or a camera would be reset in the middle of a normal capture.
TIMING_OPTIONS = {
    'auto_keep': ('AUTO_KEEP_SECONDS', 1),
    'countdown_home': ('COUNTDOWN_IDLE_SECONDS', 5),
    'select_format_home': ('SELECT_FORMAT_IDLE_SECONDS', 5),
    'review_home': ('REVIEW_IDLE_SECONDS', 5),
    'remote_gallery_home': ('PHONE_PHOTOS_IDLE_SECONDS', 5),
    'error_home': ('ERROR_IDLE_SECONDS', 5),
    'qr_popup': ('QR_CODES_IDLE_SECONDS', 10),
    'print_min': ('PRINT_SCREEN_MIN_SECONDS', 0),
    'shot_timeout': ('CAPTURE_TIMEOUT_SECONDS', 3),
    'print_sheet_timeout': ('PRINT_SHEET_TIMEOUT_SECONDS', 30),
}

# The WS2812 ring the booth is built around; larger rings exist.
DEFAULT_RINGLED_PIXELS = 12
MAX_RINGLED_PIXELS = 256

class Config:
    def __init__(self):
        self.config = configparser.ConfigParser()
        # UTF-8 whatever the locale: the admin form writes it that way, and an
        # event called "Soirée" is exactly what an operator types into it.
        loaded_files = self.config.read(CONFIG_PATH, encoding='utf-8')
        if not loaded_files:
            raise FileNotFoundError(
                f'Cannot load configuration file: {CONFIG_PATH}. '
                'Copy config.ini.example to config.ini and adjust it.'
            )

    def _get_value(self, getter_name, sections, option, fallback=None):
        """Read the first section that carries `option`, falling back on nonsense.

        configparser raises on a value it cannot coerce, and a raise here is a
        booth that will not start: the same file is rewritten by the admin form
        on site, so a stray letter in a port or a countdown is one typo away.
        The options that had been bitten already - ROTATION, MAX_PRINTS,
        CALIBRATION, the window sides - each grew their own guard; this puts it
        under all of them.
        """
        getter = getattr(self.config, getter_name)
        for section in sections:
            if not self.config.has_option(section, option):
                continue
            try:
                return getter(section, option)
            except ValueError:
                Logger.warning(
                    'Config: invalid %s=%r in [%s], using %r',
                    option, self.config.get(section, option, fallback=''), section, fallback,
                )
                return fallback
        return fallback

    def _get_string(self, sections, option, fallback=''):
        return self._get_value('get', sections, option, fallback=fallback)

    def _get_boolean(self, sections, option, fallback=False):
        return self._get_value('getboolean', sections, option, fallback=fallback)

    def _get_int(self, sections, option, fallback=0):
        return self._get_value('getint', sections, option, fallback=fallback)

    def _get_float(self, sections, option, fallback=0.0):
        return self._get_value('getfloat', sections, option, fallback=fallback)

    def get_fullscreen(self):
        return self._get_boolean(('Global',), 'FULLSCREEN', fallback=True)

    def get_window_size(self):
        """Window size in pixels, as (width, height).

        Also the mode fullscreen runs at: the booth asks for a real fullscreen
        rather than a borderless desktop-sized one, so a panel that negotiates
        1920x1080 needs to be told so here as well.
        """
        width = self._get_window_side('WINDOW_WIDTH', DEFAULT_WINDOW_SIZE[0])
        height = self._get_window_side('WINDOW_HEIGHT', DEFAULT_WINDOW_SIZE[1])
        return width, height

    def get_window_rotation(self):
        """Quarter turn applied to the whole interface, for a panel on its side.

        WINDOW_WIDTH and WINDOW_HEIGHT stay the panel's own mode: a 1920x1080
        screen turned upright is 1920 x 1080 with ROTATION = 90, and the
        interface lays itself out in the 1080x1920 Kivy then reports.

        Windows is the exception: Kivy sizes its viewport from the rotated size
        there rather than from the panel's, and clips the interface to a corner
        of the window. The booth's Linux host renders it correctly.
        """
        raw_value = self._get_string(('Global',), 'ROTATION', fallback='0').strip()
        try:
            rotation = int(raw_value)
        except ValueError:
            Logger.warning('Config: invalid ROTATION=%r, keeping the screen unrotated', raw_value)
            return 0
        if rotation not in WINDOW_ROTATIONS:
            Logger.warning('Config: ROTATION must be one of %s, got %d, keeping the screen unrotated',
                           ', '.join(str(value) for value in WINDOW_ROTATIONS), rotation)
            return 0
        return rotation

    def _get_window_side(self, option, fallback):
        raw_value = self._get_string(('Global',), option, fallback=str(fallback)).strip()
        try:
            side = int(raw_value)
        except ValueError:
            # A malformed value must never keep the booth from starting on site.
            Logger.warning('Config: invalid %s=%r, using %d', option, raw_value, fallback)
            return fallback
        if side < MIN_WINDOW_SIDE:
            Logger.warning('Config: %s=%d is below %d, using %d', option, side, MIN_WINDOW_SIDE, fallback)
            return fallback
        return side

    def get_share(self):
        return self._get_boolean(('Global',), 'SHARE', fallback=True)

    def get_ringled(self):
        return self._get_boolean(('Global',), 'RINGLED', fallback=False)

    def get_ringled_pixels(self):
        """How many LEDs the ring has: the animations go round that many."""
        pixels = self._get_int(('Global',), 'RINGLED_PIXELS', fallback=DEFAULT_RINGLED_PIXELS)
        return min(MAX_RINGLED_PIXELS, max(1, pixels))

    def get_timings(self):
        """Every tunable delay, in seconds, keyed as libs/timings.py names them."""
        return {
            name: max(minimum, self._get_float(('Timing',), option, fallback=timings.DEFAULTS[name]))
            for name, (option, minimum) in TIMING_OPTIONS.items()
        }

    # --- the event --------------------------------------------------------

    def _get_raw_string(self, section, option):
        """A text the operator typed, read without interpolation.

        configparser treats % as the start of a reference by default, and an
        event called "100% fun" would stop the booth from starting.
        """
        try:
            return self.config.get(section, option, raw=True, fallback='').strip()
        except configparser.Error as exc:
            Logger.warning('Config: unreadable %s in [%s]: %s', option, section, exc)
            return ''

    def get_event_name(self):
        """What {event} prints as on a template."""
        return self._get_raw_string('Event', 'EVENT_NAME')

    def get_date_format(self):
        """How {date} prints, as a strftime pattern. Nonsense falls back to dd/mm/yyyy."""
        date_format = self._get_raw_string('Event', 'DATE_FORMAT') or DEFAULT_DATE_FORMAT
        try:
            datetime(2026, 9, 13).strftime(date_format)
        except ValueError:
            Logger.warning('Config: invalid DATE_FORMAT=%r, using %r', date_format, DEFAULT_DATE_FORMAT)
            return DEFAULT_DATE_FORMAT
        return date_format

    def get_welcome_title(self):
        """The big words on the welcome screen. Empty keeps the booth's own."""
        return self._get_raw_string('Event', 'WELCOME_TITLE')

    def get_welcome_subtitle(self):
        return self._get_raw_string('Event', 'WELCOME_SUBTITLE')

    def get_welcome_font(self):
        """The lettering style of the welcome title, one of event.WELCOME_FONTS."""
        style = self._get_raw_string('Event', 'WELCOME_FONT').lower() or event.DEFAULT_WELCOME_FONT
        if style not in event.WELCOME_FONTS:
            Logger.warning('Config: unknown WELCOME_FONT=%r, using %r', style, event.DEFAULT_WELCOME_FONT)
            return event.DEFAULT_WELCOME_FONT
        return style

    def get_slideshow(self):
        """Whether the welcome screen shows the evening's photos while nobody is there."""
        return self._get_boolean(('Slideshow',), 'SLIDESHOW', fallback=False)

    def get_slideshow_idle_seconds(self):
        return max(10, self._get_int(('Slideshow',), 'SLIDESHOW_IDLE_SECONDS', fallback=60))

    def get_slideshow_photo_seconds(self):
        return max(2, self._get_int(('Slideshow',), 'SLIDESHOW_PHOTO_SECONDS', fallback=6))

    def get_language(self):
        """Interface language: the booth's screen, and the admin web pages."""
        language = self._get_string(('Global',), 'LANGUAGE', fallback=DEFAULT_LANGUAGE).strip().lower()
        if language not in AVAILABLE_LANGUAGES:
            Logger.warning('Config: unknown LANGUAGE=%r, falling back to %r', language, DEFAULT_LANGUAGE)
            return DEFAULT_LANGUAGE
        return language

    def get_admin_password(self):
        password = self._get_string(('Global',), 'ADMIN_PASSWORD', fallback='').strip()
        return password if password and password.upper() != 'NONE' else None

    def get_web_port(self):
        return self._get_int(('Web', 'Global'), 'WEB_PORT', fallback=5000)

    def get_web_host(self):
        """Address the web server binds to.

        0.0.0.0 exposes the admin to every network the booth is attached to,
        which on a venue LAN or a home network is more than intended. Set
        127.0.0.1 to keep it local, or a specific address to pin it to one
        interface.
        """
        return self._get_string(('Web',), 'WEB_HOST', fallback='0.0.0.0').strip() or '0.0.0.0'

    def get_wifi_ssid(self):
        """Name of the network guests join to reach the booth, for the QR code.

        The booth does not create or configure that network; it only describes
        it, so a phone can join without anyone typing. Empty means no network
        code at all, for guests who are on the booth's network already.
        """
        return self._get_string(('WiFi',), 'WIFI_SSID', fallback='').strip()

    def get_wifi_password(self):
        """Empty for an open network."""
        password = self._get_string(('WiFi',), 'WIFI_PASSWORD', fallback='').strip()
        return password if password and password.upper() != 'NONE' else ''

    def get_wifi_hidden(self):
        return self._get_boolean(('WiFi',), 'WIFI_HIDDEN', fallback=False)

    def get_remote_capture(self):
        """Whether guests may send photos taken with their own phone."""
        return self._get_boolean(('Remote',), 'REMOTE_CAPTURE', fallback=False)

    def get_remote_url(self):
        """Address every QR code carries, or None to derive it from the booth."""
        url = self._get_string(('Remote',), 'REMOTE_URL', fallback='').strip()
        return url if url and url.upper() != 'NONE' else None

    def get_remote_max_upload_mb(self):
        return max(1, self._get_int(('Remote',), 'REMOTE_MAX_UPLOAD_MB', fallback=12))

    def get_remote_max_image_pixels(self):
        """Longest side kept when an incoming photo is re-encoded."""
        return max(640, self._get_int(('Remote',), 'REMOTE_MAX_IMAGE_PIXELS', fallback=2400))

    def get_remote_max_per_sender(self):
        return max(1, self._get_int(('Remote',), 'REMOTE_MAX_PER_SENDER', fallback=20))

    def get_remote_max_pending(self):
        return max(1, self._get_int(('Remote',), 'REMOTE_MAX_PENDING', fallback=200))

    def get_remote_min_upload_interval(self):
        return max(0, self._get_int(('Remote',), 'REMOTE_MIN_UPLOAD_INTERVAL', fallback=3))

    def get_countdown(self):
        """Seconds of countdown before the shot; 0 fires as soon as it is asked for."""
        return max(0, self._get_int(('Capture', 'Picture'), 'COUNTDOWN', fallback=5))

    def get_dcim_directory(self):
        dcim_directory = self._get_string(('Storage', 'Picture'), 'DCIM_DIRECTORY', fallback='./DCIM')
        path = Path(dcim_directory).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return str(path.resolve())

    def get_disk_min_free_gb(self):
        return max(0.0, self._get_float(('Storage', 'Picture'), 'DISK_MIN_FREE_GB', fallback=2.0))

    def get_disk_max_used_percent(self):
        return min(100.0, max(0.0, self._get_float(('Storage', 'Picture'), 'DISK_MAX_USED_PERCENT', fallback=90.0)))

    def get_log_retention_days(self):
        return max(1, self._get_int(('Log', 'Global'), 'LOG_RETENTION_DAYS', fallback=14))

    def get_log_max_files(self):
        return max(1, self._get_int(('Log', 'Global'), 'LOG_MAX_FILES', fallback=40))

    def get_printer_wait_timeout(self):
        return max(5, self._get_int(('Print', 'Picture'), 'PRINTER_WAIT_TIMEOUT', fallback=45))

    def get_usb_export_enabled(self):
        return self._get_boolean(('USB', 'Picture'), 'USB_EXPORT', fallback=True)

    def get_usb_min_free_gb(self):
        return max(0.0, self._get_float(('USB', 'Picture'), 'USB_MIN_FREE_GB', fallback=1.0))

    def get_printer(self):
        printer = self._get_string(('Print', 'Picture'), 'PRINTER', fallback='None')
        return printer if printer != 'None' else None

    def get_max_prints(self):
        max_prints = self._get_string(('Print', 'Picture'), 'MAX_PRINTS', fallback='None').strip()
        if not max_prints or max_prints.upper() == 'NONE':
            return None
        try:
            return max(0, int(max_prints))
        except ValueError:
            # A malformed value must never keep the booth from starting on site.
            Logger.warning('Config: invalid MAX_PRINTS=%r, printing left unlimited', max_prints)
            return None

    def get_max_copies(self):
        """How many copies of one collage a guest may ask for in a single job.

        Not a quota: MAX_PRINTS is what limits the paper. This only bounds the
        stepper on the review screen, so a mistouch cannot empty a ribbon.
        """
        return min(10, max(1, self._get_int(('Print', 'Picture'), 'MAX_COPIES', fallback=3)))

    def get_collage_dpi(self):
        """Resolution the saved and printed collage is assembled at."""
        dpi = self._get_int(('Print', 'Picture'), 'COLLAGE_DPI', fallback=DEFAULT_COLLAGE_DPI)
        if dpi not in COLLAGE_DPIS:
            Logger.warning('Config: COLLAGE_DPI must be one of %s, got %d, using %d',
                           ', '.join(str(value) for value in COLLAGE_DPIS), dpi, DEFAULT_COLLAGE_DPI)
            return DEFAULT_COLLAGE_DPI
        return dpi

    def get_camera_backend(self):
        backend = self._get_string(('Capture',), 'CAMERA', fallback='auto').strip().lower()
        if backend not in CAMERA_BACKENDS:
            Logger.warning("Config: unknown CAMERA=%r, falling back to 'auto'", backend)
            return 'auto'
        return backend

    def get_calibration(self):
        calibration = self._get_string(('Capture', 'Picture'), 'CALIBRATION', fallback='None').strip()
        if not calibration or calibration.upper() == 'NONE':
            return None
        try:
            parsed = ast.literal_eval(calibration)
        except (ValueError, SyntaxError):
            Logger.warning('Config: invalid CALIBRATION=%r, calibration disabled', calibration)
            return None
        if not isinstance(parsed, (tuple, list)) or len(parsed) != 3:
            Logger.warning(
                'Config: CALIBRATION must be a (zoom, offset_x, offset_y) triple, got %r, calibration disabled',
                calibration,
            )
            return None
        return tuple(parsed)

    def get_filters(self):
        return self._get_boolean(('Capture', 'Picture'), 'FILTERS', fallback=False)

    def get_preview_blur_refresh_frames(self):
        return max(1, self._get_int(('Capture', 'Picture'), 'PREVIEW_BLUR_REFRESH_FRAMES', fallback=3))

    def get_blur_camera(self):
        return self._get_boolean(('Capture', 'Picture'), 'BLUR_CAMERA', fallback=True)

    def get_blur_images(self):
        return self._get_boolean(('Capture', 'Picture'), 'BLUR_IMAGES', fallback=False)

    def get_blur_collage(self):
        return self._get_boolean(('Capture', 'Picture'), 'BLUR_COLLAGE', fallback=False)

    def _get_dslr_params(self, section):
        """Returns a dict param -> value for the given DSLR section. Empty or None value = do not set."""
        keys = ['SHUTTERSPEED', 'APERTURE', 'FOCUSMODE', 'ISO']
        out = {}
        if not self.config.has_section(section):
            return out
        for k in keys:
            if self.config.has_option(section, k):
                v = self.config.get(section, k).strip()
                if v and v.upper() != 'NONE':
                    out[k] = v
        return out

    def get_dslr_liveview_params(self):
        return self._get_dslr_params('DSLR_Liveview')

    def get_dslr_capture_params(self):
        return self._get_dslr_params('DSLR_Capture')


def window_settings_from_config():
    """(width, height, rotation) for Kivy, needed before the app object exists.

    Kivy fixes the window when kivy.core.window is first imported, and reads
    these from the Kivy config as it stands at that moment - so config.ini has to
    be consulted at the top of photoboothapp.py, ahead of every Kivy import. A
    file that cannot be read is not reported here: the application loads it again
    a moment later and raises then, with the message an operator should see.
    """
    try:
        config = Config()
    except (OSError, configparser.Error):
        return DEFAULT_WINDOW_SIZE + (0,)
    return config.get_window_size() + (config.get_window_rotation(),)
