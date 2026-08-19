"""The same booth on a screen turned upright.

A panel mounted on its side gives Kivy a window whose tall side is the height,
and every distance measured against that side came out almost twice too big:
inflated gaps, cards that no longer fitted, buttons that changed shape. The
convention is that distances come from the shortest side, and these hold the
screens to it.
"""

import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault('KIVY_NO_ARGS', '1')
os.environ.setdefault('KIVY_GL_BACKEND', 'mock')

sys.path.append(str(Path(__file__).resolve().parents[1]))

from libs import kivywidgets
from libs.kivywidgets import ICON_TEXT_MIN_RATIO, icon_text_button_size, short_side
from libs.screens import remote_gallery, select_format
from libs.screens.remote_gallery import RemoteGalleryScreen
from libs.screens.select_format import SelectFormatScreen

LANDSCAPE = (1920, 1080)
PORTRAIT = (1080, 1920)
SCREENS_DIR = Path(__file__).resolve().parents[1] / 'libs' / 'screens'


@pytest.fixture
def screen_size(monkeypatch):
    """Put every module that measures the window on the same fake panel."""
    def use(size):
        window = SimpleNamespace(size=size, width=size[0], height=size[1])
        for module in (kivywidgets, remote_gallery, select_format):
            monkeypatch.setattr(module, 'Window', window, raising=False)
        return window
    return use


# --- the convention --------------------------------------------------------

def test_a_distance_is_the_same_lying_flat_or_standing_up(screen_size):
    screen_size(LANDSCAPE)
    flat = short_side(0.02)
    screen_size(PORTRAIT)

    assert short_side(0.02) == flat


MEASURED_AGAINST_ONE_SIDE = re.compile(r'Window\.(height|width) \* 0\.0\d+')


def test_no_screen_measures_a_gap_against_one_side_of_the_window():
    """Paddings, spacings and radii go through short_side(), not Window.height.

    Kept as a rule rather than a review note because it reads as harmless every
    single time: on the landscape screen these were written for, the height is
    the short side, so the bug is invisible until a booth is stood upright.
    """
    offenders = []
    for path in sorted(SCREENS_DIR.glob('*.py')):
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if MEASURED_AGAINST_ONE_SIDE.search(line):
                offenders.append(f'{path.name}:{number}')

    assert offenders == []


# --- what the screens make of a tall window --------------------------------

def test_the_queue_of_waiting_photos_fits_either_way(screen_size):
    for size in (LANDSCAPE, PORTRAIT):
        window = screen_size(size)
        width, height, cols = RemoteGalleryScreen._card_size(None)

        assert cols * width <= window.width, size
        assert height <= window.height * 0.86, size


class Choosing:
    """Just enough of the format screen to ask it for a card size."""

    MIN_CARD_WIDTH = SelectFormatScreen.MIN_CARD_WIDTH
    MIN_CARD_HEIGHT = SelectFormatScreen.MIN_CARD_HEIGHT
    MAX_CARD_WIDTH = SelectFormatScreen.MAX_CARD_WIDTH
    MAX_CARD_HEIGHT = SelectFormatScreen.MAX_CARD_HEIGHT
    HOME_BAR_FRACTION = SelectFormatScreen.HOME_BAR_FRACTION
    _calculate_card_size = SelectFormatScreen._calculate_card_size

    def __init__(self, count):
        self.format_cards = [None] * count


def test_the_format_cards_fit_either_way(screen_size):
    for size in (LANDSCAPE, PORTRAIT):
        window = screen_size(size)
        width, height, cols = Choosing(3)._calculate_card_size()

        assert cols * width <= window.width, size
        assert height <= window.height * (1 - SelectFormatScreen.HOME_BAR_FRACTION), size


def test_a_tall_screen_shows_more_than_one_format_at_a_time(screen_size):
    """A single column left one card floating and the rest below the fold."""
    screen_size(PORTRAIT)

    _width, _height, cols = Choosing(3)._calculate_card_size()

    assert cols >= 2


# --- the print and share buttons -------------------------------------------

def test_a_button_the_screen_sized_itself_is_left_alone():
    """It used to multiply the parent by the None it was handed, and crash."""
    assert icon_text_button_size((1080, 1920), (None, None)) is None
    assert icon_text_button_size((1080, 1920), (0.3, None)) is None


def test_a_button_keeps_its_shape_on_a_tall_screen():
    for parent in (LANDSCAPE, PORTRAIT):
        width, height = icon_text_button_size(parent, (0.16, 0.09))

        assert width / height >= ICON_TEXT_MIN_RATIO - 0.01, parent
        assert width <= parent[0], parent
