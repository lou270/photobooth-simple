"""Photo filters, now that they live outside the screen that shows them."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.imaging import DEFAULT_FILTER, FILTERS, apply_filter, filter_keys


def photo(height=48, width=64):
    """A gradient with saturated corners, so every channel path is exercised."""
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :, 0] = np.linspace(0, 255, width, dtype=np.uint8)
    image[:, :, 1] = np.linspace(255, 0, width, dtype=np.uint8)
    image[:, :, 2] = np.linspace(0, 255, height, dtype=np.uint8)[:, None]
    return image


@pytest.mark.parametrize('key', filter_keys())
def test_every_filter_returns_a_usable_image(key):
    source = photo()

    result = apply_filter(source, key)

    assert result.shape == source.shape
    assert result.dtype == np.uint8


@pytest.mark.parametrize('key', filter_keys())
def test_no_filter_modifies_the_photo_it_was_given(key):
    source = photo()
    untouched = source.copy()

    apply_filter(source, key)

    assert np.array_equal(source, untouched)


def test_the_default_filter_leaves_the_photo_alone():
    source = photo()
    assert apply_filter(source, DEFAULT_FILTER) is source


def test_the_default_filter_is_one_of_the_offered_filters():
    assert DEFAULT_FILTER in filter_keys()


def test_an_unknown_filter_returns_the_photo_unchanged():
    source = photo()
    assert apply_filter(source, 'sparkles') is source


@pytest.mark.parametrize('key', [key for key in filter_keys() if key != DEFAULT_FILTER])
def test_every_other_filter_actually_changes_the_photo(key):
    source = photo()
    assert not np.array_equal(apply_filter(source, key), source)


def test_black_and_white_leaves_no_colour():
    result = apply_filter(photo(), 'bw')

    assert np.array_equal(result[:, :, 0], result[:, :, 1])
    assert np.array_equal(result[:, :, 1], result[:, :, 2])


def test_the_catalogue_is_complete_and_unique():
    keys = filter_keys()
    assert len(keys) == len(set(keys))
    for definition in FILTERS:
        assert definition['name']
        assert callable(definition['apply'])


@pytest.mark.parametrize('key', filter_keys())
def test_filters_survive_a_single_pixel_photo(key):
    """Thumbnails get small when the window does."""
    assert apply_filter(photo(height=1, width=1), key).shape == (1, 1, 3)
