import logging
import threading
import time
import traceback

Logger = logging.getLogger('kivy.photobooth')


class ProcessRunner:
    """Runs one background job at a time and remembers how it ended.

    Captures and collages are slow and must never block the UI thread, but the
    UI still has to poll their outcome from its clock. Every query here is
    therefore cheap and non-blocking: is the job still running, did it fail, has
    it been running for too long.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._abandoned_thread = None
        self._token = 0
        self._state = self._idle_state()

    @staticmethod
    def _idle_state():
        return {
            'kind': None,
            'token': 0,
            'error': None,
            'traceback': None,
            'started_at': None,
            'finished_at': None,
        }

    def start(self, kind, target, *args, **kwargs):
        """Run `target` in a daemon thread, replacing any previously tracked job."""
        with self._lock:
            self._token += 1
            token = self._token
            self._state = {
                'kind': kind,
                'token': token,
                'error': None,
                'traceback': None,
                'started_at': time.monotonic(),
                'finished_at': None,
            }
            thread = threading.Thread(
                target=self._run,
                args=(kind, token, target, args, kwargs),
                name=f'photobooth-{kind}-{token}',
                daemon=True,
            )
            self._thread = thread

        Logger.info('ProcessRunner: %s started token=%s', kind, token)
        thread.start()
        return token

    def _run(self, kind, token, target, args, kwargs):
        error = None
        formatted_traceback = None

        try:
            target(*args, **kwargs)
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__
            formatted_traceback = traceback.format_exc()
            Logger.error('ProcessRunner: %s failed: %s', kind, error)
            Logger.error(formatted_traceback)
        finally:
            # A job abandoned while it was running no longer owns the state:
            # its outcome must not overwrite whatever replaced it.
            with self._lock:
                duration = None
                if self._state.get('token') == token:
                    self._state['error'] = error
                    self._state['traceback'] = formatted_traceback
                    self._state['finished_at'] = time.monotonic()
                    duration = self._state['finished_at'] - self._state['started_at']

            if error is None:
                Logger.info('ProcessRunner: %s completed token=%s duration=%.2fs', kind, token, duration or 0)
            else:
                Logger.error('ProcessRunner: %s finished with error token=%s duration=%.2fs', kind, token, duration or 0)

    def is_running(self):
        with self._lock:
            thread = self._thread
        return bool(thread and thread.is_alive())

    def state(self):
        with self._lock:
            return dict(self._state)

    def has_failed(self, kind=None):
        state = self.state()
        if kind is not None and state.get('kind') != kind:
            return False
        return state.get('error') is not None

    def get_error(self, kind=None):
        state = self.state()
        if kind is not None and state.get('kind') != kind:
            return None
        return state.get('traceback') or state.get('error')

    def has_timed_out(self, kind, timeout_seconds):
        state = self.state()
        if state.get('kind') != kind or state.get('finished_at') is not None:
            return False
        started_at = state.get('started_at')
        if started_at is None:
            return False
        return (time.monotonic() - started_at) >= timeout_seconds

    def abandon(self, kind=None, reason='unknown'):
        """Stop tracking the current job.

        The thread itself keeps running: it is usually blocked inside a camera
        driver and cannot be interrupted, so the caller must treat the device as
        unusable until it has been reset.
        """
        with self._lock:
            if kind is not None and self._state.get('kind') != kind:
                return False
            Logger.warning('ProcessRunner: abandoning %s reason=%s', self._state.get('kind'), reason)
            self._token += 1
            self._state['error'] = reason
            self._state['finished_at'] = time.monotonic()
            self._abandoned_thread = self._thread
            self._thread = None
        return True

    def wait_for_abandoned(self, timeout):
        """Give an abandoned job a bounded chance to leave its native driver.

        Returns False when it is still running. Callers must treat that as "this
        device can never be safely released": freeing a handle a thread is
        blocked inside segfaults the process instead of raising.
        """
        with self._lock:
            thread = self._abandoned_thread

        if thread is None or not thread.is_alive():
            return True

        thread.join(timeout)
        if thread.is_alive():
            return False

        with self._lock:
            if self._abandoned_thread is thread:
                self._abandoned_thread = None
        return True
