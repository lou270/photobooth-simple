"""Writing the session once the guest has settled on a look.

The review screen shows a preview built from the small captures, and only when
the guest prints or leaves does anything on disk change. These cover both ends
of that: the throwaway preview, and the files the guest goes home with.
"""

import os
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

os.environ.setdefault('KIVY_NO_ARGS', '1')
os.environ.setdefault('KIVY_GL_BACKEND', 'mock')

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.core import SessionStorage
from libs.file_utils import FileUtils
from libs.stats_store import StatsStore
from libs.template_collage import TemplateCollage
from photoboothapp import PhotoboothApp


TEMPLATE = {
    'name': 'One photo',
    'page': {'width': 300, 'height': 200},
    'photos': [{'x': 10, 'y': 10, 'width': 200, 'height': 150}],
}


def coloured_photo(height=150, width=200):
    """Saturated blue: greyscale is unmistakable, and JPEG cannot blur it away."""
    return np.full((height, width, 3), (200, 40, 40), dtype=np.uint8)


def make_app(tmp_path):
    app = PhotoboothApp.__new__(PhotoboothApp)
    # Whatever this machine has left is not what these are about.
    app.storage = SessionStorage(str(tmp_path / 'DCIM'), min_free_gb=0, max_used_percent=100)
    app.print_formats = [TemplateCollage(template=dict(TEMPLATE))]
    app.stats_store = StatsStore(str(tmp_path / 'DCIM' / 'save' / '.stats.json'))

    shot = app.get_shot(0)
    FileUtils.write_image(shot, coloured_photo())
    FileUtils.write_image(FileUtils.get_small_path(shot), coloured_photo(60, 80))
    app.print_formats[0].assemble([shot], output_path=app.get_collage(), for_print=True)
    return app


def is_grey(image):
    blue, green, red = cv2.split(image)
    return np.allclose(blue, green, atol=6) and np.allclose(green, red, atol=6)


@pytest.fixture
def app(tmp_path):
    return make_app(tmp_path)


# --- the preview -----------------------------------------------------------

def test_the_preview_shows_the_chosen_look(app):
    plain = app.build_preview_collage(0, 'color')
    grey = app.build_preview_collage(0, 'bw')

    assert not is_grey(plain)
    assert is_grey(grey[20:60, 20:60])


def test_the_preview_changes_nothing_on_disk(app):
    """Trying five filters must not rewrite five sets of captures."""
    before = Path(app.get_shot(0)).read_bytes()

    app.build_preview_collage(0, 'bw')

    assert Path(app.get_shot(0)).read_bytes() == before


def test_the_preview_survives_a_capture_with_no_small_copy(app):
    """A photo staged from a phone used to arrive without one."""
    os.remove(FileUtils.get_small_path(app.get_shot(0)))

    assert app.build_preview_collage(0, 'color') is not None


# --- what the guest goes home with -----------------------------------------

def test_the_captures_are_rewritten_with_the_chosen_look(app):
    app.finalize_session(0, 'bw')

    saved = Path(app.storage.last_saved_session_directory)
    assert is_grey(cv2.imread(str(saved / 'capture-0.jpg')))
    assert is_grey(cv2.imread(str(saved / 'collage.jpg'))[20:60, 20:60])


def test_the_session_is_filed_away(app):
    app.finalize_session(0, 'color')

    saved = Path(app.storage.last_saved_session_directory)
    # The collage's small copy comes along — the gallery grid serves it. The
    # captures' own small copies stay behind, and the captures themselves moved.
    assert sorted(p.name for p in saved.iterdir()) == [
        'capture-0.jpg', 'collage.jpg', 'collage_small.jpg',
    ]
    assert not Path(app.get_shot(0)).exists()


def test_nothing_is_rebuilt_when_the_guest_kept_the_colours(app):
    """The collage processing already made is the one to save."""
    before = Path(app.get_collage()).read_bytes()

    app.finalize_session(0, 'color')

    saved = Path(app.storage.last_saved_session_directory)
    assert (saved / 'collage.jpg').read_bytes() == before


# --- one session at a time in DCIM/tmp ------------------------------------------


def with_photo_tasks(app):
    app.pending_photo_tasks = []
    app._pending_photo_error = None
    app._pending_photo_lock = threading.Lock()
    return app


def wait_for_photo_tasks(app, seconds=5.0):
    deadline = time.monotonic() + seconds
    while app.has_pending_photo_tasks() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not app.has_pending_photo_tasks()


def test_a_photo_picked_from_the_phones_waits_for_the_last_session_to_be_saved(tmp_path):
    """Picking a phone's photo empties DCIM/tmp before copying it in, and did so
    while the previous guest's session was still on its way out of it."""
    app = with_photo_tasks(make_app(tmp_path))

    def slow_finalize():
        time.sleep(0.3)  # a filter applied to a DSLR's photos, on a Pi
        app.finalize_session(0, 'bw')

    app.start_photo_task(slow_finalize)
    app.start_photo_task(app.purge_tmp)  # what stage_remote_photo starts with
    wait_for_photo_tasks(app)

    saved = Path(app.storage.last_saved_session_directory)
    assert (saved / 'capture-0.jpg').is_file()
    assert (saved / 'collage.jpg').is_file()
    assert app.get_pending_photo_error() is None


def test_a_failure_of_the_last_session_is_not_reported_as_the_next_ones(tmp_path):
    app = with_photo_tasks(make_app(tmp_path))

    def failing_finalize():
        time.sleep(0.1)
        raise OSError('disk went away')

    app.start_photo_task(failing_finalize)
    app.start_photo_task(lambda: None)
    wait_for_photo_tasks(app)

    assert app.get_pending_photo_error() is None


def test_a_photo_task_still_reports_its_own_failure(tmp_path):
    app = with_photo_tasks(make_app(tmp_path))

    def failing_stage():
        raise FileNotFoundError('photo withdrawn by its phone')

    app.start_photo_task(failing_stage)
    wait_for_photo_tasks(app)

    assert 'photo withdrawn by its phone' in app.get_pending_photo_error()


class HandoverApp:
    """The parts of the app start_session reads, with the writing switched by hand."""

    def __init__(self, screen='start'):
        self.writing = True
        self.screen = screen
        self.events = []
        self._session_start_clock = None
        self.print_formats = [object()]
        self.devices = type('Devices', (), {'wake_preview': lambda devices: None})()

    def has_pending_photo_tasks(self):
        return self.writing

    def has_background_processes(self):
        return False

    def get_current_screen_name(self):
        return self.screen

    def purge_tmp(self):
        self.events.append('purge')

    def transition_to(self, screen, **kwargs):
        self.events.append(screen)

    start_session = PhotoboothApp.start_session
    _is_writing_a_session = PhotoboothApp._is_writing_a_session
    _start_session_once_written = PhotoboothApp._start_session_once_written
    _enter_session = PhotoboothApp._enter_session


def tick_for(seconds):
    from kivy.clock import Clock

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        Clock.tick()
        time.sleep(0.02)


def test_a_session_starts_once_the_last_one_is_written():
    """A guest through the countdown before the last session left DCIM/tmp
    overwrote its first photo with their own."""
    app = HandoverApp()

    app.start_session()
    tick_for(0.3)
    assert app.events == []

    app.writing = False
    tick_for(0.3)
    assert app.events == ['purge', 'countdown']


def test_touching_twice_while_waiting_starts_one_session():
    app = HandoverApp()

    app.start_session()
    app.start_session()
    app.writing = False
    tick_for(0.3)

    assert app.events == ['purge', 'countdown']


def test_a_guest_who_went_elsewhere_meanwhile_is_left_there():
    app = HandoverApp()

    app.start_session()
    app.screen = 'remote_gallery'
    tick_for(0.3)
    app.writing = False
    tick_for(0.3)

    assert app.events == []
    assert app._session_start_clock is None


def test_with_nothing_being_written_a_session_starts_at_once():
    app = HandoverApp()
    app.writing = False

    app.start_session()

    assert app.events == ['purge', 'countdown']
