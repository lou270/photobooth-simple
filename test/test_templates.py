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


def test_built_in_template_exposes_its_print_parameters():
    template = TemplateCollage(template=DEFAULT_TEMPLATE)

    assert template.get_print_params()['PageSize'] == 'w288h432'
    assert template.get_aspect_ratio() == 1620 / 1080
