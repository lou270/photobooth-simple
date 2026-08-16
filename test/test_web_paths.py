"""Everything standing between a request path and a file on disk."""

import os
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.webserver.paths import (
    is_valid_image_filename,
    is_valid_session,
    safe_log_path,
    safe_photo_path,
    sanitize_template_filename,
    unique_template_filename,
)


@pytest.fixture
def gallery(tmp_path):
    session = tmp_path / '20260816_120000'
    session.mkdir()
    (session / 'collage.jpg').write_bytes(b'collage')
    (session / 'capture-0.jpg').write_bytes(b'capture')
    return tmp_path


# --- names the booth produces ----------------------------------------------

@pytest.mark.parametrize('session', ['20260816_120000', '19991231_235959'])
def test_a_session_name_is_accepted(session):
    assert is_valid_session(session)


@pytest.mark.parametrize('session', [
    '', '..', '2026-08-16_120000', '20260816', '20260816_12000', '20260816_1200000',
    'a0260816_120000', '20260816_120000/..', None, 42,
])
def test_anything_else_is_not_a_session(session):
    assert not is_valid_session(session)


@pytest.mark.parametrize('filename', ['collage.jpg', 'capture-0.jpg', 'capture-11.jpg', 'COLLAGE.JPG'])
def test_a_photo_name_is_accepted(filename):
    assert is_valid_image_filename(filename)


@pytest.mark.parametrize('filename', [
    '', 'collage.png', 'collage_small.jpg', 'collage_print.jpg', 'capture-.jpg',
    '../config.ini', 'collage.jpg.exe', '.stats.json', None,
])
def test_anything_else_is_not_a_photo(filename):
    assert not is_valid_image_filename(filename)


# --- resolving a photo ------------------------------------------------------

def test_a_real_photo_resolves(gallery):
    resolved = safe_photo_path(str(gallery), '20260816_120000', 'collage.jpg')

    assert resolved is not None
    assert Path(resolved).read_bytes() == b'collage'


@pytest.mark.parametrize('session,filename', [
    ('..', 'collage.jpg'),
    ('20260816_120000', '../../config.ini'),
    ('20260816_120000', 'collage_small.jpg'),
    ('20260816_999999', 'collage.jpg'),      # well formed, does not exist
    ('20260816_120000', 'capture-9.jpg'),    # well formed, does not exist
])
def test_a_photo_outside_the_gallery_is_refused(gallery, session, filename):
    assert safe_photo_path(str(gallery), session, filename) is None


def test_a_symlink_pointing_out_of_the_gallery_is_refused(gallery, tmp_path):
    """The name looks right; realpath is what tells the truth."""
    secret = tmp_path.parent / 'secret.jpg'
    secret.write_bytes(b'not yours')
    link = gallery / '20260816_120000' / 'capture-1.jpg'
    try:
        os.symlink(secret, link)
    except (OSError, NotImplementedError):
        pytest.skip('creating a symlink needs privileges on this platform')

    assert safe_photo_path(str(gallery), '20260816_120000', 'capture-1.jpg') is None


# --- resolving a log --------------------------------------------------------

def test_a_real_log_resolves(tmp_path):
    (tmp_path / 'photobooth.txt').write_text('log', encoding='utf-8')

    assert safe_log_path(str(tmp_path), 'photobooth.txt') == str(tmp_path / 'photobooth.txt')


@pytest.mark.parametrize('filename', [
    '../config.ini', '..', 'nested/photobooth.txt', '/etc/passwd',
    'absent.txt', '', None,
])
def test_a_log_outside_the_directory_is_refused(tmp_path, filename):
    (tmp_path / 'photobooth.txt').write_text('log', encoding='utf-8')

    assert safe_log_path(str(tmp_path), filename) is None


def test_a_subdirectory_is_not_a_log(tmp_path):
    (tmp_path / 'archive').mkdir()
    assert safe_log_path(str(tmp_path), 'archive') is None


# --- naming a template ------------------------------------------------------

@pytest.mark.parametrize('given,expected', [
    ('strip.json', 'strip.json'),
    ('strip', 'strip.json'),
    ('Photo Strip', 'Photo_Strip.json'),
    ('../../etc/passwd', 'passwd.json'),
    ('/absolute/path/frame.json', 'frame.json'),
    ('...', 'template.json'),
    ('', 'template.json'),
    ('éàü', 'template.json'),
    ('a b/c d.json', 'c_d.json'),
])
def test_a_template_can_only_be_named_next_to_the_others(given, expected):
    assert sanitize_template_filename(given) == expected


def test_a_template_falls_back_to_its_own_name():
    assert sanitize_template_filename(None, 'Full Page') == 'Full_Page.json'


def test_a_new_template_never_overwrites_an_existing_one(tmp_path):
    (tmp_path / 'strip.json').write_text('{}', encoding='utf-8')
    (tmp_path / 'strip_1.json').write_text('{}', encoding='utf-8')

    assert unique_template_filename(str(tmp_path), 'strip.json') == 'strip_2.json'


def test_an_unused_name_is_left_alone(tmp_path):
    assert unique_template_filename(str(tmp_path), 'strip.json') == 'strip.json'
