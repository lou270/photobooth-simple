"""What makes a booth this evening's booth: its name, its date, its welcome.

An operator dresses the booth for each event from the admin page: a title and a
subtitle on the welcome screen, a photo behind them, and a name that templates
print on every sheet. Everything here is plain data and files, so the screens,
the collage builder and the web server can share it without importing each
other, and without importing Kivy.
"""

import importlib.util
import logging
import re
from datetime import datetime
from pathlib import Path

Logger = logging.getLogger('kivy.photobooth')

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Files the operator uploads for one event. Outside assets/, which is tracked,
# and outside DCIM/, which "delete all sessions" empties between two events
# while the decoration is typically kept for the next day.
EVENT_DIRECTORY = PROJECT_ROOT / 'event'
WELCOME_BACKGROUND_PATH = EVENT_DIRECTORY / 'welcome_background.jpg'
DEFAULT_WELCOME_BACKGROUND = PROJECT_ROOT / 'assets' / 'backgrounds' / 'bg_waiting.jpeg'

DEFAULT_DATE_FORMAT = '%d/%m/%Y'

# The welcome screen's lettering, one look per kind of evening. Each pairs a
# title face with a plainer one for the subtitle: a script or a display serif
# reads beautifully in large words and poorly in a line of names and a date.
# All under the SIL Open Font License, shipped because the booth is offline.
WELCOME_FONT_DIRECTORY = PROJECT_ROOT / 'assets' / 'fonts' / 'welcome'
WELCOME_FONTS = {
    'elegant': ('PlayfairDisplay.ttf', 'Montserrat-Medium.ttf'),
    'script': ('GreatVibes-Regular.ttf', 'Montserrat-Medium.ttf'),
    'modern': ('Montserrat-Bold.ttf', 'Montserrat-Medium.ttf'),
    'playful': ('Fredoka-SemiBold.ttf', 'Fredoka-Medium.ttf'),
}
DEFAULT_WELCOME_FONT = 'elegant'

# The words a template may put in its text: {event}, {date}, {time}. Anything
# else between braces is left as written, so a stray brace in an event name, or
# a placeholder from a newer version, prints as text instead of failing.
PLACEHOLDER_PATTERN = re.compile(r'\{(event|date|time)\}')
PLACEHOLDERS = ('event', 'date', 'time')


def welcome_background():
    """The photo behind the welcome screen: the event's own, or the shipped one."""
    if WELCOME_BACKGROUND_PATH.is_file():
        return WELCOME_BACKGROUND_PATH
    return DEFAULT_WELCOME_BACKGROUND


def welcome_fonts(style):
    """The (title, subtitle) font files for a lettering style, by path."""
    title, subtitle = WELCOME_FONTS.get(style, WELCOME_FONTS[DEFAULT_WELCOME_FONT])
    return str(WELCOME_FONT_DIRECTORY / title), str(WELCOME_FONT_DIRECTORY / subtitle)


def text_values(event_name='', date_format=DEFAULT_DATE_FORMAT, now=None):
    """The words placeholders stand for, at the moment a collage is built."""
    now = now or datetime.now()
    try:
        date = now.strftime(date_format or DEFAULT_DATE_FORMAT)
    except ValueError:
        date = now.strftime(DEFAULT_DATE_FORMAT)
    return {
        'event': event_name or '',
        'date': date,
        'time': now.strftime('%H:%M'),
    }


def fill_placeholders(text, values):
    return PLACEHOLDER_PATTERN.sub(lambda match: str(values.get(match.group(1), '')), text or '')


def font_path(bold=False):
    """The font printed text is drawn in, and the one the template editor shows.

    Roboto, as shipped inside Kivy: the booth already depends on it, so text on
    a print needs no font of its own in the repository. Located without
    importing Kivy, which would open a window in a headless process.
    """
    spec = importlib.util.find_spec('kivy')
    if spec is None or not spec.submodule_search_locations:
        return None
    name = 'Roboto-Bold.ttf' if bold else 'Roboto-Regular.ttf'
    path = Path(list(spec.submodule_search_locations)[0]) / 'data' / 'fonts' / name
    if not path.is_file():
        Logger.warning('Event: font %s not found', path)
        return None
    return path
