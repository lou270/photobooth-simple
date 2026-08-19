import configparser
import ast
import logging
from pathlib import Path

from libs.i18n import AVAILABLE_LANGUAGES, DEFAULT_LANGUAGE

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / 'config.ini'

# Child of Kivy's logger so records land in the application log when Kivy is
# running, without importing Kivy here: config must stay readable headless.
Logger = logging.getLogger('kivy.photobooth')

# Capture backends accepted by CAMERA. 'auto' probes the hardware, 'fake'
# runs the whole application with a synthetic camera and no hardware at all.
CAMERA_BACKENDS = ('auto', 'gphoto2', 'picamera2', 'opencv', 'fake')

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

class Config:
    def __init__(self):
        self.config = configparser.ConfigParser()
        loaded_files = self.config.read(CONFIG_PATH)
        if not loaded_files:
            raise FileNotFoundError(
                f'Cannot load configuration file: {CONFIG_PATH}. '
                'Copy config.ini.example to config.ini and adjust it.'
            )

    def _get_value(self, getter_name, sections, option, fallback=None):
        getter = getattr(self.config, getter_name)
        for section in sections:
            if self.config.has_option(section, option):
                return getter(section, option)
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
        """Network name put in the QR code that joins the booth's access point.

        This setting is the source of truth for the network's identity:
        setup/apply-wifi.sh generates hostapd.conf from it, rather than the
        booth trying to read the access point's own configuration. Renaming the
        network here and re-running that script keeps the QR code and the
        broadcast network in step.
        """
        return self._get_string(('WiFi',), 'WIFI_SSID', fallback='PhotoBooth').strip()

    def get_wifi_password(self):
        """Empty for an open network, which is how the access point ships."""
        password = self._get_string(('WiFi',), 'WIFI_PASSWORD', fallback='').strip()
        return password if password and password.upper() != 'NONE' else ''

    def get_wifi_hidden(self):
        return self._get_boolean(('WiFi',), 'WIFI_HIDDEN', fallback=False)

    def get_wifi_ap_address(self):
        """The booth's own address on the access point it runs.

        Guessing it does not work here: the access point deliberately carries no
        default route, so the interface the system would pick to reach the
        outside is the venue's network, not the one guests are standing on.
        Empty falls back to that guess, for a booth on somebody else's WiFi.
        """
        return self._get_string(('WiFi',), 'WIFI_AP_ADDRESS', fallback='192.168.4.1').strip()

    def get_remote_capture(self):
        """Whether guests may send photos taken with their own phone."""
        return self._get_boolean(('Remote',), 'REMOTE_CAPTURE', fallback=False)

    def get_remote_url(self):
        """Address printed in the QR code, or None to derive it from the booth."""
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
        return self._get_int(('Capture', 'Picture'), 'COUNTDOWN', fallback=5)

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
