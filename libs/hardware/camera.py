import logging
import threading

from libs.file_utils import FileUtils

# Child of Kivy's logger so records land in the application log when Kivy is
# running, without importing Kivy here: this package must stay headless.
Logger = logging.getLogger('kivy.photobooth')


class Camera:
    """Contract implemented by every capture backend.

    The application never learns which hardware is connected: it asks for a
    preview frame and for a capture, and the backend decides how to produce
    them. `FakeCamera` implements the same contract without any hardware.
    """

    _instance = None

    # --- capabilities ----------------------------------------------------

    def get_preview_fps(self):
        """Refresh rate the preview widget should aim for."""
        return 30

    def has_physical_flash(self):
        """True when the hardware fires its own flash, so the ring LED stays off."""
        return False

    def is_healthy(self):
        return self._instance is not None

    # --- preview ---------------------------------------------------------

    def get_preview_frame_id(self):
        """Value changing on every new frame, so the UI can skip redundant redraws."""
        return 0

    def get_preview(self, aspect_ratio=None, zoom=None):
        raise NotImplementedError

    # --- capture ---------------------------------------------------------

    def capture(self, output_name, aspect_ratio=None, zoom=None, flash_fn=None):
        raise NotImplementedError

    def close(self):
        pass

    # --- shared helpers --------------------------------------------------

    def _crop_to_aspect_ratio(self, image, aspect_ratio):
        """Centre-crop to the target width/height ratio (1.0 square, >1 landscape)."""
        if aspect_ratio is None:
            return image

        height, width, _ = image.shape
        current_ratio = width / height

        if abs(current_ratio - aspect_ratio) < 0.01:
            return image

        if current_ratio > aspect_ratio:
            new_width = int(height * aspect_ratio)
            left = (width - new_width) // 2
            return image[:, left:left + new_width]

        new_height = int(width / aspect_ratio)
        top = (height - new_height) // 2
        return image[top:top + new_height, :]

    # CALIBRATION is the (zoom, offset_x, offset_y) triple produced by
    # tools/calibrate_zoom.py on a hybrid rig, where preview and capture come
    # from two cameras with different fields of view. The tool stores a single
    # factor and decides from its value which side has to be zoomed in:
    #     zoom > 1  ->  the preview is too wide, zoom the preview by `zoom`
    #     zoom < 1  ->  the capture is too wide, zoom the capture by `1 / zoom`
    # Offsets are passed through unchanged on both sides, exactly as the tool
    # applies them while the operator validates the overlay on screen.

    @staticmethod
    def _apply_preview_zoom(image, zoom):
        if not zoom or zoom[0] <= 1.0:
            return image
        return FileUtils.zoom(image, zoom)

    @staticmethod
    def _apply_capture_zoom(image, zoom):
        if not zoom or zoom[0] >= 1.0:
            return image
        return FileUtils.zoom(image, (1.0 / zoom[0], zoom[1], zoom[2]))

    def _write_capture(self, output_name, image):
        """Write the capture, then build its small preview off the capture path."""
        FileUtils.write_image(output_name, image)
        threading.Thread(
            target=self._write_small_preview,
            args=(image.copy(), output_name),
            name='photobooth-small-preview',
            daemon=True,
        ).start()

    def _write_small_preview(self, image, output_name):
        try:
            FileUtils.write_image(FileUtils.get_small_path(output_name), FileUtils.resize(image))
        except Exception as e:
            Logger.error('Camera: could not create small preview for %s: %s', output_name, e)
