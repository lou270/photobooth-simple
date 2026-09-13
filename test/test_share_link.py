"""The page the sharing QR code opens: one guest's own collage.

The code goes on screen while the booth is still writing the session, so a
phone can be quicker than the disk. That phone must wait for its photo rather
than be sent somewhere else, and a link the booth never announced must not
pretend to be on its way.
"""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault('KIVY_NO_ARGS', '1')
os.environ.setdefault('KIVY_GL_BACKEND', 'mock')

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs import i18n
from libs.webserver import WebServer

SESSION = '20260913_214703'


@pytest.fixture
def server(tmp_path):
    instance = WebServer(str(tmp_path / 'save'))
    instance.templates_directory = str(tmp_path / 'templates')
    instance.logs_directory = str(tmp_path / 'logs')
    return instance


@pytest.fixture
def client(server):
    return server.app.test_client()


def save_collage(server, session=SESSION):
    directory = Path(server.save_directory, session)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'collage.jpg').write_bytes(b'collage bytes')


def test_a_saved_session_opens_on_its_own_collage(server, client):
    save_collage(server)

    response = client.get(f'/collage/{SESSION}')

    assert response.status_code == 200
    assert f'/image/{SESSION}/collage.jpg'.encode() in response.data


def test_an_announced_session_waits_for_its_collage(server, client):
    server.expect_session(SESSION)

    response = client.get(f'/collage/{SESSION}', headers={'Accept-Language': 'fr'})

    assert response.status_code == 200
    assert i18n.translate('fr', 'web.gallery.pending_title').encode() in response.data
    assert b'http-equiv="refresh"' in response.data
    assert response.headers['Cache-Control'] == 'no-store'


def test_the_waiting_page_gives_way_to_the_collage_once_saved(server, client):
    server.expect_session(SESSION)
    client.get(f'/collage/{SESSION}')

    save_collage(server)

    assert b'http-equiv="refresh"' not in client.get(f'/collage/{SESSION}').data


def test_an_unknown_session_is_not_waited_for(client):
    response = client.get(f'/collage/{SESSION}')

    assert response.status_code == 302


def test_an_announcement_does_not_wait_forever(server, client, monkeypatch):
    """A session that was never saved stops being on its way."""
    server.expect_session(SESSION)
    monkeypatch.setattr(WebServer, 'EXPECTED_SESSION_SECONDS', -1)

    assert client.get(f'/collage/{SESSION}').status_code == 302


def test_announcements_are_bounded(server):
    for second in range(WebServer.MAX_EXPECTED_SESSIONS + 5):
        server.expect_session(f'20260913_21{second // 60:02d}{second % 60:02d}')

    assert len(server._expected_sessions) == WebServer.MAX_EXPECTED_SESSIONS
    assert not server.is_session_expected('20260913_210000')
