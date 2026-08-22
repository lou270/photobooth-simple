"""Screens a guest could get stuck on, and buttons that explained nothing.

Each of these covers a dead end found by walking the booth as a guest rather
than reading it as code: an overlay nothing closed, a failure that looked like
the booth restarting itself, a grey button with no reason beside it, and a
house icon that quietly ended the session. They are held as tests because all
four look like ordinary code at the call site — the missing piece is always
something that was never written, so nothing points at it.
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
from kivy.uix.widget import Widget

from libs import i18n
from libs.screens import review
from libs.screens import ReviewScreen, ScreenMgr, StartScreen
from libs.screens.names import ScreenNames
from libs.screens.popups import QRCodePopup
from libs.screens.theme import QR_POPUP_TIMEOUT_SECONDS
from photoboothapp import PhotoboothApp


@pytest.fixture(autouse=True)
def a_clock_that_starts_here():
    """Kivy's clock only moves when it is ticked, so everything spent in the
    previous test arrives as one jump on the first tick of this one — long
    enough to fire a delay that was only just armed."""
    Clock.tick()
    yield


def settle(seconds):
    time.sleep(seconds)
    Clock.tick()
    # What the deadline scheduled runs on the frame after it, the way closing
    # by hand does: the popup hands its dismissal to the next tick.
    Clock.tick()


def wait_for(predicate, seconds=3.0):
    """Poll until a worker thread has done its work, or give up."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class FakeOverlay:
    """Enough of a layout to be added to and removed from."""

    def add_widget(self, widget):
        widget.parent = self

    def remove_widget(self, widget):
        widget.parent = None


# --- the codes on the welcome screen -----------------------------------------


class Codes:
    """Just the self-closing part of the codes overlay."""

    _arm_auto_dismiss = QRCodePopup._arm_auto_dismiss
    _cancel_auto_dismiss = QRCodePopup._cancel_auto_dismiss
    _auto_dismiss_event = QRCodePopup._auto_dismiss_event
    _close = QRCodePopup._close

    def __init__(self, seconds):
        self._auto_dismiss_seconds = seconds
        self._auto_dismiss_clock = None
        self._close_scheduled = False
        self.parent = object()
        self.dismissed = 0
        self.on_dismiss = self._record_dismiss

    def _record_dismiss(self):
        self.dismissed += 1
        self.parent = None


def test_the_codes_close_themselves():
    """The welcome screen never leaves on its own, and this overlay eats every
    touch, so a guest who walked away from it left the booth answering nobody."""
    codes = Codes(0.05)

    codes._arm_auto_dismiss()
    settle(0.08)

    assert codes.dismissed == 1


def test_a_touch_gives_the_whole_delay_back():
    """Two scans and a phone joining a network outlast any fixed delay."""
    codes = Codes(0.06)
    codes._arm_auto_dismiss()

    settle(0.04)
    codes._arm_auto_dismiss()
    settle(0.04)

    assert codes.dismissed == 0
    settle(0.04)
    assert codes.dismissed == 1


def test_a_screen_that_times_out_on_its_own_keeps_its_codes_open():
    """Zero is the review screen's case: its own countdown already runs."""
    codes = Codes(0)

    codes._arm_auto_dismiss()
    settle(0.08)

    assert codes.dismissed == 0


def test_closing_by_hand_cancels_the_delay():
    codes = Codes(0.05)
    codes._arm_auto_dismiss()

    codes._close(None)
    Clock.tick()
    settle(0.08)

    assert codes.dismissed == 1


class Welcome:
    """Just the part of the welcome screen that puts the codes on screen."""

    remote_qr_event = StartScreen.remote_qr_event

    def __init__(self):
        self.app = SimpleNamespace(
            remote_url='http://192.168.4.1:8080/remote',
            get_qr_invitation=lambda url: ([(url, '')], 'title', url),
        )
        self.qr_popup = None
        self.added = []

    def add_widget(self, widget):
        self.added.append(widget)
        widget.parent = self

    def _dismiss_qr_popup(self):
        self.qr_popup = None


def test_the_welcome_screen_hands_its_codes_a_delay(monkeypatch):
    built = {}

    class Recorder(Widget):
        def __init__(self, steps, **kwargs):
            super().__init__()
            built.update(kwargs)

    monkeypatch.setattr('libs.screens.start.QRCodePopup', Recorder)
    screen = Welcome()

    screen.remote_qr_event(None)

    assert built['auto_dismiss_seconds'] == QR_POPUP_TIMEOUT_SECONDS
    assert QR_POPUP_TIMEOUT_SECONDS > 0


# --- a capture that failed ---------------------------------------------------


class Booth:
    """Just the recovery path, without the devices it rebuilds."""

    recover_devices_and_return_home = PhotoboothApp.recover_devices_and_return_home

    def __init__(self, reset_ok=True):
        self.reset_ok = reset_ok
        self.transitions = []
        self.abandoned = []
        self.maintenance = []

    def abandon_background_processes(self, kind, reason):
        self.abandoned.append((kind, reason))

    def reset_devices(self, reason='unknown'):
        return self.reset_ok

    def request_transition_to(self, screen, **kwargs):
        self.transitions.append((screen, kwargs))

    def enter_maintenance_mode(self, message, **kwargs):
        self.maintenance.append(message)


def test_a_failed_capture_says_so_instead_of_reappearing_at_the_start():
    """A guest who posed, saw the flash and then found the welcome screen had no
    way to tell whether the photo existed or whether to try again."""
    booth = Booth()

    booth.recover_devices_and_return_home(reason='capture_failure', message='no photo')

    assert wait_for(lambda: booth.transitions)
    screen, kwargs = booth.transitions[0]
    assert screen == ScreenMgr.ERROR
    assert kwargs['message'] == 'no photo'
    assert kwargs['show_continue'] is True
    # The camera is back by the time this is read, so there is nothing for an
    # operator to restart.
    assert kwargs['show_restart'] is False


def test_the_message_waits_for_the_camera_to_come_back():
    """Shown after the reset, so continue lands on a booth that works."""
    booth = Booth()

    booth.recover_devices_and_return_home(reason='capture_timeout', message='too slow')

    assert wait_for(lambda: booth.transitions)
    assert booth.abandoned == [('shot', 'capture_timeout')]


def test_a_recovery_with_nothing_to_say_still_goes_home():
    booth = Booth()

    booth.recover_devices_and_return_home(reason='whatever')

    assert wait_for(lambda: booth.transitions)
    assert booth.transitions == [(ScreenMgr.START, {})]


def test_a_camera_that_will_not_come_back_leaves_the_screen_alone():
    """reset_devices has already asked for a restart; nothing else to show."""
    booth = Booth(reset_ok=False)

    booth.recover_devices_and_return_home(reason='capture_failure', message='no photo')

    settle(0.1)
    assert booth.transitions == []


# --- why printing is not on offer --------------------------------------------


class Reviewing:
    """Just the line of text that explains the print button."""

    _sync_print_status = ReviewScreen._sync_print_status

    def __init__(self, printer):
        self.app = SimpleNamespace(PRINTER=printer)
        self.lbl_print_status = SimpleNamespace(text='')
        self.print_status = SimpleNamespace(parent=None)
        self.overlay_layout = FakeOverlay()


def test_a_spent_quota_is_explained_rather_than_greyed_out():
    """A disabled button with nothing beside it reads as a broken booth."""
    screen = Reviewing('DS620')

    screen._sync_print_status(printer_available=True, print_available=False)

    assert screen.lbl_print_status.text == i18n.t('review.print_limit_reached')
    assert screen.print_status.parent is not None


def test_a_printer_that_went_away_says_so():
    screen = Reviewing('DS620')

    screen._sync_print_status(printer_available=False, print_available=False)

    assert screen.lbl_print_status.text == i18n.t('review.printer_unavailable')
    assert screen.print_status.parent is not None


def test_a_booth_with_no_printer_does_not_advertise_one():
    """Announcing an absent feature on every session is noise, not help."""
    screen = Reviewing(None)

    screen._sync_print_status(printer_available=False, print_available=False)

    assert screen.lbl_print_status.text == ''
    assert screen.print_status.parent is None


def test_a_working_printer_needs_no_explanation():
    screen = Reviewing('DS620')
    screen._sync_print_status(printer_available=True, print_available=False)

    screen._sync_print_status(printer_available=True, print_available=True)

    assert screen.lbl_print_status.text == ''
    assert screen.print_status.parent is None


# --- leaving the review screen -----------------------------------------------


class FakeConfirmPopup(Widget):
    """A real widget, because the screen adds it to a real layout."""

    def __init__(self, title, message, on_confirm, on_dismiss=None, **kwargs):
        super().__init__()
        self.title = title
        self.on_confirm = on_confirm
        self.on_dismiss = on_dismiss

    def answer(self, confirmed):
        """What ConfirmPopup does: both callbacks, confirm first."""
        if confirmed:
            self.on_confirm()
        if self.on_dismiss:
            self.on_dismiss()


class ReviewApp:
    FILTERS_ENABLED = False
    SHARE = False
    BLUR_COLLAGE = False
    MAX_COPIES = 3
    PRINTER = 'DS620'

    def __init__(self):
        self.transitions = []
        self.screen_name = ScreenNames.REVIEW

    def transition_to(self, screen, **kwargs):
        self.transitions.append(screen)
        self.screen_name = screen

    def get_current_screen_name(self):
        return self.screen_name

    def get_copies_per_sheet(self, format_idx=0):
        return 1


@pytest.fixture
def leaving(monkeypatch):
    monkeypatch.setattr(review, 'ConfirmPopup', FakeConfirmPopup)
    app = ReviewApp()
    screen = ReviewScreen(app, name='review-under-test')
    return app, screen


def test_leaving_a_printable_photo_asks_first(leaving):
    """The house is the button a guest presses meaning "back", and it ends the
    session for good. Every other irreversible action in the booth asks."""
    app, screen = leaving
    screen._print_state = (True, True, None)

    screen.home_event(None)

    assert isinstance(screen.confirm_popup, FakeConfirmPopup)
    assert app.transitions == []


def test_answering_yes_leaves(leaving):
    app, screen = leaving
    screen._print_state = (True, True, None)
    screen.home_event(None)

    screen.confirm_popup.answer(True)

    assert app.transitions == [ScreenNames.START]


def test_answering_no_keeps_the_photo_on_screen(leaving):
    app, screen = leaving
    screen._print_state = (True, True, None)
    screen.home_event(None)

    screen.confirm_popup.answer(False)

    assert app.transitions == []
    assert screen.confirm_popup is None


def test_a_booth_that_could_not_print_anyway_does_not_ask(leaving):
    """Nothing was lost by leaving, so the question would only be in the way."""
    app, screen = leaving
    screen._print_state = (False, False, None)

    screen.home_event(None)

    assert screen.confirm_popup is None
    assert app.transitions == [ScreenNames.START]


def test_the_walk_away_timeout_does_not_ask(leaving):
    """Nobody is left to answer, and a question nobody answers is a booth stuck
    on the previous guest's photo."""
    app, screen = leaving
    screen._print_state = (True, True, None)

    screen._home_timeout_event(0)

    assert screen.confirm_popup is None
    assert app.transitions == [ScreenNames.START]


def test_confirming_leaves_no_timer_running_behind_it(leaving):
    """Both callbacks fire after the screen has gone; restarting the countdown
    there would drag whatever came next back to the welcome screen."""
    app, screen = leaving
    screen._print_state = (True, True, None)
    screen.home_event(None)

    screen.confirm_popup.answer(True)

    assert screen._home_timeout_clock is None


def test_a_second_press_does_not_stack_two_questions(leaving):
    app, screen = leaving
    screen._print_state = (True, True, None)
    screen.home_event(None)
    first = screen.confirm_popup

    screen.home_event(None)

    assert screen.confirm_popup is first
