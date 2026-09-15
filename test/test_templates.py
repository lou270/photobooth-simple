"""load_templates() must always yield a usable format, so the booth always starts."""

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.template_collage import DEFAULT_TEMPLATE, TemplateCollage, load_templates


def test_missing_templates_directory_falls_back_to_the_built_in(tmp_path):
    templates = load_templates(str(tmp_path / 'absent'))

    assert len(templates) == 1
    assert templates[0].get_name() == DEFAULT_TEMPLATE['name']


def test_empty_templates_directory_falls_back_to_the_built_in(tmp_path):
    empty_directory = tmp_path / 'empty'
    empty_directory.mkdir()

    templates = load_templates(str(empty_directory))

    assert len(templates) == 1


def test_corrupted_template_is_skipped_and_falls_back(tmp_path):
    directory = tmp_path / 'broken'
    directory.mkdir()
    (directory / 'oops.json').write_text('{ this is not json', encoding='utf-8')

    templates = load_templates(str(directory))

    assert len(templates) == 1
    assert templates[0].get_name() == DEFAULT_TEMPLATE['name']


def test_valid_template_is_loaded_and_the_fallback_stays_out(tmp_path):
    directory = tmp_path / 'templates'
    directory.mkdir()
    (directory / 'square.json').write_text(
        '{"name": "Square", "page": {"width": 600, "height": 600},'
        ' "photos": [{"x": 0, "y": 0, "width": 600, "height": 600}]}',
        encoding='utf-8',
    )

    templates = load_templates(str(directory))

    assert [template.get_name() for template in templates] == ['Square']


def test_built_in_template_assembles_a_full_page(tmp_path):
    template = TemplateCollage(template=DEFAULT_TEMPLATE)
    photo = tmp_path / 'shot.jpg'
    cv2.imwrite(str(photo), np.full((600, 900, 3), 128, dtype=np.uint8))

    canvas = template.assemble([str(photo)])

    assert template.get_photos_required() == 1
    assert canvas.shape == (1200, 1800, 3)


def test_at_600_dpi_the_whole_layout_is_doubled(tmp_path):
    """Same print, twice the pixels: the photo lands where the template put it."""
    template = TemplateCollage(template=DEFAULT_TEMPLATE, dpi=600)
    photo = tmp_path / 'shot.jpg'
    cv2.imwrite(str(photo), np.full((600, 900, 3), 0, dtype=np.uint8))

    canvas = template.assemble([str(photo)])

    assert canvas.shape == (2400, 3600, 3)
    photo_area = np.argwhere(canvas.max(axis=2) < 30)
    assert photo_area.min(axis=0).tolist() == [120, 180]
    assert photo_area.max(axis=0).tolist() == [120 + 2160 - 1, 180 + 3240 - 1]


def test_a_text_box_grows_with_the_resolution():
    definition = dict(DEFAULT_TEMPLATE, texts=[{
        'x': 100, 'y': 1100, 'width': 1600, 'height': 90,
        'text': 'LOU & MAX', 'color': '#ff0000', 'align': 'center', 'bold': False,
    }])
    template = TemplateCollage(template=definition, dpi=600, text_values=lambda: {})

    canvas = template.assemble([])

    red = np.argwhere((canvas[:, :, 2] > 200) & (canvas[:, :, 1] < 80))
    assert red[:, 0].min() >= 2200 and red[:, 0].max() < 2380
    assert red[:, 0].max() - red[:, 0].min() > 90


def test_previews_stay_at_the_template_s_own_resolution():
    """The review screen rebuilds its preview on every filter a guest tries."""
    template = TemplateCollage(template=DEFAULT_TEMPLATE, dpi=600)

    assert template.assemble([], full_resolution=False).shape == (1200, 1800, 3)


def test_a_strip_printed_twice_is_duplicated_at_600_dpi(tmp_path):
    definition = {
        'name': 'Strip', 'page': {'width': 600, 'height': 1800},
        'photos': [{'x': 30, 'y': 30, 'width': 540, 'height': 520}],
        'duplicate_horizontal': True,
    }
    template = TemplateCollage(template=definition, dpi=600)

    canvas = template.assemble([], output_path=str(tmp_path / 'collage.jpg'), for_print=True)

    assert canvas.shape == (3600, 2400, 3)
    assert cv2.imread(str(tmp_path / 'collage.jpg')).shape == (3600, 1200, 3)


def test_loaded_templates_carry_the_resolution(tmp_path):
    templates = load_templates(str(tmp_path / 'absent'), dpi=600)

    assert templates[0].assemble([]).shape == (2400, 3600, 3)


def test_built_in_template_exposes_its_print_parameters():
    template = TemplateCollage(template=DEFAULT_TEMPLATE)

    assert template.get_print_params()['PageSize'] == 'w288h432'
    assert template.get_aspect_ratio() == 1620 / 1080
