"""Getting the job to the printer, and getting the booth back to the next guest.

Pressing print leaves the review screen for good, so this state machine owns
what happens next: it either frees the booth on its own or hands the guest to
the error screen. Exercised without building a screen, which needs a window
this suite does not have.
"""

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

from libs.screens import PrintingScreen, ScreenMgr
from libs.screens import printing as printing_module


class FakeDevices:
    def __init__(self, status='done'):
        self.status = status

    def get_print_status(self, task_id):
        return self.status


class FakeApp:
    PRINTER_WAIT_TIMEOUT = 45

    def __init__(self, status='done', printer=True, pending=False, photo_error=None):
        self.devices = FakeDevices(status)
        self.printer = printer
        self.pending = pending
        self.photo_error = photo_error
        self.printed = []
        self.counted = 0
        self.transitions = []

    def has_pending_photo_tasks(self):
        return self.pending

    def get_pending_photo_error(self):
        return self.photo_error

    def has_printer(self):
        return self.printer

    def trigger_print(self, copies, format_idx):
        self.printed.append((copies, format_idx))
        return 7

    def track_print_sent(self, copies=1):
        self.counted += copies

    def transition_to(self, screen, **kwargs):
        self.transitions.append((screen, kwargs))


class Printing:
    """Just enough of the printing screen to run its state machine."""

    _tick = PrintingScreen._tick
    _fail = PrintingScreen._fail
    _done = PrintingScreen._done

    def __init__(self, app, copies=1):
        self.app = app
        self._copies = copies
        self._current_format = 0
        self._started_at = time.monotonic()
        self._print_started = False
        self._print_counted = False
        self._print_task_id = None
        self._printer_wait_started_at = None
        self._timeout = app.PRINTER_WAIT_TIMEOUT
        self._clock = None
        self.title = SimpleNamespace(text='')
        self.message = SimpleNamespace(text='')
        self.animation = SimpleNamespace(stop=lambda: None)


def settle(seconds):
    time.sleep(seconds)
    Clock.tick()


@pytest.fixture
def quick_exit(monkeypatch):
    monkeypatch.setattr(printing_module, 'PRINT_DONE_SECONDS', 0.01)


# --- the job goes through --------------------------------------------------

def test_the_booth_frees_itself_once_the_printer_has_the_job(quick_exit):
    app = FakeApp()
    screen = Printing(app)

    screen._tick(None)
    settle(0.05)

    assert app.printed == [(1, 0)]
    assert app.transitions == [(ScreenMgr.START, {})]


def test_a_job_of_three_copies_is_sent_and_counted_as_three(quick_exit):
    app = FakeApp()
    screen = Printing(app, copies=3)

    screen._tick(None)

    assert app.printed == [(3, 0)]
    assert app.counted == 3


def test_a_job_still_running_keeps_the_guest_informed():
    app = FakeApp(status='pending')
    screen = Printing(app)

    screen._tick(None)

    assert app.printed == [(1, 0)]
    assert app.counted == 0
    assert app.transitions == []
    assert screen.message.text  # something to read while it prints


# --- the job does not go through -------------------------------------------

def test_a_photo_that_could_not_be_saved_is_never_printed():
    app = FakeApp(photo_error='disk on fire')
    screen = Printing(app)

    screen._tick(None)

    assert app.printed == []
    assert app.transitions[0][0] == ScreenMgr.ERROR


def test_a_printer_that_refuses_the_job_sends_the_guest_to_the_error_screen():
    app = FakeApp()
    app.trigger_print = lambda copies, format_idx: None  # no task id back
    screen = Printing(app)

    screen._tick(None)

    screen_name, kwargs = app.transitions[0]
    assert screen_name == ScreenMgr.ERROR
    assert kwargs['show_continue'] is True
    assert kwargs['message']  # says the photo was saved anyway


def test_a_printer_that_never_comes_back_gives_up():
    app = FakeApp(printer=False)
    screen = Printing(app)
    screen._printer_wait_started_at = time.monotonic() - 100

    screen._tick(None)

    assert app.transitions[0][0] == ScreenMgr.ERROR


def test_a_printer_that_is_only_briefly_away_is_waited_for():
    app = FakeApp(printer=False)
    screen = Printing(app)

    screen._tick(None)

    assert app.transitions == []
    assert screen._printer_wait_started_at is not None


def test_nothing_is_sent_while_the_photo_is_still_being_written():
    app = FakeApp(pending=True)
    screen = Printing(app)

    screen._tick(None)

    assert app.printed == []
    assert app.transitions == []
