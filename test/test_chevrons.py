"""The chevrons: an ambient level, a pulse towards the lens, full power for the shot."""

import sys
import time
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
import libs.hardware.chevrons as chevrons_module
from libs.hardware.chevrons import (
    GAMMA, WAVE_BOOST, GpioRows, NullChevrons, PwmChevrons, SerialRows, countdown_levels, create_chevrons, wave_levels,
)


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
    return PwmChevrons(GpioRows(rows), idle_percent=idle_percent), rows


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

    assert [row.value for row in chevrons._rows._rows] == pytest.approx([0.4 ** GAMMA] * 3)


def test_null_chevrons_accept_every_effect():
    chevrons = NullChevrons()

    chevrons.idle()
    chevrons.wave()
    chevrons.show_countdown(3)
    chevrons.flash()
    chevrons.off()
    chevrons.close()


def test_idle_flash_and_off_hold_every_row():
    chevrons, rows = make_chevrons(idle_percent=25)

    chevrons.idle()
    assert [row.value for row in rows] == pytest.approx([0.25 ** GAMMA] * 3)
    chevrons.flash()
    assert [row.value for row in rows] == [1.0, 1.0, 1.0]
    chevrons.off()
    assert [row.value for row in rows] == [0.0, 0.0, 0.0]






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
    assert all(row.factory is factories[0] for row in chevrons._rows._rows)


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


# --- the RP2040 on the serial port ------------------------------------------

class FakePort:
    def __init__(self, fail=False):
        self.lines = []
        self.fail = fail
        self.closed = False

    def write(self, data):
        if self.fail:
            raise OSError('Input/output error')
        self.lines += data.decode('ascii').splitlines()

    def close(self):
        self.closed = True


def make_serial_chevrons(port, idle_percent=30, frequency=200):
    idle_duty = (idle_percent / 100) ** GAMMA
    return PwmChevrons(SerialRows(port, frequency, idle_duty), idle_percent=idle_percent)


def test_the_rp2040_is_told_the_frequency_and_the_ambient_level_first():
    port = FakePort()
    make_serial_chevrons(port, idle_percent=30, frequency=1000)

    ambient = str(round(0.3 ** GAMMA * 65535))
    assert port.lines[0] == 'F 1000'
    assert port.lines[1] == f'I {ambient} {ambient} {ambient}'


def test_levels_go_out_as_16_bit_duty_cycles():
    port = FakePort()
    chevrons = make_serial_chevrons(port)

    chevrons.flash()

    assert port.lines[-1] == 'L 65535 65535 65535'


def test_the_heartbeat_resends_the_levels(monkeypatch):
    monkeypatch.setattr(SerialRows, 'HEARTBEAT_SECONDS', 0.05)
    port = FakePort()
    chevrons = make_serial_chevrons(port)
    chevrons.flash()
    sent = len(port.lines)

    time.sleep(0.2)

    assert len(port.lines) > sent
    assert port.lines[-1] == 'L 65535 65535 65535'
    chevrons.close()


def test_closing_leaves_the_rp2040_dark_for_good():
    port = FakePort()
    chevrons = make_serial_chevrons(port)

    chevrons.close()

    assert 'I 0 0 0' in port.lines
    assert port.lines[-1] == 'L 0 0 0'
    assert port.closed


def test_a_broken_serial_link_never_stops_the_booth():
    chevrons = make_serial_chevrons(FakePort(fail=True))

    chevrons.idle()
    chevrons.flash()
    chevrons.close()


def test_missing_pyserial_degrades_to_null_chevrons(monkeypatch):
    monkeypatch.setattr(chevrons_module, 'serial', None)
    assert isinstance(create_chevrons(enabled=True, driver='serial'), NullChevrons)


def test_an_unplugged_serial_port_degrades_to_null_chevrons(monkeypatch):
    class Serial:
        @staticmethod
        def Serial(port, baudrate, write_timeout):
            raise OSError(f'could not open port {port}')

    monkeypatch.setattr(chevrons_module, 'serial', Serial)
    assert isinstance(create_chevrons(enabled=True, driver='serial'), NullChevrons)


# --- the firmware itself, on a stand-in for MicroPython -----------------------

class FakePwm:
    def __init__(self, pin):
        self.duty = None
        self.frequency = None

    def duty_u16(self, value):
        self.duty = value

    def freq(self, value):
        self.frequency = value


@pytest.fixture
def firmware(monkeypatch):
    import importlib.util
    import types

    machine = types.ModuleType('machine')
    machine.PWM = FakePwm
    machine.Pin = lambda number: number
    machine.UART = object
    monkeypatch.setitem(sys.modules, 'machine', machine)
    path = Path(__file__).resolve().parents[1] / 'firmware' / 'chevrons_rp2040' / 'main.py'
    spec = importlib.util.spec_from_file_location('chevrons_firmware', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_firmware_applies_levels(firmware):
    assert firmware.handle(b'L 100 200 65535')
    assert [row.duty for row in firmware.rows] == [100, 200, 65535]


def test_the_firmware_clamps_what_it_cannot_apply(firmware):
    firmware.handle(b'L -5 70000 3')
    assert [row.duty for row in firmware.rows] == [0, 65535, 3]


def test_the_firmware_ignores_garbage(firmware):
    firmware.handle(b'L 1 2 3')
    for line in (b'', b'L 1 2', b'X 1 2 3', b'L a b c', b'\xff\xfe'):
        assert not firmware.handle(line)
    assert [row.duty for row in firmware.rows] == [1, 2, 3]


def test_the_firmware_keeps_the_levels_across_a_new_frequency(firmware):
    firmware.handle(b'L 10 20 30')
    firmware.handle(b'F 500')
    assert [row.frequency for row in firmware.rows] == [500, 500, 500]
    assert [row.duty for row in firmware.rows] == [10, 20, 30]


def test_the_firmware_remembers_the_ambient_level_without_applying_it(firmware):
    firmware.handle(b'L 1 1 1')
    firmware.handle(b'I 7 8 9')
    assert firmware.idle_duties == [7, 8, 9]
    assert [row.duty for row in firmware.rows] == [1, 1, 1]


def test_a_quiet_booth_brings_the_chevrons_back_to_the_ambient_level(firmware):
    firmware.handle(b'I 7 8 9')
    firmware.handle(b'L 65535 65535 65535')

    state = firmware.fall_back(firmware.SILENCE_MS + 1, 'live')

    assert state == 'idle'
    assert [row.duty for row in firmware.rows] == [7, 8, 9]


def test_a_booth_silent_for_a_minute_leaves_the_chevrons_dark(firmware):
    firmware.handle(b'I 7 8 9')
    firmware.handle(b'L 65535 65535 65535')

    state = firmware.fall_back(firmware.SILENCE_MS + 1, 'live')
    state = firmware.fall_back(firmware.DARK_AFTER_MS + 1, state)

    assert state == 'dark'
    assert [row.duty for row in firmware.rows] == [0, 0, 0]


def test_a_short_silence_changes_nothing(firmware):
    firmware.handle(b'L 1 2 3')

    assert firmware.fall_back(firmware.SILENCE_MS - 1, 'live') == 'live'
    assert [row.duty for row in firmware.rows] == [1, 2, 3]


# --- the countdown and the welcome wave -------------------------------------

@pytest.mark.parametrize('remaining,expected', [
    (5, [0.3, 0.3, 0.3]),
    (4, [0.3, 0.3, 0.3]),
    (3, [0.3, 0.3, 1.0]),
    (2, [0.3, 1.0, 1.0]),
    (1, [1.0, 1.0, 1.0]),
])
def test_the_countdown_lights_the_rows_from_the_outside_in(remaining, expected):
    assert countdown_levels(remaining, 0.3) == expected


def test_the_countdown_shows_on_the_rows():
    chevrons, rows = make_chevrons(idle_percent=30)

    chevrons.show_countdown(2)

    assert [row.value for row in rows] == pytest.approx([0.3 ** GAMMA, 1.0, 1.0])


def test_the_wave_reaches_the_outer_row_first_and_the_inner_row_last():
    crest_of = {}
    for step in range(300):
        moment = step / 100
        for row, level in enumerate(wave_levels(moment, 0.3)):
            if level > crest_of.get(row, (None, -1))[1]:
                crest_of[row] = (moment, level)

    outer, middle, inner = crest_of[2][0], crest_of[1][0], crest_of[0][0]
    assert outer < middle < inner


def test_the_wave_stays_between_the_ambient_level_and_a_little_above():
    for step in range(300):
        for level in wave_levels(step / 100, 0.3):
            assert 0.3 <= level <= 0.3 + WAVE_BOOST + 1e-9


def test_the_wave_never_goes_past_full_power():
    assert max(max(wave_levels(step / 100, 0.95)) for step in range(300)) <= 1.0


def test_the_wave_moves_until_something_else_is_shown():
    chevrons, rows = make_chevrons(idle_percent=30)

    chevrons.wave()
    time.sleep(0.3)
    chevrons.flash()
    time.sleep(0.1)

    assert len(set(rows[0].history)) > 2
    assert [row.value for row in rows] == [1.0, 1.0, 1.0]
    assert chevrons._proc is None


def test_full_power_reaches_the_rp2040_as_its_top_value():
    """65535 is what MicroPython turns into a steady high, with no PWM at all."""
    port = FakePort()
    chevrons = make_serial_chevrons(port)

    chevrons.show_countdown(1)
    assert port.lines[-1] == 'L 65535 65535 65535'
    chevrons.flash()
    assert port.lines[-1] == 'L 65535 65535 65535'


def test_the_firmware_passes_full_power_through_untouched(firmware):
    firmware.handle(b'L 65535 65535 65535')
    assert [row.duty for row in firmware.rows] == [65535, 65535, 65535]
