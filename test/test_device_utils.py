import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.device_utils import DeviceUtils
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
