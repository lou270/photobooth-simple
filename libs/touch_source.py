"""Keep one path for the touchscreen, whichever one actually reaches Kivy.

On Linux Kivy listens to the touchscreen twice: through the window, where the
display server hands a tap over as a mouse click, and through probesysfs, which
reads /dev/input itself whenever the user may open it. Which of the two works
depends on how the booth was started - inside cage, from a desktop, by a user
who joined the input group before or after logging in - and when both do, every
tap arrives twice. A button that only moves to another screen hides that; the
countdown's start/cancel toggle does not, and cancelled itself on every tap.

Choosing one provider in the Kivy config would hold only for the setup it was
chosen on: dropping the mouse leaves a booth started from a console without
touch, and dropping probesysfs did the same under Wayfire. So nothing is chosen
in advance. A tap that begins on a second device right after one began on
another is the same tap seen twice: the device that delivered it late is
ignored from then on, and the one that delivered it first is the booth's.
"""

from kivy.logger import Logger


class TouchSourceFilter:
    # Both copies of a tap come from the same press, a few milliseconds apart.
    # Nobody moves from one input device to another this fast.
    DUPLICATE_WINDOW_SECONDS = 0.3

    def __init__(self, clock):
        self._clock = clock
        self._ignored = set()
        self._last_begin = None    # (device, time) of the last tap let through

    def on_motion(self, window, etype, me):
        """Window on_motion handler: True swallows the event before any widget."""
        device = me.device
        if device in self._ignored:
            return True
        if etype != 'begin' or not me.is_touch:
            return False
        now = self._clock()
        if self._last_begin is not None:
            first_device, first_time = self._last_begin
            if device != first_device and now - first_time < self.DUPLICATE_WINDOW_SECONDS:
                self._ignored.add(device)
                Logger.info(
                    'TouchSource: every tap arrives from both %s and %s, keeping %s only.',
                    first_device, device, first_device,
                )
                return True
        self._last_begin = (device, now)
        return False


def install(window, clock):
    """Filter every motion event the window receives; keep what this returns.

    Kivy binds a method through a weak reference: a filter nobody holds is
    collected at once, and the window quietly stops calling it.
    """
    touch_filter = TouchSourceFilter(clock)
    window.bind(on_motion=touch_filter.on_motion)
    return touch_filter
