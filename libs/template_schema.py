"""Validation for photo layout templates.

Templates are the one structured input the booth accepts from outside itself:
they come from the local editor today, and from a file handed over by an
operator tomorrow. Everything in a template ends up driving image allocation
and pixel writes, so an unchecked page size or photo rectangle is an easy way
to exhaust memory or produce garbage prints. Validation happens here, once,
and returns a normalised template with unknown keys dropped.
"""

import base64
import binascii
import re

# A 10x15 cm page at 300 dpi is about 2.1 Mpx; the ceiling leaves room for
# large or duplicated layouts while keeping a single canvas well under the
# memory a Raspberry Pi can spare.
MAX_PAGE_SIDE = 20000
MAX_PAGE_PIXELS = 40_000_000
MAX_PHOTOS = 12
MAX_NAME_LENGTH = 80
MAX_DESCRIPTION_LENGTH = 300
MAX_PRINT_PARAMS = 20
MAX_PRINT_PARAM_LENGTH = 120
MAX_EMBEDDED_IMAGE_BYTES = 12 * 1024 * 1024

DATA_URI_PATTERN = re.compile(r'^data:image/(png|jpeg|jpg|webp);base64,(.+)$', re.IGNORECASE | re.DOTALL)
ASSET_FILENAME_PATTERN = re.compile(r'^[A-Za-z0-9._-]+\.(png|jpe?g|webp)$', re.IGNORECASE)

LAYER_KEYS = ('background', 'foreground')


class TemplateValidationError(ValueError):
    """Raised with an operator-readable reason when a template is rejected."""


def _require_int(value, field, minimum=None, maximum=None):
    # bool is an int subclass; accepting it here would silently turn True into 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TemplateValidationError(f'{field} must be an integer')
    if minimum is not None and value < minimum:
        raise TemplateValidationError(f'{field} must be at least {minimum}')
    if maximum is not None and value > maximum:
        raise TemplateValidationError(f'{field} must be at most {maximum}')
    return value


def _validate_page(page):
    if not isinstance(page, dict):
        raise TemplateValidationError('page must be an object')

    width = _require_int(page.get('width'), 'page.width', minimum=1, maximum=MAX_PAGE_SIDE)
    height = _require_int(page.get('height'), 'page.height', minimum=1, maximum=MAX_PAGE_SIDE)

    if width * height > MAX_PAGE_PIXELS:
        raise TemplateValidationError(
            f'page is {width}x{height} pixels, above the {MAX_PAGE_PIXELS} pixel limit'
        )

    return {'width': width, 'height': height}


def _validate_photos(photos, page):
    if not isinstance(photos, list) or not photos:
        raise TemplateValidationError('photos must be a non-empty list')
    if len(photos) > MAX_PHOTOS:
        raise TemplateValidationError(f'a template cannot hold more than {MAX_PHOTOS} photos')

    validated = []
    for index, photo in enumerate(photos):
        if not isinstance(photo, dict):
            raise TemplateValidationError(f'photos[{index}] must be an object')

        x = _require_int(photo.get('x'), f'photos[{index}].x', minimum=0, maximum=page['width'])
        y = _require_int(photo.get('y'), f'photos[{index}].y', minimum=0, maximum=page['height'])
        width = _require_int(photo.get('width'), f'photos[{index}].width', minimum=1, maximum=page['width'])
        height = _require_int(photo.get('height'), f'photos[{index}].height', minimum=1, maximum=page['height'])

        # Slots must fit: assemble() would otherwise silently clip them, and the
        # printed result would not match what the editor showed.
        if x + width > page['width'] or y + height > page['height']:
            raise TemplateValidationError(f'photos[{index}] does not fit inside the page')

        validated.append({'x': x, 'y': y, 'width': width, 'height': height})

    return validated


def _validate_layer(value, field):
    """A background or foreground: absent, embedded base64, or a plain filename."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise TemplateValidationError(f'{field} must be a string')

    value = value.strip()
    if not value or value.upper() == 'NONE':
        return None

    if value.lower().startswith('data:'):
        match = DATA_URI_PATTERN.match(value)
        if not match:
            raise TemplateValidationError(f'{field} must be a base64 PNG, JPEG or WebP data URI')
        try:
            decoded = base64.b64decode(match.group(2), validate=True)
        except (binascii.Error, ValueError):
            raise TemplateValidationError(f'{field} is not valid base64') from None
        if not decoded:
            raise TemplateValidationError(f'{field} is empty')
        if len(decoded) > MAX_EMBEDDED_IMAGE_BYTES:
            raise TemplateValidationError(
                f'{field} is {len(decoded)} bytes, above the {MAX_EMBEDDED_IMAGE_BYTES} byte limit'
            )
        return value

    # Anything else is resolved against the templates directory, so it must be a
    # bare filename: no separators, no traversal, no absolute path.
    if not ASSET_FILENAME_PATTERN.match(value):
        raise TemplateValidationError(
            f'{field} must be an embedded image or a plain image filename, got {value!r}'
        )
    return value


def _validate_print_params(print_params):
    if print_params is None:
        return {}
    if not isinstance(print_params, dict):
        raise TemplateValidationError('print_params must be an object')
    if len(print_params) > MAX_PRINT_PARAMS:
        raise TemplateValidationError(f'print_params cannot hold more than {MAX_PRINT_PARAMS} entries')

    validated = {}
    for key, value in print_params.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise TemplateValidationError('print_params keys and values must be strings')
        if len(key) > MAX_PRINT_PARAM_LENGTH or len(value) > MAX_PRINT_PARAM_LENGTH:
            raise TemplateValidationError(
                f'print_params entries must be at most {MAX_PRINT_PARAM_LENGTH} characters'
            )
        validated[key] = value

    return validated


def _validate_text(value, field, max_length, required=False):
    if value is None:
        if required:
            raise TemplateValidationError(f'{field} is required')
        return ''
    if not isinstance(value, str):
        raise TemplateValidationError(f'{field} must be a string')

    value = value.strip()
    if required and not value:
        raise TemplateValidationError(f'{field} is required')
    if len(value) > max_length:
        raise TemplateValidationError(f'{field} must be at most {max_length} characters')
    return value


def validate_template(data):
    """Return a normalised copy of `data`, or raise TemplateValidationError."""
    if not isinstance(data, dict):
        raise TemplateValidationError('template must be an object')

    page = _validate_page(data.get('page'))
    margin_percent = data.get('margin_percent', 5)
    if isinstance(margin_percent, bool) or not isinstance(margin_percent, (int, float)):
        raise TemplateValidationError('margin_percent must be a number')
    if not 0 <= margin_percent <= 50:
        raise TemplateValidationError('margin_percent must be between 0 and 50')

    template = {
        'name': _validate_text(data.get('name'), 'name', MAX_NAME_LENGTH, required=True),
        'description': _validate_text(data.get('description'), 'description', MAX_DESCRIPTION_LENGTH),
        'page': page,
        'photos': _validate_photos(data.get('photos'), page),
        'print_params': _validate_print_params(data.get('print_params')),
        'margin_percent': margin_percent,
        'duplicate_horizontal': bool(data.get('duplicate_horizontal', False)),
        'duplicate_vertical': bool(data.get('duplicate_vertical', False)),
    }

    for key in LAYER_KEYS:
        template[key] = _validate_layer(data.get(key), key)

    return template
