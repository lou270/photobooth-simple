"""Colours, icons, type scale and the timings shared by every screen."""

from kivy.core.window import Window
from kivy.metrics import dp

from libs.kivywidgets import hex_to_rgba, window_size_registry
from libs.timings import TIMINGS, Timing  # noqa: F401 - re-exported for the screens


# Font sizes as fractions of min(Window.width, Window.height) — DPI-independent and
# orientation-independent: the shortest side is always the binding constraint so fonts
# stay visible whether the window is landscape or portrait.
def XLARGE_FONT(): return min(Window.size) * 0.22
def LARGE_FONT():  return min(Window.size) * 0.07
def NORMAL_FONT(): return min(Window.size) * 0.055
def SMALL_FONT():  return min(Window.size) * 0.035
def TINY_FONT():   return min(Window.size) * 0.018

def wh_bind(widget, attr, fn):
    """Keep widget.attr at fn() across window resizes.

    Call it after creating a widget: wh_bind(label, 'font_size', LARGE_FONT).

    This kept its own weakref list, pruned only while a resize walked it — so on
    a booth in kiosk mode, which never resizes, it only ever grew. The registry
    it now shares with ResizeLabel and the round buttons prunes on both.
    """
    window_size_registry.add(
        widget,
        lambda target, attr=attr, fn=fn: setattr(target, attr, fn()),
    )

# The delays an operator can tune are TIMINGS, from libs/timings.py, read from
# config.ini: screens read them when a delay starts rather than at import.

# A beat between the printer taking the job and the screen getting out of the
# way, so the animation does not cut mid-sheet. Not a setting: it only paces an
# animation, and print_min is the delay a guest actually feels.
PRINT_DONE_SECONDS = 1.5

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
# 0 draws no frame at all; short_side(0.011) is the one it used to draw.
BORDER_THINKNESS = dp(0)
PROGRESS_COLOR = hex_to_rgba('#e5e5e5')
CONFIRM_COLOR = hex_to_rgba('#538a64')
CANCEL_COLOR = hex_to_rgba('#8b4846')
HOME_COLOR = hex_to_rgba('#534969')
HOME_PROGRESS_COLOR = darken_rgba(HOME_COLOR) #lighten_rgba(HOME_COLOR)
CONFIRM_PROGRESS_COLOR = darken_rgba(CONFIRM_COLOR)
BADGE_COLOR = hex_to_rgba('#8b4846')
SHARE_COLOR = hex_to_rgba('#667eea')
STEPPER_COLOR = hex_to_rgba('#4a5c6a')
REMOTE_COLOR = hex_to_rgba('#4a7c8c')

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
ICON_USB = '\u49ba'
ICON_TRIGGER = '\u3d3e'
ICON_QRCODE = '\u45f4'
ICON_SHARE = '\u46d4'
ICON_MINUS = '\u43b0'
ICON_PLUS = '\u3aa9'
ICON_DELETE = '\u3efa'
