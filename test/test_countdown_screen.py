"""The countdown state machine, and the two ways it used to trap a session.

Exercised without building a screen, the way test_printing_screen.py does: the
countdown owns a clock, a ring and a flash layer, and all three have to come
back to a usable state whatever happens to the capture underneath them.
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault('KIVY_NO_ARGS', '1')
os.environ.setdefault('KIVY_GL_BACKEND', 'mock')

sys.path.append(str(Path(__file__).resolve().parents[1]))
from kivy.clock import Clock
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.widget import Widget

from libs.screens import ScreenMgr
from libs.screens.countdown import CountdownScreen


class Ring(Widget):
    """The circular counter: a real widget, because the screen reparents it."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.texts = []
        self.progress = []

    def set_text(self, text):
        self.texts.append(str(text))

    def set_progress(self, value):
        self.progress.append(value)


class Countdown:
    """Just enough of the countdown screen to run its state machine."""

    timer_event = CountdownScreen.timer_event
    timer_progress = CountdownScreen.timer_progress
    timer_bg = CountdownScreen.timer_bg
    _show_flash = CountdownScreen._show_flash
    _hide_flash = CountdownScreen._hide_flash

    def __init__(self, countdown=5, capture_error=None):
        self.transitions = []
        self.shots = []
        self.capture_error = capture_error

        self.layout = AnchorLayout()
        self.overlay_layout = FloatLayout()
        self.color_background = Widget()
        self.loading_layout = Widget()
        self.btn_trigger = Widget()
        self.overlay_layout.add_widget(self.btn_trigger)

        self.circular_counter = Ring()
        self.overlay_layout.add_widget(self.circular_counter)
        self.camera = SimpleNamespace(opacity=1)

        self._timer_active = True
        self.time_remaining = countdown
        self.total_countdown = countdown
        self.start_time = Clock.get_boottime()
        self._clock = self._clock_progress = self._clock_trigger = None
        self._current_shot = 0
        self._current_format = 0

        def trigger_shot(shot, format_idx):
            if self.capture_error is not None:
                raise self.capture_error
            self.shots.append((shot, format_idx))

        self.app = SimpleNamespace(
            trigger_shot=trigger_shot,
            transition_to=lambda screen, **kw: self.transitions.append(screen),
        )

    def timer_trigger(self, obj):
        """Polls the capture for completion; not what these tests are about."""

    def reenter(self):
        """What on_exit + on_entry leave behind between two visits."""
        self._hide_flash()
        if self.loading_layout.parent:
            self.overlay_layout.remove_widget(self.loading_layout)
        if not self.btn_trigger.parent:
            self.overlay_layout.add_widget(self.btn_trigger)
        self._timer_active = True
        self.time_remaining = self.total_countdown


# --- a capture that cannot even be started ---------------------------------

def test_a_capture_that_fails_to_start_sends_the_guest_to_the_error_screen():
    screen = Countdown(countdown=1, capture_error=RuntimeError('Photo storage is almost full'))

    screen.timer_event(None)

    assert screen.transitions == [ScreenMgr.ERROR]


def test_a_failed_capture_does_not_leave_the_flash_behind():
    """The white blink is added before the shot and taken down 0.2s after it.

    On the failure path that removal was never scheduled, so the layer stayed a
    child of the layout for the life of the process. Kivy refuses to add a
    widget that already has a parent, so every later capture died in add_widget
    before reaching the camera, and the booth answered every session with the
    same error screen long after the disk had been emptied.
    """
    screen = Countdown(countdown=1, capture_error=RuntimeError('Photo storage is almost full'))

    screen.timer_event(None)

    assert screen.color_background.parent is None


def test_the_booth_takes_photos_again_once_the_cause_is_fixed():
    screen = Countdown(countdown=1, capture_error=RuntimeError('Photo storage is almost full'))
    screen.timer_event(None)

    screen.capture_error = None           # the operator freed some space
    screen.reenter()
    screen.transitions.clear()
    screen.timer_event(None)

    assert screen.shots == [(0, 0)]
    assert screen.transitions == []


def test_the_flash_comes_down_after_a_capture_that_worked():
    screen = Countdown(countdown=1)
    screen.timer_event(None)
    assert screen.color_background.parent is not None

    screen.timer_bg(None)

    assert screen.color_background.parent is None


# --- a countdown configured at zero ----------------------------------------

def test_a_countdown_of_zero_takes_the_photo_instead_of_counting_backwards():
    """COUNTDOWN = 0 is what the admin form offers as its minimum.

    A bare truth test on the remaining seconds let it fall to -1, which is
    truthy, so the ring counted down for ever and the shot never came.
    """
    screen = Countdown(countdown=0)

    screen.timer_event(None)

    assert screen.shots == [(0, 0)]
    assert screen.circular_counter.texts == []


def test_a_countdown_of_zero_does_not_divide_by_it():
    """timer_progress runs 30 times a second off Clock.schedule_interval.

    An exception there is not caught by anything: Kivy's default policy
    re-raises it out of the main loop and the booth stops in front of a guest.
    """
    screen = Countdown(countdown=0)

    screen.timer_progress(1 / 30.0)      # must not raise

    assert screen.circular_counter.progress == []


@pytest.mark.parametrize('countdown', [1, 3, 5])
def test_a_configured_countdown_still_counts_down_to_the_shot(countdown):
    screen = Countdown(countdown=countdown)

    for _ in range(countdown):
        screen.timer_event(None)

    assert screen.shots == [(0, 0)]
    assert screen.circular_counter.texts == [str(n) for n in range(countdown - 1, 0, -1)]
