#!/usr/bin/python3

import os
import sys
import signal
import threading
import time
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
LOG_DIRECTORY = PROJECT_ROOT / 'logs'
LOG_DIRECTORY.mkdir(exist_ok=True)

from kivy.config import Config as KivyConfig
KivyConfig.set('kivy', 'log_enable', '1')
KivyConfig.set('kivy', 'log_dir', str(LOG_DIRECTORY))
KivyConfig.set('kivy', 'log_name', 'photobooth_%y-%m-%d_%_.txt')
KivyConfig.set('kivy', 'exit_on_escape', '0')
# The Pi's VideoCore has no spare fill rate for antialiasing: multisampling costs
# several ms per frame here and buys nothing on a photobooth UI.
KivyConfig.set('graphics', 'multisamples', '0')

# os.environ['KIVY_NO_CONSOLELOG'] = '1'
from kivy.app import App
from kivy.clock import Clock
from kivy.logger import Logger
from kivy.uix.screenmanager import FadeTransition

from libs.config import Config
from libs.core import ProcessRunner, SessionStorage
from libs.device_utils import DeviceUtils
from libs.screens import ScreenMgr
from libs.hardware.led import create_led
from libs.stats_store import StatsStore
from libs.template_collage import load_templates
from libs.usb_transfer import UsbTransfer
from libs.web_server import WebServer

RINGLED = None

def signal_handler(sig, frame):
    print("\nCtrl+C detected. Exiting gracefully...")
    if RINGLED:
        RINGLED.clear()
    sys.exit(0)
signal.signal(signal.SIGINT, signal_handler)

class PhotoboothApp(App):
    def __init__(self, **kwargs):
        global RINGLED
        Logger.info('PhotoboothApp: __init__().')
        super(PhotoboothApp, self).__init__(**kwargs)

        # Load configuration
        config = Config()
        self.FULLSCREEN = config.get_fullscreen()
        self.SHARE = config.get_share()
        self.WEB_PORT = config.get_web_port()
        self.WEB_HOST = config.get_web_host()
        self.FILTERS = config.get_filters()
        self.PREVIEW_BLUR_REFRESH_FRAMES = config.get_preview_blur_refresh_frames()
        self.BLUR_CAMERA = config.get_blur_camera()
        self.BLUR_IMAGES = config.get_blur_images()
        self.BLUR_COLLAGE = config.get_blur_collage()
        self.COUNTDOWN = config.get_countdown()
        self.DCIM_DIRECTORY = config.get_dcim_directory()
        self.DISK_MIN_FREE_GB = config.get_disk_min_free_gb()
        self.DISK_MAX_USED_PERCENT = config.get_disk_max_used_percent()
        self.PRINTER_WAIT_TIMEOUT = config.get_printer_wait_timeout()
        self.USB_EXPORT = config.get_usb_export_enabled()
        self.USB_MIN_FREE_GB = config.get_usb_min_free_gb()
        self.PRINTER = config.get_printer()
        self.MAX_PRINTS = config.get_max_prints()
        self.CALIBRATION = config.get_calibration()
        self.CAMERA_BACKEND = config.get_camera_backend()
        self._dslr_liveview_params = config.get_dslr_liveview_params()
        self._dslr_capture_params = config.get_dslr_capture_params()
        self._log_retention_days = config.get_log_retention_days()
        self._log_max_files = config.get_log_max_files()

        self._rotate_logs()
        
        # Always a usable object: a ring light that cannot be driven degrades to
        # a no-op instead of stopping the booth from starting.
        RINGLED = create_led(enabled=config.get_ringled(), num_pixels=12)

        # Assign local variables
        self.sm = None
        self._requested_screen = None
        self._requested_kwargs = None
        self.pending_photo_tasks = []
        self._pending_photo_error = None
        self._pending_photo_lock = threading.Lock()
        self.process_runner = ProcessRunner()
        self.usb_transfer = None
        self.ringled = RINGLED
        self.devices = DeviceUtils(
            printer_name=self.PRINTER,
            zoom=self.CALIBRATION,
            dslr_liveview_params=self._dslr_liveview_params,
            dslr_capture_params=self._dslr_capture_params,
            camera_backend=self.CAMERA_BACKEND,
        )
        
        # Always at least one format: load_templates() falls back to a built-in
        # template rather than returning an empty list.
        self.print_formats = load_templates('templates')

        self.storage = SessionStorage(
            self.DCIM_DIRECTORY,
            min_free_gb=self.DISK_MIN_FREE_GB,
            max_used_percent=self.DISK_MAX_USED_PERCENT,
        )
        # Kept as attributes: UsbTransfer and WebServer are wired with them.
        self.tmp_directory = self.storage.tmp_directory
        self.save_directory = self.storage.save_directory
        self.stats_store = StatsStore(
            os.path.join(self.save_directory, '.stats.json'),
            max_prints=self.MAX_PRINTS,
        )

        # Start USB transfer
        if self.USB_EXPORT:
            self.usb_transfer = UsbTransfer(self, self.save_directory, min_free_gb=self.USB_MIN_FREE_GB)
            self.usb_transfer.start()
        else:
            Logger.info('PhotoboothApp: USB export disabled')
        
        # The web server always runs for gallery/admin access; SHARE only controls UI buttons.
        abs_save_directory = os.path.abspath(self.save_directory)
        self.web_server = WebServer(
            abs_save_directory,
            host=self.WEB_HOST,
            port=self.WEB_PORT,
            admin_password=config.get_admin_password(),
            stats_store=self.stats_store,
            restart_callback=self.request_restart,
        )
        if self.web_server.start():
            Logger.info(
                'PhotoboothApp: Web server started at %s:%s (share_ui=%s)',
                abs_save_directory,
                self.WEB_PORT,
                self.SHARE,
            )
        else:
            Logger.error('PhotoboothApp: Web server failed to start; gallery and admin are unavailable')
            self._requested_screen = ScreenMgr.ERROR
            self._requested_kwargs = {
                'message': f"Web server cannot be bound to port {self.WEB_PORT}.",
                'show_continue': True,
                'show_restart': True,
            }

        self.storage.log_disk_usage('startup')
        if self.is_disk_space_critical():
            self._requested_screen = ScreenMgr.ERROR
            self._requested_kwargs = self._disk_maintenance_kwargs()
        self._log_runtime_snapshot('startup')

    def build(self):
        Logger.info('PhotoboothApp: build().')
        self.sm = ScreenMgr(self, transition=FadeTransition(duration=0.08))
        if self._requested_screen:
            self.sm.current = self._requested_screen
        self.sm.current_screen.on_entry()
        if self._requested_screen and self._requested_kwargs:
            self.sm.current_screen.on_entry(self._requested_kwargs)
        return self.sm

    def on_stop(self):
        self._log_runtime_snapshot('shutdown')
        if self.ringled:
            self.ringled.clear()
        if getattr(self, 'web_server', None):
            self.web_server.stop()
        if getattr(self, 'usb_transfer', None):
            self.usb_transfer.stop()
        if getattr(self, 'devices', None):
            self.devices.close()

    def request_restart(self):
        """Request a clean application restart from a background thread."""
        Logger.warning('PhotoboothApp: restart requested')
        self._log_runtime_snapshot('restart_requested')
        Clock.schedule_once(lambda dt: self.stop(), 0)

    def request_transition_to(self, new_state, **kwargs):
        """
        Request a screen transition from any thread.
        """
        Clock.schedule_once(lambda dt: self.transition_to(new_state, **kwargs), 0)

    def transition_to(self, new_state, **kwargs):
        self.sm.current_screen.on_exit()
        self.sm.current = new_state
        self.sm.current_screen.on_entry(kwargs)

    def enter_maintenance_mode(self, message, show_continue=False, show_restart=True):
        Logger.error('PhotoboothApp: entering maintenance mode message=%s', message)
        self.request_transition_to(
            ScreenMgr.ERROR,
            message=message,
            show_continue=show_continue,
            show_restart=show_restart,
        )

    def get_current_screen_name(self):
        if self.sm is None:
            return None
        return self.sm.current

    def is_usb_copy_allowed(self):
        current_screen = self.get_current_screen_name()
        return current_screen == ScreenMgr.START

    def get_shot(self, shot_idx):
        return self.storage.get_shot(shot_idx)

    def get_collage(self):
        return self.storage.get_collage()

    def get_saved_collage(self):
        return self.storage.get_saved_collage()

    def get_shots_to_take(self, format=0):
        return self.print_formats[format].get_photos_required()

    def get_layout_previews(self, format=0):
        return [f.get_preview() for f in self.print_formats]

    def get_format_aspect_ratio(self, format_idx):
        """Get the aspect ratio (width/height) for the given format."""
        return self.print_formats[format_idx].get_aspect_ratio()

    def _rotate_logs(self):
        try:
            now = time.time()
            max_age = self._log_retention_days * 86400
            log_files = [path for path in LOG_DIRECTORY.iterdir() if path.is_file()]

            removed = 0
            for path in log_files:
                try:
                    if now - path.stat().st_mtime > max_age:
                        path.unlink()
                        removed += 1
                except OSError as exc:
                    Logger.warning('PhotoboothApp: could not remove old log %s: %s', path, exc)

            remaining = sorted(
                [path for path in LOG_DIRECTORY.iterdir() if path.is_file()],
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            for path in remaining[self._log_max_files:]:
                try:
                    path.unlink()
                    removed += 1
                except OSError as exc:
                    Logger.warning('PhotoboothApp: could not remove extra log %s: %s', path, exc)

            Logger.info('PhotoboothApp: log rotation removed_files=%s retention_days=%s max_files=%s', removed, self._log_retention_days, self._log_max_files)
        except Exception as exc:
            Logger.warning('PhotoboothApp: log rotation failed: %s', exc)

    def get_disk_usage(self):
        return self.storage.get_disk_usage()

    def is_disk_space_critical(self):
        return self.storage.is_disk_space_critical()

    def _disk_maintenance_kwargs(self):
        return {
            'message': 'Photo storage is full. Please call an operator.',
            'show_continue': False,
            'show_restart': True,
        }

    def ensure_disk_space_or_maintenance(self):
        if not self.is_disk_space_critical():
            return True
        self.enter_maintenance_mode(**self._disk_maintenance_kwargs())
        return False

    def _log_runtime_snapshot(self, context):
        Logger.info(
            'PhotoboothApp: runtime snapshot [%s] threads=%d current_screen=%s share=%s printer=%s',
            context,
            len(threading.enumerate()),
            self.get_current_screen_name(),
            self.SHARE,
            self.PRINTER,
        )

    def _start_background_process(self, kind, target, *args, **kwargs):
        self.process_runner.start(kind, target, *args, **kwargs)

    def has_process_failed(self, kind=None):
        return self.process_runner.has_failed(kind)

    def get_process_error(self, kind=None):
        return self.process_runner.get_error(kind)

    def has_process_timed_out(self, kind, timeout_seconds):
        return self.process_runner.has_timed_out(kind, timeout_seconds)

    def abandon_background_processes(self, kind=None, reason='unknown'):
        self.process_runner.abandon(kind, reason)

    def trigger_shot(self, shot_idx, format_idx):
        Logger.info('PhotoboothApp: trigger_shot().')
        if not self.ensure_disk_space_or_maintenance():
            raise RuntimeError('Photo storage is almost full')
        aspect_ratio = self.get_format_aspect_ratio(format_idx)
        Logger.info('PhotoboothApp: shot request idx=%s format=%s aspect_ratio=%.4f', shot_idx, format_idx, aspect_ratio)
        self.storage.log_disk_usage('before_shot')
        flash_callback = self.ringled.flash if self.ringled else None
        self._start_background_process('shot', self.devices.capture, self.get_shot(shot_idx), aspect_ratio, flash_callback)

    def is_shot_completed(self, shot_idx):
        return not self.process_runner.is_running()

    def trigger_collage(self, format=0):
        Logger.info('PhotoboothApp: trigger_collage().')
        if not self.ensure_disk_space_or_maintenance():
            raise RuntimeError('Photo storage is almost full')
        photos = []
        for i in range(0, self.get_shots_to_take(format)): photos.append(self.get_shot(i))
        Logger.info('PhotoboothApp: collage request format=%s photos=%s', format, len(photos))
        self.storage.log_disk_usage('before_collage')
        # Pass for_print=True to enable horizontal duplication for strip formats
        self._start_background_process(
            'collage',
            self.print_formats[format].assemble,
            output_path=self.get_collage(),
            image_paths=photos,
            for_print=True,
        )

    def is_collage_completed(self):
        return not self.process_runner.is_running()

    def has_background_processes(self):
        return self.process_runner.is_running()

    def has_physical_flash(self):
        return self.devices.has_physical_flash()

    def has_printer(self):
        return self.devices.has_printer()

    def can_start_print(self):
        if not self.has_printer():
            return False
        return self.stats_store.can_print()

    def get_print_limit_info(self):
        return self.stats_store.get_print_limit_info()

    def track_print_sent(self):
        self.stats_store.track_print()

    def trigger_print(self, copies, format=0):
        Logger.info('PhotoboothApp: trigger_print().')
        if not self.has_printer():
            raise RuntimeError('Printer is not available')
        if not self.stats_store.can_print():
            raise RuntimeError('Print limit reached')
        options = self.print_formats[format].get_print_params()
        options['copies'] = str(copies)
        Logger.info('PhotoboothApp: print request format=%s copies=%s printer_available=%s', format, copies, self.has_printer())
        self.storage.log_disk_usage('before_print')
        
        # Use duplicated print output only for templates that generate one.
        print_collage = self.storage.get_print_collage()
        if self.print_formats[format].uses_print_version() and os.path.exists(print_collage):
            Logger.info(f'PhotoboothApp: Using print version: {print_collage}')
            return self.devices.print(print_collage, options)

        collage = self.get_collage() if os.path.exists(self.get_collage()) else self.get_saved_collage()
        if collage is None:
            raise FileNotFoundError('No collage available to print')
        return self.devices.print(collage, options)

    def start_photo_task(self, target, *args):
        def run_target():
            try:
                target(*args)
            except Exception:
                with self._pending_photo_lock:
                    self._pending_photo_error = traceback.format_exc()
                Logger.error(self._pending_photo_error)

        task = threading.Thread(target=run_target, name='photobooth-photo-task', daemon=True)
        with self._pending_photo_lock:
            self._pending_photo_error = None
            self.pending_photo_tasks = [task for task in self.pending_photo_tasks if task.is_alive()]
            self.pending_photo_tasks.append(task)
        task.start()

    def has_pending_photo_tasks(self):
        with self._pending_photo_lock:
            self.pending_photo_tasks = [task for task in self.pending_photo_tasks if task.is_alive()]
            return bool(self.pending_photo_tasks)

    def get_pending_photo_error(self):
        with self._pending_photo_lock:
            return self._pending_photo_error

    def clear_pending_photo_error(self):
        with self._pending_photo_lock:
            self._pending_photo_error = None

    def is_print_completed(self, print_task_id):
        try:
            status = self.devices.get_print_status(print_task_id)
            Logger.info('PhotoboothApp: print status task=%s status=%s', print_task_id, status)
            return status == 'done'
        except Exception as exc:
            Logger.error('PhotoboothApp: print status check failed task=%s error=%s', print_task_id, exc)
            return False

    def reset_devices(self, reason='unknown'):
        Logger.warning('PhotoboothApp: resetting devices reason=%s', reason)
        try:
            if getattr(self, 'devices', None):
                self.devices.close()
        except Exception as exc:
            Logger.warning('PhotoboothApp: device close during reset failed: %s', exc)

        self.devices = DeviceUtils(
            printer_name=self.PRINTER,
            zoom=self.CALIBRATION,
            dslr_liveview_params=self._dslr_liveview_params,
            dslr_capture_params=self._dslr_capture_params,
            camera_backend=self.CAMERA_BACKEND,
        )
        self._log_runtime_snapshot('devices_reset')

    def recover_devices_and_return_home(self, reason='unknown'):
        def recover():
            try:
                self.abandon_background_processes(kind='shot', reason=reason)
                self.reset_devices(reason=reason)
                self.request_transition_to(ScreenMgr.START)
            except Exception as exc:
                Logger.error('PhotoboothApp: device recovery failed: %s', exc)
                Logger.error(traceback.format_exc())
                self.enter_maintenance_mode(
                    message='Camera recovery failed. Please call an operator.',
                )

        threading.Thread(target=recover, name='photobooth-device-recovery', daemon=True).start()

    def save_collage(self):
        Logger.info('PhotoboothApp: save_collage().')
        if not self.ensure_disk_space_or_maintenance():
            raise RuntimeError('Photo storage is almost full')
        session_id, moved_files = self.storage.save_session()
        self.storage.log_disk_usage('after_save')
        for _ in range(moved_files):
            self.stats_store.track_photo_taken(session_id=session_id)

    def purge_tmp(self):
        self.storage.purge_tmp()

if __name__ == '__main__':
    PhotoboothApp().run()
