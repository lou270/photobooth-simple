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


def template(dpi=300, **overrides):
    definition = {
        'name': 'Layered',
        'page': dict(PAGE),
        'photos': [{'x': 10, 'y': 10, 'width': 100, 'height': 100}],
    }
    definition.update(overrides)
    return TemplateCollage(template=definition, dpi=dpi)


def cached_layer(collage, layer):
    """The one size a layer has been cached at so far."""
    sizes = [image for (name, _size), image in collage._layer_cache.items() if name == layer]
    assert len(sizes) == 1
    return sizes[0]


@pytest.fixture
def photo(tmp_path):
    path = tmp_path / 'shot.jpg'
    cv2.imwrite(str(path), np.full((400, 600, 3), 60, dtype=np.uint8))
    return str(path)


def test_a_foreground_is_cached_at_page_size_not_source_size(photo):
    """The shipped frames are far larger than the page they are drawn on."""
    collage = template(foreground=png_data_uri(900, 600))

    collage.assemble([photo])

    assert cached_layer(collage, 'foreground').shape[:2] == (PAGE['height'], PAGE['width'])


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

    assert cached_layer(collage, 'background').shape[:2] == (PAGE['height'], PAGE['width'])


def test_pasting_photos_never_writes_into_the_background_cache(photo):
    """The cache is shared with every later collage of the session."""
    collage = template(background=png_data_uri(300, 200, channels=3))

    collage.assemble([photo])
    cached_after_first = cached_layer(collage, 'background').copy()
    collage.assemble([photo])

    assert np.array_equal(cached_layer(collage, 'background'), cached_after_first)


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


# --- what comes out of the printer -----------------------------------------

def test_a_plain_template_is_one_photo_per_sheet():
    assert template().get_copies_per_sheet() == 1


def test_a_strip_printed_twice_across_the_sheet_is_two_photos():
    """It is cut in two, so one sheet is two strips in the guest's hand."""
    assert template(duplicate_horizontal=True).get_copies_per_sheet() == 2


def test_a_template_duplicated_both_ways_is_four():
    assert template(duplicate_horizontal=True, duplicate_vertical=True).get_copies_per_sheet() == 4


@pytest.fixture
def photo(tmp_path):
    path = tmp_path / 'shot.jpg'
    cv2.imwrite(str(path), np.full((100, 100, 3), 90, dtype=np.uint8))
    return str(path)


def sheet_size(collage, photo):
    return collage.assemble([photo], for_print=True).shape[1::-1]


@pytest.mark.parametrize('page, sheet', [
    ({'width': 600, 'height': 1200}, (1800, 1200)),   # 2x4 upright, three across: 6x4
    ({'width': 1200, 'height': 600}, (1200, 1800)),   # 2x4 lying down, three high: 4x6
])
def test_a_2x4_cut_three_from_a_4x6_fills_the_sheet_whichever_way_it_is_drawn(page, sheet, photo):
    """The QW410's 2x4*3: anything but a 4x6 sheet would put the cuts through the photos."""
    collage = template(page=page, copies_per_sheet=3)

    assert collage.get_copies_per_sheet() == 3
    assert collage.uses_print_version()
    assert sheet_size(collage, photo) == sheet


def test_a_4x3_cut_two_from_a_4x6_is_laid_end_to_end(photo):
    assert sheet_size(template(page={'width': 1200, 'height': 900}, copies_per_sheet=2), photo) == (1200, 1800)


def test_the_collage_kept_for_the_gallery_is_one_print(tmp_path, photo):
    collage = template(page={'width': 600, 'height': 1200}, copies_per_sheet=3)
    output = tmp_path / 'collage.jpg'

    collage.assemble([photo], output_path=str(output), for_print=True)

    assert cv2.imread(str(output)).shape[1::-1] == (600, 1200)
    assert cv2.imread(str(tmp_path / 'collage_print.jpg')).shape[1::-1] == (1800, 1200)


QW410_DIV3 = {'label': '2x4*3', 'paper': [337.92, 440.64], 'area': [17.04, 0.0, 320.88, 440.64]}


@pytest.mark.parametrize('dpi', [300, 600])
def test_on_the_qw410_page_each_copy_starts_where_its_print_does(tmp_path, dpi):
    """The cutter goes through 620 and 1220: each copy must run from one cut to the next."""
    shot = tmp_path / 'shot.jpg'
    # A photo with distinct edges, so a copy shifted by a pixel shows.
    image = np.zeros((1200, 600, 3), dtype=np.uint8)
    image[:, :, 0] = np.linspace(0, 255, 600, dtype=np.uint8)
    image[:, :, 1] = np.linspace(0, 255, 1200, dtype=np.uint8)[:, None]
    cv2.imwrite(str(shot), image)
    collage = template(dpi=dpi, page={'width': 600, 'height': 1200},
                       photos=[{'x': 0, 'y': 0, 'width': 600, 'height': 1200}],
                       print_params={'PageSize': 'w288h432-div3'}, copies_per_sheet=3)
    collage.set_printer_page(QW410_DIV3, cut_offset=20)
    scale = dpi // 300

    one = cv2.rotate(collage.assemble([str(shot)]), cv2.ROTATE_90_CLOCKWISE)
    sheet = collage.assemble([str(shot)], for_print=True)

    assert sheet.shape[1::-1] == (1266 * scale, 1836 * scale)
    for start in (20, 620, 1220):
        copy = sheet[start * scale:(start + 600) * scale, 33 * scale:1233 * scale]
        assert np.array_equal(copy, one)
    # Printed past the paper: the design prolonged, not white.
    assert np.array_equal(sheet[0], sheet[20 * scale])
    assert np.array_equal(sheet[:, 0], sheet[:, 33 * scale])


def test_a_single_4x3_is_printed_at_its_own_size(tmp_path, photo):
    """Fitted to the driver's 936x1266 page, a 900x1200 design lost its edges."""
    collage = template(page={'width': 900, 'height': 1200}, photos=[{'x': 0, 'y': 0, 'width': 900, 'height': 1200}],
                       print_params={'PageSize': 'w288h216'})
    collage.set_printer_page({'label': '4x3', 'paper': [440.64, 337.92], 'area': [216.0, 17.04, 440.64, 320.88]},
                             cut_offset=20)
    output = tmp_path / 'collage.jpg'

    one = collage.assemble([photo])
    sheet = collage.assemble([photo], output_path=str(output), for_print=True)

    assert collage.uses_print_version()
    assert sheet.shape[1::-1] == (936, 1266)
    assert np.array_equal(sheet[33:1233, 20:920], one)
    assert (tmp_path / 'collage_print.jpg').exists()


def test_without_a_printer_the_sheet_is_fitted_as_before(photo):
    collage = template(page={'width': 600, 'height': 1200}, print_params={'PageSize': 'w288h432-div3'},
                       copies_per_sheet=3)
    collage.set_printer_page(None, cut_offset=20)

    assert sheet_size(collage, photo) == (1800, 1200)


def test_the_duplicate_flags_still_say_which_way(photo):
    """A strip drawn before copies_per_sheet existed keeps printing as it did."""
    strip = template(page={'width': 600, 'height': 1800}, duplicate_vertical=True)

    assert sheet_size(strip, photo) == (600, 3600)


# --- a designed template: images, photos and texts in any order ------------

def solid_png(width, height, bgr, alpha=255):
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[:, :] = (*bgr, alpha)
    encoded = cv2.imencode('.png', image)[1]
    return 'data:image/png;base64,' + base64.b64encode(encoded.tobytes()).decode('ascii')


def image(src, x=0, y=0, width=PAGE['width'], height=PAGE['height'], **overrides):
    return dict({'type': 'image', 'src': src, 'x': x, 'y': y, 'width': width, 'height': height}, **overrides)


PHOTO = {'type': 'photo', 'index': 0}
BLUE, RED = (255, 0, 0), (0, 0, 255)


@pytest.fixture
def grey_photo(tmp_path):
    """Uniform, so a pixel's value does not depend on how the photo is cropped."""
    path = tmp_path / 'grey.jpg'
    cv2.imwrite(str(path), np.full((400, 400, 3), 100, dtype=np.uint8))
    return str(path)


def test_an_image_under_the_photo_is_hidden_by_it_and_shows_around_it(grey_photo):
    collage = template(stack=[image(solid_png(300, 200, BLUE)), PHOTO])

    canvas = collage.assemble([grey_photo])

    assert canvas[50, 50].tolist() == [100, 100, 100]
    assert canvas[150, 250].tolist() == list(BLUE)


def test_an_image_over_the_photo_covers_part_of_it(grey_photo):
    collage = template(stack=[PHOTO, image(solid_png(40, 40, RED), x=10, y=10, width=40, height=40)])

    canvas = collage.assemble([grey_photo])

    assert canvas[20, 20].tolist() == list(RED)       # under the decoration
    assert canvas[80, 80].tolist() == [100, 100, 100]  # the rest of the photo


def test_an_image_can_sit_between_two_photos(tmp_path):
    first, second = tmp_path / 'a.jpg', tmp_path / 'b.jpg'
    cv2.imwrite(str(first), np.full((100, 100, 3), 40, dtype=np.uint8))
    cv2.imwrite(str(second), np.full((100, 100, 3), 200, dtype=np.uint8))
    collage = template(
        photos=[{'x': 0, 'y': 0, 'width': 100, 'height': 100}, {'x': 60, 'y': 0, 'width': 100, 'height': 100}],
        stack=[PHOTO, image(solid_png(300, 200, RED), x=50, y=0, width=20, height=200),
               {'type': 'photo', 'index': 1}],
    )

    canvas = collage.assemble([str(first), str(second)])

    assert canvas[50, 30].tolist() == [40, 40, 40]     # first photo, left of the stripe
    assert canvas[50, 55].tolist() == list(RED)        # the stripe over the first photo
    assert canvas[50, 65].tolist() == [200, 200, 200]  # the second photo over the stripe


def test_transparency_and_opacity_multiply(grey_photo):
    """A half-transparent image at half opacity lets three quarters through."""
    collage = template(stack=[PHOTO, image(solid_png(300, 200, (0, 0, 0), alpha=128), opacity=0.5)])

    canvas = collage.assemble([grey_photo])

    assert abs(canvas[50, 50, 0] - 75) <= 1


def test_a_photo_can_be_see_through(grey_photo):
    collage = template(stack=[image(solid_png(300, 200, (0, 0, 0))), dict(PHOTO, opacity=0.5)])

    canvas = collage.assemble([grey_photo])

    assert abs(canvas[50, 50, 0] - 50) <= 1


def test_a_text_can_be_drawn_under_a_decoration(grey_photo):
    box = {'x': 150, 'y': 50, 'width': 140, 'height': 100, 'text': 'MMMM', 'color': '#000000', 'bold': True}
    under = template(texts=[box], stack=[PHOTO, {'type': 'text', 'index': 0},
                                          image(solid_png(150, 150, RED), x=150, y=50, width=150, height=150)])
    over = template(texts=[box], stack=[PHOTO, image(solid_png(150, 150, RED), x=150, y=50, width=150, height=150),
                                         {'type': 'text', 'index': 0}])

    hidden = under.assemble([grey_photo])[50:150, 150:290]
    shown = over.assemble([grey_photo])[50:150, 150:290]

    assert (hidden == RED).all()
    assert not (shown == RED).all()


def test_a_see_through_text_is_lighter_than_a_solid_one(grey_photo):
    box = {'x': 150, 'y': 50, 'width': 140, 'height': 100, 'text': 'MMMM', 'color': '#000000', 'bold': True}
    solid = template(texts=[box], stack=[PHOTO, {'type': 'text', 'index': 0}])
    faint = template(texts=[box], stack=[PHOTO, {'type': 'text', 'index': 0, 'opacity': 0.3}])

    darkest_solid = solid.assemble([grey_photo])[50:150, 150:290].min()
    darkest_faint = faint.assemble([grey_photo])[50:150, 150:290].min()

    assert darkest_solid < 20
    assert darkest_faint > 150


def test_a_stack_image_is_cached_at_the_size_it_is_drawn(grey_photo):
    collage = template(stack=[PHOTO, image(png_data_uri(400, 400), x=10, y=20, width=80, height=60)])

    collage.assemble([grey_photo])
    collage.assemble([grey_photo])

    assert cached_layer(collage, 'stack1').shape[:2] == (60, 80)


def test_at_600_dpi_a_stack_image_is_drawn_at_twice_its_place(grey_photo):
    collage = template(dpi=600, stack=[PHOTO, image(solid_png(20, 20, RED), x=150, y=100, width=20, height=20)])

    canvas = collage.assemble([grey_photo])

    assert canvas.shape[:2] == (400, 600)
    assert canvas[300 - 1, 300 + 39].tolist() == [255, 255, 255]
    assert canvas[200 + 39, 300 + 39].tolist() == list(RED)
    assert canvas[200 + 41, 300 + 41].tolist() == [255, 255, 255]


def test_a_legacy_foreground_without_transparency_still_blends_at_half(grey_photo):
    opaque = cv2.imencode('.png', np.zeros((200, 300, 3), dtype=np.uint8))[1]
    uri = 'data:image/png;base64,' + base64.b64encode(opaque.tobytes()).decode('ascii')
    collage = template(foreground=uri)

    canvas = collage.assemble([grey_photo])

    assert abs(canvas[50, 50, 0] - 50) <= 1
