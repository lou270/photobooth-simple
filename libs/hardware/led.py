import colorsys
import logging
import math
import threading
import time

import numpy as np

try:
    import spidev
except ImportError:
    spidev = None

Logger = logging.getLogger('kivy.photobooth')


class Led:
    """Contract for the ring light.

    `NullLed` implements every effect as a no-op, so the application can call
    the ring unconditionally whether the hardware is present, disabled by
    configuration, or missing on a machine that is not a Raspberry Pi.
    """

    def start_countdown(self, time_seconds):
        pass

    def start_rainbow(self):
        pass

    def flash(self, stop=False):
        pass

    def blink(self, color):
        pass

    def wave(self, color):
        pass

    def clear(self):
        pass


class NullLed(Led):
    """Ring light that does nothing: used when the hardware is absent or disabled."""


class WS2812:
    def __init__(self, spi, nb_leds=12):
        self._spi = spi
        self._nb_leds = nb_leds
        # One list per pixel: a shared row would make set() mutate every pixel.
        self._pixels = [[0, 0, 0] for _ in range(self._nb_leds)]

    def write(self, rgb, brightness=1.0):
        self._pixels = rgb
        scaled_rgb = [[int(c * brightness) for c in color] for color in rgb]
        grb = [[arr[1], arr[0], arr[2]] for arr in scaled_rgb]
        d = np.array(grb).ravel()
        tx = np.zeros(len(d) * 4, dtype=np.uint8)
        for ibit in range(4):
            tx[3 - ibit::4] = ((d >> (2 * ibit + 1)) & 1) * 0x60 + ((d >> (2 * ibit + 0)) & 1) * 0x06 + 0x88
        self._spi.xfer(tx.tolist(), int(4 / 1.25e-6))

    def fill(self, color, brightness=1.0):
        self.write([list(color) for _ in range(self._nb_leds)], brightness)

    def set(self, pixel, color, brightness=1.0):
        self._pixels[pixel] = [int(c * brightness) for c in color]
        self.write(self._pixels)

    def get(self, pixel=-1):
        if pixel < 0:
            return self._pixels
        return self._pixels[pixel]


class RingLed(Led):
    """WS2812 ring driven over SPI.

    Raises on construction when SPI is unavailable; use `create_led()` to get a
    working ring or a NullLed instead of having to handle that here.
    """

    # Every effect now waits on the stop flag rather than sleeping past it, so
    # this only has to cover one SPI write. Reaching it means something is
    # genuinely wedged, and starting a second effect on the bus would make it
    # worse rather than better.
    WORKER_STOP_TIMEOUT_SECONDS = 1

    def __init__(self, num_pixels=12):
        Logger.info('RingLed: __init__().')
        if spidev is None:
            raise RuntimeError('spidev is not installed')

        self._num_pixels = num_pixels
        self._top_pixel = 6
        self._proc = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

        spi = spidev.SpiDev()
        spi.open(0, 0)  # raises when SPI is not enabled on the board
        self._leds = WS2812(spi, self._num_pixels)

    def _stop_worker(self):
        """Stop the running effect. False when it would not let go.

        A countdown checks the stop flag once per pixel, so a long one can take
        several seconds to notice. Forgetting the thread anyway and starting the
        next effect put two of them on the SPI bus at once, which is what turns
        a ring light into confetti.
        """
        if self._proc and self._proc.is_alive():
            self._stop.set()
            self._proc.join(timeout=self.WORKER_STOP_TIMEOUT_SECONDS)
            if self._proc.is_alive():
                Logger.warning('RingLed: worker thread did not stop cleanly, skipping this effect')
                return False
        self._proc = None
        return True

    def _start_worker(self, name, target, *args):
        with self._lock:
            if not self._stop_worker():
                return
            self._stop.clear()
            self._proc = threading.Thread(target=target, args=args, name=f'ringled-{name}', daemon=True)
            self._proc.start()

    def start_countdown(self, time_seconds):
        Logger.info('RingLed: start_countdown().')
        self._start_worker('countdown', self._countdown, time_seconds)

    def start_rainbow(self):
        Logger.info('RingLed: start_rainbow().')
        self._start_worker('rainbow', self._rainbow)

    def flash(self, stop=False):
        Logger.info('RingLed: flash().')
        with self._lock:
            self._stop_worker()
            self._stop.clear()
        if stop:
            self._leds.fill([0, 0, 0])
        else:
            self._leds.fill([255, 255, 255])
            time.sleep(0.1)

    def blink(self, color):
        Logger.info('RingLed: blink().')
        self._start_worker('blink', self._blink, color)

    def wave(self, color):
        Logger.info('RingLed: wave().')
        self._start_worker('wave', self._wave, color)

    def clear(self):
        Logger.info('RingLed: clear().')
        with self._lock:
            self._stop_worker()
            self._stop.clear()
            self._leds.fill([0, 0, 0])

    def _blink(self, color):
        while True:
            self._leds.fill(color)
            if self._stop.wait(0.1):
                return
            self._leds.fill([0, 0, 0])
            if self._stop.wait(0.1):
                return

    def _wave(self, color):
        wave_intensity = 0.5
        wave_length = self._num_pixels
        while True:
            for step in range(self._num_pixels):
                for i in range(self._num_pixels):
                    # Calculate intensity based on a sine wave
                    intensity = (math.sin(2 * math.pi * ((i + step) % wave_length) / wave_length) + 1) / 2
                    intensity = wave_intensity * intensity  # Scale intensity to desired range
                    self._leds.set(i, color, brightness=intensity)
                    if self._stop.is_set():
                        return
                if self._stop.wait(0.1):
                    return

    def _countdown(self, time_seconds):
        time_between_pixels = time_seconds / self._num_pixels
        p1 = reversed(range(0, self._top_pixel + 1))
        p2 = reversed(range(self._top_pixel, self._num_pixels))

        self._leds.fill([255, 255, 255])
        time.sleep(0.1)
        for i in [*p1, *p2]:
            self._leds.set(i, [0, 0, 0])
            # Waiting on the flag rather than sleeping past it: a long countdown
            # spaces these several seconds apart, and clear() was giving up on
            # the thread before it looked.
            if self._stop.wait(time_between_pixels):
                return

    def _rainbow(self):
        hue_step = 1.0 / self._num_pixels

        while True:
            for step in range(self._num_pixels):
                for i in range(self._num_pixels):
                    # Calculate hue for the current LED, with an offset for rotation
                    hue = (hue_step * ((i + step) % self._num_pixels)) % 1.0
                    rgb = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
                    rgb_scaled = [int(255 * x) for x in rgb]
                    self._leds.set(i, rgb_scaled)
                    if self._stop.is_set():
                        return
                if self._stop.wait(0.1):
                    return


def create_led(enabled=True, num_pixels=12):
    """Return a usable ring light, never raising.

    A missing spidev, a disabled SPI bus or a wiring problem must degrade to a
    booth that still takes photos, not to a booth that refuses to start.
    """
    if not enabled:
        Logger.info('Led: ring light disabled by configuration')
        return NullLed()

    try:
        led = RingLed(num_pixels=num_pixels)
    except Exception as exc:
        Logger.warning('Led: ring light unavailable (%s), continuing without it', exc)
        return NullLed()

    Logger.info('Led: ring light enabled (%s pixels)', num_pixels)
    return led
