"""The typed admin form over config.ini.

An operator edits the booth's configuration on site, through a form rather than
a text box, so every field carries its control, its type and its bounds. The
description and the coercion live together here: the form the admin page shows
and the values the application will accept cannot drift apart.

The words live in locales/, under web.config: a field's label and help are
looked up from its section and option, so the same form reads in the booth's
language, and an operator coming back to it months later is told what each
setting does, what it defaults to, and what it is called in config.ini.

Nothing in this module touches Flask or the filesystem. It takes a ConfigParser
and a submitted form, and returns either rendered fields or new config text.
"""

import configparser
import re

from libs import i18n, timings
from libs.config import TIMING_OPTIONS

# A choice is (value, translation key). A key of None shows the value itself,
# for values that read the same in every language, such as a shutter speed.
LEAVE_UNCHANGED = ('', 'web.config.leave_unchanged')

DSLR_SHUTTERSPEED_CHOICES = [LEAVE_UNCHANGED] + [
    (speed, None) for speed in ('1/30', '1/60', '1/80', '1/100', '1/125', '1/160', '1/200', '1/250', '1/320', '1/400', '1/500')
]
DSLR_APERTURE_CHOICES = [LEAVE_UNCHANGED] + [
    (aperture, None) for aperture in ('1.8', '2', '2.8', '4', '5.6', '8', '11', '13', '16', '22')
]
DSLR_FOCUSMODE_CHOICES = [LEAVE_UNCHANGED] + [
    (mode, None) for mode in ('One Shot', 'AF-S', 'AF-A', 'AF-C', 'Manual')
]
DSLR_ISO_CHOICES = [LEAVE_UNCHANGED] + [
    (iso, None) for iso in ('100', '200', '400', '800', '1600', '3200', '6400')
]


def _dslr_fields(section):
    # Both DSLR sections take the same four settings, so they share their words.
    return (
        {'section': section, 'option': 'SHUTTERSPEED', 'text_key': 'DSLR', 'control': 'select', 'choices': DSLR_SHUTTERSPEED_CHOICES, 'default': ''},
        {'section': section, 'option': 'APERTURE', 'text_key': 'DSLR', 'control': 'select', 'choices': DSLR_APERTURE_CHOICES, 'default': ''},
        {'section': section, 'option': 'FOCUSMODE', 'text_key': 'DSLR', 'control': 'select', 'choices': DSLR_FOCUSMODE_CHOICES, 'default': ''},
        {'section': section, 'option': 'ISO', 'text_key': 'DSLR', 'control': 'select', 'choices': DSLR_ISO_CHOICES, 'default': ''},
    )


# Ordered the way an operator sets a booth up for an evening, not the way
# config.ini happens to be laid out: each field still names its own [Section].
# 'default' is what libs/config.py falls back to when the option is absent, as
# it would be written in the file; test_config_form holds the two together.
CONFIG_FORM_SECTIONS = (
    {
        'id': 'event',
        'fields': (
            {'section': 'Event', 'option': 'WELCOME_TITLE', 'control': 'text', 'placeholder': 'Photo Booth', 'default': ''},
            {'section': 'Event', 'option': 'WELCOME_SUBTITLE', 'control': 'text', 'placeholder': 'Lou & Max, 13/09/2026', 'default': ''},
            {'section': 'Event', 'option': 'WELCOME_FONT', 'control': 'select', 'default': 'elegant',
             'choices': [('elegant', 'web.config.choices.welcome_font.elegant'), ('script', 'web.config.choices.welcome_font.script'),
                         ('modern', 'web.config.choices.welcome_font.modern'), ('playful', 'web.config.choices.welcome_font.playful')]},
            {'section': 'Event', 'option': 'EVENT_NAME', 'control': 'text', 'placeholder': 'Lou & Max', 'default': ''},
            {'section': 'Event', 'option': 'DATE_FORMAT', 'control': 'text', 'placeholder': '%d/%m/%Y', 'default': '%d/%m/%Y'},
        ),
    },
    {
        'id': 'slideshow',
        'fields': (
            {'section': 'Slideshow', 'option': 'SLIDESHOW', 'control': 'checkbox', 'default': 'False'},
            {'section': 'Slideshow', 'option': 'SLIDESHOW_IDLE_SECONDS', 'control': 'number', 'number_type': 'int', 'min': 10, 'step': 1, 'unit': 'seconds', 'default': '60'},
            {'section': 'Slideshow', 'option': 'SLIDESHOW_PHOTO_SECONDS', 'control': 'number', 'number_type': 'int', 'min': 2, 'step': 1, 'unit': 'seconds', 'default': '6'},
        ),
    },
    {
        'id': 'timing',
        'fields': tuple(
            {'section': 'Timing', 'option': option, 'control': 'number', 'number_type': 'int', 'min': minimum, 'step': 1, 'unit': 'seconds', 'default': str(timings.DEFAULTS[name])}
            for name, (option, minimum) in TIMING_OPTIONS.items()
        ),
    },
    {
        'id': 'capture',
        'fields': (
            {'section': 'Capture', 'option': 'COUNTDOWN', 'control': 'number', 'number_type': 'int', 'min': 0, 'step': 1, 'unit': 'seconds', 'default': '5'},
            {'section': 'Capture', 'option': 'FILTERS', 'control': 'checkbox', 'default': 'False'},
            {'section': 'Capture', 'option': 'CAMERA', 'control': 'select', 'default': 'auto',
             'choices': [('auto', 'web.config.choices.camera.auto'), ('gphoto2', 'web.config.choices.camera.gphoto2'),
                         ('picamera2', 'web.config.choices.camera.picamera2'), ('opencv', 'web.config.choices.camera.opencv'),
                         ('fake', 'web.config.choices.camera.fake')]},
            {'section': 'Capture', 'option': 'CALIBRATION', 'control': 'text', 'placeholder': '(1.4, 0, 0)', 'default': 'None', 'default_key': 'web.config.value.disabled'},
            {'section': 'Capture', 'option': 'BLUR_CAMERA', 'control': 'checkbox', 'default': 'True'},
            {'section': 'Capture', 'option': 'PREVIEW_BLUR_REFRESH_FRAMES', 'control': 'number', 'number_type': 'int', 'min': 1, 'step': 1, 'unit': 'frames', 'default': '3'},
            {'section': 'Capture', 'option': 'BLUR_IMAGES', 'control': 'checkbox', 'default': 'False'},
            {'section': 'Capture', 'option': 'BLUR_COLLAGE', 'control': 'checkbox', 'default': 'False'},
        ),
    },
    {
        'id': 'print',
        'fields': (
            {'section': 'Print', 'option': 'PRINTER', 'control': 'text', 'placeholder': 'DS620', 'none_means_empty': True, 'default': 'None', 'default_key': 'web.config.value.printing_disabled'},
            {'section': 'Print', 'option': 'MAX_PRINTS', 'control': 'number', 'number_type': 'optional_int', 'min': 0, 'step': 1, 'unit': 'prints', 'placeholder_key': 'web.config.value.unlimited', 'default': 'None', 'default_key': 'web.config.value.unlimited'},
            {'section': 'Print', 'option': 'MAX_COPIES', 'control': 'number', 'number_type': 'int', 'min': 1, 'max': 10, 'step': 1, 'unit': 'copies', 'default': '3'},
            {'section': 'Print', 'option': 'PRINTER_WAIT_TIMEOUT', 'control': 'number', 'number_type': 'int', 'min': 5, 'step': 1, 'unit': 'seconds', 'default': '45'},
        ),
    },
    {
        'id': 'phones',
        'fields': (
            {'section': 'Global', 'option': 'SHARE', 'control': 'checkbox', 'default': 'True'},
            {'section': 'Remote', 'option': 'REMOTE_CAPTURE', 'control': 'checkbox', 'default': 'False'},
            {'section': 'Remote', 'option': 'REMOTE_MAX_UPLOAD_MB', 'control': 'number', 'number_type': 'int', 'min': 1, 'step': 1, 'unit': 'megabytes', 'default': '12'},
            {'section': 'Remote', 'option': 'REMOTE_MAX_IMAGE_PIXELS', 'control': 'number', 'number_type': 'int', 'min': 640, 'step': 10, 'unit': 'pixels', 'default': '2400'},
            {'section': 'Remote', 'option': 'REMOTE_MAX_PER_SENDER', 'control': 'number', 'number_type': 'int', 'min': 1, 'step': 1, 'unit': 'photos', 'default': '20'},
            {'section': 'Remote', 'option': 'REMOTE_MAX_PENDING', 'control': 'number', 'number_type': 'int', 'min': 1, 'step': 1, 'unit': 'photos', 'default': '200'},
            {'section': 'Remote', 'option': 'REMOTE_MIN_UPLOAD_INTERVAL', 'control': 'number', 'number_type': 'int', 'min': 0, 'step': 1, 'unit': 'seconds', 'default': '3'},
        ),
    },
    {
        'id': 'guest_network',
        'fields': (
            {'section': 'WiFi', 'option': 'WIFI_SSID', 'control': 'text', 'placeholder': 'Photobooth', 'default': ''},
            {'section': 'WiFi', 'option': 'WIFI_PASSWORD', 'control': 'text', 'placeholder_key': 'web.config.value.open_network', 'default': ''},
            {'section': 'WiFi', 'option': 'WIFI_HIDDEN', 'control': 'checkbox', 'default': 'False'},
            {'section': 'Remote', 'option': 'REMOTE_URL', 'control': 'text', 'placeholder': '192.168.8.20:5000', 'none_means_empty': True, 'default': 'None', 'default_key': 'web.config.value.automatic'},
        ),
    },
    {
        'id': 'screen',
        'fields': (
            {'section': 'Global', 'option': 'LANGUAGE', 'control': 'select', 'default': 'en',
             'choices': [('en', 'web.config.choices.language.en'), ('fr', 'web.config.choices.language.fr')]},
            {'section': 'Global', 'option': 'FULLSCREEN', 'control': 'checkbox', 'default': 'True'},
            {'section': 'Global', 'option': 'WINDOW_WIDTH', 'control': 'number', 'number_type': 'int', 'min': 320, 'step': 1, 'unit': 'pixels', 'default': '1024'},
            {'section': 'Global', 'option': 'WINDOW_HEIGHT', 'control': 'number', 'number_type': 'int', 'min': 320, 'step': 1, 'unit': 'pixels', 'default': '600'},
            {'section': 'Global', 'option': 'ROTATION', 'control': 'select', 'default': '0',
             'choices': [('0', 'web.config.choices.rotation.0'), ('90', 'web.config.choices.rotation.90'),
                         ('180', 'web.config.choices.rotation.180'), ('270', 'web.config.choices.rotation.270')]},
            {'section': 'Global', 'option': 'RINGLED', 'control': 'checkbox', 'default': 'False'},
            {'section': 'Global', 'option': 'RINGLED_PIXELS', 'control': 'number', 'number_type': 'int', 'min': 1, 'max': 256, 'step': 1, 'unit': 'leds', 'default': '12'},
        ),
    },
    {
        'id': 'storage',
        'fields': (
            {'section': 'Storage', 'option': 'DCIM_DIRECTORY', 'control': 'text', 'placeholder': './DCIM', 'default': './DCIM'},
            {'section': 'Storage', 'option': 'DISK_MIN_FREE_GB', 'control': 'number', 'number_type': 'float', 'min': 0, 'step': 0.1, 'unit': 'gigabytes', 'default': '2.0'},
            {'section': 'Storage', 'option': 'DISK_MAX_USED_PERCENT', 'control': 'number', 'number_type': 'float', 'min': 0, 'max': 100, 'step': 0.1, 'unit': 'percent', 'default': '90.0'},
            {'section': 'USB', 'option': 'USB_EXPORT', 'control': 'checkbox', 'default': 'True'},
            {'section': 'USB', 'option': 'USB_MIN_FREE_GB', 'control': 'number', 'number_type': 'float', 'min': 0, 'step': 0.1, 'unit': 'gigabytes', 'default': '1.0'},
        ),
    },
    {
        'id': 'access',
        'fields': (
            {'section': 'Global', 'option': 'ADMIN_PASSWORD', 'control': 'password', 'placeholder_key': 'web.config.password_placeholder'},
            {'section': 'Web', 'option': 'WEB_PORT', 'control': 'number', 'number_type': 'int', 'min': 1, 'max': 65535, 'step': 1, 'default': '5000'},
            {'section': 'Web', 'option': 'WEB_HOST', 'control': 'text', 'placeholder': '0.0.0.0', 'default': '0.0.0.0'},
            {'section': 'Log', 'option': 'LOG_RETENTION_DAYS', 'control': 'number', 'number_type': 'int', 'min': 1, 'step': 1, 'unit': 'days', 'default': '14'},
            {'section': 'Log', 'option': 'LOG_MAX_FILES', 'control': 'number', 'number_type': 'int', 'min': 1, 'step': 1, 'unit': 'files', 'default': '40'},
        ),
    },
    {
        'id': 'dslr_liveview',
        'advanced': True,
        'fields': _dslr_fields('DSLR_Liveview'),
    },
    {
        'id': 'dslr_capture',
        'advanced': True,
        'fields': _dslr_fields('DSLR_Capture'),
    },
)

TRUE_VALUES = ('1', 'true', 'yes', 'on')

SECTION_PATTERN = re.compile(r'^\s*\[(.+?)\]\s*$')
OPTION_PATTERN = re.compile(r'^(\s*)([^=;#][^=]*?)(\s*=\s*)(.*?)(\r?\n?)$')


def load_parser(content):
    """Parse config.ini text, preserving option case."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string(content)
    return parser


def field_name(section, option):
    return f'{section}__{option}'


def text_key(field_spec, part):
    """The translation key for a field's 'label' or 'help'."""
    group = field_spec.get('text_key', field_spec['section'])
    return f'web.config.fields.{group}.{field_spec["option"]}.{part}'


def field_label(field_spec, lang=i18n.DEFAULT_LANGUAGE):
    return i18n.translate(lang, text_key(field_spec, 'label'))


def choice_label(choice_key, value, lang):
    return value if choice_key is None else i18n.translate(lang, choice_key)


def normalize_value(field_spec, raw_value):
    """The value to put in the form control, as opposed to in the file."""
    value = '' if raw_value is None else str(raw_value).strip()
    control = field_spec['control']

    if control == 'checkbox':
        return value.lower() in TRUE_VALUES

    if field_spec['option'] == 'ADMIN_PASSWORD':
        # Never send the current password back to the browser.
        return ''

    if field_spec.get('number_type') == 'optional_int' and value.upper() == 'NONE':
        return ''

    if field_spec.get('none_means_empty') and value.upper() == 'NONE':
        return ''

    if field_spec['option'] == 'CALIBRATION' and value.upper() == 'NONE':
        return ''

    return value


def build_select_choices(field_spec, current_value, lang=i18n.DEFAULT_LANGUAGE):
    """Offered choices as (value, label), plus whatever the file already holds.

    A value set by hand, or by a newer version, must not silently vanish from
    the form the moment an operator saves.
    """
    choices = [(value, choice_label(key, value, lang)) for value, key in field_spec.get('choices', ())]
    choice_values = {value for value, _label in choices}
    if current_value and current_value not in choice_values:
        choices.append((current_value, i18n.translate(lang, 'web.config.current_value', value=current_value)))
    return choices


def default_text(field_spec, lang=i18n.DEFAULT_LANGUAGE):
    """What the booth does when the option is absent, in words, or None."""
    if 'default' not in field_spec:
        return None
    if field_spec.get('default_key'):
        return i18n.translate(lang, field_spec['default_key'])

    default = field_spec['default']
    control = field_spec['control']
    if control == 'checkbox':
        return i18n.translate(lang, 'web.config.value.on' if default.lower() in TRUE_VALUES else 'web.config.value.off')
    if control == 'select':
        for value, key in field_spec['choices']:
            if value == default:
                return choice_label(key, value, lang)
    if default == '':
        return i18n.translate(lang, 'web.config.value.empty')
    if field_spec.get('unit'):
        return f'{default} {i18n.translate(lang, "web.config.units." + field_spec["unit"])}'
    return default


def current_values(parser):
    values = {}
    for section_spec in CONFIG_FORM_SECTIONS:
        for field_spec in section_spec['fields']:
            section, option = field_spec['section'], field_spec['option']
            values[(section, option)] = parser.get(section, option, fallback='')
    return values


def render_sections(parser, form_values=None, lang=i18n.DEFAULT_LANGUAGE):
    """Build the form the admin page renders, from the file or a rejected submission."""
    form_values = form_values or {}
    sections = []

    for section_spec in CONFIG_FORM_SECTIONS:
        rendered_fields = []
        for field_spec in section_spec['fields']:
            section, option = field_spec['section'], field_spec['option']
            name = field_name(section, option)
            file_value = parser.get(section, option, fallback='')
            raw_value = form_values.get(name, file_value)
            normalized_value = normalize_value(field_spec, raw_value)

            rendered_field = dict(field_spec)
            rendered_field['name'] = name
            rendered_field['id'] = name.lower()
            rendered_field['value'] = normalized_value
            rendered_field['checked'] = bool(normalized_value) if field_spec['control'] == 'checkbox' else False
            rendered_field['label'] = field_label(field_spec, lang)
            rendered_field['help'] = i18n.translate(lang, text_key(field_spec, 'help'))
            rendered_field['default_text'] = default_text(field_spec, lang)
            rendered_field['unit_text'] = i18n.translate(lang, f'web.config.units.{field_spec["unit"]}') if field_spec.get('unit') else ''
            if field_spec.get('placeholder_key'):
                rendered_field['placeholder'] = i18n.translate(lang, field_spec['placeholder_key'])

            if field_spec['control'] == 'select':
                rendered_field['choices'] = build_select_choices(field_spec, normalized_value, lang)

            if option == 'ADMIN_PASSWORD':
                rendered_field['password_set'] = bool(file_value.strip()) and file_value.strip().upper() != 'NONE'

            rendered_fields.append(rendered_field)

        sections.append({
            'id': section_spec['id'],
            'title': i18n.translate(lang, f'web.config.sections.{section_spec["id"]}.title'),
            'description': i18n.translate(lang, f'web.config.sections.{section_spec["id"]}.description'),
            'advanced': section_spec.get('advanced', False),
            'fields': rendered_fields,
        })

    return sections


def _bounded_number(field_spec, value, parse, lang):
    label = field_label(field_spec, lang)
    try:
        parsed_value = parse(value)
    except ValueError:
        raise ValueError(i18n.translate(lang, 'web.config.errors.not_a_number', label=label)) from None
    if 'min' in field_spec and parsed_value < field_spec['min']:
        raise ValueError(i18n.translate(lang, 'web.config.errors.at_least', label=label, min=field_spec['min']))
    if 'max' in field_spec and parsed_value > field_spec['max']:
        raise ValueError(i18n.translate(lang, 'web.config.errors.at_most', label=label, max=field_spec['max']))
    return str(parsed_value)


def coerce_value(field_spec, submitted_value, current_value, lang=i18n.DEFAULT_LANGUAGE):
    """Turn one submitted field into the text to write, or refuse it.

    Raises ValueError with a message meant for the operator, not for a log.
    """
    if field_spec['control'] == 'checkbox':
        return 'True' if submitted_value else 'False'

    value = '' if submitted_value is None else str(submitted_value).strip()
    option = field_spec['option']
    number_type = field_spec.get('number_type')

    if option == 'ADMIN_PASSWORD':
        # Blank means "keep the one already there", since it is never shown.
        return current_value if value == '' else value

    if option == 'CALIBRATION':
        return value or 'None'

    if number_type in ('int', 'float'):
        if value == '':
            raise ValueError(i18n.translate(lang, 'web.config.errors.required', label=field_label(field_spec, lang)))
        return _bounded_number(field_spec, value, int if number_type == 'int' else float, lang)

    if number_type == 'optional_int':
        return 'None' if value == '' else _bounded_number(field_spec, value, int, lang)

    if field_spec.get('none_means_empty'):
        return value or 'None'

    return value


def collect_updates(form, parser, lang=i18n.DEFAULT_LANGUAGE):
    """Read the whole submitted form; returns (updates, values to redisplay)."""
    existing = current_values(parser)
    updates = {}
    submitted_form_values = {}

    for section_spec in CONFIG_FORM_SECTIONS:
        for field_spec in section_spec['fields']:
            key = (field_spec['section'], field_spec['option'])
            name = field_name(*key)

            # An unchecked checkbox is simply absent from the submission.
            submitted_value = name in form if field_spec['control'] == 'checkbox' else form.get(name, '')
            submitted_form_values[name] = submitted_value

    # Every field is read before the first refusal, so a rejected submission
    # redisplays everything the operator typed, not just what came before it.
    for section_spec in CONFIG_FORM_SECTIONS:
        for field_spec in section_spec['fields']:
            key = (field_spec['section'], field_spec['option'])
            try:
                updates[key] = coerce_value(field_spec, submitted_form_values[field_name(*key)], existing[key], lang)
            except ValueError as exc:
                exc.submitted_form_values = submitted_form_values
                raise

    return updates, submitted_form_values


def apply_updates(content, updates):
    """Rewrite config.ini in place, keeping comments, order and spacing.

    The file is edited by hand as much as through this form, so it is patched
    line by line rather than regenerated by ConfigParser, which would drop every
    comment explaining what the settings do.
    """
    section_values = {}
    for (section, option), value in updates.items():
        section_values.setdefault(section, {})[option] = value

    lines = content.splitlines(keepends=True)
    rendered_lines = []
    existing_sections = set()
    seen_options = set()
    current_section = None
    line_ending = '\n'

    def append_missing_options(section):
        for option, value in section_values.get(section, {}).items():
            key = (section, option)
            if key in seen_options:
                continue
            rendered_lines.append(f'{option} = {value}{line_ending}')
            seen_options.add(key)

    for line in lines:
        if line.endswith('\r\n'):
            line_ending = '\r\n'
        elif line.endswith('\n'):
            line_ending = '\n'

        section_match = SECTION_PATTERN.match(line.strip())
        if section_match:
            if current_section is not None:
                append_missing_options(current_section)
            current_section = section_match.group(1).strip()
            existing_sections.add(current_section)
            rendered_lines.append(line)
            continue

        option_match = OPTION_PATTERN.match(line)
        if current_section is not None and option_match:
            option_name = option_match.group(2).strip()
            key = (current_section, option_name)
            if key in updates:
                rendered_lines.append(
                    f'{option_match.group(1)}{option_name}{option_match.group(3)}'
                    f'{updates[key]}{option_match.group(5) or line_ending}'
                )
                seen_options.add(key)
                continue

        rendered_lines.append(line)

    if current_section is not None:
        append_missing_options(current_section)

    for section, options in section_values.items():
        if section in existing_sections:
            continue
        if rendered_lines and rendered_lines[-1].strip():
            rendered_lines.append(line_ending)
        rendered_lines.append(f'[{section}]{line_ending}')
        for option, value in options.items():
            rendered_lines.append(f'{option} = {value}{line_ending}')

    return ''.join(rendered_lines)
