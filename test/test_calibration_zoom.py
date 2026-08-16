"""A calibration triple must zoom exactly one side of a hybrid rig.

tools/calibrate_zoom.py stores a single factor: above 1 the preview is zoomed,
below 1 the capture is zoomed by its inverse. Applying the raw factor to the
capture used to raise, so calibrated rigs either lost their framing or failed
on every shot.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.file_utils import FileUtils
from libs.hardware import Camera


def gradient_image(height=120, width=200):
    column = np.linspace(0, 255, width, dtype=np.uint8)
    return np.repeat(np.tile(column, (height, 1))[:, :, None], 3, axis=2)


@pytest.mark.parametrize('zoom', [None, (1.0, 0, 0), (0.7, 0, 0)])
def test_preview_is_left_alone_unless_the_factor_is_above_one(zoom):
    image = gradient_image()
    assert Camera._apply_preview_zoom(image, zoom) is image


@pytest.mark.parametrize('zoom', [None, (1.0, 0, 0), (1.4, 0, 0)])
def test_capture_is_left_alone_unless_the_factor_is_below_one(zoom):
    image = gradient_image()
    assert Camera._apply_capture_zoom(image, zoom) is image


def test_preview_zoom_keeps_the_frame_size_and_changes_the_framing():
    image = gradient_image()

    zoomed = Camera._apply_preview_zoom(image, (1.5, 0, 0))

    assert zoomed.shape == image.shape
    assert not np.array_equal(zoomed, image)


def test_capture_zoom_below_one_applies_the_inverse_factor():
    image = gradient_image()

    zoomed = Camera._apply_capture_zoom(image, (0.5, 0, 0))

    assert zoomed.shape == image.shape
    # 0.5 on the capture side must mean the same crop as 2.0 on the preview side.
    assert np.array_equal(zoomed, Camera._apply_preview_zoom(image, (2.0, 0, 0)))


def test_capture_zoom_below_one_no_longer_raises():
    """Regression: the raw factor used to reach FileUtils.zoom and blow up."""
    Camera._apply_capture_zoom(gradient_image(), (0.667, 0, 0))


def test_offsets_shift_the_crop_window():
    image = gradient_image()

    centered = Camera._apply_preview_zoom(image, (2.0, 0, 0))
    shifted = Camera._apply_preview_zoom(image, (2.0, 40, 0))

    assert centered.shape == shifted.shape
    assert not np.array_equal(centered, shifted)


def test_zoom_primitive_rejects_a_factor_below_one():
    with pytest.raises(ValueError):
        FileUtils.zoom(gradient_image(), (0.5, 0, 0))
