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
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def _black_and_white_glam(image):
    """Black and white with enhanced contrast and subtle skin smoothing."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    smoothed = cv2.bilateralFilter(enhanced, d=5, sigmaColor=50, sigmaSpace=50)
    return cv2.cvtColor(smoothed, cv2.COLOR_GRAY2BGR)


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


def _vintage(image):
    """Reduced saturation with warm tones."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] *= 0.7
    result = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR)
    result[:, :, 0] = np.clip(result[:, :, 0] * 0.9, 0, 255)   # less blue
    result[:, :, 2] = np.clip(result[:, :, 2] * 1.1, 0, 255)   # more red
    return result.astype(np.uint8)


def _warm_glow(image):
    """Golden hour: orange cast, a little more saturation and brightness."""
    result = image.astype(np.float32)
    result[:, :, 0] = np.clip(result[:, :, 0] * 0.85, 0, 255)
    result[:, :, 1] = np.clip(result[:, :, 1] * 1.05, 0, 255)
    result[:, :, 2] = np.clip(result[:, :, 2] * 1.15, 0, 255)

    hsv = cv2.cvtColor(result.astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.2, 0, 255)
    hsv[:, :, 2] = np.clip(hsv[:, :, 2] * 1.05, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def _cool_tone(image):
    """Cinematic blue cast with slightly more contrast."""
    result = image.astype(np.float32)
    result[:, :, 0] = np.clip(result[:, :, 0] * 1.15, 0, 255)
    result[:, :, 1] = np.clip(result[:, :, 1] * 1.05, 0, 255)
    result[:, :, 2] = np.clip(result[:, :, 2] * 0.9, 0, 255)
    return cv2.convertScaleAbs(result, alpha=1.1, beta=-5)


def _soft_focus(image):
    """Dreamy: edge-preserving smoothing, a glow, a touch more brightness."""
    smoothed = cv2.bilateralFilter(image, d=9, sigmaColor=75, sigmaSpace=75)
    result = cv2.addWeighted(smoothed, 0.6, image, 0.4, 0)
    blurred = cv2.GaussianBlur(result, (21, 21), 0)
    glow = cv2.addWeighted(result, 0.85, blurred, 0.15, 0)

    hsv = cv2.cvtColor(glow, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 2] = np.clip(hsv[:, :, 2] * 1.08, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def _retro_70s(image):
    """Faded contrast with a yellow-orange cast."""
    faded = cv2.convertScaleAbs(image, alpha=0.85, beta=15)
    result = faded.astype(np.float32)
    result[:, :, 0] = np.clip(result[:, :, 0] * 0.88, 0, 255)
    result[:, :, 1] = np.clip(result[:, :, 1] * 1.08, 0, 255)
    result[:, :, 2] = np.clip(result[:, :, 2] * 1.12, 0, 255)

    hsv = cv2.cvtColor(result.astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 0.85, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def _pastel(image):
    """Bright, desaturated, washed with white."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 2] = np.clip(hsv[:, :, 2] * 1.25, 0, 255)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 0.5, 0, 255)
    result = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    white_overlay = np.full_like(result, 255)
    return cv2.addWeighted(result, 0.75, white_overlay, 0.25, 0)


def _polaroid(image):
    """Instant camera look: faded, slightly cool, vignetted."""
    faded = cv2.convertScaleAbs(image, alpha=0.9, beta=10)
    result = faded.astype(np.float32)
    result[:, :, 0] = np.clip(result[:, :, 0] * 1.05, 0, 255)
    result[:, :, 1] = np.clip(result[:, :, 1] * 0.98, 0, 255)
    result[:, :, 2] = np.clip(result[:, :, 2] * 1.02, 0, 255)

    hsv = cv2.cvtColor(result.astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 0.75, 0, 255)
    result = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    rows, cols = result.shape[:2]
    kernel = cv2.getGaussianKernel(rows, rows / 2.5) * cv2.getGaussianKernel(cols, cols / 2.5).T
    mask = np.dstack([kernel / kernel.max()] * 3)
    vignette = (result * mask).astype(np.uint8)
    return cv2.addWeighted(result, 0.3, vignette, 0.7, 0)


# Order matters: this is the order the filter cards appear in.
FILTERS = (
    {'key': 'color', 'name': 'Color', 'apply': _color},
    {'key': 'bw', 'name': 'B&W', 'apply': _black_and_white},
    {'key': 'bwglam', 'name': 'B&W Glam', 'apply': _black_and_white_glam},
    {'key': 'sepia', 'name': 'Sepia', 'apply': _sepia},
    {'key': 'glam', 'name': 'Glam', 'apply': _glam},
    {'key': 'vintage', 'name': 'Vintage', 'apply': _vintage},
    {'key': 'warmglow', 'name': 'Warm Glow', 'apply': _warm_glow},
    {'key': 'cooltone', 'name': 'Cool Tone', 'apply': _cool_tone},
    {'key': 'softfocus', 'name': 'Soft Focus', 'apply': _soft_focus},
    {'key': 'retro70s', 'name': 'Retro 70s', 'apply': _retro_70s},
    {'key': 'pastel', 'name': 'Pastel', 'apply': _pastel},
    {'key': 'polaroid', 'name': 'Polaroid', 'apply': _polaroid},
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
