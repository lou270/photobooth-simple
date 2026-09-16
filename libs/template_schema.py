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
import json
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
# All the images one template embeds, together: the web server refuses a
# request above 32 MB, and base64 grows the bytes by a third on the way.
MAX_EMBEDDED_TOTAL_BYTES = 22 * 1024 * 1024
MAX_TEXTS = 10
MAX_TEXT_LENGTH = 200
TEXT_ALIGNMENTS = ('left', 'center', 'right')
COLOR_PATTERN = re.compile(r'^#[0-9a-fA-F]{6}$')
# Every level of a designed template is an image, a photo or a text, so this
# bounds how many full compositing passes one collage can cost the booth.
MAX_STACK_ENTRIES = 40
STACK_TYPES = ('image', 'photo', 'text')
# The editor's own description of a design, kept so it can be opened again.
# It holds shapes and references to assets, never pixels.
MAX_DESIGN_BYTES = 2 * 1024 * 1024

DATA_URI_PATTERN = re.compile(r'^data:image/(png|jpeg|jpg|webp);base64,(.+)$', re.IGNORECASE | re.DOTALL)
# A bare file name next to the templates, or one in their assets/ folder.
ASSET_FILENAME_PATTERN = re.compile(r'^(?:assets/)?[A-Za-z0-9._-]+\.(png|jpe?g|webp)$', re.IGNORECASE)

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


def _validate_texts(texts, page):
    """Boxes of text drawn over the collage, placeholders included.

    The text is fitted to its box when the collage is built, so a box carries a
    place and a look but no font size: an event name twice as long as the one
    the template was drawn for shrinks instead of running off the sheet.
    """
    if texts is None:
        return []
    if not isinstance(texts, list):
        raise TemplateValidationError('texts must be a list')
    if len(texts) > MAX_TEXTS:
        raise TemplateValidationError(f'a template cannot hold more than {MAX_TEXTS} texts')

    validated = []
    for index, text in enumerate(texts):
        field = f'texts[{index}]'
        if not isinstance(text, dict):
            raise TemplateValidationError(f'{field} must be an object')

        x = _require_int(text.get('x'), f'{field}.x', minimum=0, maximum=page['width'])
        y = _require_int(text.get('y'), f'{field}.y', minimum=0, maximum=page['height'])
        width = _require_int(text.get('width'), f'{field}.width', minimum=1, maximum=page['width'])
        height = _require_int(text.get('height'), f'{field}.height', minimum=1, maximum=page['height'])
        if x + width > page['width'] or y + height > page['height']:
            raise TemplateValidationError(f'{field} does not fit inside the page')

        content = text.get('text', '')
        if not isinstance(content, str):
            raise TemplateValidationError(f'{field}.text must be a string')
        if len(content) > MAX_TEXT_LENGTH:
            raise TemplateValidationError(f'{field}.text must be at most {MAX_TEXT_LENGTH} characters')

        color = text.get('color', '#000000')
        if not isinstance(color, str) or not COLOR_PATTERN.match(color):
            raise TemplateValidationError(f'{field}.color must be a #rrggbb colour')

        align = text.get('align', 'center')
        if align not in TEXT_ALIGNMENTS:
            raise TemplateValidationError(f'{field}.align must be one of {", ".join(TEXT_ALIGNMENTS)}')

        validated.append({
            'x': x, 'y': y, 'width': width, 'height': height,
            'text': content,
            'color': color.lower(),
            'align': align,
            'bold': bool(text.get('bold', False)),
        })

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
    # bare filename, or one inside assets/: no other separator, no traversal,
    # no absolute path.
    if not ASSET_FILENAME_PATTERN.match(value) or '..' in value.split('/'):
        raise TemplateValidationError(
            f'{field} must be an embedded image or a plain image filename, got {value!r}'
        )
    return value


def _embedded_bytes(value):
    """Decoded size of an embedded image, 0 for a file name or no image."""
    if not value or not value.lower().startswith('data:'):
        return 0
    encoded = value.split(',', 1)[1]
    return len(encoded) * 3 // 4


def _validate_opacity(value, field):
    if value is None:
        return 1
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TemplateValidationError(f'{field} must be a number')
    if not 0 <= value <= 1:
        raise TemplateValidationError(f'{field} must be between 0 and 1')
    return value


def _validate_stack(stack, page, photos, texts):
    """The order the booth draws a designed template in, bottom first.

    Each entry is a flattened image, one photo slot or one text box. Photos
    and texts keep their geometry in `photos` and `texts`, which the rest of
    the booth reads; the stack only says when each is drawn and how opaque.
    Every photo and every text must be drawn exactly once: a slot left out
    would be a guest's photo taken and never printed.
    """
    if stack is None:
        return None
    if not isinstance(stack, list):
        raise TemplateValidationError('stack must be a list')
    if len(stack) > MAX_STACK_ENTRIES:
        raise TemplateValidationError(f'stack cannot hold more than {MAX_STACK_ENTRIES} entries')

    validated = []
    placed = {'photo': [], 'text': []}
    for index, entry in enumerate(stack):
        field = f'stack[{index}]'
        if not isinstance(entry, dict):
            raise TemplateValidationError(f'{field} must be an object')

        kind = entry.get('type')
        if kind not in STACK_TYPES:
            raise TemplateValidationError(f'{field}.type must be one of {", ".join(STACK_TYPES)}')
        opacity = _validate_opacity(entry.get('opacity'), f'{field}.opacity')

        if kind == 'image':
            src = _validate_layer(entry.get('src'), f'{field}.src')
            if src is None:
                raise TemplateValidationError(f'{field}.src is required')
            x = _require_int(entry.get('x'), f'{field}.x', minimum=0, maximum=page['width'])
            y = _require_int(entry.get('y'), f'{field}.y', minimum=0, maximum=page['height'])
            width = _require_int(entry.get('width'), f'{field}.width', minimum=1, maximum=page['width'])
            height = _require_int(entry.get('height'), f'{field}.height', minimum=1, maximum=page['height'])
            if x + width > page['width'] or y + height > page['height']:
                raise TemplateValidationError(f'{field} does not fit inside the page')
            validated.append({
                'type': 'image', 'src': src,
                'x': x, 'y': y, 'width': width, 'height': height,
                'opacity': opacity,
            })
            continue

        boxes = photos if kind == 'photo' else texts
        position = _require_int(entry.get('index'), f'{field}.index', minimum=0, maximum=max(0, len(boxes) - 1))
        if position >= len(boxes):
            raise TemplateValidationError(f'{field}.index points to no {kind}')
        placed[kind].append(position)
        validated.append({'type': kind, 'index': position, 'opacity': opacity})

    for kind, boxes in (('photo', photos), ('text', texts)):
        if sorted(placed[kind]) != list(range(len(boxes))):
            raise TemplateValidationError(f'stack must draw every {kind} exactly once')

    return validated


def _validate_design(design):
    if design is None:
        return None
    if not isinstance(design, dict):
        raise TemplateValidationError('design must be an object')
    try:
        encoded = json.dumps(design, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        raise TemplateValidationError('design must be plain JSON') from None
    if len(encoded.encode('utf-8')) > MAX_DESIGN_BYTES:
        raise TemplateValidationError(f'design is above the {MAX_DESIGN_BYTES} byte limit')
    # A round trip, so what is stored is exactly what was checked.
    return json.loads(encoded)


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
        'texts': _validate_texts(data.get('texts'), page),
        'print_params': _validate_print_params(data.get('print_params')),
        'margin_percent': margin_percent,
        'duplicate_horizontal': bool(data.get('duplicate_horizontal', False)),
        'duplicate_vertical': bool(data.get('duplicate_vertical', False)),
    }

    for key in LAYER_KEYS:
        template[key] = _validate_layer(data.get(key), key)

    template['stack'] = _validate_stack(data.get('stack'), page, template['photos'], template['texts'])
    if template['stack'] is not None and (template['background'] or template['foreground']):
        # Two descriptions of the same drawing would leave the booth guessing
        # which one the editor meant.
        raise TemplateValidationError('a template with a stack puts its images in it, not in background or foreground')
    template['design'] = _validate_design(data.get('design'))

    images = [template[key] for key in LAYER_KEYS]
    images += [entry['src'] for entry in template['stack'] or () if entry['type'] == 'image']
    total = sum(_embedded_bytes(image) for image in images)
    if total > MAX_EMBEDDED_TOTAL_BYTES:
        raise TemplateValidationError(
            f'embedded images add up to {total} bytes, above the {MAX_EMBEDDED_TOTAL_BYTES} byte limit'
        )

    return template
