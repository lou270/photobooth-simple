"""Photo filters, offered once the collage is on screen.

Each filter takes a BGR image and returns the filtered result. None of them
modifies its input, except that `color` returns the very same array, since
there is nothing to do; callers that need to keep the original should pass a
copy.
"""

import logging

import cv2
import numpy as np

from libs.file_utils import FileUtils

Logger = logging.getLogger('kivy.photobooth')

DEFAULT_FILTER = 'color'


def _color(image):
    """No change: the photo as the camera saw it."""
    return image


def _black_and_white(image):
    """Black and white, with the contrast lifted locally so faces do not go flat."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return cv2.cvtColor(clahe.apply(gray), cv2.COLOR_GRAY2BGR)


def _sepia(image):
    sepia_matrix = np.array([
        [0.272, 0.534, 0.131],
        [0.349, 0.686, 0.168],
        [0.393, 0.769, 0.189],
    ])
    return np.clip(cv2.transform(image, sepia_matrix), 0, 255).astype(np.uint8)


def _glam(image):
    """More saturation, more contrast."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] *= 1.3
    hsv[:, :, 2] *= 1.1
    result = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR)
    return cv2.convertScaleAbs(result, alpha=1.2, beta=10)


# Order matters: this is the order the filter cards appear in. Kept short on
# purpose: every look must be told apart at thumbnail size, and all the cards
# must fit on screen without scrolling.
FILTERS = (
    {'key': 'color', 'name': 'Color', 'apply': _color},
    {'key': 'bw', 'name': 'B&W', 'apply': _black_and_white},
    {'key': 'sepia', 'name': 'Sepia', 'apply': _sepia},
    {'key': 'glam', 'name': 'Glam', 'apply': _glam},
)

_BY_KEY = {definition['key']: definition for definition in FILTERS}


def filter_keys():
    return tuple(definition['key'] for definition in FILTERS)


def apply_filter(image, key):
    """Apply the named filter, or return the image untouched if it is unknown."""
    definition = _BY_KEY.get(key)
    if definition is None:
        Logger.warning('filters: unknown filter %r, leaving the photo unchanged', key)
        return image
    return definition['apply'](image)


def apply_filter_to_file(path, filter_key, small_path=None, small_scale=0.3):
    """Rewrite a capture with the filter applied, and its small copy with it.

    The captures are saved beside the collage and shown in the online gallery,
    so a guest who picked black and white has to find black and white there too.
    Returns False when the file could not be read.
    """
    image = cv2.imread(path)
    if image is None:
        Logger.warning('apply_filter_to_file: could not read %s', path)
        return False

    filtered = apply_filter(image, filter_key)
    FileUtils.write_image(path, filtered)
    if small_path:
        FileUtils.write_image(small_path, cv2.resize(filtered, (0, 0), fx=small_scale, fy=small_scale))
    return True
