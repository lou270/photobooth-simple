"""Sending an abandoned session home, shared by every screen that waits."""

import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault('KIVY_NO_ARGS', '1')
os.environ.setdefault('KIVY_GL_BACKEND', 'mock')

sys.path.append(str(Path(__file__).resolve().parents[1]))
from kivy.clock import Clock

from libs.timings import TIMINGS
from libs.screens import (
    ConfirmCaptureScreen,
    CountdownScreen,
    HomeTimeoutMixin,
    ReviewScreen,
    ScreenMgr,
    SelectFormatScreen,
)


class FakeApp:
    def __init__(self):
        self.transitions = []

    def transition_to(self, screen, **kwargs):
        self.transitions.append(screen)


class Waiting(HomeTimeoutMixin):
    HOME_TIMEOUT_SECONDS = 0.05

    def __init__(self, app, hides_ring=False):
        self.HOME_TIMEOUT_HIDES_RING = hides_ring
        self.app = app
        self.btn_home = SimpleNamespace(progress=1.0, show_progress=False)
        self._init_home_timeout()


@pytest.fixture
def app():
    return FakeApp()


def settle(seconds):
    time.sleep(seconds)
    Clock.tick()


def test_a_forgotten_session_goes_back_to_the_start_screen(app):
    screen = Waiting(app)

    screen._start_home_timeout()
    settle(0.08)

    assert app.transitions == [ScreenMgr.START]


def test_stopping_the_timeout_keeps_the_guest_where_they_are(app):
    screen = Waiting(app)
    screen._start_home_timeout()

    screen._stop_home_timeout()
    settle(0.08)

    assert app.transitions == []


def test_restarting_the_timeout_does_not_stack_two_of_them(app):
    screen = Waiting(app)

    screen._start_home_timeout()
    screen._start_home_timeout()
    settle(0.08)

    assert app.transitions == [ScreenMgr.START]


def test_the_ring_empties_as_the_timeout_runs(app):
    screen = Waiting(app)

    screen._start_home_timeout()
    assert screen.btn_home.progress == 1.0
    settle(0.03)

    assert 0 <= screen.btn_home.progress < 1.0


def test_a_screen_that_owns_the_ring_hides_it_while_idle(app):
    screen = Waiting(app, hides_ring=True)

    screen._start_home_timeout()
    assert screen.btn_home.show_progress is True

    screen._stop_home_timeout()
    assert screen.btn_home.show_progress is False


def test_a_screen_that_shares_the_ring_never_touches_it(app):
    screen = Waiting(app, hides_ring=False)

    screen._start_home_timeout()
    screen._stop_home_timeout()

    assert screen.btn_home.show_progress is False


def test_the_home_button_goes_home(app):
    screen = Waiting(app)
    screen._start_home_timeout()

    screen.home_event(None)

    assert app.transitions == [ScreenMgr.START]
    settle(0.08)
    assert app.transitions == [ScreenMgr.START]  # the timeout was cancelled


# --- the real screens ------------------------------------------------------

@pytest.mark.parametrize(
    'screen',
    [CountdownScreen, ConfirmCaptureScreen, ReviewScreen, SelectFormatScreen],
)
def test_every_waiting_screen_shares_the_behaviour(screen):
    assert issubclass(screen, HomeTimeoutMixin)
    assert screen.HOME_TIMEOUT_SECONDS > 0


def test_a_screen_follows_the_delay_the_operator_set(monkeypatch):
    """Screens are imported before config.ini is read, so they must not copy it."""
    monkeypatch.setattr(TIMINGS, 'review_home', 12)

    assert ReviewScreen.HOME_TIMEOUT_SECONDS == 12


def test_the_confirm_screen_never_leaves_before_it_keeps_the_shot(monkeypatch):
    monkeypatch.setattr(TIMINGS, 'auto_keep', 45)

    assert ConfirmCaptureScreen.HOME_TIMEOUT_SECONDS > TIMINGS.auto_keep


def test_only_the_countdown_owns_the_ring():
    assert CountdownScreen.HOME_TIMEOUT_HIDES_RING is True
    assert ConfirmCaptureScreen.HOME_TIMEOUT_HIDES_RING is False
    assert ReviewScreen.HOME_TIMEOUT_HIDES_RING is False


# --- keeping a shot without being asked ------------------------------------

class Deciding:
    """Just enough of the confirm screen to run its auto-keep countdown."""

    _start_auto_keep = ConfirmCaptureScreen._start_auto_keep
    _stop_auto_keep = ConfirmCaptureScreen._stop_auto_keep
    _update_auto_keep_progress = ConfirmCaptureScreen._update_auto_keep_progress
    _auto_keep_event = ConfirmCaptureScreen._auto_keep_event

    def __init__(self):
        self.btn_confirm = SimpleNamespace(progress=1.0, show_progress=False)
        self._current_shot = 0
        self._auto_keep_clock = None
        self._auto_keep_progress_clock = None
        self._auto_keep_started_at = 0.0
        self.kept = 0

    def keep_event(self, obj):
        self.kept += 1


@pytest.fixture
def quick_auto_keep(monkeypatch):
    monkeypatch.setattr(TIMINGS, 'auto_keep', 0.05)


def test_a_shot_nobody_answers_is_kept(quick_auto_keep):
    screen = Deciding()

    screen._start_auto_keep()
    settle(0.08)

    assert screen.kept == 1


def test_touching_the_photo_gives_the_guest_the_delay_back(quick_auto_keep):
    screen = Deciding()
    screen._start_auto_keep()

    settle(0.03)
    screen._start_auto_keep()
    settle(0.03)

    assert screen.kept == 0
    settle(0.05)
    assert screen.kept == 1


def test_the_confirm_ring_shows_the_delay_running_out(quick_auto_keep):
    screen = Deciding()

    screen._start_auto_keep()
    assert screen.btn_confirm.show_progress is True
    assert screen.btn_confirm.progress == 1.0
    settle(0.03)

    assert 0 <= screen.btn_confirm.progress < 1.0


def test_leaving_the_screen_keeps_nothing_and_hides_the_ring(quick_auto_keep):
    screen = Deciding()
    screen._start_auto_keep()

    screen._stop_auto_keep()
    settle(0.08)

    assert screen.kept == 0
    assert screen.btn_confirm.show_progress is False

