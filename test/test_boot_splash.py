"""The picture shown while the booth boots, and the loading screen after it.

Plymouth draws on the panel as it is mounted, while the booth turns its
interface by ROTATION. Getting that mapping backwards produces a splash lying on
its side on the one booth that stands upright, which nobody sees until the
evening it is switched on - hence the tests on where things land.
"""

import json
import os
import sys
from pathlib import Path

import pytest
from PIL import Image

os.environ.setdefault('KIVY_NO_ARGS', '1')
os.environ.setdefault('KIVY_GL_BACKEND', 'mock')

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs import boot_splash, i18n

LOCALES = Path(__file__).resolve().parents[1] / 'locales'
ROTATIONS = (0, 90, 180, 270)


def marked_photo(tmp_path, guest_size, mark):
    """A grey photo with one red square at `mark`, a fraction of the guest's view."""
    width, height = guest_size
    photo = Image.new('RGB', guest_size, (128, 128, 128))
    x, y = int(mark[0] * width), int(mark[1] * height)
    photo.paste((255, 0, 0), (x - 6, y - 6, x + 6, y + 6))
    path = tmp_path / 'welcome.png'
    photo.save(path)
    return path


def red_centre(picture):
    pixels = picture.load()
    found = [
        (x, y)
        for y in range(picture.height)
        for x in range(picture.width)
        if pixels[x, y][0] > 120 and pixels[x, y][1] < 60
    ]
    assert found, 'the mark did not survive'
    return (
        sum(x for x, _ in found) / len(found) / picture.width,
        sum(y for _, y in found) / len(found) / picture.height,
    )


@pytest.mark.parametrize('rotation', ROTATIONS)
def test_the_picture_fills_the_panel_as_mounted(tmp_path, rotation):
    panel = (320, 200)
    source = marked_photo(tmp_path, boot_splash.guest_size(panel, rotation), (0.5, 0.5))

    picture = boot_splash.render_background(source, panel, rotation)

    assert picture.size == panel


@pytest.mark.parametrize('rotation', ROTATIONS)
def test_the_dots_are_placed_where_the_picture_turned_them(tmp_path, rotation):
    """The dots and the picture must turn together, whichever way that is."""
    panel = (320, 200)
    mark = (0.3, 0.8)
    source = marked_photo(tmp_path, boot_splash.guest_size(panel, rotation), mark)

    picture = boot_splash.render_background(source, panel, rotation)

    assert red_centre(picture) == pytest.approx(boot_splash.to_panel_fraction(mark, rotation), abs=0.03)


@pytest.mark.parametrize('rotation', ROTATIONS)
def test_the_dots_run_the_way_a_guest_reads(tmp_path, rotation):
    panel = (320, 200)
    left, right = (0.4, 0.5), (0.6, 0.5)
    guest = boot_splash.guest_size(panel, rotation)

    left_on_panel = red_centre(boot_splash.render_background(marked_photo(tmp_path, guest, left), panel, rotation))
    right_on_panel = red_centre(boot_splash.render_background(marked_photo(tmp_path, guest, right), panel, rotation))

    step_x, step_y = boot_splash.guest_right_on_panel(rotation)
    moved = (right_on_panel[0] - left_on_panel[0], right_on_panel[1] - left_on_panel[1])
    assert moved[0] * step_x + moved[1] * step_y > 0
    assert abs(moved[0] * step_y) + abs(moved[1] * step_x) == pytest.approx(0, abs=0.02)


def test_the_theme_is_written_for_where_it_is_installed(tmp_path):
    source = marked_photo(tmp_path, (1080, 1920), (0.5, 0.5))

    paths = boot_splash.build_theme(tmp_path / 'theme', '/usr/share/plymouth/themes/photobooth', source, (1920, 1080), 90)

    assert Image.open(paths['splash']).size == (1920, 1080)
    assert Image.open(paths['dot']).mode == 'RGBA'
    descriptor = paths['descriptor'].read_bytes().decode('utf-8')
    assert 'ModuleName=script' in descriptor
    assert 'ScriptFile=/usr/share/plymouth/themes/photobooth/photobooth.script' in descriptor
    script = paths['script'].read_bytes().decode('utf-8')
    assert 'Image("splash.png")' in script
    assert 'Plymouth.SetRefreshFunction(refresh_callback);' in script


def test_the_theme_files_have_unix_line_endings(tmp_path):
    """Written on Windows in development, read by Plymouth on Linux."""
    source = marked_photo(tmp_path, (320, 200), (0.5, 0.5))
    paths = boot_splash.build_theme(tmp_path / 'theme', '/themes/photobooth', source, (320, 200), 0)

    assert b'\r\n' not in paths['script'].read_bytes()
    assert b'\r\n' not in paths['descriptor'].read_bytes()


# --- the application's loading screen ---------------------------------------

STARTUP_KEYS = ('title', 'camera', 'templates', 'storage', 'services', 'screens')


@pytest.mark.parametrize('lang', i18n.AVAILABLE_LANGUAGES)
def test_every_startup_step_is_named_in_every_language(lang):
    texts = json.loads((LOCALES / f'{lang}.json').read_text(encoding='utf-8'))
    assert sorted(texts['loading']) == sorted(STARTUP_KEYS)


class FakeLoading:
    def __init__(self):
        self.shown = []

    def show_step(self, caption, progress):
        self.shown.append((caption, progress))


class FakeWindow:
    """Only the flip: the moment a drawn frame reaches the screen."""

    def __init__(self):
        self.on_flip = []

    def bind(self, on_flip):
        self.on_flip.append(on_flip)

    def unbind(self, on_flip):
        self.on_flip.remove(on_flip)

    def flip(self):
        for callback in list(self.on_flip):
            callback(self)


def test_a_startup_step_waits_for_its_caption_to_reach_the_screen(monkeypatch):
    """A step holds the main loop, so its caption must be on screen before it starts.

    The first step, the camera, is the slow one on a DSLR booth - and it was the
    one that used to run before its caption had been drawn.
    """
    import photoboothapp
    from photoboothapp import PhotoboothApp

    window = FakeWindow()
    scheduled = []
    monkeypatch.setattr(photoboothapp, 'Window', window)
    monkeypatch.setattr(photoboothapp.Clock, 'schedule_once', lambda callback, timeout=0: scheduled.append(callback))

    app = PhotoboothApp.__new__(PhotoboothApp)
    app.loading = FakeLoading()
    order = []
    app._show_booth = lambda: order.append('booth')
    app._startup_steps = [
        ('loading.camera', lambda: order.append('camera')),
        ('loading.screens', lambda: order.append('screens')),
    ]
    app._startup_step_count = 2

    app._announce_startup_step()
    assert [progress for _, progress in app.loading.shown] == [0.0]

    # Clock ticks before any frame is shown start nothing.
    while scheduled:
        scheduled.pop(0)(0)
    assert order == []

    for _ in range(2):
        window.flip()
        while scheduled:
            scheduled.pop(0)(0)

    assert order == ['camera', 'screens', 'booth']
    assert [progress for _, progress in app.loading.shown] == [0.0, 0.5]
    assert window.on_flip == []
