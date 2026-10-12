"""The three rows of LED chevrons either side of the lens, dimmed over PWM.

Each row (the left and right chevron of the same rank, wired together) hangs
off its own MOSFET, so the three are driven independently. Between photos they
sit at a steady ambient level; during the countdown a pulse runs from the
outer row to the inner one once a second, pointing the guests at the lens; and
the shot is taken with all three at full power.
"""

import logging
import threading
import time

try:
    from gpiozero import PWMLED
except ImportError:
    PWMLED = None

Logger = logging.getLogger('kivy.photobooth')

# Inner (next to the lens), middle, outer: the wiring the chevrons were built with.
DEFAULT_PINS = (17, 27, 22)
DEFAULT_IDLE_PERCENT = 30

# Fast enough to look steady, slow enough for the Pi's software PWM to stay
# regular. Only ever seen at the ambient level: the shot is taken at 100 %, a
# steady current the camera cannot catch as banding.
PWM_FREQUENCY = 1000

# The pulse that runs towards the lens: when each row peaks within the second,
# outer row first, and how long it takes to rise from the ambient level.
PULSE_PEAKS = {2: 0.15, 1: 0.35, 0: 0.55}
PULSE_HALF_WIDTH = 0.2
FRAME_SECONDS = 1 / 50


def pulse_levels(seconds_into_tick, idle):
    """Brightness of each row, inner first, at a point of one countdown second.

    Each row rises from the ambient level to full power and falls back as the
    pulse passes it; between pulses all three are back at the ambient level.
    """
    levels = []
    for row in range(3):
        distance = abs(seconds_into_tick - PULSE_PEAKS[row])
        boost = max(0.0, 1.0 - distance / PULSE_HALF_WIDTH)
        levels.append(idle + (1.0 - idle) * boost)
    return levels


class Chevrons:
    """Contract for the chevrons.

    `NullChevrons` implements every effect as a no-op, so the application can
    call them unconditionally whether the hardware is present or not.
    """

    def idle(self):
        pass

    def start_countdown(self, time_seconds):
        pass

    def flash(self):
        pass

    def off(self):
        pass


class NullChevrons(Chevrons):
    """Chevrons that do nothing: used when the hardware is absent or disabled."""


class PwmChevrons(Chevrons):
    """Three PWM outputs, inner row first, each with a `value` from 0 to 1."""

    WORKER_STOP_TIMEOUT_SECONDS = 1

    def __init__(self, rows, idle_percent=DEFAULT_IDLE_PERCENT):
        self._rows = tuple(rows)
        self._idle = min(100, max(0, idle_percent)) / 100
        self._proc = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def _set(self, levels):
        for row, level in zip(self._rows, levels):
            row.value = level

    def _stop_worker(self):
        if self._proc and self._proc.is_alive():
            self._stop.set()
            self._proc.join(timeout=self.WORKER_STOP_TIMEOUT_SECONDS)
            if self._proc.is_alive():
                Logger.warning('Chevrons: countdown thread did not stop cleanly')
        self._proc = None
        self._stop.clear()

    def _hold(self, level):
        with self._lock:
            self._stop_worker()
            self._set([level] * len(self._rows))

    def idle(self):
        Logger.info('Chevrons: idle() at %d%%.', round(self._idle * 100))
        self._hold(self._idle)

    def flash(self):
        Logger.info('Chevrons: flash().')
        self._hold(1.0)

    def off(self):
        Logger.info('Chevrons: off().')
        self._hold(0.0)

    def start_countdown(self, time_seconds):
        Logger.info('Chevrons: start_countdown(%s).', time_seconds)
        with self._lock:
            self._stop_worker()
            self._proc = threading.Thread(
                target=self._countdown, args=(time_seconds,), name='chevrons-countdown', daemon=True,
            )
            self._proc.start()

    def _countdown(self, time_seconds):
        start = time.monotonic()
        while True:
            elapsed = time.monotonic() - start
            if elapsed >= time_seconds:
                break
            self._set(pulse_levels(elapsed % 1.0, self._idle))
            if self._stop.wait(FRAME_SECONDS):
                return
        # The screen asks for the flash on its own clock; until it does, the
        # rows wait at the ambient level rather than wherever the pulse left them.
        self._set([self._idle] * len(self._rows))


def create_chevrons(enabled=True, pins=DEFAULT_PINS, idle_percent=DEFAULT_IDLE_PERCENT):
    """Return usable chevrons, never raising.

    A missing gpiozero or a machine that is not a Pi must degrade to a booth
    that still takes photos, not to one that refuses to start.
    """
    if not enabled:
        Logger.info('Chevrons: disabled by configuration')
        return NullChevrons()

    rows = []
    try:
        if PWMLED is None:
            raise RuntimeError('gpiozero is not installed')
        for pin in pins:
            rows.append(PWMLED(pin, frequency=PWM_FREQUENCY))
    except Exception as exc:
        Logger.warning('Chevrons: unavailable (%s), continuing without them', exc)
        # Release the pins already claimed, so a retry or another tool can have them.
        for row in rows:
            row.close()
        return NullChevrons()

    Logger.info('Chevrons: enabled on GPIO %s, ambient %s%%', ', '.join(str(pin) for pin in pins), idle_percent)
    chevrons = PwmChevrons(rows, idle_percent=idle_percent)
    chevrons.idle()
    return chevrons
