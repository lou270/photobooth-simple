"""The admin form over config.ini: what it shows, and what it writes back."""

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.webserver import config_form
from libs.webserver.config_form import (
    CONFIG_FORM_SECTIONS,
    apply_updates,
    build_select_choices,
    coerce_value,
    collect_updates,
    field_name,
    load_parser,
    normalize_value,
    render_sections,
)

SAMPLE = textwrap.dedent("""\
    [Global]
    # If set to True, the window will be fullscreen
    FULLSCREEN = False
    ADMIN_PASSWORD = un mot de passe convenable

    [Capture]
    COUNTDOWN = 5
    CALIBRATION = None
    """)


SHIPPED_CONFIG = (Path(__file__).resolve().parents[1] / 'config.ini.example').read_text(encoding='utf-8')


def full_form(parser, **overrides):
    """A submission with every field present, the way a browser sends one.

    A partial form is not a realistic input: the page renders every field, so
    every required one comes back.
    """
    form = {}
    for section_spec in CONFIG_FORM_SECTIONS:
        for field_spec in section_spec['fields']:
            name = field_name(field_spec['section'], field_spec['option'])
            value = parser.get(field_spec['section'], field_spec['option'], fallback='')
            if field_spec['control'] == 'checkbox':
                if value.strip().lower() in ('1', 'true', 'yes', 'on'):
                    form[name] = 'on'  # unchecked boxes are simply absent
                continue
            form[name] = normalize_value(field_spec, value)
    form.update(overrides)
    return form


def spec(section, option):
    for section_spec in CONFIG_FORM_SECTIONS:
        for field_spec in section_spec['fields']:
            if (field_spec['section'], field_spec['option']) == (section, option):
                return field_spec
    raise AssertionError(f'no field for {section}.{option}')


# --- rewriting the file ----------------------------------------------------

def test_an_updated_value_keeps_its_comment_and_its_place():
    result = apply_updates(SAMPLE, {('Capture', 'COUNTDOWN'): '8'})

    assert '# If set to True, the window will be fullscreen' in result
    assert 'COUNTDOWN = 8' in result
    assert result.index('[Global]') < result.index('[Capture]')


def test_untouched_values_are_left_byte_for_byte():
    result = apply_updates(SAMPLE, {('Capture', 'COUNTDOWN'): '5'})
    assert result == SAMPLE


def test_a_missing_option_is_added_to_its_section():
    result = apply_updates(SAMPLE, {('Capture', 'CAMERA'): 'fake'})

    parser = load_parser(result)
    assert parser.get('Capture', 'CAMERA') == 'fake'
    assert parser.get('Capture', 'COUNTDOWN') == '5'


def test_a_missing_section_is_appended():
    result = apply_updates(SAMPLE, {('Web', 'WEB_PORT'): '5001'})

    parser = load_parser(result)
    assert parser.get('Web', 'WEB_PORT') == '5001'


def test_windows_line_endings_survive():
    result = apply_updates(SAMPLE.replace('\n', '\r\n'), {('Capture', 'COUNTDOWN'): '9'})

    assert 'COUNTDOWN = 9\r\n' in result
    assert result.count('\n') == result.count('\r\n')  # no line left with a bare LF


def test_option_case_is_preserved():
    parser = load_parser(apply_updates(SAMPLE, {('Global', 'FULLSCREEN'): 'True'}))
    assert 'FULLSCREEN' in parser['Global']


# --- coercing one field ----------------------------------------------------

def test_a_checkbox_becomes_a_boolean_string():
    assert coerce_value(spec('Global', 'FULLSCREEN'), True, 'False') == 'True'
    assert coerce_value(spec('Global', 'FULLSCREEN'), False, 'True') == 'False'


def test_a_blank_admin_password_keeps_the_current_one():
    assert coerce_value(spec('Global', 'ADMIN_PASSWORD'), '', 'kept') == 'kept'
    assert coerce_value(spec('Global', 'ADMIN_PASSWORD'), 'new one', 'kept') == 'new one'


def test_a_required_number_refuses_to_be_empty():
    with pytest.raises(ValueError, match='required'):
        coerce_value(spec('Capture', 'COUNTDOWN'), '', '5')


@pytest.mark.parametrize('value', ['-1', '0'])
def test_a_number_below_its_floor_is_refused(value):
    with pytest.raises(ValueError, match='at least'):
        coerce_value(spec('Web', 'WEB_PORT'), value, '5000')


def test_a_number_above_its_ceiling_is_refused():
    with pytest.raises(ValueError, match='at most'):
        coerce_value(spec('Storage', 'DISK_MAX_USED_PERCENT'), '150', '90')


def test_an_optional_number_left_empty_becomes_none():
    assert coerce_value(spec('Print', 'MAX_PRINTS'), '', 'None') == 'None'
    assert coerce_value(spec('Print', 'MAX_PRINTS'), '120', 'None') == '120'


def test_an_emptied_printer_name_becomes_none():
    assert coerce_value(spec('Print', 'PRINTER'), '', 'DS620') == 'None'


def test_an_emptied_calibration_becomes_none():
    assert coerce_value(spec('Capture', 'CALIBRATION'), '  ', '(1.4, 0, 0)') == 'None'


# --- what the form shows ---------------------------------------------------

def test_the_admin_password_is_never_sent_back_to_the_browser():
    assert normalize_value(spec('Global', 'ADMIN_PASSWORD'), 'un secret') == ''


def test_none_reads_as_empty_in_an_optional_field():
    assert normalize_value(spec('Print', 'MAX_PRINTS'), 'None') == ''
    assert normalize_value(spec('Print', 'PRINTER'), 'None') == ''


def test_a_value_set_by_hand_stays_selectable():
    """A shutter speed the form does not offer must not vanish on save."""
    choices = build_select_choices(spec('DSLR_Capture', 'SHUTTERSPEED'), '1/2000')

    assert ('1/2000', 'Current: 1/2000') in choices


def test_a_known_value_is_not_duplicated():
    choices = build_select_choices(spec('DSLR_Capture', 'SHUTTERSPEED'), '1/125')
    assert [value for value, _label in choices].count('1/125') == 1


def test_every_field_is_rendered_with_a_name_and_an_id():
    sections = render_sections(load_parser(SAMPLE))

    rendered = [field for section in sections for field in section['fields']]
    expected = [field for section in CONFIG_FORM_SECTIONS for field in section['fields']]
    assert len(rendered) == len(expected)
    for field in rendered:
        assert field['name'] == field_name(field['section'], field['option'])
        assert field['id'] == field['name'].lower()


def test_a_checkbox_is_rendered_checked_from_the_file():
    sections = render_sections(load_parser('[Global]\nFULLSCREEN = True\n'))
    fullscreen = next(f for s in sections for f in s['fields'] if f['option'] == 'FULLSCREEN')

    assert fullscreen['checked'] is True


def test_a_rejected_submission_is_shown_back_to_the_operator():
    submitted = {field_name('Capture', 'COUNTDOWN'): '12'}

    sections = render_sections(load_parser(SAMPLE), form_values=submitted)

    countdown = next(f for s in sections for f in s['fields'] if f['option'] == 'COUNTDOWN')
    assert countdown['value'] == '12'


# --- reading the whole form ------------------------------------------------

def test_an_unchecked_checkbox_is_absent_from_the_submission():
    parser = load_parser(SHIPPED_CONFIG)
    form = full_form(parser)
    form.pop(field_name('Global', 'FULLSCREEN'), None)

    updates, _submitted = collect_updates(form, parser)

    assert updates[('Global', 'FULLSCREEN')] == 'False'


def test_a_checked_checkbox_is_present_with_any_value():
    parser = load_parser(SHIPPED_CONFIG)

    updates, _submitted = collect_updates(full_form(parser, **{field_name('Global', 'FULLSCREEN'): 'on'}), parser)

    assert updates[('Global', 'FULLSCREEN')] == 'True'


def test_a_missing_required_number_is_refused_by_name():
    parser = load_parser(SHIPPED_CONFIG)
    form = full_form(parser, **{field_name('Web', 'WEB_PORT'): ''})

    with pytest.raises(ValueError, match='Web port'):
        collect_updates(form, parser)


def test_a_full_round_trip_over_the_shipped_config_changes_only_what_was_edited():
    parser = load_parser(SHIPPED_CONFIG)
    form = full_form(parser, **{field_name('Capture', 'COUNTDOWN'): '7'})

    updates, _submitted = collect_updates(form, parser)
    written = load_parser(apply_updates(SHIPPED_CONFIG, updates))

    assert written.get('Capture', 'COUNTDOWN') == '7'
    for section in parser.sections():
        for option in parser[section]:
            if (section, option) == ('Capture', 'COUNTDOWN'):
                continue
            assert written.get(section, option) == parser.get(section, option), f'{section}.{option} drifted'


def test_the_shipped_config_declares_every_option_the_form_edits():
    """A form field with no home in config.ini.example would be invisible."""
    parser = load_parser(SHIPPED_CONFIG)

    for section_spec in CONFIG_FORM_SECTIONS:
        for field_spec in section_spec['fields']:
            assert parser.has_option(field_spec['section'], field_spec['option']), \
                f'{field_spec["section"]}.{field_spec["option"]} missing from config.ini.example'


def test_the_form_covers_every_option_only_once():
    keys = [(f['section'], f['option']) for s in CONFIG_FORM_SECTIONS for f in s['fields']]
    assert len(keys) == len(set(keys))


def test_every_field_declares_a_control_the_form_can_render():
    known = {'checkbox', 'text', 'password', 'number', 'select'}
    for section_spec in CONFIG_FORM_SECTIONS:
        for field_spec in section_spec['fields']:
            assert field_spec['control'] in known
            assert field_spec['label']
            if field_spec['control'] == 'select':
                assert field_spec['choices']
            if field_spec['control'] == 'number':
                assert field_spec['number_type'] in {'int', 'float', 'optional_int'}
