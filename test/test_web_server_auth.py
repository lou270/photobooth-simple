"""Which routes an unauthenticated visitor can reach.

The template API used to be fully open: anyone on the network could write or
delete layout files on the booth.
"""

import io
import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.web_server import WebServer

ADMIN_PASSWORD = 'correct horse'


@pytest.fixture
def server(tmp_path):
    """A server whose templates directory is isolated from the project's own."""
    instance = WebServer(str(tmp_path / 'save'), admin_password=ADMIN_PASSWORD)
    instance.templates_directory = str(tmp_path / 'templates')
    instance.logs_directory = str(tmp_path / 'logs')
    return instance


@pytest.fixture
def client(server):
    return server.app.test_client()


def login(client, password=ADMIN_PASSWORD):
    return client.post('/admin/login', data={'password': password})


def valid_template(name='Strip'):
    return {
        'name': name,
        'page': {'width': 600, 'height': 1800},
        'photos': [{'x': 30, 'y': 30, 'width': 540, 'height': 520}],
    }


@pytest.mark.parametrize('method,path', [
    ('get', '/api/templates'),
    ('post', '/api/templates'),
    ('delete', '/api/templates/strip.json'),
    ('get', '/api/admin/logs'),
    ('get', '/api/admin/logs/photobooth.txt'),
    ('delete', '/api/admin/logs'),
])
def test_api_routes_reject_anonymous_callers_with_401(client, method, path):
    response = getattr(client, method)(path)
    assert response.status_code == 401
    assert response.get_json()['error'] == 'Authentication required'


@pytest.mark.parametrize('path', ['/admin', '/admin/editor', '/admin/logs', '/stats',
                                  '/download/all-photos'])
def test_admin_pages_redirect_anonymous_visitors_to_the_login(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert '/admin/login' in response.headers['Location']


def test_an_anonymous_caller_cannot_create_a_template(client, server):
    client.post('/api/templates', json={'template': valid_template()})
    assert not Path(server.templates_directory).exists()


def test_an_authenticated_admin_can_create_a_template(client, server):
    login(client)

    response = client.post('/api/templates', json={'template': valid_template()})

    assert response.status_code == 200
    saved = Path(server.templates_directory, response.get_json()['filename'])
    assert json.loads(saved.read_text(encoding='utf-8'))['name'] == 'Strip'


def test_an_invalid_template_is_refused_with_a_reason(client):
    login(client)

    response = client.post('/api/templates', json={
        'template': valid_template() | {'page': {'width': 0, 'height': 10}},
    })

    assert response.status_code == 400
    assert 'page.width' in response.get_json()['error']


def test_a_template_naming_a_file_outside_the_directory_is_refused(client):
    login(client)

    response = client.post('/api/templates', json={
        'template': valid_template() | {'background': '../../config.ini'},
    })

    assert response.status_code == 400


def test_a_wrong_password_does_not_open_the_api(client):
    login(client, password='nope')
    assert client.get('/api/templates').status_code == 401


def test_the_gallery_stays_open_to_guests(client):
    assert client.get('/gallery').status_code == 200


# --- bulk download ---------------------------------------------------------

def test_the_streamed_archive_holds_every_session(client, server):
    session = Path(server.save_directory, '20260816_120000')
    session.mkdir(parents=True)
    (session / 'collage.jpg').write_bytes(b'collage bytes')
    (session / 'capture-0.jpg').write_bytes(b'capture bytes')
    login(client)

    response = client.get('/download/all-photos')

    assert response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(response.get_data()))
    assert sorted(archive.namelist()) == [
        '20260816_120000/capture-0.jpg', '20260816_120000/collage.jpg',
    ]
    assert archive.read('20260816_120000/collage.jpg') == b'collage bytes'


def test_an_empty_gallery_reports_nothing_to_download(client, server):
    login(client)
    assert client.get('/download/all-photos').status_code == 404


# --- watchdog --------------------------------------------------------------

def test_the_watchdog_gives_up_instead_of_retrying_forever(tmp_path):
    """A port held by a leftover process does not free itself."""
    server = WebServer(str(tmp_path / 'save'), admin_password=ADMIN_PASSWORD)
    server.server_thread = SimpleNamespace(is_alive=lambda: False)
    server._watchdog_stop = SimpleNamespace(wait=lambda timeout: False)
    attempts = []

    def failing_start(force_restart=False):
        attempts.append(force_restart)
        return False

    server.start = failing_start

    server._watchdog_loop()  # returns instead of looping forever

    assert len(attempts) == len(WebServer.WATCHDOG_BACKOFF_SECONDS)


def test_the_watchdog_backoff_grows():
    delays = WebServer.WATCHDOG_BACKOFF_SECONDS
    assert list(delays) == sorted(delays)
    assert delays[-1] >= 60


@pytest.mark.parametrize('weak_password', ['admin', 'Admin', 'password', '1234', 'court'])
def test_a_weak_admin_password_keeps_admin_access_disabled(tmp_path, weak_password):
    """Fail closed: the booth still takes photos, only the web admin stays shut."""
    server = WebServer(str(tmp_path / 'save'), admin_password=weak_password)

    assert server.admin_password is None

    response = server.app.test_client().post('/admin/login', data={'password': weak_password})
    assert response.status_code == 403
    assert b'Admin access is disabled' in response.data


def test_a_strong_admin_password_is_accepted(tmp_path):
    server = WebServer(str(tmp_path / 'save'), admin_password='un mot de passe convenable')
    assert server.admin_password == 'un mot de passe convenable'


def test_repeated_failures_lock_the_client_out(client):
    for _ in range(4):
        assert login(client, password='wrong').status_code == 403

    assert login(client, password='wrong').status_code == 429
    # Even the right password has to wait out the lockout.
    assert login(client).status_code == 429


def test_a_successful_login_clears_earlier_failures(client):
    login(client, password='wrong')
    login(client, password='wrong')

    assert login(client).status_code == 302

    client.get('/admin/logout')
    assert login(client, password='wrong').status_code == 403
