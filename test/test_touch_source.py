"""One tap, one touch: the touchscreen reaching Kivy by two paths at once."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault('KIVY_NO_ARGS', '1')

sys.path.append(str(Path(__file__).resolve().parents[1]))
from kivy.event import EventDispatcher

from libs.touch_source import TouchSourceFilter, install


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def touch(device):
    return SimpleNamespace(device=device, is_touch=True)


def tap(touch_filter, me):
    """What the window would let through of a whole tap: begin, update, end."""
    return [etype for etype in ('begin', 'update', 'end') if not touch_filter.on_motion(None, etype, me)]


def test_a_tap_seen_by_both_paths_reaches_the_screen_once():
    clock = FakeClock()
    touch_filter = TouchSourceFilter(clock)

    first = tap(touch_filter, touch('hidinput_mtdev'))
    clock.now += 0.01
    second = tap(touch_filter, touch('mouse'))

    assert first == ['begin', 'update', 'end']
    assert second == []


def test_the_late_path_stays_ignored_even_when_it_wins_the_race():
    clock = FakeClock()
    touch_filter = TouchSourceFilter(clock)
    tap(touch_filter, touch('hidinput_mtdev'))
    clock.now += 0.01
    tap(touch_filter, touch('mouse'))

    clock.now += 5
    early_mouse = tap(touch_filter, touch('mouse'))
    clock.now += 0.01
    late_touchscreen = tap(touch_filter, touch('hidinput_mtdev'))

    assert early_mouse == []
    assert late_touchscreen == ['begin', 'update', 'end']


def test_a_single_path_is_never_filtered():
    """Started from a console, or on Windows: only one device ever speaks."""
    clock = FakeClock()
    touch_filter = TouchSourceFilter(clock)

    taps = []
    for _ in range(5):
        taps.append(tap(touch_filter, touch('mouse')))
        clock.now += 0.1         # quick taps on the same device are real taps

    assert taps == [['begin', 'update', 'end']] * 5


def test_two_devices_used_far_apart_are_both_kept():
    """An operator's mouse plugged in next to the touchscreen still works."""
    clock = FakeClock()
    touch_filter = TouchSourceFilter(clock)

    tap(touch_filter, touch('hidinput_mtdev'))
    clock.now += 2
    mouse = tap(touch_filter, touch('mouse'))

    assert mouse == ['begin', 'update', 'end']


class Window(EventDispatcher):
    __events__ = ('on_motion',)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.touches = []

    def on_motion(self, etype, me):
        self.touches.append((etype, me.device))


def test_a_swallowed_event_never_reaches_the_window_default_handler():
    """The filter relies on a bound handler returning True to stop dispatch."""
    clock = FakeClock()
    window = Window()
    touch_filter = install(window, clock)

    window.dispatch('on_motion', 'begin', touch('hidinput_mtdev'))
    clock.now += 0.01
    window.dispatch('on_motion', 'begin', touch('mouse'))

    assert window.touches == [('begin', 'hidinput_mtdev')]
    assert touch_filter is not None
