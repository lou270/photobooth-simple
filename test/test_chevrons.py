"""The chevrons: an ambient level, a pulse towards the lens, full power for the shot."""

import sys
import time
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
import libs.hardware.chevrons as chevrons_module
from libs.hardware.chevrons import GAMMA, NullChevrons, PwmChevrons, create_chevrons, pulse_levels


class FakeRow:
    def __init__(self, pin=None, frequency=None, pin_factory=None):
        self.value = 0.0
        self.history = []
        self.closed = False

    def __setattr__(self, name, value):
        if name == 'value' and hasattr(self, 'history'):
            self.history.append(value)
        super().__setattr__(name, value)

    def close(self):
        self.closed = True


def make_chevrons(idle_percent=30):
    rows = [FakeRow(), FakeRow(), FakeRow()]
    return PwmChevrons(rows, idle_percent=idle_percent), rows


def test_disabled_chevrons_do_nothing():
    assert isinstance(create_chevrons(enabled=False), NullChevrons)


def test_missing_gpiozero_degrades_to_null_chevrons(monkeypatch):
    monkeypatch.setattr(chevrons_module, 'PWMLED', None)
    assert isinstance(create_chevrons(enabled=True), NullChevrons)


def test_a_pin_that_cannot_be_claimed_releases_the_others(monkeypatch):
    claimed = []

    def pwmled(pin, frequency, pin_factory=None):
        if pin == 22:
            raise RuntimeError('pin busy')
        row = FakeRow()
        claimed.append(row)
        return row

    monkeypatch.setattr(chevrons_module, 'PWMLED', pwmled)

    assert isinstance(create_chevrons(enabled=True, pins=(17, 27, 22)), NullChevrons)
    assert [row.closed for row in claimed] == [True, True]


def test_working_chevrons_start_at_the_ambient_level(monkeypatch):
    monkeypatch.setattr(chevrons_module, 'PWMLED', FakeRow)

    chevrons = create_chevrons(enabled=True, idle_percent=40)

    assert [row.value for row in chevrons._rows] == pytest.approx([0.4 ** GAMMA] * 3)


def test_null_chevrons_accept_every_effect():
    chevrons = NullChevrons()

    chevrons.idle()
    chevrons.start_countdown(3)
    chevrons.flash()
    chevrons.off()


def test_idle_flash_and_off_hold_every_row():
    chevrons, rows = make_chevrons(idle_percent=25)

    chevrons.idle()
    assert [row.value for row in rows] == pytest.approx([0.25 ** GAMMA] * 3)
    chevrons.flash()
    assert [row.value for row in rows] == [1.0, 1.0, 1.0]
    chevrons.off()
    assert [row.value for row in rows] == [0.0, 0.0, 0.0]


def test_the_pulse_reaches_the_outer_row_first_and_the_inner_row_last():
    idle = 0.3
    peak_of = {}
    for step in range(100):
        moment = step / 100
        for row, level in enumerate(pulse_levels(moment, idle)):
            if level > peak_of.get(row, (None, -1))[1]:
                peak_of[row] = (moment, level)

    outer, middle, inner = peak_of[2][0], peak_of[1][0], peak_of[0][0]
    assert outer < middle < inner
    assert all(level == pytest.approx(1.0) for _moment, level in peak_of.values())


def test_between_pulses_every_row_rests_at_the_ambient_level():
    assert pulse_levels(0.95, 0.3) == pytest.approx([0.3, 0.3, 0.3])


def test_the_pulse_never_drops_below_the_ambient_level():
    for step in range(100):
        assert min(pulse_levels(step / 100, 0.3)) >= 0.3


def test_a_countdown_ends_at_the_ambient_level():
    chevrons, rows = make_chevrons(idle_percent=30)

    chevrons.start_countdown(0.6)
    chevrons._proc.join(timeout=2)

    assert [row.value for row in rows] == pytest.approx([0.3 ** GAMMA] * 3)
    assert max(rows[0].history) > 0.3 ** GAMMA


def test_the_flash_stops_the_countdown_and_stays_at_full_power():
    chevrons, rows = make_chevrons()

    chevrons.start_countdown(10)
    time.sleep(0.1)
    chevrons.flash()
    time.sleep(0.1)

    assert [row.value for row in rows] == [1.0, 1.0, 1.0]
    assert chevrons._proc is None


def test_an_ambient_level_out_of_range_is_clamped():
    chevrons, rows = make_chevrons(idle_percent=150)
    chevrons.idle()
    assert [row.value for row in rows] == [1.0, 1.0, 1.0]


def test_the_ambient_level_is_brightness_as_seen_not_duty_cycle():
    """At a 30 % duty cycle the chevrons already looked nearly full."""
    chevrons, rows = make_chevrons(idle_percent=30)
    chevrons.idle()
    assert rows[0].value < 0.1


def test_the_pigpio_daemon_is_used_when_it_runs(monkeypatch):
    factories = []

    class Factory:
        def __init__(self):
            factories.append(self)

    def pwmled(pin, frequency, pin_factory=None):
        row = FakeRow()
        row.factory = pin_factory
        return row

    monkeypatch.setattr(chevrons_module, 'PiGPIOFactory', Factory)
    monkeypatch.setattr(chevrons_module, 'PWMLED', pwmled)

    chevrons = create_chevrons(enabled=True)

    assert len(factories) == 1
    assert all(row.factory is factories[0] for row in chevrons._rows)


def test_without_pigpiod_the_default_pins_are_used(monkeypatch):
    def unreachable():
        raise OSError('failed to connect to localhost:8888')

    seen = []

    def pwmled(pin, frequency, pin_factory=None):
        seen.append(pin_factory)
        return FakeRow()

    monkeypatch.setattr(chevrons_module, 'PiGPIOFactory', unreachable)
    monkeypatch.setattr(chevrons_module, 'PWMLED', pwmled)

    assert isinstance(create_chevrons(enabled=True), PwmChevrons)
    assert seen == [None, None, None]
