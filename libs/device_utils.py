import os
import subprocess
import threading
import time
import traceback
import numpy as np
from kivy.logger import Logger

from libs.file_utils import FileUtils
from libs.hardware import Camera, FakeCamera

try:
    import cups
except ImportError:
    cups = None

try:
    from picamera2 import Picamera2
    from libcamera import controls, Transform
except ImportError:
    Picamera2 = None

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None

try:
    import libs.gphoto2 as gp
except:
    gp = None

class PrintDevice:
    _instance = None

    def print(self, file_path, print_params={}):
        pass

    def get_print_status(self, task_id):
        pass

class Cv2Camera(Camera):
    def __init__(self, port=-1):
        self._preview_lock = threading.Lock()
        self._camera_lock = threading.Lock()
        self._preview_frame = None
        self._preview_frame_id = 0
        self._preview_thread = None
        self._preview_stop = False
        self._preview_fps = 30
        self._preview_size = (1920, 1080)
        if cv2:
            if port > -1:
                camera = cv2.VideoCapture(port)
                if camera.isOpened():
                    self._configure_camera(camera, self._preview_size)
                    self._instance = camera
            else:
                for i in range(3):  # Test 3 first ports
                    camera = cv2.VideoCapture(i)
                    if camera.isOpened():
                        self._configure_camera(camera, self._preview_size)
                        self._instance = camera
                        break
                    camera.release()
        if not self._instance: raise Exception('Cannot find any CV2 camera or CV2 is not installed.')

    def _configure_camera(self, camera, size):
        camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
        camera.set(cv2.CAP_PROP_FPS, self._preview_fps)
        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def _read_latest_frame(self):
        return self._instance.read()

    def _preview_loop(self):
        """Read webcam frames continuously so Kivy never waits on camera I/O."""
        while not self._preview_stop:
            try:
                with self._camera_lock:
                    ret, buf = self._read_latest_frame()
                if ret:
                    im = cv2.flip(buf, -1)
                    with self._preview_lock:
                        self._preview_frame = im
                        self._preview_frame_id += 1
            except Exception as e:
                Logger.debug('Cv2Camera preview thread: %s', e)
                time.sleep(1.0 / self._preview_fps)

    def _start_preview_thread(self):
        if self._preview_thread is not None and self._preview_thread.is_alive():
            return
        self._preview_stop = False
        self._preview_thread = threading.Thread(target=self._preview_loop, daemon=True)
        self._preview_thread.start()

    def get_preview(self, aspect_ratio=None, zoom=None):
        self._start_preview_thread()
        with self._preview_lock:
            im = self._preview_frame
        if im is None: return None
        im = self._crop_to_aspect_ratio(im, aspect_ratio)
        im = self._apply_preview_zoom(im, zoom)
        return im

    def get_preview_frame_id(self):
        with self._preview_lock:
            return self._preview_frame_id

    def capture(self, output_name, aspect_ratio=None, zoom=None, flash_fn=None):
        with self._camera_lock:
            if flash_fn and not self.has_physical_flash(): flash_fn()
            ret, im = self._instance.read()
            if flash_fn and not self.has_physical_flash(): flash_fn(stop=True)
        if not ret:
            raise IOError('OpenCV camera capture failed')
        #im = cv2.flip(im, 0)
        im = self._crop_to_aspect_ratio(im, aspect_ratio)
        im = self._apply_capture_zoom(im, zoom)

        self._write_capture(output_name, im)
    
    def close(self):
        if not self._release_preview_thread():
            return False
        if self._instance is not None:
            self._instance.release()
            self._instance = None
        return True

class Gphoto2Camera(Camera):
    def __init__(self, dslr_liveview_params=None, dslr_capture_params=None):
        self._preview_failures = 0
        if gp:
            # List connected DSLR cameras
            if gp.cameraList().count():
                self._instance = gp.camera()

                self.dslr_liveview_params = dslr_liveview_params or {}
                self.dslr_capture_params = dslr_capture_params or {}
                self._preview_lock = threading.Lock()
                self._camera_lock = threading.Lock()
                self._preview_frame = None
                self._preview_frame_id = 0
                self._preview_thread = None
                self._preview_stop = False
                self._preview_fps = 15  # DSLR preview limited by USB throughput
                # Reduced JPEG decode (1/2 resolution) for smoother preview (OpenCV 4+)
                self._imread_preview = getattr(cv2, 'IMREAD_REDUCED_COLOR_2', cv2.IMREAD_COLOR)

                try:
                    self._set_parameters(self.dslr_liveview_params)
                except Exception:
                    Logger.info('Could not set default DSLR settings, maybe unsupported camera model.')

        if not self._instance: raise Exception('Cannot find any gPhoto2 camera or gPhoto2 is not installed.')

    def _get_param(self, params, key):
        """Returns the value if defined and non-empty, otherwise None."""
        v = params.get(key) or params.get(key.upper())
        if v is None or (isinstance(v, str) and v.strip() == ''): return None
        return v

    def _normalize_aperture_for_manufacturer(self, value, manufacturer):
        """Accept either '1.8' or 'f/1.8' and convert to the camera-specific format."""
        if value is None:
            return None

        normalized = str(value).strip()
        if not normalized:
            return None

        bare_value = normalized[2:] if normalized.lower().startswith('f/') else normalized
        if not bare_value:
            return None

        if manufacturer == 'Canon Inc.':
            return bare_value

        if manufacturer in ('Nikon Corporation', 'Sony Corporation'):
            return f'f/{bare_value}'

        return normalized

    # Config paths per manufacturer, and the exposure modes in which each setting
    # can actually be written (None = writable in any mode). Sourced from the
    # libgphoto2 camera notes:
    # https://github.com/gphoto/libgphoto2/tree/master/camlibs/ptp2/cameras
    DSLR_PROFILES = {
        'Canon Inc.': {
            'mode_path': '/main/capturesettings/autoexposuremode',
            'SHUTTERSPEED': ('/main/capturesettings/shutterspeed', ('Manual', 'TV')),
            'APERTURE': ('/main/capturesettings/aperture', ('Manual', 'AV')),
            'FOCUSMODE': ('/main/capturesettings/focusmode', None),
            'ISO': ('/main/imgsettings/iso', None),
        },
        'Nikon Corporation': {
            'mode_path': '/main/capturesettings/expprogram',
            'SHUTTERSPEED': ('/main/capturesettings/shutterspeed', ('M', 'S')),
            'APERTURE': ('/main/capturesettings/f-number', ('M', 'A')),
            'FOCUSMODE': ('/main/capturesettings/focusmode', None),
            'ISO': ('/main/imgsettings/iso', None),
        },
        'Sony Corporation': {
            'mode_path': '/main/capturesettings/expprogram',
            'SHUTTERSPEED': ('/main/capturesettings/shutterspeed', ('M', 'S')),
            'APERTURE': ('/main/capturesettings/f-number', ('M', 'A')),
            'FOCUSMODE': ('/main/capturesettings/focusmode', None),
            'ISO': ('/main/imgsettings/iso', None),
        },
    }
    DSLR_SETTINGS = ('SHUTTERSPEED', 'APERTURE', 'FOCUSMODE', 'ISO')

    @staticmethod
    def _read_config(config, path):
        """Read a widget, or None when this camera model does not expose it."""
        widget = config.get_path(path)
        return widget.get_value() if widget is not None else None

    @staticmethod
    def _write_config(config, path, value):
        """Write a widget when the camera exposes it; report when it does not."""
        widget = config.get_path(path)
        if widget is None:
            Logger.warning('Gphoto2Camera: camera does not expose %s, setting skipped', path)
            return False
        widget.set_value(value)
        return True

    def _set_parameters(self, params):
        """
        Applies DSLR parameters (config.ini key -> value dict) according to manufacturer.
        If a parameter is missing or None, it is not changed.

        Every lookup goes through _read_config/_write_config: get_path() returns
        None for a widget the model does not expose, and dereferencing that used
        to raise AttributeError inside a caller that swallows failures at debug
        level, so configured settings silently never reached the camera.
        """
        if not params: return

        config = self._instance.get_config()
        manufacturer = self._read_config(config, '/main/status/manufacturer')
        profile = self.DSLR_PROFILES.get(manufacturer)
        if profile is None:
            Logger.info('Gphoto2Camera: unsupported camera model: %s', manufacturer)
            return

        current_mode = self._read_config(config, profile['mode_path'])
        wrote_any_setting = False

        for setting in self.DSLR_SETTINGS:
            path, required_modes = profile[setting]
            value = self._get_param(params, setting)
            if setting == 'APERTURE':
                value = self._normalize_aperture_for_manufacturer(value, manufacturer)
            if not value:
                continue

            if required_modes is not None and current_mode not in required_modes:
                # Worth saying out loud: this is the usual reason a configured
                # aperture or shutter speed appears to be ignored.
                Logger.info(
                    'Gphoto2Camera: %s needs exposure mode %s but the camera is in %s, setting skipped',
                    setting, '/'.join(required_modes), current_mode,
                )
                continue

            wrote_any_setting |= self._write_config(config, path, value)

        if wrote_any_setting:
            self._instance.commit_config(config)

    def _preview_loop(self):
        """Dedicated thread: continuous capture + decode so as not to block the UI."""
        while not self._preview_stop:
            try:
                with self._camera_lock:
                    cfile = self._instance.capture_preview()
                buf = np.frombuffer(cfile.get_data(auto_clean=False), dtype=np.uint8)
                im = cv2.imdecode(buf, self._imread_preview)
                if im is not None:
                    self._preview_failures = 0
                    im = cv2.rotate(im, cv2.ROTATE_180)
                    with self._preview_lock:
                        self._preview_frame = im
                        self._preview_frame_id += 1
                time.sleep(1.0 / self._preview_fps)
            except Exception as e:
                self._preview_failures += 1
                if self._preview_failures in (5, 15) or self._preview_failures % 60 == 0:
                    Logger.warning('Gphoto2Camera preview thread failed %s times: %s', self._preview_failures, e)
                else:
                    Logger.debug('Gphoto2Camera preview thread: %s', e)
                time.sleep(1.0 / self._preview_fps)

    def _start_preview_thread(self):
        if self._preview_thread is not None and self._preview_thread.is_alive():
            return
        self._preview_stop = False
        self._preview_thread = threading.Thread(target=self._preview_loop, daemon=True)
        self._preview_thread.start()

    def has_physical_flash(self):
        return True

    def get_preview_fps(self):
        """Recommended FPS for preview (DSLR limited by USB throughput)."""
        return self._preview_fps

    def get_preview_frame_id(self):
        """Counter the preview widget uses to skip frames it has already drawn.

        Without it this class inherited Camera's constant 0, and KivyCamera read
        that as "no new frame" for every frame after the first: a booth whose
        only camera is the DSLR showed a still image for the whole countdown.
        """
        with self._preview_lock:
            return self._preview_frame_id

    def get_preview(self, aspect_ratio=None, zoom=None):
        self._start_preview_thread()
        with self._preview_lock:
            im = (self._preview_frame.copy() if self._preview_frame is not None else None)
        if im is None:
            return None
        im = self._crop_to_aspect_ratio(im, aspect_ratio)
        im = self._apply_preview_zoom(im, zoom)
        return im

    def capture(self, output_name, aspect_ratio=None, zoom=None, flash_fn=None):
        with self._camera_lock:
            # Apply capture parameters (config.ini [DSLR_Capture]) right before capture
            try:
                self._set_parameters(self.dslr_capture_params or {})
            except Exception as e:
                Logger.debug('Gphoto2Camera: could not apply capture params: %s', e)

            # Capture photo
            if flash_fn and not self.has_physical_flash(): flash_fn()
            cfile = self._instance.capture_image()
            if flash_fn and not self.has_physical_flash(): flash_fn(stop=True)

            # Set DSLR back to liveview before the preview thread can resume.
            try:
                self._set_parameters(self.dslr_liveview_params)
            except Exception as e:
                Logger.debug('Gphoto2Camera: could not apply liveview params: %s', e)

        # Rotate and crop if necessary
        buf = np.frombuffer(cfile.get_data(), dtype=np.uint8)
        im = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if im is None:
            raise IOError('gPhoto2 returned an unreadable image buffer')
        #im = cv2.rotate(im, cv2.ROTATE_180)
        im = self._crop_to_aspect_ratio(im, aspect_ratio)
        im = self._apply_capture_zoom(im, zoom)

        self._write_capture(output_name, im)


    def close(self):
        if not self._release_preview_thread():
            return False
        if self._instance is not None:
            try:
                self._instance.close()
            except Exception as e:
                Logger.warning('Gphoto2Camera: could not close camera cleanly: %s', e)
            self._instance = None
        return True

class Picamera2Camera(Camera):
    def __init__(self, port=0):
        self._preview_lock = threading.Lock()
        self._camera_lock = threading.Lock()
        self._preview_frame = None
        self._preview_thread = None
        self._preview_stop = False
        self._preview_fps = 30
        self._capturing = False
        if Picamera2:
            try:
                self._instance = Picamera2(camera_num=port)
                self._preview_config = self._instance.create_preview_configuration(
                    main={'format': 'RGB888', 'size': (1280, 720)},
                    transform=Transform(hflip=1, vflip=1),
                    controls={'FrameRate': 30},
                )
                self._still_config = self._instance.create_still_configuration(main={"size": (2304, 1296), "format": "RGB888"}, buffer_count=2, controls={'FrameRate': 30})
                self._instance.configure(self._preview_config)
                self._instance.set_controls({'AfMode': controls.AfModeEnum.Continuous, 'AfSpeed': controls.AfSpeedEnum.Fast})
                self._instance.start()
            except Exception as e:
                Logger.error('Picamera2Camera: initialization failed: %s', e)
                Logger.error(traceback.format_exc())
                self.close()
        if not self._instance: raise Exception('Cannot find any Picamera2 or picamera2 is not installed.')

    def _preview_loop(self):
        """Read PiCamera frames continuously so Kivy never waits on camera I/O."""
        while not self._preview_stop:
            try:
                if self._capturing:
                    time.sleep(1.0 / self._preview_fps)
                    continue
                with self._camera_lock:
                    im = self._instance.capture_array()
                with self._preview_lock:
                    self._preview_frame = im
                time.sleep(1.0 / self._preview_fps)
            except Exception as e:
                Logger.debug('Picamera2Camera preview thread: %s', e)
                # Sleep here too, like the other two backends: an error that
                # persists - the camera busy across a switch_mode, say - turned
                # this into a spin that ate a whole core of the Pi.
                time.sleep(1.0 / self._preview_fps)

    def _start_preview_thread(self):
        if self._preview_thread is not None and self._preview_thread.is_alive():
            return
        self._preview_stop = False
        self._preview_thread = threading.Thread(target=self._preview_loop, daemon=True)
        self._preview_thread.start()

    def get_preview_fps(self):
        return self._preview_fps

    def get_preview_frame_id(self):
        with self._preview_lock:
            return id(self._preview_frame)

    def get_preview(self, aspect_ratio=None, zoom=None):
        self._start_preview_thread()
        with self._preview_lock:
            im = self._preview_frame
        if im is None: return None
        im = self._crop_to_aspect_ratio(im, aspect_ratio)
        im = self._apply_preview_zoom(im, zoom)
        return im

    def capture(self, output_name, aspect_ratio=None, zoom=None, flash_fn=None):
        self._capturing = True
        try:
            with self._camera_lock:
                self._instance.switch_mode(self._still_config)
                if flash_fn and not self.has_physical_flash(): flash_fn()
                im = self._instance.capture_array()
                if flash_fn and not self.has_physical_flash(): flash_fn(stop=True)
                #im = cv2.rotate(im, cv2.ROTATE_180)
                im = self._crop_to_aspect_ratio(im, aspect_ratio)
                self._instance.switch_mode(self._preview_config)
        finally:
            self._capturing = False
        im = self._apply_capture_zoom(im, zoom)

        self._write_capture(output_name, im)
    
    def close(self):
        if not self._release_preview_thread():
            return False
        if self._instance is not None:
            try:
                self._instance.stop()
            except Exception:
                pass
            try:
                self._instance.close()
            except Exception:
                pass
            self._instance = None
        return True

class CupsPrinter(PrintDevice):
    _name = None

    def __init__(self, name=None):
        if cups:
            # Try to detect connected printer
            printer_found = False
            cups_conn = cups.Connection()
            if not name or name.lower() == 'default':
                printer_found = cups_conn.getDefault()
                if not printer_found and cups_conn.getPrinters(): printer_found = list(cups_conn.getPrinters().keys())[0]
            elif name in cups_conn.getPrinters():
                printer_found = name

            # Cannot find any printer
            if printer_found:
                self._name = printer_found
                self._instance = cups_conn
                Logger.info('CupsPrinter: Connected to printer \'%s\'', printer_found)
            elif not name or name.lower() == 'default':
                Logger.warning('CupsPrinter: No printer configured in CUPS (see http://localhost:631)')
            else:
                Logger.warning('CupsPrinter: No printer named \'%s\' in CUPS (see http://localhost:631)', name)
        if not self._instance: raise Exception('Cannot find any CUPS printer or cups is not installed.')
        self.cancel_stale_jobs()

    def print(self, file_path, print_params={}):
        if not self.is_available():
            raise RuntimeError(f"Printer '{self._name}' is not available")
        return self._instance.printFile(self._name, os.path.abspath(file_path), os.path.basename(file_path), print_params)

    # IPP job-state values, RFC 8011 section 5.3.7. Naming them because the bare
    # numbers were read backwards: 9 is completed, not canceled, so every
    # successful print was reported as a failure and every failed one as a
    # success. The print counter never advanced either, which left MAX_PRINTS
    # unable to ever trigger.
    JOB_STATE_PROCESSING_STOPPED = 6
    JOB_STATE_CANCELED = 7
    JOB_STATE_ABORTED = 8
    JOB_STATE_COMPLETED = 9

    @staticmethod
    def _format_job_reasons(attributes):
        """job-state-reasons is a string on some CUPS versions, a list on others."""
        reasons = attributes.get('job-state-reasons') or 'unknown'
        if isinstance(reasons, (list, tuple)):
            return ', '.join(str(reason) for reason in reasons) or 'unknown'
        return str(reasons)

    def get_print_status(self, task_id):
        attributes = self._instance.getJobAttributes(task_id)
        state = attributes['job-state']

        if state == self.JOB_STATE_COMPLETED:
            return 'done'

        if state == self.JOB_STATE_CANCELED:
            raise RuntimeError(f'Print job canceled: {self._format_job_reasons(attributes)}')

        if state == self.JOB_STATE_ABORTED:
            raise RuntimeError(f'Print job aborted: {self._format_job_reasons(attributes)}')

        if state == self.JOB_STATE_PROCESSING_STOPPED:
            # Recoverable and common: out of paper, ribbon spent, cover open.
            # Keep waiting so the job finishes once the operator intervenes; the
            # caller's timeout is what eventually gives up.
            Logger.warning(
                'CupsPrinter: printer stopped on job %s: %s',
                task_id, self._format_job_reasons(attributes),
            )
            return 'pending'

        return 'pending'

    def cancel_stale_jobs(self):
        if self._instance is None or not self._name:
            return 0
        canceled = 0
        try:
            jobs = self._instance.getJobs(which_jobs='not-completed')
            for job_id, job in jobs.items():
                if job.get('printer-uri', '').endswith('/' + self._name) or job.get('printer-name') == self._name:
                    try:
                        self._instance.cancelJob(job_id)
                        canceled += 1
                    except Exception as exc:
                        Logger.warning('CupsPrinter: could not cancel stale job %s: %s', job_id, exc)
        except Exception as exc:
            Logger.warning('CupsPrinter: stale job cleanup failed for %s: %s', self._name, exc)
        if canceled:
            Logger.warning('CupsPrinter: canceled stale jobs count=%s printer=%s', canceled, self._name)
        return canceled

    def is_available(self):
        if self._instance is None or not self._name:
            return False

        try:
            printers = self._instance.getPrinters()
            printer = printers.get(self._name)
            if not printer:
                return False

            if printer.get('printer-is-accepting-jobs') is False:
                return False

            # CUPS states: 3=idle, 4=printing, 5=stopped
            return printer.get('printer-state') != 5
        except Exception as e:
            Logger.warning('CupsPrinter: availability check failed for %s: %s', self._name, e)
            return False

class DeviceUtils:
    _preview = None
    _capture = None
    _printer = None

    def __init__(self, printer_name=None, picamera2_port=0, cv2_port=-1, zoom=None,
                 dslr_liveview_params=None, dslr_capture_params=None, camera_backend='auto'):
        self._zoom = zoom
        backend = (camera_backend or 'auto').strip().lower()

        try:
            self._printer = CupsPrinter(printer_name)
        except Exception as e:
            Logger.warning('DeviceUtils: printer initialization failed: %s', e)
            self._printer = None

        if backend == 'fake':
            Logger.warning('DeviceUtils: CAMERA=fake, running without any capture hardware')
            self._preview = self._capture = FakeCamera()
            return

        # An explicit backend keeps startup fast and predictable: probing every
        # backend opens webcams that are not meant to be used and costs seconds.
        pi2_camera = g2_camera = cv2_camera = None
        if backend in ('auto', 'picamera2'):
            try:
                pi2_camera = Picamera2Camera(picamera2_port)
            except Exception as e:
                Logger.warning('DeviceUtils: Picamera2 unavailable: %s', e)
        if backend in ('auto', 'gphoto2'):
            try:
                g2_camera = Gphoto2Camera(dslr_liveview_params=dslr_liveview_params,
                                          dslr_capture_params=dslr_capture_params)
            except Exception as e:
                Logger.warning('DeviceUtils: gPhoto2 unavailable: %s', e)
        if backend in ('auto', 'opencv'):
            try:
                cv2_camera = Cv2Camera(cv2_port)
            except Exception as e:
                Logger.warning('DeviceUtils: OpenCV camera unavailable: %s', e)

        # Switch to the best option
        if pi2_camera and g2_camera:
            Logger.info('Switch to hybrid camera (Picamera + gPhoto2)')
            self._preview = pi2_camera
            self._capture = g2_camera
        elif cv2_camera and g2_camera:
            Logger.info('Switch to hybrid camera (OpenCV + gPhoto2)')
            self._preview = cv2_camera
            self._capture = g2_camera
        elif pi2_camera:
            Logger.info('Switch to Picamera camera')
            self._preview = pi2_camera
            self._capture = pi2_camera
        elif g2_camera:
            Logger.info('Switch to gPhoto2 camera')
            self._preview = g2_camera
            self._capture = g2_camera
        elif cv2_camera:
            Logger.info('Switch to CV2 camera')
            self._preview = cv2_camera
            self._capture = cv2_camera
        else:
            Logger.error('DeviceUtils: no camera available (CAMERA=%s)', backend)
            raise Exception(
                'This app requires at least a piCamera, a DSLR or a webcam to work. '
                'Set CAMERA = fake in config.ini to run without hardware.'
            )

    def has_physical_flash(self):
        return self._capture.has_physical_flash()

    def get_preview_fps(self):
        return self._preview.get_preview_fps()

    def get_preview_frame_id(self):
        return self._preview.get_preview_frame_id()

    def get_preview(self, aspect_ratio=None):
        return self._preview.get_preview(aspect_ratio=aspect_ratio, zoom=self._zoom)

    def capture(self, output_name, aspect_ratio=None, flash_fn=None):
        return self._capture.capture(output_name, aspect_ratio, self._zoom, flash_fn)

    def has_printer(self):
        if self._printer is None:
            return False
        return self._printer.is_available()

    def cancel_stale_print_jobs(self):
        if self._printer is None:
            return 0
        return self._printer.cancel_stale_jobs()

    def print(self, file_path, print_params={}):
        if not self._printer: raise RuntimeError('No printer configured')
        return self._printer.print(file_path, print_params)

    def get_print_status(self, task_id):
        if not self._printer: return 'done'
        return self._printer.get_print_status(task_id)

    def close(self):
        """Release every device. False when one of them could not be freed.

        A False here is not a tidy-up failure to log and move past: it means a
        thread is still inside the driver, and the caller must restart the
        process rather than carry on with a device it cannot reopen.
        """
        # dict.fromkeys dedupes by identity: preview and capture are the same
        # object on every rig that is not a hybrid, and closing twice made the
        # second call work on a handle the first had already dropped.
        devices = dict.fromkeys(d for d in (self._preview, self._capture) if d is not None)
        released = True
        for device in devices:
            try:
                if not device.close():
                    released = False
            except Exception as e:
                Logger.warning('DeviceUtils: could not close device cleanly: %s', e)
                released = False
        return released
