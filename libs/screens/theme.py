"""Colours, icons, type scale and the timings shared by every screen."""

from kivy.core.window import Window
from kivy.metrics import dp

from libs.kivywidgets import hex_to_rgba


# Font sizes as fractions of min(Window.width, Window.height) — DPI-independent and
# orientation-independent: the shortest side is always the binding constraint so fonts
# stay visible whether the window is landscape or portrait.
def XLARGE_FONT(): return min(Window.size) * 0.22
def LARGE_FONT():  return min(Window.size) * 0.07
def NORMAL_FONT(): return min(Window.size) * 0.055
def SMALL_FONT():  return min(Window.size) * 0.035
def TINY_FONT():   return min(Window.size) * 0.018

# Registry of (weakref, attr, fraction_fn) updated on every Window resize.
# Call wh_bind(widget, 'font_size', LARGE_FONT) after creating a widget to keep it live.
import weakref as _weakref
_WH_BINDINGS = []  # [(weakref, attr, fn), ...]

def wh_bind(widget, attr, fn):
    """Register a widget attribute to be updated on Window resize."""
    _WH_BINDINGS.append((_weakref.ref(widget), attr, fn))

def _on_window_resize(instance, size):
    dead = []
    for entry in _WH_BINDINGS:
        ref, attr, fn = entry
        obj = ref()
        if obj is None:
            dead.append(entry)
        else:
            setattr(obj, attr, fn())
    for d in dead:
        _WH_BINDINGS.remove(d)

Window.bind(size=_on_window_resize)

SHOT_TIMEOUT_SECONDS = 10
REVIEW_HOME_TIMEOUT_SECONDS = 60
COUNTDOWN_HOME_TIMEOUT_SECONDS = 30
CONFIRM_CAPTURE_HOME_TIMEOUT_SECONDS = 30
SELECT_FORMAT_HOME_TIMEOUT_SECONDS = 30

def lighten_rgba(color, amount=0.35):
    return (
        min(1.0, color[0] + (1.0 - color[0]) * amount),
        min(1.0, color[1] + (1.0 - color[1]) * amount),
        min(1.0, color[2] + (1.0 - color[2]) * amount),
        color[3],
    )

def darken_rgba(color, amount=0.25):
    return (
        max(0.0, color[0] * (1.0 - amount)),
        max(0.0, color[1] * (1.0 - amount)),
        max(0.0, color[2] * (1.0 - amount)),
        color[3],
    )

# Colors
BACKGROUND_COLOR = hex_to_rgba('#26495c')
BORDER_COLOR = hex_to_rgba('#c4a35a')
BORDER_THINKNESS = dp(0)#Window.height * 0.011
PROGRESS_COLOR = hex_to_rgba('#e5e5e5')
CONFIRM_COLOR = hex_to_rgba('#538a64')
CANCEL_COLOR = hex_to_rgba('#8b4846')
HOME_COLOR = hex_to_rgba('#534969')
HOME_PROGRESS_COLOR = darken_rgba(HOME_COLOR) #lighten_rgba(HOME_COLOR)
BADGE_COLOR = hex_to_rgba('#8b4846')
SHARE_COLOR = hex_to_rgba('#667eea')

# Icons
ICON_TTF = './assets/fonts/hugeicons.ttf' # https://hugeicons.com/free-icon-font and https://hugeicons.com/icons?style=Stroke&type=Rounded
ICON_TOUCH = '\u3d3e'
ICON_ERROR = '\u3b03'
ICON_ERROR_PRINTING = '\u458d'
ICON_ERROR_TRIGGER = '\u3d39'
ICON_LOADING = '\u45ec'
ICON_PROCESSING = '\u3ad2'
ICON_SHOT_TO_TAKE = '\u47f2'
ICON_SHOT_TAKEN = '\u3daa'
ICON_CONFIRM = '\u4908'
ICON_CANCEL = '\u3d42'
ICON_HOME = '\u4161'
ICON_PRINT = '\u458e'
ICON_SUCCESS = '\u4903'
ICON_SUCCESS2 = '\u4304'
ICON_USB = '\u49ba'
ICON_TRIGGER = '\u3d3e'
ICON_QRCODE = '\u45f4'
ICON_SHARE = '\u46d4'
