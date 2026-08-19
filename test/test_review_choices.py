"""What a guest can still decide once the collage is on screen.

The review screen is the last stop: the look applies to the whole collage, the
copies to the print job, and the session is only written once those two are
settled. These exercise that arithmetic without building a screen, which needs
a window this suite does not have.
"""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault('KIVY_NO_ARGS', '1')
os.environ.setdefault('KIVY_GL_BACKEND', 'mock')

sys.path.append(str(Path(__file__).resolve().parents[1]))

from libs.imaging import DEFAULT_FILTER
from libs.screens import ReviewScreen


class FakeApp:
    MAX_COPIES = 3
    FILTERS_ENABLED = True

    def __init__(self):
        self.finalized = []

    def start_photo_task(self, target, *args):
        self.finalized.append((target, args))

    def finalize_session(self, format_idx, filter_key):
        pass


class Choosing:
    """Just enough of a review screen to run the choices it offers."""

    _copies_limit = ReviewScreen._copies_limit
    copies_event = ReviewScreen.copies_event
    _finalize_once = ReviewScreen._finalize_once
    on_filter_selected = ReviewScreen.on_filter_selected

    def __init__(self, app, remaining=None):
        self.app = app
        self._copies = 1
        self._print_remaining = remaining
        self._current_format = 0
        self._selected_filter = DEFAULT_FILTER
        self._finalized = False
        self.filters = None
        self.lbl_copies = None
        self.rebuilds = 0
        self.timeouts_reset = 0

    def _sync_copies(self, printing_possible=True):
        pass

    def _reset_timeout(self):
        self.timeouts_reset += 1

    def _rebuild_preview(self):
        self.rebuilds += 1


@pytest.fixture
def app():
    return FakeApp()


# --- copies ----------------------------------------------------------------

def test_the_copies_go_round_rather_than_stopping(app):
    """Tapping past the last one comes back to one, so nobody is stranded."""
    screen = Choosing(app)

    seen = []
    for _ in range(5):
        screen.copies_event(None)
        seen.append(screen._copies)

    assert seen == [2, 3, 1, 2, 3]


def test_the_quota_left_wins_over_the_operator_limit(app):
    """Two prints left is two copies, whatever MAX_COPIES says."""
    screen = Choosing(app, remaining=2)

    seen = []
    for _ in range(3):
        screen.copies_event(None)
        seen.append(screen._copies)

    assert seen == [2, 1, 2]


def test_an_unlimited_quota_leaves_the_operator_limit_alone(app):
    screen = Choosing(app, remaining=None)

    assert screen._copies_limit() == FakeApp.MAX_COPIES


def test_a_single_possible_copy_is_not_a_question(app):
    """A booth with one print left has nothing to cycle through."""
    screen = Choosing(app, remaining=1)

    screen.copies_event(None)

    assert screen._copies == 1


# --- the look, and when it stops being a question --------------------------

def test_choosing_a_filter_redraws_the_collage(app):
    screen = Choosing(app)

    screen.on_filter_selected('bw')

    assert screen._selected_filter == 'bw'
    assert screen.rebuilds == 1


def test_the_session_is_written_once(app):
    screen = Choosing(app)

    screen._finalize_once()
    screen._finalize_once()

    assert len(app.finalized) == 1


def test_the_session_is_written_with_the_chosen_look(app):
    screen = Choosing(app)
    screen.on_filter_selected('sepia')

    screen._finalize_once()

    target, args = app.finalized[0]
    assert target == app.finalize_session
    assert args == (0, 'sepia')


def test_the_look_stops_changing_once_the_session_is_written(app):
    """The print is out and the files are saved: a later choice would be a lie."""
    screen = Choosing(app)
    screen._finalize_once()

    screen.on_filter_selected('sepia')

    assert screen._selected_filter == DEFAULT_FILTER
    assert screen.rebuilds == 0
