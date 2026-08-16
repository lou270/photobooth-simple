"""The booth's visual vocabulary: typography, depth, background.

Kept apart from the screens on purpose. These are palette and typography
decisions, not Kivy ones: if the front-end is ever replaced they translate to
CSS almost line for line, which is not true of the layout code around them.
"""

import logging
from functools import lru_cache
from pathlib import Path

import numpy as np
from kivy.graphics import Color, RoundedRectangle
from kivy.graphics.texture import Texture
from kivy.metrics import dp

Logger = logging.getLogger('kivy.photobooth')

# Where a system font install drops its files.
FONT_SEARCH_PATHS = (
    '/usr/share/fonts',
    '/usr/local/share/fonts',
    str(Path.home() / '.local/share/fonts'),
    'C:/Windows/Fonts',
    '/Library/Fonts',
    '/System/Library/Fonts',
)

# First match wins. A geometric sans reads as "event" rather than "settings
# screen", which is most of what makes the booth look dated. None of these ship
# with Raspberry Pi OS: `sudo apt install fonts-inter` (or drop a .ttf into
# ~/.local/share/fonts) and it is picked up on the next start. Without one of
# them the booth falls back to Kivy's Roboto and looks exactly as it did.
DISPLAY_FONT_CANDIDATES = (
    'Poppins-SemiBold', 'Montserrat-SemiBold', 'Raleway-SemiBold',
    'Inter-SemiBold', 'Inter_28pt-SemiBold', 'InterDisplay-SemiBold',
    'NotoSans-SemiBold', 'DejaVuSans-Bold',
)
UI_FONT_CANDIDATES = (
    'Poppins-Regular', 'Montserrat-Regular', 'Inter-Regular', 'Inter_28pt-Regular',
    'NotoSans-Regular', 'DejaVuSans',
)


@lru_cache(maxsize=1)
def _installed_fonts():
    """Map lowercase font file stems to their path, walked once."""
    fonts = {}
    for root in FONT_SEARCH_PATHS:
        base = Path(root)
        if not base.is_dir():
            continue
        try:
            for path in base.rglob('*.[to]tf'):
                fonts.setdefault(path.stem.lower(), str(path))
        except OSError as exc:
            Logger.debug('ui_theme: could not read %s: %s', base, exc)
    return fonts


def find_font(candidates, fallback='Roboto'):
    """Return the first installed candidate, or Kivy's default."""
    installed = _installed_fonts()
    for name in candidates:
        path = installed.get(name.lower())
        if path:
            return path
    return fallback


DISPLAY_FONT = find_font(DISPLAY_FONT_CANDIDATES)
UI_FONT = find_font(UI_FONT_CANDIDATES)
Logger.info('ui_theme: display font %s, interface font %s', DISPLAY_FONT, UI_FONT)


def vertical_gradient_texture(top_color, bottom_color, steps=256):
    """A one-pixel-wide vertical ramp, stretched across the screen by the GPU.

    A flat fill is the single strongest "this is an old application" signal, and
    a gradient costs one small texture uploaded once.
    """
    top = np.array(top_color[:3], dtype=np.float32)
    bottom = np.array(bottom_color[:3], dtype=np.float32)
    ramp = np.linspace(0.0, 1.0, steps, dtype=np.float32)[:, None]
    colors = ((top * (1.0 - ramp) + bottom * ramp) * 255.0).astype(np.uint8)

    texture = Texture.create(size=(1, steps), colorfmt='rgb')
    texture.blit_buffer(colors[:, None, :].tobytes(), colorfmt='rgb', bufferfmt='ubyte')
    texture.wrap = 'clamp_to_edge'
    texture.flip_vertical()  # row 0 is the top of the screen
    return texture


class SoftShadow:
    """Stacked translucent rounded rectangles standing in for a blur.

    Kivy's canvas cannot blur, and a pre-blurred nine-patch would be a binary
    asset to keep in step with the palette by hand. A handful of very faint
    rectangles growing outwards costs a few draw calls, needs nothing on disk,
    and reads as depth at the size of a format card.

    Draw it before the shape it sits under, then feed it the same pos and size.
    """

    def __init__(self, canvas, radius, layers=6, spread=dp(16), alpha=0.05, drop=0.35):
        self._layers = []
        self._drop = spread * drop
        with canvas:
            for index in range(layers, 0, -1):
                Color(0, 0, 0, alpha)
                rectangle = RoundedRectangle(radius=[radius + spread * index / layers])
                self._layers.append((rectangle, spread * index / layers))

    def update(self, pos, size):
        for rectangle, inset in self._layers:
            rectangle.pos = (pos[0] - inset, pos[1] - inset - self._drop)
            rectangle.size = (size[0] + 2 * inset, size[1] + 2 * inset)
