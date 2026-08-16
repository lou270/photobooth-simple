"""Sending an abandoned session home, shared by the three screens that wait."""

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

from libs.screens import (
    ConfirmCaptureScreen,
    CountdownScreen,
    HomeTimeoutMixin,
    ReviewScreen,
    ScreenMgr,
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

@pytest.mark.parametrize('screen', [CountdownScreen, ConfirmCaptureScreen, ReviewScreen])
def test_every_waiting_screen_shares_the_behaviour(screen):
    assert issubclass(screen, HomeTimeoutMixin)
    assert screen.HOME_TIMEOUT_SECONDS > 0


def test_only_the_countdown_owns_the_ring():
    assert CountdownScreen.HOME_TIMEOUT_HIDES_RING is True
    assert ConfirmCaptureScreen.HOME_TIMEOUT_HIDES_RING is False
    assert ReviewScreen.HOME_TIMEOUT_HIDES_RING is False


def test_the_review_home_button_offers_the_success_screen_instead():
    """Its timeout goes home, but pressing home celebrates first."""
    assert ReviewScreen.home_event is not HomeTimeoutMixin.home_event
