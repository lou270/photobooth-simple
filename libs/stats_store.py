import json
import logging
import os
import threading
from datetime import datetime

# Child of Kivy's logger so records land in the application log when Kivy is
# running, without importing Kivy: stats must stay readable headless.
Logger = logging.getLogger('kivy.photobooth')


class StatsStore:
    """Persist photobooth usage statistics in a JSON file.

    Two threads write here: the booth records photos and prints, the web server
    records gallery views and downloads. Every mutation therefore goes through
    _mutate, which reads, changes and writes under a single lock. Releasing the
    lock between the read and the write, as this used to, silently drops
    whichever update lands second.
    """

    def __init__(self, stats_file, max_prints=None):
        self.stats_file = stats_file
        self.max_prints = max_prints if isinstance(max_prints, int) and max_prints >= 0 else None
        self._lock = threading.Lock()

    def get_default_stats(self):
        return {
            'photos_taken': 0,
            'prints': 0,
            'downloads': 0,
            'gallery_views': 0,
            'collage_views': 0,
            'image_views': 0,
            'first_photo_date': None,
            'last_photo_date': None,
            'last_print_date': None,
            'last_download_date': None,
            'sessions': [],
        }

    # --- storage, callers must hold the lock -----------------------------

    def _read(self):
        stats = self.get_default_stats()
        if not os.path.exists(self.stats_file):
            return stats

        with open(self.stats_file, 'r', encoding='utf-8') as handle:
            loaded_stats = json.load(handle)
        if isinstance(loaded_stats, dict):
            stats.update(loaded_stats)
        return stats

    def _write(self, stats):
        stats_directory = os.path.dirname(self.stats_file)
        if stats_directory:
            os.makedirs(stats_directory, exist_ok=True)

        temp_stats_file = f'{self.stats_file}.tmp'
        with open(temp_stats_file, 'w', encoding='utf-8') as handle:
            json.dump(stats, handle, indent=2)
            handle.write('\n')

        os.replace(temp_stats_file, self.stats_file)

    def _mutate(self, change):
        """Read, change and write as one atomic step."""
        try:
            with self._lock:
                stats = self._read()
                change(stats)
                self._write(stats)
        except Exception as exc:
            # Losing a counter must never take a session down with it.
            Logger.error('StatsStore: Error updating stats: %s', exc)

    # --- public API ------------------------------------------------------

    def load(self):
        try:
            with self._lock:
                return self._read()
        except Exception as exc:
            Logger.error('StatsStore: Error loading stats: %s', exc)
            return self.get_default_stats()

    def save(self, stats):
        try:
            with self._lock:
                self._write(stats)
        except Exception as exc:
            Logger.error('StatsStore: Error saving stats: %s', exc)

    def reset(self):
        self.save(self.get_default_stats())

    def track_event(self, event_type):
        fields = {
            'print': ('prints', 'last_print_date'),
            'download': ('downloads', 'last_download_date'),
            'gallery_view': ('gallery_views', None),
            'collage_view': ('collage_views', None),
            'image_view': ('image_views', None),
        }.get(event_type)
        if fields is None:
            return

        counter, date_field = fields

        def change(stats):
            stats[counter] = stats.get(counter, 0) + 1
            if date_field:
                stats[date_field] = datetime.now().isoformat()

        self._mutate(change)

    def track_session(self, session_id, photos):
        """Record a saved session and the photos it holds."""
        if photos <= 0:
            return

        def change(stats):
            timestamp = datetime.now().isoformat()
            stats['photos_taken'] = stats.get('photos_taken', 0) + photos
            stats['last_photo_date'] = timestamp
            if stats.get('first_photo_date') is None:
                stats['first_photo_date'] = timestamp
            if session_id and session_id not in stats['sessions']:
                stats['sessions'].append(session_id)

        self._mutate(change)

    def get_print_limit_info(self):
        stats = self.load()
        prints = max(0, int(stats.get('prints', 0) or 0))

        if self.max_prints is None:
            return {
                'enabled': False,
                'max_prints': None,
                'prints': prints,
                'remaining': None,
                'reached': False,
            }

        remaining = max(0, self.max_prints - prints)
        return {
            'enabled': True,
            'max_prints': self.max_prints,
            'prints': prints,
            'remaining': remaining,
            'reached': prints >= self.max_prints,
        }

    def can_print(self):
        return not self.get_print_limit_info()['reached']

    def track_print(self):
        self.track_event('print')
