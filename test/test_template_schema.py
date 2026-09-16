"""Templates are the booth's one structured outside input: validate them hard."""

import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.template_collage import DEFAULT_TEMPLATE
from libs.template_schema import (
    MAX_DESIGN_BYTES,
    MAX_EMBEDDED_IMAGE_BYTES,
    MAX_EMBEDDED_TOTAL_BYTES,
    MAX_PAGE_PIXELS,
    MAX_STACK_ENTRIES,
    TemplateValidationError,
    validate_template,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def minimal_template(**overrides):
    template = {
        'name': 'Strip',
        'page': {'width': 600, 'height': 1800},
        'photos': [{'x': 30, 'y': 30, 'width': 540, 'height': 520}],
    }
    template.update(overrides)
    return template


def data_uri(size):
    return 'data:image/png;base64,' + base64.b64encode(b'\0' * size).decode('ascii')


def test_a_minimal_template_is_accepted_and_normalised():
    validated = validate_template(minimal_template())

    assert validated['name'] == 'Strip'
    assert validated['description'] == ''
    assert validated['print_params'] == {}
    assert validated['background'] is None
    assert validated['duplicate_horizontal'] is False


def test_unknown_keys_are_dropped():
    validated = validate_template(minimal_template(surprise='<script>'))
    assert 'surprise' not in validated


@pytest.mark.parametrize('template', [
    None,
    'a string',
    {},
    minimal_template(name=''),
    minimal_template(name='x' * 200),
    minimal_template(page={'width': 0, 'height': 100}),
    minimal_template(page={'width': 100}),
    minimal_template(page={'width': 100, 'height': 'tall'}),
    minimal_template(photos=[]),
    minimal_template(photos='nope'),
    minimal_template(photos=[{'x': 0, 'y': 0, 'width': 10}]),
    minimal_template(margin_percent=90),
    minimal_template(print_params={'PageSize': 4}),
    minimal_template(print_params='w288h432'),
])
def test_malformed_templates_are_rejected(template):
    with pytest.raises(TemplateValidationError):
        validate_template(template)


def test_a_page_larger_than_the_pixel_ceiling_is_rejected():
    side = int(MAX_PAGE_PIXELS ** 0.5) + 1000
    with pytest.raises(TemplateValidationError, match='pixel limit'):
        validate_template(minimal_template(page={'width': side, 'height': side}))


def test_a_photo_slot_outside_the_page_is_rejected():
    with pytest.raises(TemplateValidationError, match='does not fit'):
        validate_template(minimal_template(
            page={'width': 600, 'height': 600},
            photos=[{'x': 500, 'y': 0, 'width': 200, 'height': 100}],
        ))


def test_booleans_are_not_accepted_as_coordinates():
    with pytest.raises(TemplateValidationError):
        validate_template(minimal_template(photos=[{'x': True, 'y': 0, 'width': 10, 'height': 10}]))


@pytest.mark.parametrize('layer', ['background', 'foreground'])
def test_a_layer_may_be_absent_or_embedded(layer):
    assert validate_template(minimal_template(**{layer: None}))[layer] is None
    assert validate_template(minimal_template(**{layer: 'None'}))[layer] is None
    assert validate_template(minimal_template(**{layer: 'frame.png'}))[layer] == 'frame.png'
    assert validate_template(minimal_template(**{layer: data_uri(16)}))[layer].startswith('data:image/png')


@pytest.mark.parametrize('value', [
    '../../etc/passwd',
    '/etc/passwd',
    'C:\\Windows\\win.ini',
    'frames/nested.png',
    'script.js',
    'data:text/html;base64,PHNjcmlwdD4=',
    'data:image/png;base64,not base64!!',
])
def test_a_layer_pointing_outside_the_templates_directory_is_rejected(value):
    with pytest.raises(TemplateValidationError):
        validate_template(minimal_template(background=value))


def test_an_oversized_embedded_image_is_rejected():
    with pytest.raises(TemplateValidationError, match='byte limit'):
        validate_template(minimal_template(foreground=data_uri(MAX_EMBEDDED_IMAGE_BYTES + 1)))


def test_the_built_in_fallback_template_validates():
    validate_template(DEFAULT_TEMPLATE)


@pytest.mark.parametrize('template_path', sorted((PROJECT_ROOT / 'templates').glob('*.json')))
def test_shipped_templates_validate(template_path):
    """The templates the booth ships with must survive the new rules."""
    validate_template(json.loads(template_path.read_text(encoding='utf-8')))


# --- designed templates: a stack of images, photos and texts ---------------

def stacked_template(stack, **overrides):
    return minimal_template(
        texts=[{'x': 30, 'y': 1600, 'width': 540, 'height': 100, 'text': '{event}'}],
        stack=stack,
        **overrides,
    )


def image_entry(**overrides):
    entry = {'type': 'image', 'src': 'assets/frame.png', 'x': 0, 'y': 0, 'width': 600, 'height': 1800}
    entry.update(overrides)
    return entry


def test_a_stack_is_normalised_with_full_opacity_by_default():
    validated = validate_template(stacked_template([
        image_entry(),
        {'type': 'photo', 'index': 0, 'opacity': 0.5},
        image_entry(x=100, y=100, width=200, height=200, extra='dropped'),
        {'type': 'text', 'index': 0},
    ]))

    assert validated['stack'] == [
        {'type': 'image', 'src': 'assets/frame.png', 'x': 0, 'y': 0, 'width': 600, 'height': 1800, 'opacity': 1},
        {'type': 'photo', 'index': 0, 'opacity': 0.5},
        {'type': 'image', 'src': 'assets/frame.png', 'x': 100, 'y': 100, 'width': 200, 'height': 200, 'opacity': 1},
        {'type': 'text', 'index': 0, 'opacity': 1},
    ]


def test_a_template_without_a_stack_keeps_none():
    assert validate_template(minimal_template())['stack'] is None


@pytest.mark.parametrize('stack', [
    'photo',
    [{'type': 'video'}],
    [{'type': 'photo', 'index': 0}],                                   # the text is never drawn
    [{'type': 'text', 'index': 0}],                                    # the photo is never drawn
    [{'type': 'photo', 'index': 0}, {'type': 'photo', 'index': 0}, {'type': 'text', 'index': 0}],
    [{'type': 'photo', 'index': 1}, {'type': 'text', 'index': 0}],
    [{'type': 'photo', 'index': 0, 'opacity': 1.5}, {'type': 'text', 'index': 0}],
    [{'type': 'photo', 'index': 0, 'opacity': True}, {'type': 'text', 'index': 0}],
    [image_entry(x=100), {'type': 'photo', 'index': 0}, {'type': 'text', 'index': 0}],
    [image_entry(src=None), {'type': 'photo', 'index': 0}, {'type': 'text', 'index': 0}],
    [image_entry(src='assets/../../secret.png'), {'type': 'photo', 'index': 0}, {'type': 'text', 'index': 0}],
    [image_entry(src='other/frame.png'), {'type': 'photo', 'index': 0}, {'type': 'text', 'index': 0}],
])
def test_a_malformed_stack_is_rejected(stack):
    with pytest.raises(TemplateValidationError):
        validate_template(stacked_template(stack))


def test_a_stack_and_a_foreground_cannot_both_describe_the_drawing():
    stack = [{'type': 'photo', 'index': 0}, {'type': 'text', 'index': 0}]
    with pytest.raises(TemplateValidationError, match='stack'):
        validate_template(stacked_template(stack, foreground='frame.png'))


def test_a_stack_too_deep_for_the_booth_is_rejected():
    stack = [image_entry() for _ in range(MAX_STACK_ENTRIES)]
    stack += [{'type': 'photo', 'index': 0}, {'type': 'text', 'index': 0}]
    with pytest.raises(TemplateValidationError, match='more than'):
        validate_template(stacked_template(stack))


def test_embedded_images_are_limited_together_not_only_one_by_one():
    half = MAX_EMBEDDED_TOTAL_BYTES // 2 + 1024
    stack = [image_entry(src=data_uri(half)), image_entry(src=data_uri(half)),
             {'type': 'photo', 'index': 0}, {'type': 'text', 'index': 0}]
    with pytest.raises(TemplateValidationError, match='add up'):
        validate_template(stacked_template(stack))


def test_the_editor_design_is_kept_as_plain_json():
    design = {'levels': [{'name': 'Décor', 'opacity': 0.8, 'elements': []}]}
    assert validate_template(minimal_template(design=design))['design'] == design


@pytest.mark.parametrize('design', ['levels', {'size': float('nan')}, {'blob': 'x' * (MAX_DESIGN_BYTES + 1)}])
def test_a_design_that_is_not_small_plain_json_is_rejected(design):
    with pytest.raises(TemplateValidationError):
        validate_template(minimal_template(design=design))
