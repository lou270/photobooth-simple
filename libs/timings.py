"""How long the booth waits, in seconds: the delays an operator can tune.

The screens are imported long before config.ini is read, and built once, so a
delay copied into a class attribute or a module constant at import would never
see the operator's value. They read TIMINGS when a delay starts instead, and the
application fills it from config.ini before building any screen, the way the
language is set.

Kept free of Kivy, like libs/config.py, which takes its fallbacks from here.
"""

DEFAULTS = {
    # Keeping the shot is what nearly everyone does; retaking is the exception,
    # so it is the one that needs a button press. Any touch restarts it.
    'auto_keep': 6,
    'countdown_home': 30,
    'select_format_home': 30,
    'review_home': 60,
    # Longer than the others: a guest browsing the photos phones sent is reading
    # a wall of faces, not answering a prompt.
    'remote_gallery_home': 90,
    # An error a guest can walk away from - a print that failed, say - left the
    # booth showing their failure to everyone who came after them. Only applied
    # when there is a continue button: a booth in maintenance is meant to stay
    # there, and sending it home would walk it into the same wall again.
    'error_home': 90,
    # The codes are the one overlay with nothing behind it that times out: the
    # welcome screen never leaves on its own, and the popup swallows every touch
    # to stop a tap on the card from starting a session. Long enough for two
    # scans and a phone joining a network; every touch gives the delay back.
    'qr_popup': 45,
    # A floor under the printing screen, because a printer that answers at once
    # would otherwise leave nothing on screen long enough to read. A touch skips it.
    'print_min': 6,
    # How long a capture may take before the camera is reset.
    'shot_timeout': 10,
    # Ceiling on the printing itself, per sheet. PRINTER_WAIT_TIMEOUT is what an
    # operator sets for a printer that went away, and used to bound this too,
    # which meant a dye-sub taking its usual minute a sheet was reported to the
    # guest as a failure while the prints were coming out. Only a safety net
    # against a job CUPS never finishes, so it is generous.
    'print_sheet_timeout': 180,
}

# The confirm screen's walk-away timeout is a safety net rather than a visible
# countdown: auto-keep always fires first, so this only catches a guest who
# left with the screen somehow still waiting. It must outlast auto-keep.
CONFIRM_CAPTURE_HOME_FLOOR = 30
CONFIRM_CAPTURE_HOME_MARGIN = 10


class Timings:
    def __init__(self):
        self.update(DEFAULTS)

    def update(self, values):
        for name, seconds in values.items():
            if name not in DEFAULTS:
                raise KeyError(f'unknown timing {name!r}')
            setattr(self, name, seconds)

    @property
    def confirm_capture_home(self):
        return max(CONFIRM_CAPTURE_HOME_FLOOR, self.auto_keep + CONFIRM_CAPTURE_HOME_MARGIN)


TIMINGS = Timings()


class Timing:
    """A class attribute that reads TIMINGS each time, on the class or an instance.

        HOME_TIMEOUT_SECONDS = Timing('review_home')

    A subclass may still set a plain number over it, as the tests do.
    """

    def __init__(self, name):
        self.name = name

    def __get__(self, instance, owner=None):
        return getattr(TIMINGS, self.name)
