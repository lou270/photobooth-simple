"""Dressing the booth for one event: its name on the prints, its welcome screen.

An operator sets these on site, often an hour before guests arrive, from a
phone. What they type must print, whatever it contains; what they upload must
be something the booth can show at its next start; and a template's text must
never leave the sheet, however long the name turns out to be.
"""

import io
import os
import sys
import textwrap
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

os.environ.setdefault('KIVY_NO_ARGS', '1')
os.environ.setdefault('KIVY_GL_BACKEND', 'mock')

sys.path.append(str(Path(__file__).resolve().parents[1]))
import libs.config as config_module
from libs import event
from libs.config import Config
from libs.template_collage import TemplateCollage
from libs.template_schema import TemplateValidationError, validate_template
from libs.webserver import WebServer

ADMIN_PASSWORD = 'correct horse'
MOMENT = datetime(2026, 9, 13, 21, 47)


# --- placeholders ------------------------------------------------------------

def test_placeholders_become_the_event_s_words():
    values = event.text_values('Lou & Max', '%d/%m/%Y', now=MOMENT)

    assert event.fill_placeholders('{event} - {date} {time}', values) == 'Lou & Max - 13/09/2026 21:47'


def test_an_unknown_placeholder_prints_as_written():
    """A brace in an event name is text, not a mistake to fail on."""
    values = event.text_values('Lou', now=MOMENT)

    assert event.fill_placeholders('{event} {guest} {}', values) == 'Lou {guest} {}'


def test_the_print_font_is_found_without_importing_kivy():
    assert event.font_path() is not None
    assert event.font_path(bold=True).name == 'Roboto-Bold.ttf'


# --- config.ini --------------------------------------------------------------

def write_config(tmp_path, monkeypatch, body):
    config_path = tmp_path / 'config.ini'
    config_path.write_text(textwrap.dedent(body), encoding='utf-8')
    monkeypatch.setattr(config_module, 'CONFIG_PATH', config_path)
    return Config()


def test_an_event_name_with_a_percent_sign_is_read_as_typed(tmp_path, monkeypatch):
    """configparser interpolates % by default; "100% fun" would stop the booth."""
    config = write_config(tmp_path, monkeypatch, """
        [Event]
        EVENT_NAME = 100% fun
        WELCOME_TITLE = Soirée 100%
        DATE_FORMAT = %d %m
    """)

    assert config.get_event_name() == '100% fun'
    assert config.get_welcome_title() == 'Soirée 100%'
    assert config.get_date_format() == '%d %m'


def test_nothing_set_means_the_booth_s_own_welcome_and_no_slideshow(tmp_path, monkeypatch):
    config = write_config(tmp_path, monkeypatch, """
        [Global]
        SHARE = True
    """)

    assert config.get_welcome_title() == ''
    assert config.get_welcome_subtitle() == ''
    assert config.get_date_format() == event.DEFAULT_DATE_FORMAT
    assert config.get_welcome_font() == event.DEFAULT_WELCOME_FONT
    assert config.get_slideshow() is False


def test_an_unknown_lettering_falls_back_to_the_booth_s_own(tmp_path, monkeypatch):
    config = write_config(tmp_path, monkeypatch, """
        [Event]
        WELCOME_FONT = Comic Sans
    """)

    assert config.get_welcome_font() == event.DEFAULT_WELCOME_FONT


def test_every_lettering_ships_its_fonts():
    """A style the admin page offers with a file missing would start the booth
    on a font Kivy cannot open."""
    for style in event.WELCOME_FONTS:
        for path in event.welcome_fonts(style):
            assert Path(path).is_file(), f'{style}: {path} is missing'


def test_slideshow_delays_have_a_floor(tmp_path, monkeypatch):
    """A slideshow that starts a second after the last guest leaves is a
    welcome screen nobody gets to see."""
    config = write_config(tmp_path, monkeypatch, """
        [Slideshow]
        SLIDESHOW = True
        SLIDESHOW_IDLE_SECONDS = 1
        SLIDESHOW_PHOTO_SECONDS = 0
    """)

    assert config.get_slideshow() is True
    assert config.get_slideshow_idle_seconds() == 10
    assert config.get_slideshow_photo_seconds() == 2


# --- templates ---------------------------------------------------------------

def text_template(**text):
    box = {'x': 100, 'y': 900, 'width': 1000, 'height': 150, 'text': '{event}'}
    box.update(text)
    return {
        'name': 'With text',
        'page': {'width': 1200, 'height': 1200},
        'photos': [{'x': 0, 'y': 0, 'width': 10, 'height': 10}],
        'texts': [box],
    }


def test_a_text_box_is_accepted_with_its_defaults():
    validated = validate_template(text_template())

    assert validated['texts'] == [{
        'x': 100, 'y': 900, 'width': 1000, 'height': 150,
        'text': '{event}', 'color': '#000000', 'align': 'center', 'bold': False,
    }]


def test_a_template_without_texts_has_none():
    template = text_template()
    del template['texts']

    assert validate_template(template)['texts'] == []


@pytest.mark.parametrize('override', [
    {'x': 1100},                 # leaves the page
    {'color': 'red'},
    {'align': 'justify'},
    {'text': 'x' * 201},
    {'text': 42},
])
def test_a_malformed_text_box_is_refused(override):
    with pytest.raises(TemplateValidationError):
        validate_template(text_template(**override))


def ink(canvas):
    """Where anything but the white page was drawn."""
    return np.argwhere(canvas.min(axis=2) < 200)


def assemble(template, name):
    collage = TemplateCollage(
        template=template,
        text_values=lambda: event.text_values(name, now=MOMENT),
    )
    return collage.assemble([])


def test_the_event_name_is_printed_inside_its_box():
    canvas = assemble(text_template(), 'Lou & Max')

    drawn = ink(canvas)
    assert len(drawn) > 0
    top, left = drawn.min(axis=0)
    bottom, right = drawn.max(axis=0)
    assert 900 <= top and bottom < 1050
    assert 100 <= left and right < 1100


def test_a_long_name_shrinks_instead_of_leaving_its_box():
    canvas = assemble(text_template(), 'Le mariage absolument inoubliable de Louise et Maximilien, 2026')

    drawn = ink(canvas)
    assert drawn[:, 1].min() >= 100 and drawn[:, 1].max() < 1100
    assert drawn[:, 0].min() >= 900 and drawn[:, 0].max() < 1050


def test_an_empty_event_name_prints_nothing():
    """A template drawn for {event} on a booth with no name set leaves the
    space empty rather than printing the placeholder."""
    assert len(ink(assemble(text_template(), ''))) == 0


def test_the_text_takes_the_colour_it_was_given():
    canvas = assemble(text_template(color='#ff0000'), 'LOU')

    reds = canvas[(canvas[:, :, 2] > 200) & (canvas[:, :, 1] < 80) & (canvas[:, :, 0] < 80)]
    assert len(reds) > 0


def test_a_failing_value_provider_does_not_cost_the_print():
    def broken():
        raise RuntimeError('config went away')

    collage = TemplateCollage(template=text_template(text='{date}'), text_values=broken)

    assert len(ink(collage.assemble([]))) > 0


# --- the welcome photo, from the admin page ------------------------------------

@pytest.fixture
def server(tmp_path):
    instance = WebServer(str(tmp_path / 'save'), admin_password=ADMIN_PASSWORD)
    instance.templates_directory = str(tmp_path / 'templates')
    instance.logs_directory = str(tmp_path / 'logs')
    instance.config_file = str(tmp_path / 'config.ini')
    instance.welcome_background_path = str(tmp_path / 'event' / 'welcome_background.jpg')
    Path(instance.config_file).write_text('[Event]\nEVENT_NAME = Lou & Max\nDATE_FORMAT = %Y\n', encoding='utf-8')
    return instance


@pytest.fixture
def admin(server):
    client = server.app.test_client()
    client.post('/admin/login', data={'password': ADMIN_PASSWORD})
    return client


def image_bytes(width, height, extension='.png'):
    image = np.full((height, width, 3), (40, 120, 200), dtype=np.uint8)
    return cv2.imencode(extension, image)[1].tobytes()


def upload(client, data):
    return client.post(
        '/admin/event/background',
        data={'background': (io.BytesIO(data), 'photo.png')},
        content_type='multipart/form-data',
    )


def test_an_uploaded_photo_is_stored_as_a_screen_sized_jpeg(server, admin):
    response = upload(admin, image_bytes(5000, 2500))

    assert response.status_code == 200
    stored = cv2.imread(server.welcome_background_path)
    assert stored is not None
    assert max(stored.shape[:2]) == 3840
    assert Path(server.welcome_background_path).read_bytes()[:2] == b'\xff\xd8'


def test_a_file_that_is_not_a_photo_is_refused(server, admin):
    response = upload(admin, b'not a picture at all')

    assert response.status_code == 400
    assert not os.path.exists(server.welcome_background_path)


def test_the_photo_can_be_taken_back(server, admin):
    upload(admin, image_bytes(800, 600))

    admin.post('/admin/event/background/delete')

    assert not os.path.exists(server.welcome_background_path)


def test_a_visitor_cannot_change_the_welcome_photo(server):
    visitor = server.app.test_client()

    response = upload(visitor, image_bytes(800, 600))

    assert response.status_code == 302
    assert not os.path.exists(server.welcome_background_path)


def test_the_editor_gets_the_print_font_and_today_s_values(admin):
    font = admin.get('/admin/editor/fonts/bold')
    payload = admin.get('/api/templates').get_json()

    assert font.status_code == 200 and font.mimetype == 'font/ttf'
    assert admin.get('/admin/editor/fonts/../../config').status_code == 404
    assert payload['text_values']['event'] == 'Lou & Max'
    assert payload['text_values']['date'] == str(datetime.now().year)


def test_the_welcome_screen_falls_back_to_the_booth_s_own_photo(tmp_path, monkeypatch):
    monkeypatch.setattr(event, 'WELCOME_BACKGROUND_PATH', tmp_path / 'absent.jpg')
    assert event.welcome_background() == event.DEFAULT_WELCOME_BACKGROUND

    uploaded = tmp_path / 'welcome_background.jpg'
    uploaded.write_bytes(image_bytes(10, 10, '.jpg'))
    monkeypatch.setattr(event, 'WELCOME_BACKGROUND_PATH', uploaded)
    assert event.welcome_background() == uploaded
