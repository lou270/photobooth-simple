import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.device_utils import Cv2Camera, DeviceUtils, Gphoto2Camera, Picamera2Camera
from libs.hardware import FakeCamera
from libs.kivywidgets import KivyCamera
from photoboothapp import PhotoboothApp


class FakeStorage:
    def __init__(self, print_collage):
        self._print_collage = print_collage

    def get_print_collage(self):
        return self._print_collage

    def log_disk_usage(self, context):
        pass


class UnlimitedPrints:
    def can_print(self):
        return True


class FakePrinter:
    def __init__(self):
        self.file_path = None
        self.print_params = None
        self.jobs = []

    def print(self, file_path, print_params):
        self.file_path = file_path
        self.print_params = print_params
        self.jobs.append((file_path, dict(print_params)))
        return 123


class FakePrintFormat:
    def __init__(self, print_params=None, uses_print_version=False):
        self._print_params = print_params or {}
        self._uses_print_version = uses_print_version

    def get_print_params(self):
        return dict(self._print_params)

    def uses_print_version(self):
        return self._uses_print_version


def test_device_utils_print_returns_printer_task_id():
    devices = object.__new__(DeviceUtils)
    devices._printer = FakePrinter()

    assert devices.print('photo.jpg', {'copies': '1'}) == 123


def test_device_utils_print_without_printer_fails():
    devices = object.__new__(DeviceUtils)
    devices._printer = None

    with pytest.raises(RuntimeError):
        devices.print('photo.jpg', {'copies': '1'})


def test_photobooth_app_has_printer_uses_devices():
    class NoPrinterDevices:
        def has_printer(self):
            return False

    app = PhotoboothApp.__new__(PhotoboothApp)
    app.devices = NoPrinterDevices()

    assert app.has_printer() is False


def test_trigger_print_ignores_stale_print_collage_for_fullpage(tmp_path):
    printer = FakePrinter()
    collage = tmp_path / 'collage.jpg'
    print_collage = tmp_path / 'collage_print.jpg'
    collage.write_bytes(b'fullpage')
    print_collage.write_bytes(b'stale strip')

    app = PhotoboothApp.__new__(PhotoboothApp)
    app.devices = printer
    app.print_formats = [FakePrintFormat({'PageSize': 'w288h432'}, uses_print_version=False)]
    app.storage = FakeStorage(str(print_collage))
    app.stats_store = UnlimitedPrints()
    app.get_collage = lambda: str(collage)
    app.get_saved_collage = lambda: None
    app.has_printer = lambda: True

    assert app.trigger_print(1, format=0) == [123]
    assert printer.file_path == str(collage)
    assert printer.print_params == {'PageSize': 'w288h432', 'copies': '1'}


def test_trigger_print_uses_print_collage_for_duplicated_strip(tmp_path):
    printer = FakePrinter()
    collage = tmp_path / 'collage.jpg'
    print_collage = tmp_path / 'collage_print.jpg'
    collage.write_bytes(b'strip')
    print_collage.write_bytes(b'duplicated strip')

    app = PhotoboothApp.__new__(PhotoboothApp)
    app.devices = printer
    app.print_formats = [FakePrintFormat({'PageSize': 'w288h432-div2'}, uses_print_version=True)]
    app.storage = FakeStorage(str(print_collage))
    app.stats_store = UnlimitedPrints()
    app.get_collage = lambda: str(collage)
    app.get_saved_collage = lambda: None
    app.has_printer = lambda: True

    assert app.trigger_print(1, format=0) == [123]
    assert printer.file_path == str(print_collage)
    assert printer.print_params == {'PageSize': 'w288h432-div2', 'copies': '1'}


def test_three_copies_are_three_single_copy_jobs(tmp_path):
    """The dye-sub driver never duplicates a sheet, so the booth queues each one.

    A single job asking for three copies came out as one photo: the Gutenprint
    PPD says the device counts copies and the usb backend does not.
    """
    printer = FakePrinter()
    collage = tmp_path / 'collage.jpg'
    collage.write_bytes(b'fullpage')

    app = PhotoboothApp.__new__(PhotoboothApp)
    app.devices = printer
    app.print_formats = [FakePrintFormat({'PageSize': 'w288h432'}, uses_print_version=False)]
    app.storage = FakeStorage(str(tmp_path / 'missing_print.jpg'))
    app.stats_store = UnlimitedPrints()
    app.get_collage = lambda: str(collage)
    app.get_saved_collage = lambda: None
    app.has_printer = lambda: True

    assert app.trigger_print(3, format=0) == [123, 123, 123]
    assert printer.jobs == [(str(collage), {'PageSize': 'w288h432', 'copies': '1'})] * 3


# --- the preview contract every backend owes the widget --------------------

CAPTURE_BACKENDS = (Cv2Camera, Gphoto2Camera, Picamera2Camera, FakeCamera)


@pytest.mark.parametrize('backend', CAPTURE_BACKENDS, ids=lambda cls: cls.__name__)
def test_every_camera_reports_a_frame_of_its_own(backend):
    """Inheriting Camera.get_preview_frame_id() silently freezes the preview.

    KivyCamera reads that value to skip frames it has already drawn, and the
    base class answers a constant 0. Gphoto2Camera was missing the override, so
    a booth whose only camera is the DSLR — CAMERA = gphoto2, or auto with no
    picamera and no webcam — showed one frame and then a still image for the
    whole countdown. It is invisible on every hybrid rig, because there the
    preview comes from the other camera.
    """
    assert 'get_preview_frame_id' in backend.__dict__, (
        f'{backend.__name__} inherits the constant frame id and will freeze the preview'
    )


def test_the_dslr_preview_loop_advances_its_frame_id():
    """The rule above only checks the method exists; this checks it moves.

    Built with __new__ and driven by hand: the real constructor needs a camera
    on the USB bus.
    """
    camera = Gphoto2Camera.__new__(Gphoto2Camera)
    camera._preview_lock = threading.Lock()
    camera._camera_lock = threading.Lock()
    camera._preview_frame = None
    camera._preview_frame_id = 0
    camera._preview_failures = 0
    camera._preview_stop = False
    camera._preview_fps = 1000                    # do not sleep through the test
    camera._imread_preview = cv2.IMREAD_COLOR

    encoded = cv2.imencode('.jpg', np.zeros((32, 48, 3), dtype=np.uint8))[1].tobytes()
    frames_left = [3]

    class FakeFile:
        def get_data(self, auto_clean=True):
            return encoded

    class FakeInstance:
        def capture_preview(self):
            if frames_left[0] <= 0:
                camera._preview_stop = True
                raise RuntimeError('the camera stopped answering')
            frames_left[0] -= 1
            return FakeFile()

    camera._instance = FakeInstance()
    camera._preview_loop()

    assert camera.get_preview_frame_id() == 3


def test_a_frame_id_that_never_moves_stops_the_preview():
    """Why the rule above exists, stated as the behaviour it protects."""
    reads = []

    class FrozenId:
        def get_preview_fps(self):
            return 15

        def get_preview_frame_id(self):
            return 0                      # what the base class answers

        def get_preview(self, aspect_ratio=None):
            reads.append(1)
            return np.zeros((48, 64, 3), dtype=np.uint8)

    widget = KivyCamera(app=SimpleNamespace(devices=FrozenId()), fps=15, blur=False)
    widget._stop = True                   # no self-rescheduling in a test
    widget._aspect_ratio = None
    widget._blur_cache = None
    widget._frame_count = 0
    widget._last_frame_id = None
    widget._reset_stats()

    for _ in range(10):
        widget._update(None)

    assert len(reads) == 1
