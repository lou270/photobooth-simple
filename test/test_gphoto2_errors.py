"""The libgphoto2 wrapper's error paths, exercised without the library.

Every bug covered here lived in a path that only runs when the camera is
already unhappy: a USB glitch, a busy body, a widget the model does not expose.
Instead of a usable error the wrapper raised AttributeError or TypeError, which
buried the real cause and left the recovery logic reasoning about the wrong
failure.
"""

import ctypes
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
import libs.gphoto2 as gphoto2


class FakeFunction:
    """Stands in for a ctypes function: callable, and carries a restype."""

    def __init__(self):
        self.restype = None
        self.result = 0
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        return self.result(*args) if callable(self.result) else self.result


class FakeLibrary:
    """Stands in for the libgphoto2 handle, creating functions on demand."""

    def __init__(self):
        self._functions = {}

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return self._functions.setdefault(name, FakeFunction())


def writes(value):
    """A call that writes `value` into the pointer it is handed."""
    def implementation(_handle, out):
        out.contents.value = value
        return 0
    return implementation


@pytest.fixture
def fake_gp(monkeypatch):
    library = FakeLibrary()
    monkeypatch.setattr(gphoto2, 'gp', library)
    monkeypatch.setattr(gphoto2, 'context', ctypes.c_void_p(999))
    return library


_UNSET = object()


def widget(fake_gp, widget_type, value=_UNSET):
    fake_gp.gp_widget_get_type.result = writes(widget_type)
    if value is not _UNSET:
        fake_gp.gp_widget_get_value.result = writes(value)
    config = gphoto2.cameraConfig()
    config._ptr = ctypes.c_void_p(1)
    return config


# --- library loading -------------------------------------------------------

def test_a_missing_library_raises_a_named_error(monkeypatch):
    monkeypatch.setattr(gphoto2, 'gp', None)
    monkeypatch.setattr(gphoto2.ctypes, 'CDLL', _raise_os_error)

    with pytest.raises(gphoto2.LibraryUnavailable, match='libgphoto2'):
        gphoto2.load_library()


def _raise_os_error(name):
    raise OSError('cannot open shared object file')


# --- result reporting ------------------------------------------------------

def test_check_reports_the_library_message_and_code(fake_gp):
    fake_gp.gp_result_as_string.result = b'Could not claim the USB device'

    with pytest.raises(gphoto2.libgphoto2error) as error:
        gphoto2.check(-53)

    assert 'Could not claim the USB device' in str(error.value)
    assert '-53' in str(error.value)


def test_check_passes_success_through(fake_gp):
    assert gphoto2.check(0) == 0


def test_check_unref_releases_the_file_and_reports_the_error(fake_gp):
    """Used to read camfile.pointer, an attribute that never existed."""
    fake_gp.gp_result_as_string.result = b'I/O problem'
    camera_file = SimpleNamespace(_ptr=ctypes.c_void_p(7))

    with pytest.raises(gphoto2.libgphoto2error) as error:
        gphoto2.check_unref(-1, camera_file)

    assert fake_gp.gp_file_unref.calls == [(camera_file._ptr,)]
    assert 'I/O problem' in str(error.value)


def test_an_undecodable_message_still_produces_a_readable_error(fake_gp):
    """The message used to stay bytes and turn str(error) into a TypeError."""
    fake_gp.gp_result_as_string.result = b'\xff\xfe broken'

    with pytest.raises(gphoto2.libgphoto2error) as error:
        gphoto2.check(-7)

    assert '-7' in str(error.value)


# --- widget values ---------------------------------------------------------

def test_reading_a_text_widget(fake_gp):
    assert widget(fake_gp, 2, b'Canon Inc.').get_value() == 'Canon Inc.'


def test_reading_a_range_widget_no_longer_raises(fake_gp):
    """Went through ctypes.c_float_p, which does not exist."""
    assert widget(fake_gp, gphoto2.GP_WIDGET_RANGE, 4.0).get_value() == pytest.approx(4.0)


def test_reading_a_toggle_widget_no_longer_raises(fake_gp):
    """Went through ctypes.c_int_p, which does not exist."""
    assert widget(fake_gp, gphoto2.GP_WIDGET_TOGGLE, 1).get_value() == 1


def test_reading_an_unknown_widget_type_returns_nothing(fake_gp):
    assert widget(fake_gp, 99).get_value() is None


def test_reading_an_empty_text_widget_returns_nothing(fake_gp):
    assert widget(fake_gp, 2, value=None).get_value() is None


def test_setting_a_text_widget_encodes_the_string(fake_gp):
    widget(fake_gp, 5).set_value('One Shot')

    assert fake_gp.gp_widget_set_value.calls
    assert fake_gp.gp_widget_set_value.calls[0][1].value == b'One Shot'


def test_setting_a_text_widget_to_a_number_names_the_offending_type(fake_gp):
    """Building this message used to raise TypeError: `type` was shadowed."""
    with pytest.raises(gphoto2.libgphoto2error, match='float'):
        widget(fake_gp, 2).set_value(1.5)


def test_setting_a_range_widget_accepts_a_string(fake_gp):
    widget(fake_gp, gphoto2.GP_WIDGET_RANGE).set_value('2.8')
    assert fake_gp.gp_widget_set_value.calls


def test_setting_an_unknown_widget_type_is_ignored(fake_gp):
    widget(fake_gp, 99).set_value('anything')
    assert fake_gp.gp_widget_set_value.calls == []


def test_an_unpopulated_widget_is_never_unreffed(fake_gp):
    """A cameraConfig is built empty; unreffing NULL is a segfault, not an error."""
    config = gphoto2.cameraConfig()

    config.__del__()

    assert fake_gp.gp_widget_unref.calls == []


# --- camera teardown -------------------------------------------------------

def test_closing_a_camera_passes_the_context_and_runs_once(fake_gp):
    """__del__ used to call gp_camera_exit without the context argument."""
    camera = gphoto2.camera.__new__(gphoto2.camera)
    camera._ptr = ctypes.c_void_p(1)
    camera._preview_file = None

    camera.close()
    camera.close()

    assert len(fake_gp.gp_camera_exit.calls) == 1
    assert fake_gp.gp_camera_exit.calls[0][1] is gphoto2.context
    assert len(fake_gp.gp_camera_free.calls) == 1


def test_closing_a_camera_never_raises(fake_gp):
    def explode(*_args):
        raise OSError('device disappeared')

    fake_gp.gp_camera_exit.result = explode
    camera = gphoto2.camera.__new__(gphoto2.camera)
    camera._ptr = ctypes.c_void_p(1)
    camera._preview_file = None

    camera.close()  # teardown must not raise while the app is already recovering


def test_closing_a_half_built_camera_is_safe(fake_gp):
    """__init__ can fail before _ptr or _preview_file exist."""
    camera = gphoto2.camera.__new__(gphoto2.camera)

    camera.close()

    assert fake_gp.gp_camera_exit.calls == []
