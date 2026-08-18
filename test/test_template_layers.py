"""Layer caching: the collage runs while a guest waits for it."""

import base64
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.template_collage import TemplateCollage

PAGE = {'width': 300, 'height': 200}


def png_data_uri(width, height, channels=4):
    image = np.full((height, width, channels), 128, dtype=np.uint8)
    encoded = cv2.imencode('.png', image)[1]
    return 'data:image/png;base64,' + base64.b64encode(encoded.tobytes()).decode('ascii')


def template(**overrides):
    definition = {
        'name': 'Layered',
        'page': dict(PAGE),
        'photos': [{'x': 10, 'y': 10, 'width': 100, 'height': 100}],
    }
    definition.update(overrides)
    return TemplateCollage(template=definition)


@pytest.fixture
def photo(tmp_path):
    path = tmp_path / 'shot.jpg'
    cv2.imwrite(str(path), np.full((400, 600, 3), 60, dtype=np.uint8))
    return str(path)


def test_a_foreground_is_cached_at_page_size_not_source_size(photo):
    """The shipped frames are far larger than the page they are drawn on."""
    collage = template(foreground=png_data_uri(900, 600))

    collage.assemble([photo])

    assert collage._foreground_cache.shape[:2] == (PAGE['height'], PAGE['width'])


def test_the_layer_is_decoded_and_resized_only_once(photo, monkeypatch):
    collage = template(foreground=png_data_uri(900, 600))
    decodes = []
    original = collage._decode_image
    monkeypatch.setattr(collage, '_decode_image',
                        lambda *args, **kwargs: decodes.append(1) or original(*args, **kwargs))

    collage.assemble([photo])
    collage.assemble([photo])
    collage.assemble([photo])

    assert len(decodes) == 1


def test_a_background_is_cached_at_page_size(photo):
    collage = template(background=png_data_uri(900, 600, channels=3))

    collage.assemble([photo])

    assert collage._background_cache.shape[:2] == (PAGE['height'], PAGE['width'])


def test_pasting_photos_never_writes_into_the_background_cache(photo):
    """The cache is shared with every later collage of the session."""
    collage = template(background=png_data_uri(300, 200, channels=3))

    collage.assemble([photo])
    cached_after_first = collage._background_cache.copy()
    collage.assemble([photo])

    assert np.array_equal(collage._background_cache, cached_after_first)


def test_successive_collages_are_identical(photo):
    collage = template(foreground=png_data_uri(900, 600), background=png_data_uri(900, 600, channels=3))

    first = collage.assemble([photo])
    second = collage.assemble([photo])

    assert np.array_equal(first, second)


def test_an_unreadable_layer_is_skipped_instead_of_raising(photo):
    """cv2.imread returns None; the old code called .copy() on it."""
    collage = template(foreground='missing-frame.png')

    canvas = collage.assemble([photo])

    assert canvas.shape == (PAGE['height'], PAGE['width'], 3)


def test_a_corrupted_embedded_layer_is_skipped_instead_of_raising(photo):
    collage = template(foreground='data:image/png;base64,' + base64.b64encode(b'not a png').decode())

    canvas = collage.assemble([photo])

    assert canvas.shape == (PAGE['height'], PAGE['width'], 3)


# --- a look chosen on the review screen ------------------------------------

def test_a_photo_filter_is_applied_to_the_photos(photo):
    collage = template()

    plain = collage.assemble([photo])
    grey = collage.assemble([photo], photo_filter=lambda image: image * 0)

    assert plain[50, 50].tolist() != grey[50, 50].tolist()
    assert grey[50, 50].tolist() == [0, 0, 0]


def test_a_photo_filter_leaves_the_template_alone(photo):
    """A frame that turned grey with the faces is a change nobody asked for."""
    collage = template(background=png_data_uri(PAGE['width'], PAGE['height'], channels=3))

    plain = collage.assemble([photo])
    filtered = collage.assemble([photo], photo_filter=lambda image: image * 0)

    # A corner the photo does not reach: background only.
    assert filtered[190, 290].tolist() == plain[190, 290].tolist()
