import logging
import threading
import time

import cv2
import numpy as np

from libs.file_utils import FileUtils
from libs.hardware.camera import Camera

Logger = logging.getLogger('kivy.photobooth')


class FakeCamera(Camera):
    """Synthetic camera: runs the whole application without any hardware.

    Used for development on a workstation and by the test suite. It honours the
    same aspect-ratio and zoom contract as the real backends, so a code path
    exercised against it behaves the same against a reflex or a Camera Module.

    `capture_delay` reproduces the latency of a DSLR (roughly 0.5-1.5s), which is
    what makes the capture timeout and recovery paths testable without hardware.
    """

    def __init__(self, size=(1280, 720), fps=30, capture_delay=0.0, has_flash=False):
        self._width, self._height = int(size[0]), int(size[1])
        self._preview_fps = max(1, int(fps))
        self._capture_delay = max(0.0, float(capture_delay))
        self._has_flash = bool(has_flash)
        self._started_at = time.monotonic()
        self._lock = threading.Lock()
        self._capture_count = 0
        self._background = self._build_background()
        self._instance = self  # satisfies Camera.is_healthy()
        Logger.info(
            'FakeCamera: %sx%s @%sfps capture_delay=%.2fs flash=%s',
            self._width, self._height, self._preview_fps, self._capture_delay, self._has_flash,
        )

    # --- frame generation ------------------------------------------------

    def _build_background(self):
        """Static gradient, computed once: only the moving parts cost per frame."""
        gradient_x = np.linspace(40, 190, self._width, dtype=np.float32)
        gradient_y = np.linspace(90, 20, self._height, dtype=np.float32)
        base = gradient_y[:, None] + gradient_x[None, :]

        frame = np.empty((self._height, self._width, 3), dtype=np.uint8)
        frame[:, :, 0] = np.clip(base * 0.90, 0, 255)  # B
        frame[:, :, 1] = np.clip(base * 0.55, 0, 255)  # G
        frame[:, :, 2] = np.clip(base * 0.40, 0, 255)  # R
        return frame

    def _frame_index(self):
        return int((time.monotonic() - self._started_at) * self._preview_fps)

    def _render_frame(self):
        frame = self._background.copy()
        index = self._frame_index()

        # A moving band makes a frozen preview obvious at a glance.
        band_width = max(8, self._width // 40)
        band_x = int((index * 6) % (self._width + band_width)) - band_width
        cv2.rectangle(frame, (band_x, 0), (band_x + band_width, self._height), (255, 255, 255), -1)

        # Centre lines: quick visual check of the crop and calibration.
        cv2.line(frame, (self._width // 2, 0), (self._width // 2, self._height), (255, 255, 255), 1)
        cv2.line(frame, (0, self._height // 2), (self._width, self._height // 2), (255, 255, 255), 1)

        scale = self._height / 480.0
        cv2.putText(
            frame, 'FAKE CAMERA', (int(24 * scale), int(56 * scale)),
            cv2.FONT_HERSHEY_SIMPLEX, 1.1 * scale, (255, 255, 255), max(1, int(2 * scale)), cv2.LINE_AA,
        )
        with self._lock:
            captures = self._capture_count
        cv2.putText(
            frame, f'frame {index} | {self._width}x{self._height} | shots {captures}',
            (int(24 * scale), int(96 * scale)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6 * scale, (255, 255, 255), max(1, int(scale)), cv2.LINE_AA,
        )
        return frame

    def _frame_for_output(self, aspect_ratio, zoom, apply_zoom):
        frame = self._render_frame()
        frame = self._crop_to_aspect_ratio(frame, aspect_ratio)
        return apply_zoom(frame, zoom)

    # --- Camera contract -------------------------------------------------

    def get_preview_fps(self):
        return self._preview_fps

    def get_preview_frame_id(self):
        return self._frame_index()

    def get_preview(self, aspect_ratio=None, zoom=None):
        return self._frame_for_output(aspect_ratio, zoom, self._apply_preview_zoom)

    def has_physical_flash(self):
        return self._has_flash

    def capture(self, output_name, aspect_ratio=None, zoom=None, flash_fn=None):
        if self._capture_delay:
            time.sleep(self._capture_delay)

        if flash_fn and not self.has_physical_flash():
            flash_fn()
        frame = self._frame_for_output(aspect_ratio, zoom, self._apply_capture_zoom)
        if flash_fn and not self.has_physical_flash():
            flash_fn(stop=True)

        with self._lock:
            self._capture_count += 1

        self._write_capture(output_name, frame)

    @property
    def capture_count(self):
        with self._lock:
            return self._capture_count

    def close(self):
        self._instance = None
