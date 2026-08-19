"""The typed admin form over config.ini.

An operator edits the booth's configuration on site, through a form rather than
a text box, so every field carries its control, its type and its bounds. The
description and the coercion live together here: the form the admin page shows
and the values the application will accept cannot drift apart.

Nothing in this module touches Flask or the filesystem. It takes a ConfigParser
and a submitted form, and returns either rendered fields or new config text.
"""

import configparser
import re

DSLR_SHUTTERSPEED_CHOICES = [
    ('', 'Leave unchanged'),
    ('1/30', '1/30'), ('1/60', '1/60'), ('1/80', '1/80'), ('1/100', '1/100'),
    ('1/125', '1/125'), ('1/160', '1/160'), ('1/200', '1/200'), ('1/250', '1/250'),
    ('1/320', '1/320'), ('1/400', '1/400'), ('1/500', '1/500'),
]
DSLR_APERTURE_CHOICES = [
    ('', 'Leave unchanged'),
    ('1.8', '1.8'), ('2', '2'), ('2.8', '2.8'), ('4', '4'), ('5.6', '5.6'),
    ('8', '8'), ('11', '11'), ('13', '13'), ('16', '16'), ('22', '22'),
]
DSLR_FOCUSMODE_CHOICES = [
    ('', 'Leave unchanged'),
    ('One Shot', 'One Shot'), ('AF-S', 'AF-S'), ('AF-A', 'AF-A'),
    ('AF-C', 'AF-C'), ('Manual', 'Manual'),
]
DSLR_ISO_CHOICES = [
    ('', 'Leave unchanged'),
    ('100', '100'), ('200', '200'), ('400', '400'), ('800', '800'),
    ('1600', '1600'), ('3200', '3200'), ('6400', '6400'),
]

CONFIG_FORM_SECTIONS = (
    {
        'title': 'Global',
        'description': 'General application behavior and admin access.',
        'fields': (
            {'section': 'Global', 'option': 'LANGUAGE', 'label': 'Language', 'control': 'select',
             'choices': [('en', 'English'), ('fr', 'Français')],
             'help': 'Booth screen and admin pages. Guests on their own phone get their phone’s language instead.'},
            {'section': 'Global', 'option': 'FULLSCREEN', 'label': 'Fullscreen', 'control': 'checkbox', 'help': 'Launch PhotoBooth in fullscreen kiosk mode.'},
            {'section': 'Global', 'option': 'WINDOW_WIDTH', 'label': 'Window width (pixels)', 'control': 'number', 'number_type': 'int', 'min': 320, 'step': 1,
             'help': 'Match the panel: 1024 x 600 for the Ingcool 7″, 1920 x 1080 for a full HD monitor. Also the mode fullscreen runs at.'},
            {'section': 'Global', 'option': 'WINDOW_HEIGHT', 'label': 'Window height (pixels)', 'control': 'number', 'number_type': 'int', 'min': 320, 'step': 1,
             'help': 'Both sides are applied on the next start of the booth.'},
            {'section': 'Global', 'option': 'ROTATION', 'label': 'Screen rotation', 'control': 'select',
             'choices': [('0', 'None (landscape)'), ('90', 'Quarter turn right (portrait)'),
                         ('180', 'Upside down'), ('270', 'Quarter turn left (portrait)')],
             'help': 'For a panel mounted on its side. Leave the width and height above at the panel’s own mode, they are not swapped.'},
            {'section': 'Global', 'option': 'SHARE', 'label': 'Share buttons', 'control': 'checkbox', 'help': 'Display web sharing actions in the booth interface.'},
            {'section': 'Global', 'option': 'RINGLED', 'label': 'Ring LED', 'control': 'checkbox', 'help': 'Enable the SPI ring light hardware.'},
            {'section': 'Global', 'option': 'ADMIN_PASSWORD', 'label': 'Admin password', 'control': 'password', 'placeholder': 'Leave blank to keep current password', 'help': 'At least 10 characters, or None to disable admin login.'},
        ),
    },
    {
        'title': 'Web & Logs',
        'description': 'Web access and log retention settings.',
        'fields': (
            {'section': 'Web', 'option': 'WEB_PORT', 'label': 'Web port', 'control': 'number', 'number_type': 'int', 'min': 1, 'step': 1},
            {'section': 'Web', 'option': 'WEB_HOST', 'label': 'Bind address', 'control': 'text', 'placeholder': '0.0.0.0', 'help': '0.0.0.0 for every network, 127.0.0.1 to keep the admin local.'},
            {'section': 'Log', 'option': 'LOG_RETENTION_DAYS', 'label': 'Log retention days', 'control': 'number', 'number_type': 'int', 'min': 1, 'step': 1},
            {'section': 'Log', 'option': 'LOG_MAX_FILES', 'label': 'Maximum log files', 'control': 'number', 'number_type': 'int', 'min': 1, 'step': 1},
        ),
    },
    {
        'title': 'WiFi access point',
        'description': 'What the QR code tells a phone to join. Describes hostapd, does not configure it.',
        'fields': (
            {'section': 'WiFi', 'option': 'WIFI_SSID', 'label': 'Network name', 'control': 'text', 'placeholder': 'PhotoBooth', 'help': 'Must match ssid= in /etc/hostapd/hostapd.conf.'},
            {'section': 'WiFi', 'option': 'WIFI_PASSWORD', 'label': 'Network password', 'control': 'text', 'placeholder': 'Open network', 'help': 'Leave empty for an open network, as install.sh configures it.'},
            {'section': 'WiFi', 'option': 'WIFI_HIDDEN', 'label': 'Hidden network', 'control': 'checkbox'},
            {'section': 'WiFi', 'option': 'WIFI_AP_ADDRESS', 'label': 'Booth address on that network', 'control': 'text', 'placeholder': '192.168.4.1', 'help': 'What the QR code sends phones to. Empty to guess it from the system routes.'},
        ),
    },
    {
        'title': 'Remote camera',
        'description': 'Photos guests take with their own phone and send to the booth.',
        'fields': (
            {'section': 'Remote', 'option': 'REMOTE_CAPTURE', 'label': 'Phone camera', 'control': 'checkbox', 'help': 'Show the QR code on the welcome screen and accept photos from phones.'},
            {'section': 'Remote', 'option': 'REMOTE_URL', 'label': 'Public address', 'control': 'text', 'placeholder': 'None', 'none_means_empty': True, 'help': 'Leave empty to derive it from the interface the booth answers on, or give the whole address, port included.'},
            {'section': 'Remote', 'option': 'REMOTE_MAX_UPLOAD_MB', 'label': 'Maximum upload (MB)', 'control': 'number', 'number_type': 'int', 'min': 1, 'step': 1},
            {'section': 'Remote', 'option': 'REMOTE_MAX_IMAGE_PIXELS', 'label': 'Longest side kept (pixels)', 'control': 'number', 'number_type': 'int', 'min': 640, 'step': 10},
            {'section': 'Remote', 'option': 'REMOTE_MAX_PER_SENDER', 'label': 'Photos per phone', 'control': 'number', 'number_type': 'int', 'min': 1, 'step': 1},
            {'section': 'Remote', 'option': 'REMOTE_MAX_PENDING', 'label': 'Photos waiting in total', 'control': 'number', 'number_type': 'int', 'min': 1, 'step': 1},
            {'section': 'Remote', 'option': 'REMOTE_MIN_UPLOAD_INTERVAL', 'label': 'Seconds between two sends', 'control': 'number', 'number_type': 'int', 'min': 0, 'step': 1},
        ),
    },
    {
        'title': 'Capture',
        'description': 'Camera countdown, calibration and preview behavior.',
        'fields': (
            {'section': 'Capture', 'option': 'CAMERA', 'label': 'Camera backend', 'control': 'select',
             'choices': [('auto', 'auto (detect)'), ('gphoto2', 'gphoto2 (DSLR)'), ('picamera2', 'picamera2'),
                         ('opencv', 'opencv (webcam)'), ('fake', 'fake (no hardware)')],
             'help': 'Naming the backend makes startup faster and predictable.'},
            {'section': 'Capture', 'option': 'COUNTDOWN', 'label': 'Countdown (seconds)', 'control': 'number', 'number_type': 'int', 'min': 0, 'step': 1},
            {'section': 'Capture', 'option': 'CALIBRATION', 'label': 'Calibration', 'control': 'text', 'placeholder': 'None or (zoom, offset_x, offset_y)', 'help': 'This field stays as a raw string because it is produced by the calibration tool.'},
            {'section': 'Capture', 'option': 'FILTERS', 'label': 'Photo filters', 'control': 'checkbox', 'help': 'Allow visitors to choose a filter after each shot.'},
            {'section': 'Capture', 'option': 'BLUR_CAMERA', 'label': 'Blur preview borders', 'control': 'checkbox', 'inline_with_next': True},
            {'section': 'Capture', 'option': 'PREVIEW_BLUR_REFRESH_FRAMES', 'label': 'Preview blur refresh frames', 'control': 'number', 'number_type': 'int', 'min': 1, 'step': 1, 'inline_with_previous': True},
            {'section': 'Capture', 'option': 'BLUR_IMAGES', 'label': 'Blur captured images', 'control': 'checkbox'},
            {'section': 'Capture', 'option': 'BLUR_COLLAGE', 'label': 'Blur collages', 'control': 'checkbox'},
        ),
    },
    {
        'title': 'Storage',
        'description': 'Disk paths and safeguards against full storage.',
        'fields': (
            {'section': 'Storage', 'option': 'DCIM_DIRECTORY', 'label': 'Photo storage directory', 'control': 'text', 'placeholder': './DCIM'},
            {'section': 'Storage', 'option': 'DISK_MIN_FREE_GB', 'label': 'Minimum free space (GB)', 'control': 'number', 'number_type': 'float', 'min': 0, 'step': 0.1},
            {'section': 'Storage', 'option': 'DISK_MAX_USED_PERCENT', 'label': 'Maximum used disk (%)', 'control': 'number', 'number_type': 'float', 'min': 0, 'max': 100, 'step': 0.1},
        ),
    },
    {
        'title': 'Print & USB',
        'description': 'Printer usage limits and USB export.',
        'fields': (
            {'section': 'Print', 'option': 'PRINTER', 'label': 'Printer name', 'control': 'text', 'placeholder': 'None', 'none_means_empty': True, 'help': 'Leave empty to disable printing.'},
            {'section': 'Print', 'option': 'MAX_PRINTS', 'label': 'Maximum prints', 'control': 'number', 'number_type': 'optional_int', 'min': 0, 'step': 1, 'placeholder': 'Unlimited', 'help': 'Leave empty for unlimited prints.'},
            {'section': 'Print', 'option': 'PRINTER_WAIT_TIMEOUT', 'label': 'Printer wait timeout (seconds)', 'control': 'number', 'number_type': 'int', 'min': 5, 'step': 1},
            {'section': 'USB', 'option': 'USB_EXPORT', 'label': 'USB export', 'control': 'checkbox', 'help': 'Automatically copy saved sessions to removable USB media.'},
            {'section': 'USB', 'option': 'USB_MIN_FREE_GB', 'label': 'USB minimum free space (GB)', 'control': 'number', 'number_type': 'float', 'min': 0, 'step': 0.1},
        ),
    },
    {
        'title': 'DSLR Liveview',
        'description': 'Parameters applied while preview/liveview is active.',
        'fields': (
            {'section': 'DSLR_Liveview', 'option': 'SHUTTERSPEED', 'label': 'Shutter speed', 'control': 'select', 'choices': DSLR_SHUTTERSPEED_CHOICES},
            {'section': 'DSLR_Liveview', 'option': 'APERTURE', 'label': 'Aperture', 'control': 'select', 'choices': DSLR_APERTURE_CHOICES},
            {'section': 'DSLR_Liveview', 'option': 'FOCUSMODE', 'label': 'Focus mode', 'control': 'select', 'choices': DSLR_FOCUSMODE_CHOICES},
            {'section': 'DSLR_Liveview', 'option': 'ISO', 'label': 'ISO', 'control': 'select', 'choices': DSLR_ISO_CHOICES},
        ),
    },
    {
        'title': 'DSLR Capture',
        'description': 'Parameters applied right before taking a photo.',
        'fields': (
            {'section': 'DSLR_Capture', 'option': 'SHUTTERSPEED', 'label': 'Shutter speed', 'control': 'select', 'choices': DSLR_SHUTTERSPEED_CHOICES},
            {'section': 'DSLR_Capture', 'option': 'APERTURE', 'label': 'Aperture', 'control': 'select', 'choices': DSLR_APERTURE_CHOICES},
            {'section': 'DSLR_Capture', 'option': 'FOCUSMODE', 'label': 'Focus mode', 'control': 'select', 'choices': DSLR_FOCUSMODE_CHOICES},
            {'section': 'DSLR_Capture', 'option': 'ISO', 'label': 'ISO', 'control': 'select', 'choices': DSLR_ISO_CHOICES},
        ),
    },
)

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


def normalize_value(field_spec, raw_value):
    """The value to put in the form control, as opposed to in the file."""
    value = '' if raw_value is None else str(raw_value).strip()
    control = field_spec['control']

    if control == 'checkbox':
        return value.lower() in ('1', 'true', 'yes', 'on')

    if field_spec['option'] == 'ADMIN_PASSWORD':
        # Never send the current password back to the browser.
        return ''

    if field_spec.get('number_type') == 'optional_int' and value.upper() == 'NONE':
        return ''

    if field_spec.get('none_means_empty') and value.upper() == 'NONE':
        return ''

    return value


def build_select_choices(field_spec, current_value):
    """Offered choices, plus whatever the file already holds.

    A value set by hand, or by a newer version, must not silently vanish from
    the form the moment an operator saves.
    """
    choices = list(field_spec.get('choices', ()))
    choice_values = {value for value, _label in choices}
    if current_value and current_value not in choice_values:
        choices.append((current_value, f'Current: {current_value}'))
    return choices


def current_values(parser):
    values = {}
    for section_spec in CONFIG_FORM_SECTIONS:
        for field_spec in section_spec['fields']:
            section, option = field_spec['section'], field_spec['option']
            values[(section, option)] = parser.get(section, option, fallback='')
    return values


def render_sections(parser, form_values=None):
    """Build the form the admin page renders, from the file or a rejected submission."""
    form_values = form_values or {}
    sections = []

    for section_spec in CONFIG_FORM_SECTIONS:
        rendered_fields = []
        for field_spec in section_spec['fields']:
            section, option = field_spec['section'], field_spec['option']
            name = field_name(section, option)
            raw_value = form_values.get(name, parser.get(section, option, fallback=''))
            normalized_value = normalize_value(field_spec, raw_value)

            rendered_field = dict(field_spec)
            rendered_field['name'] = name
            rendered_field['id'] = name.lower()
            rendered_field['value'] = normalized_value
            rendered_field['checked'] = bool(normalized_value) if field_spec['control'] == 'checkbox' else False

            if field_spec['control'] == 'select':
                rendered_field['choices'] = build_select_choices(field_spec, normalized_value)

            rendered_fields.append(rendered_field)

        sections.append({
            'title': section_spec['title'],
            'description': section_spec.get('description'),
            'fields': rendered_fields,
        })

    return sections


def _bounded_number(field_spec, value, parse):
    parsed_value = parse(value)
    if 'min' in field_spec and parsed_value < field_spec['min']:
        raise ValueError(f'{field_spec["label"]} must be at least {field_spec["min"]}.')
    if 'max' in field_spec and parsed_value > field_spec['max']:
        raise ValueError(f'{field_spec["label"]} must be at most {field_spec["max"]}.')
    return str(parsed_value)


def coerce_value(field_spec, submitted_value, current_value):
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
            raise ValueError(f'{field_spec["label"]} is required.')
        return _bounded_number(field_spec, value, int if number_type == 'int' else float)

    if number_type == 'optional_int':
        return 'None' if value == '' else _bounded_number(field_spec, value, int)

    if field_spec.get('none_means_empty'):
        return value or 'None'

    return value


def collect_updates(form, parser):
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

            updates[key] = coerce_value(field_spec, submitted_value, existing[key])

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
