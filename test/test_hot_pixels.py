import sys
import threading
from pathlib import Path

import cv2
import numpy as np

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.device_utils import Gphoto2Camera
from libs.imaging.hot_pixels import find_hot_pixels, remove_hot_pixels

# Where the synthetic hot pixels sit: 2x2 blobs, as a Canon JPEG spreads them.
HOT_SPOTS = ((40, 50), (120, 200), (180, 90), (60, 260))


def _dark_scene(height=240, width=320):
    """A dim, slightly noisy scene: the kind of area hot pixels show up in."""
    rng = np.random.default_rng(7)
    image = np.full((height, width, 3), 35, dtype=np.int16)
    image += rng.integers(-6, 7, image.shape, dtype=np.int16)
    return np.clip(image, 0, 255).astype(np.uint8)


def _with_hot_pixels(image):
    image = image.copy()
    for y, x in HOT_SPOTS:
        image[y:y + 2, x:x + 2] = (215, 205, 200)
    return image


def test_hot_pixels_are_painted_over():
    clean = _dark_scene()
    result = remove_hot_pixels(_with_hot_pixels(clean))

    for y, x in HOT_SPOTS:
        assert result[y:y + 2, x:x + 2].max() < 60


def test_a_coloured_hot_pixel_is_painted_over_too():
    image = _dark_scene()
    image[100, 100] = (60, 70, 230)          # a red one, as some sensors have

    assert remove_hot_pixels(image)[100, 100].max() < 60


def test_a_scene_without_hot_pixels_comes_back_untouched():
    clean = _dark_scene()

    assert np.array_equal(remove_hot_pixels(clean), clean)


def test_thin_lines_and_edges_are_left_alone():
    """What a plain median filter gets wrong: strands of hair, catchlights, outlines."""
    image = _dark_scene()
    image[30, 20:300] = 230                  # a one-pixel bright line
    image[150:240, 160:320] = 220            # a bright area and its edge
    image[60:67, 100:107] = 240              # a catchlight: larger than any hot pixel blob

    assert np.array_equal(remove_hot_pixels(image), image)


def test_the_input_image_is_not_modified():
    image = _with_hot_pixels(_dark_scene())
    before = image.copy()

    remove_hot_pixels(image)

    assert np.array_equal(image, before)


def test_hot_pixels_on_the_border_of_the_frame_are_painted_over():
    image = _dark_scene()
    image[0:2, 0:2] = 220
    image[-2:, -2:] = 220

    result = remove_hot_pixels(image)

    assert result[0:2, 0:2].max() < 60
    assert result[-2:, -2:].max() < 60


# --- the DSLR applies it to what it hands over -----------------------------

class _CameraFile:
    def __init__(self, image):
        # PNG, not JPEG: lossless, so the hot pixels arrive exactly as drawn.
        self.encoded = cv2.imencode('.png', image)[1].tobytes()

    def get_data(self, auto_clean=True):
        return self.encoded


def _bare_dslr(image, hot_pixel_filter):
    camera = Gphoto2Camera.__new__(Gphoto2Camera)
    camera._camera_lock = threading.Lock()
    camera.dslr_liveview_params = {}
    camera.dslr_capture_params = {}
    camera._hot_pixel_filter = hot_pixel_filter

    class FakeInstance:
        def capture_image(self):
            return _CameraFile(image)

    camera._instance = FakeInstance()
    return camera


def _captured(tmp_path, hot_pixel_filter):
    written = {}
    camera = _bare_dslr(_with_hot_pixels(_dark_scene()), hot_pixel_filter)
    camera._write_capture = lambda name, image: written.setdefault('image', image)
    camera.capture(str(tmp_path / 'capture-0.jpg'))
    return written['image']


def test_the_dslr_cleans_its_photos_when_asked(tmp_path):
    photo = _captured(tmp_path, hot_pixel_filter=True)

    for y, x in HOT_SPOTS:
        assert photo[y:y + 2, x:x + 2].max() < 60


def test_the_dslr_leaves_its_photos_alone_by_default(tmp_path):
    photo = _captured(tmp_path, hot_pixel_filter=False)

    y, x = HOT_SPOTS[0]
    assert photo[y:y + 2, x:x + 2].min() > 190


def test_a_dslr_built_without_the_constructor_has_the_filter_off():
    """The preview tests build cameras with __new__; the default has to hold there."""
    camera = Gphoto2Camera.__new__(Gphoto2Camera)
    image = _with_hot_pixels(_dark_scene())

    assert camera._clean_frame(image) is image
