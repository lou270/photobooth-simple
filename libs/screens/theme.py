"""Colours, icons, type scale and the timings shared by every screen."""

from kivy.core.window import Window
from kivy.metrics import dp

from libs.kivywidgets import hex_to_rgba, window_size_registry


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

SHOT_TIMEOUT_SECONDS = 10
REVIEW_HOME_TIMEOUT_SECONDS = 60
COUNTDOWN_HOME_TIMEOUT_SECONDS = 30
SELECT_FORMAT_HOME_TIMEOUT_SECONDS = 30
# A safety net rather than a visible countdown here: the auto-keep timer below
# always fires first, so this only catches a guest who left mid-choice with the
# screen somehow still waiting.
CONFIRM_CAPTURE_HOME_TIMEOUT_SECONDS = 30

# Fewer taps between shots. A guest who kept the first photo has already said
# yes to the session, so the following countdowns start on their own — late
# enough to see the preview and reach the cancel button.
SHOT_AUTOSTART_SECONDS = 1.5
# Keeping the shot is what nearly everyone does; retaking is the exception, so
# it is the one that needs a button press. Any touch on the screen restarts it.
CONFIRM_AUTO_KEEP_SECONDS = 6
# A beat between the printer taking the job and the screen getting out of the
# way, so the animation does not cut mid-sheet...
PRINT_DONE_SECONDS = 1.5
# ...and a floor under the whole screen, because a printer that answers at once
# would otherwise leave nothing on screen long enough to read. A touch skips it.
PRINT_MIN_SECONDS = 6.0
# Ceiling on the printing itself, per sheet. PRINTER_WAIT_TIMEOUT is what an
# operator sets for a printer that went away, and used to bound this too, which
# meant a dye-sub taking its usual minute a sheet was reported to the guest as a
# failure while the prints were coming out. This is only a safety net against a
# job CUPS never finishes, so it is generous.
PRINT_SHEET_TIMEOUT_SECONDS = 180
# Longer than the others: a guest browsing the photos phones sent is reading a
# wall of faces, not answering a prompt.
REMOTE_GALLERY_HOME_TIMEOUT_SECONDS = 90
# An error a guest can walk away from — a print that failed, say — left the
# booth showing their failure to everyone who came after them, because this is
# the one interactive screen with no way back on its own. Only applied when
# there is a continue button: a booth in maintenance is meant to stay there,
# and sending it home would just walk it into the same wall again.
ERROR_HOME_TIMEOUT_SECONDS = 90
# The codes are the one overlay with nothing behind it that times out: the
# welcome screen never leaves on its own, and the popup swallows every touch to
# stop a tap on the card from starting a session. A guest who walked away from
# it therefore left the booth unusable until someone found the close button.
# Long enough for two scans and a phone joining a network, and every touch
# gives the whole delay back.
QR_POPUP_TIMEOUT_SECONDS = 45

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
