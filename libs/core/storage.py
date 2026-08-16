import logging
import os
import shutil
from datetime import datetime

from libs.file_utils import FileUtils

Logger = logging.getLogger('kivy.photobooth')


class SessionStorage:
    """Owns the DCIM layout: temporary working files and saved sessions.

    Working files live in `tmp/` while a session is in progress, then move as a
    block into a timestamped directory under `save/`. Keeping the two apart is
    what lets the booth purge a half-finished session without touching anything
    a guest already owns.
    """

    SESSION_ID_FORMAT = '%Y%m%d_%H%M%S'

    def __init__(self, dcim_directory, min_free_gb=2.0, max_used_percent=90.0):
        self.dcim_directory = dcim_directory
        self.tmp_directory = os.path.join(dcim_directory, 'tmp')
        self.save_directory = os.path.join(dcim_directory, 'save')
        self.min_free_gb = min_free_gb
        self.max_used_percent = max_used_percent
        self.last_saved_session_directory = None

        for directory in (self.dcim_directory, self.tmp_directory, self.save_directory):
            os.makedirs(directory, exist_ok=True)

    # --- paths -----------------------------------------------------------

    def get_shot(self, shot_idx):
        return os.path.join(self.tmp_directory, f'capture-{shot_idx}.jpg')

    def get_collage(self):
        return os.path.join(self.tmp_directory, 'collage.jpg')

    def get_print_collage(self):
        """Duplicated collage produced for strip formats, when the template needs one."""
        return os.path.join(self.tmp_directory, 'collage_print.jpg')

    def get_saved_collage(self):
        """Collage of the last saved session, once tmp/ has been emptied."""
        if not self.last_saved_session_directory:
            return None
        path = os.path.join(self.last_saved_session_directory, 'collage.jpg')
        return path if os.path.exists(path) else None

    # --- free space ------------------------------------------------------

    def get_disk_usage(self):
        usage = shutil.disk_usage(self.dcim_directory)
        used_percent = 0 if usage.total == 0 else ((usage.total - usage.free) / usage.total) * 100
        return {
            'free_gb': usage.free / (1024 ** 3),
            'total_gb': usage.total / (1024 ** 3),
            'used_percent': used_percent,
        }

    def is_disk_space_critical(self):
        try:
            usage = self.get_disk_usage()
        except OSError as exc:
            # An unreadable mount point must not block a session on its own.
            Logger.warning('SessionStorage: disk usage check failed: %s', exc)
            return False
        return usage['free_gb'] < self.min_free_gb or usage['used_percent'] >= self.max_used_percent

    def log_disk_usage(self, context):
        try:
            usage = self.get_disk_usage()
        except OSError as exc:
            Logger.warning('SessionStorage: disk usage check failed [%s]: %s', context, exc)
            return
        Logger.info(
            'SessionStorage: disk usage [%s] free=%.2fGB total=%.2fGB used=%.1f%% path=%s',
            context, usage['free_gb'], usage['total_gb'], usage['used_percent'], self.dcim_directory,
        )

    # --- session lifecycle -----------------------------------------------

    def save_session(self):
        """Move the working files into a timestamped session directory.

        Small previews and print-only duplicates stay behind: they are derived
        files that would only bloat the gallery and the USB export.

        Returns (session_id, moved_files); session_id is None when nothing was
        worth saving.
        """
        working_files = os.listdir(self.tmp_directory)
        if not working_files:
            return None, 0

        destination = os.path.join(self.save_directory, datetime.now().strftime(self.SESSION_ID_FORMAT))
        os.makedirs(destination, exist_ok=True)

        moved_files = 0
        for filename in working_files:
            if '_small' in filename or '_print' in filename:
                continue
            source_path = os.path.join(self.tmp_directory, filename)
            target_path = os.path.join(destination, filename)
            try:
                FileUtils.move_file(source_path, target_path)
                moved_files += 1
            except FileNotFoundError:
                Logger.warning('SessionStorage: file disappeared before save: %s', source_path)
            except Exception as exc:
                Logger.error('SessionStorage: failed to save %s to %s: %s', source_path, target_path, exc)
                raise

        if not moved_files:
            # Nothing but derived files: do not leave an empty session behind.
            try:
                os.rmdir(destination)
            except OSError:
                pass
            return None, 0

        self.last_saved_session_directory = destination
        return os.path.basename(destination), moved_files

    def purge_tmp(self):
        """Delete every working file, including the derived ones save_session left."""
        removed_files = 0
        for filename in os.listdir(self.tmp_directory):
            path = os.path.join(self.tmp_directory, filename)
            if not os.path.isfile(path):
                continue
            try:
                if FileUtils.remove_file(path):
                    removed_files += 1
            except OSError as exc:
                Logger.warning('SessionStorage: failed to purge temp file %s: %s', path, exc)

        Logger.info('SessionStorage: purged tmp directory removed_files=%s', removed_files)
        return removed_files
