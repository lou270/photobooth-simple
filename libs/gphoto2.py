import os
import time
import ctypes

RETRIES = 1
GP_CAPTURE_IMAGE = 0
GP_FILE_TYPE_NORMAL = 1
LIBRARY_NAME = 'libgphoto2.so'

# Widget types, from gphoto2-widget.h
GP_WIDGET_RANGE = 3
GP_WIDGET_TOGGLE = 4
GP_WIDGET_DATE = 8
GP_WIDGET_TEXT_TYPES = (2, 5, 6)   # TEXT, RADIO, MENU: all carry a char*
GP_WIDGET_INT_TYPES = (GP_WIDGET_TOGGLE, GP_WIDGET_DATE)

PTR = ctypes.pointer

# Loaded on first use rather than at import: this module has to be importable,
# and its logic testable, on a machine with no libgphoto2 at all.
gp = None
context = None


class LibraryUnavailable(Exception):
    """Raised when libgphoto2 cannot be loaded on this machine."""


def load_library(library=None, gp_context=None):
    """Load libgphoto2 once and create its context.

    Tests inject their own `library` to exercise the error paths without the
    shared library or a camera.
    """
    global gp, context

    if library is not None:
        gp, context = library, gp_context
        return gp

    if gp is not None:
        return gp

    try:
        gp = ctypes.CDLL(LIBRARY_NAME)
    except OSError as exc:
        raise LibraryUnavailable(f'{LIBRARY_NAME} is not available: {exc}') from None

    context = gp.gp_context_new()
    return gp


class libgphoto2error(Exception):
    def __init__(self, result, message):
        self.result = result
        self.message = message

    def __str__(self):
        # An f-string, so a bytes or int message cannot turn the error report
        # itself into a TypeError and hide the real failure.
        return f'{self.message} ({self.result})'

class CameraFilePath(ctypes.Structure):
    _fields_ = [('name', (ctypes.c_char * 128)), ('folder', (ctypes.c_char * 1024))]

class CameraText(ctypes.Structure):
    _fields_ = [('text', (ctypes.c_char * (32 * 1024)))]

def _result_message(result):
    """Human-readable text for a libgphoto2 result code."""
    gp.gp_result_as_string.restype = ctypes.c_char_p
    message = gp.gp_result_as_string(result)
    if isinstance(message, bytes):
        message = message.decode('ascii', errors='replace')
    return message or f'error {result}'

def check(result):
    if result < 0:
        raise libgphoto2error(result, _result_message(result))
    return result

def check_unref(result, camfile):
    if result != 0:
        # camfile._ptr: this used to read camfile.pointer, an attribute that has
        # never existed, so a failure here raised AttributeError and buried the
        # actual camera error.
        gp.gp_file_unref(camfile._ptr)
        raise libgphoto2error(result, _result_message(result))

class cameraList():
    def __init__(self):
        load_library()
        self._ptr = ctypes.c_void_p()
        check(gp.gp_list_new(PTR(self._ptr)))
        if not hasattr(gp, 'gp_camera_autodetect'): raise Exception('gphoto2 version is obsolete.')
        gp.gp_camera_autodetect(self._ptr, context)

    def get(self):
        return [(self._get_name(i), self._get_value(i)) for i in range(self.count())]

    def count(self):
        return check(gp.gp_list_count(self._ptr))

    def _get_name(self, index):
        name = ctypes.c_char_p()
        check(gp.gp_list_get_name(self._ptr, int(index), PTR(name)))
        return str(name.value, encoding='ascii')

    def _get_value(self, index):
        value = ctypes.c_char_p()
        check(gp.gp_list_get_value(self._ptr, int(index), PTR(value)))
        return str(value.value, encoding='ascii')

class camera():
    def __init__(self):
        load_library()
        self._ptr = ctypes.c_void_p()
        check(gp.gp_camera_new(PTR(self._ptr)))
        self._init()
        # Réutilisation du même cameraFile pour le preview (performance)
        self._preview_file = None

    def close(self):
        """Release the camera. Best effort, safe to call more than once.

        Teardown errors are not actionable and must not raise: this runs while
        the application is already recovering or shutting down.
        """
        preview_file, self._preview_file = getattr(self, '_preview_file', None), None
        if preview_file is not None:
            try:
                preview_file.unref()
            except Exception:
                pass

        if not getattr(self, '_ptr', None):
            return

        try:
            # gp_camera_exit takes the context; omitting it here used to be an
            # ABI mismatch on the one path that always runs.
            gp.gp_camera_exit(self._ptr, context)
            gp.gp_camera_free(self._ptr)
        except Exception:
            pass
        finally:
            self._ptr = None

    def __del__(self):
        # Never raise from __del__: the interpreter would only print and ignore
        # it, while the real cause stays invisible.
        try:
            self.close()
        except Exception:
            pass

    def summary(self):
        txt = CameraText()
        check(gp.gp_camera_get_summary(self._ptr, PTR(txt), context))
        summary = str(txt.text, encoding='ascii')
        r = {}
        for l in summary.splitlines():
            try:
                k, v = l.split(':')
            except ValueError:
                continue
            r[k.strip()] = v.strip()
        return summary

    def get_config(self):
        config = cameraConfig()
        check(gp.gp_camera_get_config(self._ptr, PTR(config._ptr), context))
        return config

    def commit_config(self, config):
        check(gp.gp_camera_set_config(self._ptr, config._ptr, context))

    def capture_image(self, destpath=None):
        # Triffer capture
        path = CameraFilePath()
        ans = 0
        for _ in range(1 + RETRIES):
            ans = gp.gp_camera_capture(self._ptr, GP_CAPTURE_IMAGE, PTR(path), context)
            if ans == 0: break
        check(ans)
        cfile = cameraFile(self._ptr, path.folder, path.name)

        # Save to file
        if destpath:
            cfile.save(destpath.encode('ascii'))
            cfile.unref()
            cfile.clean()
            return None
        else:
            return cfile

    def capture_preview(self, destpath=None):
        if self._preview_file is None: self._preview_file = cameraFile()
        else: self._preview_file.clean()
        
        # Trigger capture
        ans = gp.gp_camera_capture_preview(self._ptr, self._preview_file._ptr, context)
        check(ans)

        # Save to file
        if destpath:
            self._preview_file.save(destpath.encode('ascii'))
            return None
        else:
            return self._preview_file

    def trigger_capture(self):
        check(gp.gp_camera_trigger_capture(self._ptr, context))

    def _init(self):
        ans = 0
        for i in range(1 + RETRIES):
            ans = gp.gp_camera_init(self._ptr, context)
            # Success
            if ans == 0: break

            # Error (Could not lock the device)
            elif ans == -60:
                os.system('gvfs-mount -s gphoto2')
                time.sleep(1)
        check(ans)

class cameraFile():
    def __init__(self, cam = None, srcfolder = None, srcfilename = None):
        self._ptr = ctypes.c_void_p()
        check(gp.gp_file_new(PTR(self._ptr)))
        if cam: check_unref(gp.gp_camera_file_get(cam, srcfolder, srcfilename, GP_FILE_TYPE_NORMAL, self._ptr, context), self)

    def open(self, filename):
        check(gp.gp_file_open(PTR(self._ptr), filename))

    def get_data(self, auto_clean=True):
        data = ctypes.c_char_p()
        size = ctypes.c_ulong()
        check(gp.gp_file_get_data_and_size(self._ptr, PTR(data), PTR(size)))
        data = ctypes.string_at(data, int(size.value))
        if auto_clean:
            self.unref()
            self.clean()
        return data

    def save(self, filename=None):
        if filename is None: filename = self.name
        check(gp.gp_file_save(self._ptr, filename))

    def ref(self):
        check(gp.gp_file_ref(self._ptr))

    def unref(self):
        check(gp.gp_file_unref(self._ptr))

    def clean(self):
        check(gp.gp_file_clean(self._ptr))

class cameraConfig():
    def __init__(self):
        self._ptr = ctypes.c_void_p()

    def ref(self):
        check(gp.gp_widget_ref(self._ptr))

    def unref(self):
        check(gp.gp_widget_unref(self._ptr))

    def __del__(self):
        # A cameraConfig is built empty and only then filled by the caller, so a
        # widget that was never populated holds a null pointer. Unreffing that
        # used to reach libgphoto2 with NULL, and a segfault is not something a
        # destructor can report.
        try:
            if getattr(self, '_ptr', None):
                gp.gp_widget_unref(self._ptr)
        except Exception:
            pass

    def get_path(self, path):
        names = path.strip('/').split('/')
        current_widget = self
        for name in names:
            if name == 'main': continue
            current_widget = current_widget._get_child_by_name(name)
            if current_widget is None: return None
        return current_widget

    def list_paths(self, parent_path="/main"):
        children_paths = []
        children = self._get_children()
        for child in children:
            child_path = f"{parent_path}/{child.get_name()}"
            if child._count_children() == 0: children_paths.append(child_path)
            children_paths.extend(child.list_paths(child_path))
        return children_paths

    def get_label(self):
        label = ctypes.c_char_p()
        check(gp.gp_widget_get_label(self._ptr, PTR(label)))
        return str(label.value, encoding='ascii')

    def get_info(self):
        info = ctypes.c_char_p()
        check(gp.gp_widget_get_info(self._ptr, PTR(info)))
        return str(info.value, encoding='ascii')

    def get_type(self):
        type = ctypes.c_int()
        check(gp.gp_widget_get_type(self._ptr, PTR(type)))
        return type.value

    def get_value(self):
        """Read a widget, using storage of the type libgphoto2 writes into.

        The numeric branches used to cast through ctypes.c_float_p and
        ctypes.c_int_p, which do not exist: reading any range, toggle or date
        widget raised AttributeError. _set_parameters() reads the exposure mode
        before applying DSLR settings and swallows failures at debug level, so
        this silently stopped configured settings from ever being applied.
        """
        widget_type = self.get_type()

        if widget_type in GP_WIDGET_TEXT_TYPES:
            value = ctypes.c_char_p()
            check(gp.gp_widget_get_value(self._ptr, PTR(value)))
            if not value.value:
                return None
            return value.value.decode('ascii', errors='replace')

        if widget_type == GP_WIDGET_RANGE:
            value = ctypes.c_float()
            check(gp.gp_widget_get_value(self._ptr, PTR(value)))
            return value.value

        if widget_type in GP_WIDGET_INT_TYPES:
            value = ctypes.c_int()
            check(gp.gp_widget_get_value(self._ptr, PTR(value)))
            return value.value

        return None

    def set_value(self, value):
        widget_type = self.get_type()

        if widget_type in GP_WIDGET_TEXT_TYPES:
            if isinstance(value, str):
                value = value.encode('ascii')
            if not isinstance(value, bytes):
                # `type` used to be shadowed by the widget type on the line
                # above, so building this very message raised TypeError.
                raise libgphoto2error(-1, f'Value should be a string or bytes, got {type(value).__name__}')
            payload = ctypes.c_char_p(value)
        elif widget_type == GP_WIDGET_RANGE:
            payload = PTR(ctypes.c_float(float(value)))
        elif widget_type in GP_WIDGET_INT_TYPES:
            payload = PTR(ctypes.c_int(int(value)))
        else:
            return

        check(gp.gp_widget_set_value(self._ptr, payload))

    def get_name(self):
        name = ctypes.c_char_p()
        check(gp.gp_widget_get_name(self._ptr, PTR(name)))
        return str(name.value, encoding='ascii')

    def _get_child_by_name(self, name):
        for i in range(self._count_children()):
            child = cameraConfig()
            check(gp.gp_widget_get_child(self._ptr, int(i), PTR(child._ptr)))
            check(gp.gp_widget_ref(child._ptr))
            if child.get_name() == name: return child
        return None

    def _count_children(self):
        return gp.gp_widget_count_children(self._ptr)

    def _get_children(self):
        children = []
        for i in range(self._count_children()):
            child = cameraConfig()
            check(gp.gp_widget_get_child(self._ptr, int(i), PTR(child._ptr)))
            check(gp.gp_widget_ref(child._ptr))
            children.append(child)
        return children
