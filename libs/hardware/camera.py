import logging

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
        """Release the hardware. False when it could not be freed safely."""
        return True

    # How long a preview thread is given to leave its driver before close()
    # gives up. Same reasoning as the capture thread in PhotoboothApp: freeing a
    # handle a thread is blocked inside segfaults the process instead of
    # raising, so a thread that does not come back means this device can never
    # be released, only abandoned to a restart.
    PREVIEW_RELEASE_TIMEOUT_SECONDS = 5

    def _release_preview_thread(self):
        """Stop the preview thread. False when it is still inside the driver."""
        self._preview_stop = True
        thread = getattr(self, '_preview_thread', None)
        if thread is None or not thread.is_alive():
            return True

        thread.join(self.PREVIEW_RELEASE_TIMEOUT_SECONDS)
        if thread.is_alive():
            Logger.error(
                '%s: preview thread still inside the driver after %ss, leaving the device '
                'open rather than freeing it underneath a running call',
                type(self).__name__, self.PREVIEW_RELEASE_TIMEOUT_SECONDS,
            )
            return False

        self._preview_thread = None
        return True

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
        """Write the capture and its small copy before reporting the shot done.

        The small copy used to be written by a thread of its own, which nothing
        tracked: the capture job was finished the moment this returned, and the
        confirm screen went looking for a file that was still being written. It
        reads a missing preview as "nothing to show" and leaves the texture
        alone, so the guest was asked to keep or retake the previous shot.

        This already runs on the capture thread, off the UI, and the screen that
        needs the small copy is the very next one, so there is nothing to gain
        by returning ahead of it.
        """
        FileUtils.write_image(output_name, image)
        self._write_small_preview(image, output_name)

    def _write_small_preview(self, image, output_name):
        try:
            FileUtils.write_image(FileUtils.get_small_path(output_name), FileUtils.resize(image))
        except Exception as e:
            Logger.error('Camera: could not create small preview for %s: %s', output_name, e)
