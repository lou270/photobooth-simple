"""Getting the job to the printer, and getting the booth back to the next guest.

Pressing print leaves the review screen for good, so this state machine owns
what happens next: it either frees the booth on its own or hands the guest to
the error screen. Exercised without building a screen, which needs a window
this suite does not have.
"""

import json
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

from libs import i18n
from libs.screens import PrintingScreen, ScreenMgr
from libs.screens import printing as printing_module
from libs.timings import TIMINGS


class FakeDevices:
    def __init__(self, status='done'):
        self.status = status
        self.asked = []

    def get_print_status(self, task_id):
        self.asked.append(task_id)
        return self.status


class FakeApp:
    PRINTER_WAIT_TIMEOUT = 45

    def __init__(self, status='done', problem=None, pending=False, photo_error=None):
        self.devices = FakeDevices(status)
        self.problem = problem
        self.pending = pending
        self.photo_error = photo_error
        self.printed = []
        self.counted = 0
        self.transitions = []

    def has_pending_photo_tasks(self):
        return self.pending

    def get_pending_photo_error(self):
        return self.photo_error

    def get_printer_problem(self):
        return self.problem

    def trigger_print(self, copies, format_idx):
        self.printed.append((copies, format_idx))
        return list(range(7, 7 + copies))  # one task per sheet

    def track_print_sent(self, copies=1):
        self.counted += copies

    def transition_to(self, screen, **kwargs):
        self.transitions.append((screen, kwargs))


class Printing:
    """Just enough of the printing screen to run its state machine."""

    _tick = PrintingScreen._tick
    _fail = PrintingScreen._fail
    _done = PrintingScreen._done
    _leave = PrintingScreen._leave
    _count_sheets_ahead = PrintingScreen._count_sheets_ahead
    _wait_for_printer = PrintingScreen._wait_for_printer
    _end_printer_wait = PrintingScreen._end_printer_wait

    def __init__(self, app, copies=1):
        self.app = app
        self._copies = copies
        self._current_format = 0
        self._started_at = time.monotonic()
        self._print_started = False
        self._print_counted = False
        self._print_task_ids = []
        self._earlier_task_ids = []
        self._printer_wait_started_at = None
        self._can_leave = False
        self._timeout = app.PRINTER_WAIT_TIMEOUT
        self._clock = None
        self.title = SimpleNamespace(text='')
        self.message = SimpleNamespace(text='')
        self.animation = SimpleNamespace(running=True)
        self.animation.start = lambda: setattr(self.animation, 'running', True)
        self.animation.stop = lambda: setattr(self.animation, 'running', False)


def settle(seconds):
    time.sleep(seconds)
    Clock.tick()


@pytest.fixture
def quick_exit(monkeypatch):
    monkeypatch.setattr(printing_module, 'PRINT_DONE_SECONDS', 0.01)
    monkeypatch.setattr(TIMINGS, 'print_min', 0.01)


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


def test_only_the_first_sheet_of_a_three_copy_job_is_waited_for(quick_exit):
    """Three sheets are three printer tasks; the guest waits for the first.

    Waiting for the last held the booth a minute a copy on a dye-sub, while the
    other sheets were only ever going to come out behind the first.
    """
    app = FakeApp()
    app.devices.get_print_status = lambda task_id: 'done' if task_id == 7 else 'pending'
    screen = Printing(app, copies=3)

    screen._tick(None)

    assert screen._print_task_ids == [7, 8, 9]
    assert app.counted == 3
    assert screen._can_leave


def test_a_job_is_not_done_while_its_first_sheet_is_still_printing(quick_exit):
    app = FakeApp()
    app.devices.get_print_status = lambda task_id: 'pending' if task_id == 7 else 'done'
    screen = Printing(app, copies=2)

    screen._tick(None)

    assert app.counted == 0
    assert app.transitions == []


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
    app = FakeApp(status='pending', problem='unavailable')
    screen = Printing(app)
    screen._printer_wait_started_at = time.monotonic() - 100

    screen._tick(None)

    assert app.transitions[0][0] == ScreenMgr.ERROR


def test_a_printer_that_is_only_briefly_away_is_waited_for():
    app = FakeApp(status='pending', problem='unavailable')
    screen = Printing(app)

    screen._tick(None)

    assert app.transitions == []
    assert screen._printer_wait_started_at is not None


# --- a printer out of paper ------------------------------------------------

def test_a_printer_out_of_paper_says_so_at_once():
    """It used to announce the photo, then count down a wait for a printer
    that had "gone": nothing told the guest it was paper, or to fetch someone."""
    app = FakeApp(status='pending', problem='paper')
    screen = Printing(app)

    screen._tick(None)

    assert screen.title.text == i18n.t('printing.stuck_title.paper')
    assert screen.message.text == i18n.t('printing.stuck_message')
    assert app.transitions == []
    assert not screen.animation.running   # the sheet stops with the printer


@pytest.mark.parametrize('problem', ['ribbon', 'jam', 'cover', 'stopped'])
def test_a_printer_stopped_for_another_reason_names_it(problem):
    app = FakeApp(status='pending', problem=problem)
    screen = Printing(app)

    screen._tick(None)

    assert screen.title.text == i18n.t(f'printing.stuck_title.{problem}')
    assert app.transitions == []


def test_every_stuck_reason_has_a_title_like_the_welcome_banner():
    """The printing screen and the welcome banner name the same problems."""
    for language in ('en', 'fr'):
        words = json.loads((Path(__file__).resolve().parents[1] / 'locales' / f'{language}.json').read_text(encoding='utf-8'))
        assert set(words['printing']['stuck_title']) == set(printing_module.STUCK_PROBLEMS)
        assert set(words['printing']['stuck_title']) == set(words['start']['print_stuck'])


def test_a_guest_who_waited_too_long_is_told_their_photo_will_still_come_out():
    """The job stays queued and the booth starts the queue again by itself."""
    app = FakeApp(status='pending', problem='paper')
    screen = Printing(app)
    screen._tick(None)

    screen._printer_wait_started_at = time.monotonic() - (app.PRINTER_WAIT_TIMEOUT + 1)
    screen._tick(None)

    screen_name, kwargs = app.transitions[0]
    assert screen_name == ScreenMgr.ERROR
    assert i18n.t('printing.stuck_title.paper') in kwargs['message']
    assert i18n.t('printing.stuck_message') in kwargs['message']


def test_a_refilled_printer_finishes_the_print(quick_exit):
    app = FakeApp(status='pending', problem='paper')
    screen = Printing(app)
    screen._tick(None)

    app.problem = None                  # refilled, and the queue started again
    app.devices.status = 'done'
    screen._tick(None)

    assert app.counted == 1
    assert screen._can_leave
    assert screen.title.text == i18n.t('printing.title')
    assert screen.animation.running


def test_a_first_sheet_out_frees_the_guest_whatever_stops_the_copies(quick_exit):
    """The copies behind it are the welcome screen's banner's to report."""
    app = FakeApp(status='done', problem='paper')
    screen = Printing(app, copies=3)
    screen._tick(None)

    assert screen._can_leave
    assert app.counted == 3


def test_waiting_for_paper_does_not_count_against_the_printing_ceiling():
    """An operator who gives the refill five minutes must get five minutes."""
    app = FakeApp(status='pending', problem='paper')
    screen = Printing(app)
    screen._tick(None)

    # Most of the ceiling went on waiting for someone to refill the printer.
    wait = TIMINGS.print_sheet_timeout - 1
    screen._print_started_at -= wait + 2
    screen._printer_wait_started_at = time.monotonic() - wait
    app.problem = None
    screen._tick(None)

    assert app.transitions == []
    assert screen.message.text == i18n.t('printing.printing')


def test_nothing_is_sent_while_the_photo_is_still_being_written():
    app = FakeApp(pending=True)
    screen = Printing(app)

    screen._tick(None)

    assert app.printed == []
    assert app.transitions == []


# --- long enough to be read ------------------------------------------------

def test_a_printer_that_answers_at_once_does_not_flash_past():
    """CUPS calls the job done well before the sheet is out of the printer."""
    app = FakeApp()
    screen = Printing(app)

    screen._tick(None)
    settle(0.05)

    assert app.printed == [(1, 0)]
    assert app.transitions == []


def test_a_guest_who_has_understood_can_skip_the_wait():
    app = FakeApp()
    screen = Printing(app)
    screen._tick(None)

    assert screen._can_leave
    screen._leave()

    assert app.transitions == [(ScreenMgr.START, {})]


def test_skipping_the_wait_does_not_send_the_next_guest_home_too():
    """_done() leaves a timer pending, and _leave() used to abandon it.

    on_exit only unschedules what _clock still points at, and _leave had just
    set it to None. The orphan fired seconds later, by which time the booth
    belonged to somebody else: it yanked them out of the format screen or the
    countdown and back to the welcome screen.
    """
    app = FakeApp()
    screen = Printing(app)

    screen._tick(None)          # printer is done, the delay before leaving starts
    screen._leave()             # the guest taps to skip it
    settle(0.05)                # ...and the delay runs out on the next guest

    assert app.transitions == [(ScreenMgr.START, {})]


# --- a printer that is simply slow -----------------------------------------

def test_a_print_longer_than_the_wait_timeout_is_not_a_failure():
    """PRINTER_WAIT_TIMEOUT is for a printer that went away, not for printing.

    A dye-sub takes about a minute a sheet, so three copies always ran past the
    45 second default. The guest was handed an error screen while the prints
    were coming out, and the quota was never charged for them.
    """
    app = FakeApp(status='pending')
    screen = Printing(app, copies=3)
    screen._tick(None)                                  # jobs are queued

    screen._started_at = time.monotonic() - 120         # two minutes in
    screen._tick(None)

    assert app.transitions == []
    assert screen._print_task_ids == [7, 8, 9]


def test_the_quota_is_charged_when_a_slow_print_finishes(quick_exit):
    app = FakeApp(status='pending')
    screen = Printing(app, copies=3)
    screen._tick(None)

    screen._started_at = time.monotonic() - 120
    app.devices.status = 'done'                         # the sheets are out
    screen._tick(None)

    assert app.counted == 3
    assert screen._can_leave


def test_a_job_the_printer_never_finishes_still_gives_up_eventually():
    """The ceiling above must not turn a stuck job into a screen with no exit."""
    app = FakeApp(status='pending')
    screen = Printing(app, copies=1)
    screen._tick(None)

    screen._print_started_at = time.monotonic() - (TIMINGS.print_sheet_timeout + 1)
    screen._tick(None)

    assert app.transitions[0][0] == ScreenMgr.ERROR


def test_sheets_an_earlier_guest_left_queued_extend_the_deadline():
    """The next guest's first sheet comes out behind the last guest's copies."""
    app = FakeApp(status='pending')
    screen = Printing(app, copies=1)
    screen._earlier_task_ids = [3, 4]                   # still in the queue
    screen._tick(None)
    assert screen._sheets_ahead == 2

    screen._print_started_at = time.monotonic() - (TIMINGS.print_sheet_timeout + 1)
    screen._tick(None)

    assert app.transitions == []


def test_earlier_sheets_already_out_do_not_extend_the_deadline():
    app = FakeApp(status='pending')
    app.devices.get_print_status = lambda task_id: 'done' if task_id < 7 else 'pending'
    screen = Printing(app, copies=1)
    screen._earlier_task_ids = [3, 4]
    screen._tick(None)

    assert screen._sheets_ahead == 0
    assert screen._earlier_task_ids == []
