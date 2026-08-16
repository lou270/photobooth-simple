"""An unusable ring light must degrade to a no-op, never stop the booth."""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
import libs.hardware.led as led_module
from libs.hardware.led import NullLed, WS2812, create_led


class FakeSpi:
    def __init__(self):
        self.written = []

    def xfer(self, data, speed):
        self.written.append(list(data))


def test_disabled_ring_returns_a_null_led():
    assert isinstance(create_led(enabled=False), NullLed)


def test_missing_spi_support_degrades_to_a_null_led(monkeypatch):
    monkeypatch.setattr(led_module, 'spidev', None)
    assert isinstance(create_led(enabled=True), NullLed)


def test_failing_spi_bus_degrades_to_a_null_led(monkeypatch):
    class ExplodingSpiDev:
        def SpiDev(self):
            raise OSError('SPI not enabled on this board')

    monkeypatch.setattr(led_module, 'spidev', ExplodingSpiDev())
    assert isinstance(create_led(enabled=True), NullLed)


def test_null_led_accepts_every_effect():
    led = NullLed()

    led.start_countdown(5)
    led.start_rainbow()
    led.flash()
    led.flash(stop=True)
    led.blink([255, 255, 255])
    led.wave([255, 255, 255])
    led.clear()


def test_single_pixel_can_be_read_back():
    strip = WS2812(FakeSpi(), nb_leds=4)

    strip.set(2, [10, 20, 30])

    assert strip.get(2) == [10, 20, 30]
    assert len(strip.get()) == 4


def test_pixels_do_not_share_the_same_list():
    strip = WS2812(FakeSpi(), nb_leds=4)

    strip.get(0)[0] = 255

    assert strip.get(1) == [0, 0, 0]


def test_fill_honours_brightness():
    spi = FakeSpi()
    strip = WS2812(spi, nb_leds=2)

    strip.fill([200, 100, 50], brightness=1.0)
    at_full = spi.written[-1]
    strip.fill([200, 100, 50], brightness=0.25)
    dimmed = spi.written[-1]

    assert at_full != dimmed
