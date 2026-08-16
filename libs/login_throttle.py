"""Rate limiting for the admin login.

The admin password is the only thing standing between the network and a booth
whose photos can be wiped and whose configuration can be rewritten. Without a
limit on attempts, an unattended booth is a free offline cracking target for
anyone within WiFi range.
"""

import logging
import threading
import time

Logger = logging.getLogger('kivy.photobooth')

DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_LOCKOUT_SECONDS = 300
DEFAULT_WINDOW_SECONDS = 900
MAX_TRACKED_CLIENTS = 512


class LoginThrottle:
    """Locks a client out after repeated failures inside a rolling window."""

    def __init__(self, max_attempts=DEFAULT_MAX_ATTEMPTS, lockout_seconds=DEFAULT_LOCKOUT_SECONDS,
                 window_seconds=DEFAULT_WINDOW_SECONDS, time_source=time.monotonic):
        self._max_attempts = max(1, int(max_attempts))
        self._lockout_seconds = max(1, int(lockout_seconds))
        self._window_seconds = max(1, int(window_seconds))
        self._now = time_source
        self._lock = threading.Lock()
        self._clients = {}

    def _prune(self, now):
        """Drop entries that are neither locked nor inside their window."""
        stale = [
            key for key, entry in self._clients.items()
            if now >= entry['locked_until'] and now - entry['last_failure'] > self._window_seconds
        ]
        for key in stale:
            del self._clients[key]

        # Hard ceiling: a client key is attacker-controlled in principle, and an
        # unbounded dict would be a slow memory leak.
        if len(self._clients) > MAX_TRACKED_CLIENTS:
            oldest = sorted(self._clients.items(), key=lambda item: item[1]['last_failure'])
            for key, _entry in oldest[:len(self._clients) - MAX_TRACKED_CLIENTS]:
                del self._clients[key]

    def retry_after(self, key):
        """Seconds the client must wait, 0 when it may try again now."""
        now = self._now()
        with self._lock:
            self._prune(now)
            entry = self._clients.get(key)
            if entry is None:
                return 0
            return max(0, int(round(entry['locked_until'] - now)))

    def is_locked(self, key):
        return self.retry_after(key) > 0

    def record_failure(self, key):
        """Count a failed attempt; returns the seconds to wait, 0 if not locked yet."""
        now = self._now()
        with self._lock:
            self._prune(now)
            entry = self._clients.get(key)

            if entry is None or now - entry['last_failure'] > self._window_seconds:
                entry = {'failures': 0, 'last_failure': now, 'locked_until': 0}
                self._clients[key] = entry

            entry['failures'] += 1
            entry['last_failure'] = now

            if entry['failures'] >= self._max_attempts:
                entry['locked_until'] = now + self._lockout_seconds
                entry['failures'] = 0
                Logger.warning(
                    'LoginThrottle: locking out %s for %ss after %s failed admin logins',
                    key, self._lockout_seconds, self._max_attempts,
                )
                return self._lockout_seconds

            return 0

    def record_success(self, key):
        with self._lock:
            self._clients.pop(key, None)
