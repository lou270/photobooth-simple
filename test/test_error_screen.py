"""The error screen is the one interactive screen with no way back on its own.

A guest whose print failed reads the message and walks off, and everyone who
comes after them is looking at that failure. But an error that only offers a
restart is a booth waiting for an operator, and taking it home would send the
next guest straight into whatever caused it.
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault('KIVY_NO_ARGS', '1')
os.environ.setdefault('KIVY_GL_BACKEND', 'mock')

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.screens import ScreenMgr
from libs.screens.error import ErrorScreen


class Error:
    """Just the walk-away timeout, without the widgets around it."""

    _start_home_timeout = ErrorScreen._start_home_timeout
    _stop_home_timeout = ErrorScreen._stop_home_timeout
    _home_timeout_event = ErrorScreen._home_timeout_event

    def __init__(self, show_continue):
        self.transitions = []
        self._show_continue = show_continue
        self._home_timeout_clock = None
        self.app = SimpleNamespace(
            transition_to=lambda screen, **kw: self.transitions.append(screen))


def test_a_recoverable_error_takes_the_booth_home_by_itself():
    screen = Error(show_continue=True)

    screen._start_home_timeout()

    assert screen._home_timeout_clock is not None


def test_a_booth_in_maintenance_stays_where_it_is():
    """Only a restart button: the operator has to see this, and fixing it is theirs."""
    screen = Error(show_continue=False)

    screen._start_home_timeout()

    assert screen._home_timeout_clock is None


def test_the_timeout_goes_home():
    screen = Error(show_continue=True)
    screen._start_home_timeout()

    screen._home_timeout_event(0)

    assert screen.transitions == [ScreenMgr.START]


def test_leaving_the_screen_takes_the_timeout_with_it():
    screen = Error(show_continue=True)
    screen._start_home_timeout()

    screen._stop_home_timeout()

    assert screen._home_timeout_clock is None
