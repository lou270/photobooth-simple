"""Writing the session once the guest has settled on a look.

The review screen shows a preview built from the small captures, and only when
the guest prints or leaves does anything on disk change. These cover both ends
of that: the throwaway preview, and the files the guest goes home with.
"""

import os
import sys
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
