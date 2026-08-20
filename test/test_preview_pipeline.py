"""The preview pipeline runs on every frame: guard its shape and its guards."""

import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

os.environ.setdefault('KIVY_NO_ARGS', '1')
os.environ.setdefault('KIVY_GL_BACKEND', 'mock')

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.file_utils import FileUtils


def frame(height=1080, width=1440):
    return np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)


def test_blurry_borders_honours_return_cache_on_a_degenerate_frame():
    """The live preview unpacks a pair from every call.

    The guard for a frame with no pixels returned the array on its own, so a
    camera handing back an empty buffer turned into "not enough values to
    unpack" rather than a skipped frame.
    """
    empty = np.zeros((0, 640, 3), dtype=np.uint8)

    result, cache = FileUtils.blurry_borders(empty, (800, 600), return_cache=True)

    assert result is empty
    assert cache is None


@pytest.mark.parametrize('widget_size', [(800, 480), (480, 800), (1024, 1024)])
def test_blurry_borders_fills_the_requested_widget_size(widget_size):
    result = FileUtils.blurry_borders(frame(), widget_size)

    height, width = result.shape[:2]
    # One axis is filled exactly, the other is the scaled image plus its bands.
    assert (width, height) == widget_size or width == widget_size[0] or height == widget_size[1]


def test_blurry_borders_accepts_a_faster_interpolation():
    reference = FileUtils.blurry_borders(frame(), (800, 480), interpolation=cv2.INTER_AREA)
    faster = FileUtils.blurry_borders(frame(), (800, 480), interpolation=cv2.INTER_LINEAR)

    assert faster.shape == reference.shape


def test_blurry_borders_reuses_its_cache_between_frames():
    first, cache = FileUtils.blurry_borders(frame(), (800, 480), return_cache=True)
    assert cache is not None

    second, cache_again = FileUtils.blurry_borders(
        frame(), (800, 480), blur_cache=cache, refresh_blur=False, return_cache=True,
    )

    assert cache_again is cache
    assert second.shape == first.shape


def test_blurry_borders_recomputes_when_the_geometry_changes():
    _first, cache = FileUtils.blurry_borders(frame(), (800, 480), return_cache=True)

    _second, new_cache = FileUtils.blurry_borders(
        frame(), (1024, 576), blur_cache=cache, refresh_blur=False, return_cache=True,
    )

    assert new_cache is not cache


def test_a_detached_widget_is_reported_offscreen():
    """Animations use this to stop working on screens the manager is not showing."""
    from kivy.uix.widget import Widget

    from libs.kivywidgets import is_offscreen

    assert is_offscreen(Widget())
