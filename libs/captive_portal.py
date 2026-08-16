"""Telling a phone it is behind a portal, and then telling it that it is free.

An access point with no uplink is not a broken network, but every phone treats
it as one until something says otherwise. Android and iOS decide by fetching a
known URL and comparing the answer byte for byte; a booth that redirects those
requests forever is a booth the phone keeps flagging, keeps offering to abandon
for mobile data, and on some Android settings leaves on its own.

So the booth answers the way a real portal does. A phone that has not been
through the portal yet is redirected to it, which is what makes the page open by
itself. Once the guest has done what they came for, the same probes get the
exact reply each operating system is waiting for, and the phone settles.

The bodies below are not arbitrary: each one is what the vendor's own server
returns, and the check is an equality test on the client side.
"""

import logging
import threading
import time

Logger = logging.getLogger('kivy.photobooth')

# How long a phone stays released. Longer than an event, so nobody is asked
# twice in one evening, and short enough that the table empties by itself.
DEFAULT_SESSION_SECONDS = 12 * 3600
# A client key is whatever address the network hands us, so the table needs a
# ceiling for the same reason LoginThrottle has one.
MAX_TRACKED_CLIENTS = 512

APPLE_SUCCESS_BODY = '<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>'
FIREFOX_CANONICAL_BODY = (
    '<meta http-equiv="refresh" content="0;url=https://support.mozilla.org/kb/captive-portal"/>'
)

# path -> (body, status, mimetype), returned once the phone has been released.
# Anything else here would read as "still captive" to the operating system.
PROBE_RESPONSES = {
    # Android, and everything that copied it.
    '/generate_204': ('', 204, 'text/plain'),
    '/gen_204': ('', 204, 'text/plain'),
    '/generate204': ('', 204, 'text/plain'),
    # Apple.
    '/hotspot-detect.html': (APPLE_SUCCESS_BODY, 200, 'text/html'),
    '/library/test/success.html': (APPLE_SUCCESS_BODY, 200, 'text/html'),
    # Firefox.
    '/success.txt': ('success\n', 200, 'text/plain'),
    '/canonical.html': (FIREFOX_CANONICAL_BODY, 200, 'text/html'),
    # Windows.
    '/connecttest.txt': ('Microsoft Connect Test', 200, 'text/plain'),
    '/ncsi.txt': ('Microsoft NCSI', 200, 'text/plain'),
}

# Probed to find the portal rather than to test connectivity: these are where an
# operating system sends the guest, so they lead to the page in every state.
PORTAL_ENTRY_PATHS = (
    '/redirect',
    '/fwlink',
    '/check_network_status.txt',
    '/mobile/status.php',
)


class CaptivePortalClients:
    """Which phones have been through the portal, so the probes can say so.

    Two threads reach this: the web server from request handlers, and nothing
    else today, but the booth has a habit of growing background workers, so the
    table is guarded like every other shared structure here.
    """

    def __init__(self, session_seconds=DEFAULT_SESSION_SECONDS, max_clients=MAX_TRACKED_CLIENTS,
                 time_source=time.monotonic):
        self._session_seconds = max(1, int(session_seconds))
        self._max_clients = max(1, int(max_clients))
        self._now = time_source
        self._lock = threading.Lock()
        self._released = {}

    def _prune(self, now):
        expired = [key for key, released_at in self._released.items()
                   if now - released_at > self._session_seconds]
        for key in expired:
            del self._released[key]

        if len(self._released) > self._max_clients:
            oldest = sorted(self._released.items(), key=lambda item: item[1])
            for key, _released_at in oldest[:len(self._released) - self._max_clients]:
                del self._released[key]

    def is_released(self, key):
        """True when this phone has been through the portal and may be told so."""
        now = self._now()
        with self._lock:
            self._prune(now)
            return key in self._released

    def release(self, key):
        """Stop telling this phone it is captive. Returns True the first time."""
        now = self._now()
        with self._lock:
            self._prune(now)
            was_captive = key not in self._released
            self._released[key] = now

        if was_captive:
            Logger.info('CaptivePortal: %s released, its probes now answer success', key)
        return was_captive

    def forget(self, key):
        with self._lock:
            self._released.pop(key, None)

    def clear(self):
        with self._lock:
            self._released.clear()

    def count(self):
        now = self._now()
        with self._lock:
            self._prune(now)
            return len(self._released)
