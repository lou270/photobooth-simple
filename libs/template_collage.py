import os
import cv2
import json
import base64
import logging
import tempfile
import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont

from libs import event
from libs.file_utils import FileUtils
from libs.template_schema import TemplateValidationError, validate_template

# Child of Kivy's logger so records land in the application log when Kivy is
# running, without importing Kivy: collage building must stay testable headless.
Logger = logging.getLogger('kivy.photobooth')


# Shipped in code so the booth always has at least one usable format: an empty or
# corrupted templates/ directory must not leave the operator with an application
# that refuses to start on site.
DEFAULT_TEMPLATE = {
    'name': 'Full Page',
    'description': 'Built-in fallback format: one photo, 10x15 cm',
    'page': {'width': 1800, 'height': 1200},
    'photos': [{'x': 90, 'y': 60, 'width': 1620, 'height': 1080}],
    'print_params': {'PageSize': 'w288h432', 'print-scaling': 'fit'},
}

# Every template, the shipped ones and the editor's, is laid out in pixels at
# 300 dpi: an 1800x1200 page is a 10x15 cm print. A booth set to a higher
# resolution multiplies the whole layout when it assembles, so a template never
# has to be redrawn for it.
TEMPLATE_DPI = 300


class TemplateCollage:
    """
    Collage class that loads configuration from JSON template files.
    """
    
    # Space between two lines of the same text, as a fraction of the font size.
    LINE_SPACING = 0.15

    def __init__(self, template_path=None, template=None, text_values=None, dpi=TEMPLATE_DPI):
        """
        Initialize the collage from a JSON template file.

        Args:
            template_path: Path to the JSON template file
            text_values: Callable returning what {event}, {date} and {time}
                stand for. Called at each assembly, so the date is the day the
                photo was taken rather than the day the booth started.
            dpi: Resolution the saved and printed collage is assembled at.
                The printed size does not change with it, only how sharp the
                file looks on a screen.
        """
        Logger.info('TemplateCollage: __init__(%s)', template_path or 'built-in')

        if template is None and template_path is None:
            raise ValueError('TemplateCollage requires either template_path or template')
        
        self._template_path = template_path
        self._module_dir = os.path.dirname(os.path.abspath(__file__))
        self._template_dir = (
            os.path.dirname(os.path.abspath(template_path)) if template_path
            else os.path.join(self._module_dir, '..', 'templates')
        )
        
        # Load template
        if template is None:
            # UTF-8 whatever the system says: template names carry accents.
            with open(template_path, 'r', encoding='utf-8') as f:
                template = json.load(f)

        # Validate on the way in as well as on the way out: a template can reach
        # the booth as a plain file, without ever going through the web editor.
        self._template = validate_template(template)
        
        # Cache template properties
        self._name = self._template.get('name', 'Unnamed Template')
        self._description = self._template.get('description', '')
        self._page_width = self._template['page']['width']
        self._page_height = self._template['page']['height']
        self._photos = self._template['photos']
        self._texts = self._template['texts']
        self._text_values = text_values or event.text_values
        self._scale = max(1, round(dpi / TEMPLATE_DPI))
        self._fonts = {}
        self._print_params = self._template.get('print_params', {})
        self._margin_percent = self._template.get('margin_percent', 5)
        self._duplicate_horizontal = self._template.get('duplicate_horizontal', False)
        self._duplicate_vertical = self._template.get('duplicate_vertical', False)
        
        # What is drawn, bottom first: the editor's own order for a designed
        # template, the historical one for a template that only has a
        # background and a foreground.
        self._stack = self._template['stack'] or self._legacy_stack()

        # Load dummy images for preview
        self._dummies = [
            os.path.join(self._module_dir, '../assets/icons/dummy0.png'),
            os.path.join(self._module_dir, '../assets/icons/dummy1.png'),
            os.path.join(self._module_dir, '../assets/icons/dummy2.png'),
            os.path.join(self._module_dir, '../assets/icons/dummy3.png')
        ]
        
        # Cache for preview image (generate once)
        self._preview_cache = None
        
        # Images at the size they are drawn at, keyed by that size: previews
        # are assembled at 300 dpi whatever the saved collage is assembled at.
        self._layer_cache = {}

    def _legacy_stack(self):
        """The drawing order of a template written before stacks existed.

        Background, photos, foreground, then texts over everything. The two
        images are marked so they keep behaving as they always did: the
        background replaces the page, and a foreground without transparency
        is laid over the photos at half strength.
        """
        page = {'x': 0, 'y': 0, 'width': self._page_width, 'height': self._page_height, 'opacity': 1}
        stack = []
        if self._template['background']:
            stack.append(dict(page, type='image', src=self._template['background'], legacy='background'))
        stack += [{'type': 'photo', 'index': index, 'opacity': 1} for index in range(len(self._photos))]
        if self._template['foreground']:
            stack.append(dict(page, type='image', src=self._template['foreground'], legacy='foreground'))
        stack += [{'type': 'text', 'index': index, 'opacity': 1} for index in range(len(self._texts))]
        return stack

    def get_name(self):
        """Return the template name."""
        return self._name
    
    def get_description(self):
        """Return the template description."""
        return self._description
    
    def get_photos_required(self):
        """Return the number of photos required."""
        return len(self._photos)
    
    def get_aspect_ratio(self):
        """
        Return the aspect ratio (width/height) of the first photo slot.
        Used for camera preview and capture.
        Returns 1.0 for square, >1.0 for landscape, <1.0 for portrait.
        """
        if len(self._photos) > 0:
            width = self._photos[0]['width']
            height = self._photos[0]['height']
            return width / height
        return 1.0
    
    def get_print_params(self):
        """Return the print parameters."""
        return dict(self._print_params)

    def uses_print_version(self):
        """Return True when printing needs the generated _print collage."""
        return self._duplicate_horizontal or self._duplicate_vertical

    def get_copies_per_sheet(self):
        """How many finished photos one printed sheet carries.

        A strip template prints twice across the sheet and is cut in two, so a
        guest who asked for one sheet walks away with two strips. The booth
        counts sheets, because that is what the printer and the paper budget
        count; what it shows the guest has to be what they will hold.
        """
        return (2 if self._duplicate_horizontal else 1) * (2 if self._duplicate_vertical else 1)
    
    def _decode_image(self, image_data, imread_flags=cv2.IMREAD_UNCHANGED):
        """
        Decode a layer from either base64 data or a file path.

        Args:
            image_data: Either a base64 data URI (data:image/png;base64,...) or a file name
            imread_flags: OpenCV imread flags (default: IMREAD_UNCHANGED to preserve alpha)

        Returns:
            Decoded image as numpy array, or None when it could not be read
        """
        if not image_data:
            return None

        if isinstance(image_data, str) and image_data.startswith('data:image'):
            try:
                encoded = image_data.split(',', 1)[1]
                nparr = np.frombuffer(base64.b64decode(encoded), np.uint8)
                image = cv2.imdecode(nparr, imread_flags)
            except Exception as e:
                Logger.error(f'Failed to decode base64 image: {e}')
                return None
            if image is None:
                Logger.error('Embedded image could not be decoded')
            return image

        # A file name, resolved against the template directory.
        path = os.path.join(self._template_dir, image_data)
        if not os.path.exists(path):
            Logger.warning(f'Image file not found: {path}')
            return None

        image = cv2.imread(path, imread_flags)
        if image is None:
            # imread returns None rather than raising; the old code then called
            # .copy() on it and turned a bad file into an AttributeError.
            Logger.warning(f'Image file could not be decoded: {path}')
        return image

    def _get_page_layer(self, image_data, imread_flags, layer, size):
        """Return a layer already scaled to where it is drawn, decoded and resized once.

        The source art is far larger than the page it is drawn on: the shipped
        full-page frame is 4370x2880 RGBA, 48 MB in memory, for an 1800x1200
        page. It used to be copied out of the cache and resized again on every
        single collage. Caching it at its drawn size removes both, and keeps
        the resident copy at that size instead of source size.

        A booth assembling at 600 dpi draws at two sizes, the preview and the
        collage, so it decodes each layer twice rather than keeping the source.
        """
        key = (layer, size)
        if key in self._layer_cache:
            return self._layer_cache[key]

        image = self._decode_image(image_data, imread_flags)
        if image is None:
            return None

        # 8-bit BGR or BGRA from here on, whatever the file held: a 16-bit or
        # greyscale PNG is a valid drawing, not a reason to lose the layer.
        if image.dtype == np.uint16:
            image = (image >> 8).astype(np.uint8)
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

        width, height = size
        if image.shape[1] != width or image.shape[0] != height:
            shrinking = image.shape[1] >= width and image.shape[0] >= height
            image = cv2.resize(image, (width, height),
                               interpolation=cv2.INTER_AREA if shrinking else cv2.INTER_LINEAR)

        self._layer_cache[key] = image
        return image

    def _layout(self, full_resolution):
        """Page size, photo slots, text boxes and stack at the resolution to assemble at."""
        scale = self._scale if full_resolution else 1
        if scale == 1:
            return (self._page_width, self._page_height), self._photos, self._texts, self._stack

        def scaled(box):
            if 'width' not in box:
                return box
            return dict(box, **{side: box[side] * scale for side in ('x', 'y', 'width', 'height')})

        page_size = (self._page_width * scale, self._page_height * scale)
        return (page_size, [scaled(photo) for photo in self._photos], [scaled(text) for text in self._texts],
                [scaled(entry) for entry in self._stack])
    
    def get_preview(self):
        """
        Generate a preview image using dummy photos.
        Cache the result to avoid regenerating on every call.
        
        Returns:
            Path to the generated preview image
        """
        # Return cached preview if already generated
        if self._preview_cache is not None:
            return self._preview_cache
        
        # Use dummy images for preview
        num_photos = self.get_photos_required()
        image_paths = [self._dummies[min(i, len(self._dummies) - 1)] for i in range(num_photos)]
        
        # Generate collage
        collage = self.assemble(image_paths, full_resolution=False)
        collage = FileUtils.resize(collage)
        
        # Dump to temp file. mkstemp hands back an open descriptor as well as a
        # path; leaving it open leaked one per template and, on Windows, stopped
        # write_image from replacing the file it had just created.
        handle, tmp_output = tempfile.mkstemp(suffix='.jpg')
        os.close(handle)
        FileUtils.write_image(tmp_output, collage)
        
        # Cache the result
        self._preview_cache = tmp_output
        return tmp_output
    
    def assemble(self, image_paths, output_path=None, for_print=False, photo_filter=None, full_resolution=True):
        """
        Assemble photos into a collage based on the template.
        Starts from a white page and draws the stack over it, bottom first:
        images, photos (cropped to their slot, clipped to the page) and texts.

        Args:
            image_paths: List of paths to input images
            output_path: Optional path to save the output
            for_print: If True, apply duplication for printing. If False (default), don't duplicate.
            photo_filter: Optional callable applied to each photo as it is read.
                Photos only: a frame or a logo that turned grey along with the
                faces would be a change the guest never asked for.
            full_resolution: False assembles at the template's own 300 dpi,
                for a collage that is only ever shown on the booth's screen.

        Returns:
            The assembled collage as a numpy array
        """
        Logger.info(f'TemplateCollage: assemble({len(image_paths)} images)')
        page_size, photos, texts, stack = self._layout(full_resolution)
        page_width, page_height = page_size

        canvas = np.full((page_height, page_width, 3), 255, dtype=np.uint8)

        # Texts next to each other in the stack are drawn in one pass: each
        # pass converts the whole page to Pillow and back.
        pending_texts = []
        for number, entry in enumerate(stack):
            if entry['type'] == 'text':
                pending_texts.append((texts[entry['index']], entry['opacity']))
                continue
            canvas = self._draw_texts(canvas, pending_texts)
            pending_texts = []

            if entry['type'] == 'photo':
                index = entry['index']
                if index < len(image_paths):
                    self._draw_photo(canvas, image_paths[index], photos[index], entry['opacity'], photo_filter)
            else:
                canvas = self._draw_image(canvas, entry, number)

        # Texts come last in a template written before stacks: a name printed
        # under a decoration nobody can read is a name the guest never sees.
        canvas = self._draw_texts(canvas, pending_texts)

        # Step 5: Save base collage (without duplication for web gallery)
        if output_path:
            FileUtils.write_image(output_path, canvas)
            
            # Create small preview
            small = FileUtils.resize(canvas)
            FileUtils.write_image(FileUtils.get_small_path(output_path), small)
        
        # Step 6: Apply duplication for printing if needed
        if for_print:
            if self._duplicate_horizontal:
                canvas = cv2.hconcat([canvas, canvas])
            if self._duplicate_vertical:
                canvas = cv2.vconcat([canvas, canvas])
            
            # Save print version if different from base
            if output_path and (self._duplicate_horizontal or self._duplicate_vertical):
                print_path = output_path.replace('.jpg', '_print.jpg')
                FileUtils.write_image(print_path, canvas)
                Logger.info(f'TemplateCollage: Saved print version to {print_path}')
        
        return canvas
    
    # --- texts --------------------------------------------------------------

    def _font(self, size, bold):
        key = (size, bold)
        font = self._fonts.get(key)
        if font is None:
            path = event.font_path(bold)
            font = ImageFont.truetype(str(path), size) if path else ImageFont.load_default(size)
            self._fonts[key] = font
        return font

    def _text_block_size(self, lines, font, size):
        ascent, descent = font.getmetrics()
        line_height = ascent + descent
        width = max(font.getlength(line) for line in lines)
        height = line_height * len(lines) + int(size * self.LINE_SPACING) * (len(lines) - 1)
        return width, height, line_height

    def _fit_font(self, lines, box, bold):
        """The largest font the lines fit in, searched rather than guessed.

        Font metrics do not scale linearly at small sizes, so a size computed
        from one measurement can overflow by a pixel or two; a bisection over
        whole sizes cannot.
        """
        low, high = 1, max(1, box['height'])
        while low < high:
            size = (low + high + 1) // 2
            width, height, _line = self._text_block_size(lines, self._font(size, bold), size)
            if width <= box['width'] and height <= box['height']:
                low = size
            else:
                high = size - 1
        return low

    def _draw_texts(self, canvas, texts):
        """Draw (box, opacity) pairs over the canvas, in order."""
        if not texts:
            return canvas

        try:
            values = self._text_values()
        except Exception as exc:
            # A broken provider must not cost the guest their print.
            Logger.error('TemplateCollage: text values unavailable: %s', exc)
            values = event.text_values()

        image = None
        for box, opacity in texts:
            content = event.fill_placeholders(box['text'], values).strip()
            if not content or opacity <= 0:
                continue
            lines = [line.strip() for line in content.splitlines()]

            if image is None:
                image = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))

            if opacity >= 1:
                self._draw_text_lines(ImageDraw.Draw(image), box, lines, (0, 0), box['color'])
                continue

            # Pillow draws text opaque whatever alpha the ink has, so a
            # see-through text is drawn as a mask and the colour poured
            # through it. The mask reaches past the box: glyphs are fitted to
            # it by their metrics, and accents or tails may still overhang.
            margin = box['height'] // 2
            left, top = max(0, box['x'] - margin), max(0, box['y'] - margin)
            right = min(image.width, box['x'] + box['width'] + margin)
            bottom = min(image.height, box['y'] + box['height'] + margin)
            mask = Image.new('L', (right - left, bottom - top), 0)
            self._draw_text_lines(ImageDraw.Draw(mask), box, lines, (left, top), 255)
            mask = mask.point(lambda value: round(value * opacity))
            image.paste(ImageColor.getrgb(box['color']), (left, top, right, bottom), mask)

        if image is None:
            return canvas
        return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)

    def _draw_text_lines(self, draw, box, lines, origin, fill):
        """Fit the lines to their box and draw them, `origin` being where `draw` starts on the page."""
        size = self._fit_font(lines, box, box['bold'])
        font = self._font(size, box['bold'])
        _width, block_height, line_height = self._text_block_size(lines, font, size)
        y = box['y'] - origin[1] + (box['height'] - block_height) // 2
        for line in lines:
            line_width = font.getlength(line)
            if box['align'] == 'left':
                x = box['x']
            elif box['align'] == 'right':
                x = box['x'] + box['width'] - line_width
            else:
                x = box['x'] + (box['width'] - line_width) / 2
            draw.text((x - origin[0], y), line, font=font, fill=fill, anchor='la')
            y += line_height + int(size * self.LINE_SPACING)

    # --- images and photos ----------------------------------------------------

    def _draw_image(self, canvas, entry, number):
        """Lay one image of the stack over the canvas, where the editor put it."""
        legacy = entry.get('legacy')
        if legacy == 'background':
            background = self._get_page_layer(entry['src'], cv2.IMREAD_COLOR, 'background',
                                              (canvas.shape[1], canvas.shape[0]))
            # Copy: photos are pasted into the canvas, and the cache is shared
            # with every later collage.
            return canvas if background is None else background.copy()

        name = legacy or f'stack{number}'
        layer = self._get_page_layer(entry['src'], cv2.IMREAD_UNCHANGED, name, (entry['width'], entry['height']))
        if layer is None:
            return canvas

        opacity = entry['opacity']
        if legacy == 'foreground' and layer.shape[2] == 3:
            # What a foreground without transparency has always done.
            opacity = 0.5
        self._blend(canvas, layer, entry['x'], entry['y'], opacity)
        return canvas

    def _draw_photo(self, canvas, image_path, spec, opacity, photo_filter):
        img = cv2.imread(image_path, cv2.IMREAD_COLOR)
        if img is None:
            Logger.warning(f'Could not load image: {image_path}')
            return

        if photo_filter is not None:
            img = photo_filter(img)

        # Cropped to the slot's shape, then clipped to the canvas.
        img_resized = FileUtils.resize_and_crop(img, (spec['height'], spec['width']))
        self._blend(canvas, img_resized, spec['x'], spec['y'], opacity)

    def _blend(self, canvas, layer, x, y, opacity):
        """Mix a BGR or BGRA layer into the canvas at (x, y), in place.

        Only the layer's own rectangle is touched, so a small decoration costs
        its size rather than the page's, and an opaque layer is a plain copy.
        """
        height = min(layer.shape[0], canvas.shape[0] - y)
        width = min(layer.shape[1], canvas.shape[1] - x)
        if height <= 0 or width <= 0 or opacity <= 0:
            return

        color = layer[:height, :width, :3]
        alpha = layer[:height, :width, 3] if layer.shape[2] == 4 else None
        region = canvas[y:y + height, x:x + width]
        if alpha is None and opacity >= 1:
            region[:] = color
            return

        strength = round(255 * opacity)
        if alpha is None:
            weight = np.full((height, width), strength, dtype=np.uint8)
        elif strength < 255:
            weight = cv2.multiply(alpha, strength, scale=1 / 255)
        else:
            weight = alpha
        # 8-bit, saturating and vectorised by OpenCV: a 16-bit or float copy of
        # a 600 dpi page is both slower and more memory than a Pi should spend.
        weight = cv2.cvtColor(weight, cv2.COLOR_GRAY2BGR)
        region[:] = cv2.add(cv2.multiply(color, weight, scale=1 / 255),
                            cv2.multiply(region, cv2.bitwise_not(weight), scale=1 / 255))


def load_templates(templates_dir='templates', text_values=None, dpi=TEMPLATE_DPI):
    """
    Load all template files from a directory.

    Args:
        templates_dir: Directory containing template JSON files
        text_values: Callable handed to every template, see TemplateCollage
        dpi: Resolution collages are assembled at, see TemplateCollage

    Returns:
        List of TemplateCollage instances
    """
    templates = []
    module_dir = os.path.dirname(os.path.abspath(__file__))
    templates_path = os.path.join(module_dir, '..', templates_dir)
    
    if os.path.isdir(templates_path):
        filenames = sorted(os.listdir(templates_path))
    else:
        Logger.warning(f'Templates directory not found: {templates_path}')
        filenames = []
    
    # Load all JSON files
    for filename in filenames:
        if filename.endswith('.json'):
            template_path = os.path.join(templates_path, filename)
            try:
                template = TemplateCollage(template_path, text_values=text_values, dpi=dpi)
                templates.append(template)
                Logger.info(f'Loaded template: {template.get_name()} from {filename}')
            except TemplateValidationError as e:
                Logger.error(f'Rejected template {filename}: {e}')
            except Exception as e:
                Logger.error(f'Error loading template {filename}: {e}')

    # Guarantee at least one usable format, so callers never have to handle an
    # empty list and the booth always starts.
    if not templates:
        Logger.warning('TemplateCollage: no usable template found, using the built-in fallback')
        templates.append(TemplateCollage(template=DEFAULT_TEMPLATE, text_values=text_values, dpi=dpi))

    return templates
