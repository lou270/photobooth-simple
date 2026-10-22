"""The three rows of LED chevrons either side of the lens, dimmed over PWM.

Each row (the left and right chevron of the same rank, wired together) hangs
off its own MOSFET, so the three are driven independently. Between photos they
sit at a steady ambient level; during the countdown a pulse runs from the
outer row to the inner one once a second, pointing the guests at the lens; and
the shot is taken with all three at full power.

The PWM comes either from the Pi's own GPIO, or from an RP2040 on the Pi's
serial port running firmware/chevrons_rp2040/main.py. The Pi can only make
PWM in software, and its jitter shows as a shimmer at low levels; the RP2040
makes it in hardware.
"""

import logging
import threading
import time

try:
    from gpiozero import PWMLED
except ImportError:
    PWMLED = None

try:
    from gpiozero.pins.pigpio import PiGPIOFactory
except ImportError:
    PiGPIOFactory = None

try:
    import serial
except ImportError:
    serial = None

Logger = logging.getLogger('kivy.photobooth')

DRIVERS = ('gpio', 'serial')

# Inner (next to the lens), middle, outer: the wiring the chevrons were built with.
DEFAULT_PINS = (17, 27, 22)
DEFAULT_IDLE_PERCENT = 30
DEFAULT_SERIAL_PORT = '/dev/serial0'
SERIAL_BAUDRATE = 115200

# Fast enough for the eye, slow enough for the Pi's software PWM to stay
# regular: at 1 kHz its jitter showed as a visible shimmer, and MOSFET modules
# built around an optocoupler stretched every pulse until 30 % looked like full
# power. Only ever seen at the ambient level: the shot is taken at 100 %, a
# steady current the camera cannot catch as banding.
DEFAULT_PWM_FREQUENCY = 200

# Levels are brightness as the eye sees it, which grows much faster than the
# duty cycle: a 30 % duty cycle already looks nearly full. Raising to this power
# turns a perceived level into the duty cycle that produces it.
GAMMA = 2.2

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


def duty_cycle(level):
    """The duty cycle, 0 to 1, that looks like `level` to the eye."""
    return level ** GAMMA


class GpioRows:
    """Three gpiozero PWMLEDs, inner row first."""

    def __init__(self, rows):
        self._rows = tuple(rows)

    def write(self, duties):
        for row, duty in zip(self._rows, duties):
            row.value = duty

    def close(self):
        for row in self._rows:
            row.close()


class SerialRows:
    """Three hardware PWM outputs on an RP2040, reached over a serial port.

    Each change is one line, `L inner middle outer`, duty cycles from 0 to
    65535. The levels are resent every HEARTBEAT_SECONDS along with the ambient
    one (`I ...`): the firmware falls back to that once the booth goes quiet, so
    a crashed booth never leaves the chevrons blazing at 100 %, and an RP2040
    that rebooted is put back where it was within a second.
    """

    HEARTBEAT_SECONDS = 1

    def __init__(self, port, frequency, idle_duty):
        self._port = port
        self._duties = (0.0, 0.0, 0.0)
        self._idle_duties = (idle_duty,) * 3
        self._frequency = frequency
        self._failing = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        with self._lock:
            self._send_state()
        self._heartbeat = threading.Thread(target=self._beat, name='chevrons-heartbeat', daemon=True)
        self._heartbeat.start()

    @staticmethod
    def _line(command, duties):
        return f'{command} ' + ' '.join(str(round(duty * 65535)) for duty in duties)

    def _send(self, *lines):
        try:
            self._port.write(''.join(f'{line}\n' for line in lines).encode('ascii'))
        except Exception as exc:
            # Once, not fifty times a second for the rest of the evening.
            if not self._failing:
                Logger.warning('Chevrons: serial write failed: %s', exc)
            self._failing = True
        else:
            if self._failing:
                Logger.info('Chevrons: serial link back')
            self._failing = False

    def _send_state(self):
        self._send(
            f'F {self._frequency}',
            self._line('I', self._idle_duties),
            self._line('L', self._duties),
        )

    def _beat(self):
        while not self._stop.wait(self.HEARTBEAT_SECONDS):
            with self._lock:
                self._send_state()

    def write(self, duties):
        with self._lock:
            self._duties = tuple(duties)
            self._send(self._line('L', self._duties))

    def close(self):
        """Off for good: an ambient level of 0, so the firmware stays dark."""
        self._stop.set()
        self._heartbeat.join(timeout=self.HEARTBEAT_SECONDS * 2)
        with self._lock:
            self._idle_duties = self._duties = (0.0, 0.0, 0.0)
            self._send_state()
        try:
            self._port.close()
        except Exception:
            pass


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

    def close(self):
        """Off, and the hardware released: the booth is shutting down."""


class NullChevrons(Chevrons):
    """Chevrons that do nothing: used when the hardware is absent or disabled."""


class PwmChevrons(Chevrons):
    """The effects, played on rows whose `write()` takes three duty cycles."""

    WORKER_STOP_TIMEOUT_SECONDS = 1

    def __init__(self, rows, idle_percent=DEFAULT_IDLE_PERCENT):
        self._rows = rows
        self._idle = min(100, max(0, idle_percent)) / 100
        self._proc = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def _set(self, levels):
        self._rows.write([duty_cycle(level) for level in levels])

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
            self._set([level] * 3)

    def idle(self):
        Logger.info('Chevrons: idle() at %d%%.', round(self._idle * 100))
        self._hold(self._idle)

    def flash(self):
        Logger.info('Chevrons: flash().')
        self._hold(1.0)

    def off(self):
        Logger.info('Chevrons: off().')
        self._hold(0.0)

    def close(self):
        self.off()
        self._rows.close()

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
        self._set([self._idle] * 3)


def _pin_factory():
    """The pigpio daemon when it runs, else gpiozero's own choice.

    pigpio times the pulses by DMA, so they stay regular whatever the CPU is
    doing; the default factory toggles the pins from a thread, and assembling a
    collage is enough to make the chevrons waver.
    """
    if PiGPIOFactory is None:
        return None, 'default (pigpio not installed)'
    try:
        return PiGPIOFactory(), 'pigpio'
    except Exception as exc:
        return None, f'default (pigpiod unreachable: {exc})'


def _open_gpio_rows(pins, frequency):
    if PWMLED is None:
        raise RuntimeError('gpiozero is not installed')
    factory, factory_name = _pin_factory()
    rows = []
    try:
        for pin in pins:
            rows.append(PWMLED(pin, frequency=frequency, pin_factory=factory))
    except Exception:
        # Release the pins already claimed, so a retry or another tool can have them.
        for row in rows:
            row.close()
        raise
    description = f"GPIO {', '.join(str(pin) for pin in pins)}, pin factory {factory_name}"
    return GpioRows(rows), description


def _open_serial_rows(port, frequency, idle_percent):
    if serial is None:
        raise RuntimeError('pyserial is not installed')
    link = serial.Serial(port, SERIAL_BAUDRATE, write_timeout=1)
    idle_duty = duty_cycle(min(100, max(0, idle_percent)) / 100)
    return SerialRows(link, frequency, idle_duty), f'RP2040 on {port}'


def create_chevrons(enabled=True, driver='gpio', pins=DEFAULT_PINS, idle_percent=DEFAULT_IDLE_PERCENT,
                    frequency=DEFAULT_PWM_FREQUENCY, serial_port=DEFAULT_SERIAL_PORT):
    """Return usable chevrons, never raising.

    A missing library, a machine that is not a Pi or an unplugged RP2040 must
    degrade to a booth that still takes photos, not to one that refuses to start.
    """
    if not enabled:
        Logger.info('Chevrons: disabled by configuration')
        return NullChevrons()

    try:
        if driver == 'serial':
            rows, description = _open_serial_rows(serial_port, frequency, idle_percent)
        else:
            rows, description = _open_gpio_rows(pins, frequency)
    except Exception as exc:
        Logger.warning('Chevrons: unavailable (%s), continuing without them', exc)
        return NullChevrons()

    Logger.info('Chevrons: enabled on %s, ambient %s%%, %s Hz', description, idle_percent, frequency)
    chevrons = PwmChevrons(rows, idle_percent=idle_percent)
    chevrons.idle()
    return chevrons
