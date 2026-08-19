"""Two rules the screens follow, held as tests because breaking them looks fine.

Both were decided once, for reasons that are invisible at the call site: a
distance measured against the wrong side of the window looks correct on the
screen it was written for, and a touch filter that swallows every tap looks
like ordinary defensive code. Copying a nearby line is enough to reintroduce
either, which is exactly how both came back.
"""

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

SCREENS = sorted((Path(__file__).resolve().parents[1] / 'libs' / 'screens').glob('*.py'))


def offenders(pattern):
    found = []
    for path in SCREENS:
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if pattern.search(line):
                found.append(f'{path.name}:{number}')
    return found


MEASURED_AGAINST_ONE_SIDE = re.compile(r'Window\.(height|width) \* 0\.0\d+')


def test_a_gap_is_measured_against_the_short_side():
    """Paddings, spacings and radii go through short_side(), not Window.height.

    On the landscape panel these were written for, the height is the short side,
    so the mistake is invisible until a booth is stood upright — where it made
    every gap and every card almost twice the size it should be.
    """
    assert offenders(MEASURED_AGAINST_ONE_SIDE) == []


WAITS_FOR_A_MOUSE = re.compile(r'MouseMotionEvent')


def test_no_button_waits_for_a_mouse_event():
    """Touch reaches Kivy through the raw provider on the booth's Wayland kiosk.

    A handler that returns unless the touch was a synthesized mouse click is a
    button that never fires there — and the import went away with the last of
    them, so the line now raises a NameError instead of quietly doing nothing.
    """
    assert offenders(WAITS_FOR_A_MOUSE) == []
