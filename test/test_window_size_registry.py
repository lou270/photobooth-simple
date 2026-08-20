"""Widgets that follow the window size must not pile up once they are gone.

A booth in kiosk mode never resizes, so nothing ever walked the list of things
waiting for a resize — and the screens that rebuild their widgets rather than
relabel them (the queue of photos from phones rebuilds every card each time it
changes) added to it every few seconds, all evening.
"""

import gc
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault('KIVY_NO_ARGS', '1')
os.environ.setdefault('KIVY_GL_BACKEND', 'mock')

sys.path.append(str(Path(__file__).resolve().parents[1]))
from kivy.core.window import Window
from kivy.uix.label import Label

from libs.kivywidgets import ResizeLabel, make_icon_button, window_size_registry
from libs.screens.theme import SMALL_FONT, wh_bind


@pytest.fixture
def registry():
    """A registry of its own, so the widgets the suite already built are out of it."""
    from libs.kivywidgets import _WindowSizeRegistry
    return _WindowSizeRegistry()


def test_a_discarded_widget_is_dropped_when_the_window_resizes(registry):
    label = Label()
    registry.add(label, lambda widget: None)
    assert len(registry) == 1

    del label
    gc.collect()
    registry.dispatch()

    assert len(registry) == 0


def test_the_list_is_pruned_even_when_the_window_never_resizes(registry):
    """The booth's own case: fullscreen kiosk, one size, for the whole evening."""
    for _ in range(registry.PRUNE_AFTER_ADDS * 4):
        widget = Label()
        registry.add(widget, lambda w: None)
        del widget
        gc.collect()

    assert len(registry) < registry.PRUNE_AFTER_ADDS


def test_a_live_widget_is_kept_and_still_updated(registry):
    label = Label()
    seen = []
    registry.add(label, lambda widget: seen.append(widget))

    for _ in range(registry.PRUNE_AFTER_ADDS * 2):
        throwaway = Label()
        registry.add(throwaway, lambda w: None)
        del throwaway
    gc.collect()
    registry.dispatch()

    assert seen == [label]


def test_the_registry_does_not_keep_a_widget_alive(registry):
    import weakref

    label = Label()
    reference = weakref.ref(label)
    registry.add(label, lambda widget: None)

    del label
    gc.collect()

    assert reference() is None


# --- the widgets that actually use it --------------------------------------

def test_rebuilding_the_queue_cards_does_not_grow_the_registry():
    """What RemoteGalleryScreen._apply_photos does, every five seconds."""
    gc.collect()
    window_size_registry.dispatch()
    before = len(window_size_registry)

    for _ in range(200):
        card_label = ResizeLabel(text='12:30', wh_fraction=0.02)
        card_button = make_icon_button('x', size=0.07, font_size_fraction=0.032,
                                       on_release=lambda *_: None)
        del card_label, card_button
    gc.collect()
    window_size_registry.dispatch()

    assert len(window_size_registry) == before


def test_wh_bind_goes_through_the_same_registry():
    gc.collect()
    window_size_registry.dispatch()
    before = len(window_size_registry)

    label = Label()
    wh_bind(label, 'font_size', SMALL_FONT)
    assert len(window_size_registry) == before + 1

    del label
    gc.collect()
    window_size_registry.dispatch()

    assert len(window_size_registry) == before


def test_a_bound_widget_still_follows_the_window():
    label = Label()
    wh_bind(label, 'font_size', SMALL_FONT)
    label.font_size = 1

    window_size_registry.dispatch()

    assert label.font_size == SMALL_FONT()


def test_a_resize_label_still_rescales_with_the_window():
    label = ResizeLabel(text='hello', wh_fraction=0.05)
    label.max_font_size = 1

    window_size_registry.dispatch()

    assert label.max_font_size == min(Window.size) * 0.05
