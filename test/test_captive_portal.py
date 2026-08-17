"""What a phone is told before, and after, it has been through the portal.

The booth's access point has no uplink, so every phone on it is deciding whether
this network is worth staying on. It decides by comparing these answers against
what the vendor's own server would send, byte for byte. A wrong body here does
not raise anything; it just makes Android offer mobile data instead, all evening.
"""

import io
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.captive_portal import CaptivePortalClients
from libs.remote_store import RemoteStore
from libs.webserver import WebServer
from libs.webserver.captive import CAPTIVE_API_MEDIA_TYPE

BROWSER = {'Accept': 'text/html,application/xhtml+xml'}
CAPTIVE_API = {'Accept': CAPTIVE_API_MEDIA_TYPE}


def make_server(tmp_path, remote=True):
    store = RemoteStore(str(tmp_path / 'remote'), min_upload_interval=0)
    server = WebServer(
        str(tmp_path / 'save'),
        admin_password='correct horse',
        remote_store=store,
        remote_enabled=remote,
    )
    server.logs_directory = str(tmp_path / 'logs')
    return server


@pytest.fixture
def server(tmp_path):
    return make_server(tmp_path)


@pytest.fixture
def phone(server):
    return server.app.test_client()


def release(server):
    """Mark the calling client as having been through the portal."""
    server.captive_clients.release('127.0.0.1')


# --- the probes -------------------------------------------------------------

PROBE_PATHS = [
    '/generate_204', '/gen_204', '/generate204',
    '/hotspot-detect.html', '/library/test/success.html',
    '/success.txt', '/canonical.html',
    '/connecttest.txt', '/ncsi.txt',
]


@pytest.mark.parametrize('path', PROBE_PATHS)
def test_a_phone_that_has_not_seen_the_portal_is_sent_to_it(phone, path):
    """The redirect is what makes the sign-in notification appear at all."""
    response = phone.get(path)

    assert response.status_code == 302
    assert response.headers['Location'] == '/remote'


@pytest.mark.parametrize('path,status,body', [
    ('/generate_204', 204, b''),
    ('/gen_204', 204, b''),
    ('/generate204', 204, b''),
    ('/hotspot-detect.html', 200, b'<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>'),
    ('/library/test/success.html', 200, b'<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>'),
    ('/success.txt', 200, b'success\n'),
    ('/connecttest.txt', 200, b'Microsoft Connect Test'),
    ('/ncsi.txt', 200, b'Microsoft NCSI'),
])
def test_a_released_phone_gets_exactly_what_its_vendor_would_send(server, phone, path, status, body):
    release(server)

    response = phone.get(path)

    assert response.status_code == status
    assert response.data == body


def test_the_firefox_probe_answers_its_canonical_page(server, phone):
    release(server)

    response = phone.get('/canonical.html')

    assert b'captive-portal' in response.data
    assert response.mimetype == 'text/html'


def test_probe_answers_are_never_cached(server, phone):
    """A cached "you are free" would outlive the session that justified it."""
    release(server)

    response = phone.get('/generate_204')

    assert response.headers['Cache-Control'] == 'no-store'


def test_releasing_one_phone_leaves_the_others_captive(server):
    """Each guest arrives on their own and has to be shown the page."""
    server.captive_clients.release('192.168.4.20')

    other_phone = server.app.test_client()
    assert other_phone.get('/generate_204').status_code == 302


@pytest.mark.parametrize('path', ['/redirect', '/fwlink', '/check_network_status.txt', '/mobile/status.php'])
def test_the_paths_an_os_opens_always_lead_to_the_page(server, phone, path):
    """These are where an operating system sends the guest, not connectivity tests."""
    release(server)

    response = phone.get(path)

    assert response.status_code == 302
    assert response.headers['Location'] == '/remote'


def test_without_the_remote_camera_the_portal_is_the_gallery(tmp_path):
    client = make_server(tmp_path, remote=False).app.test_client()

    assert client.get('/generate_204').headers['Location'] == '/'


# --- the RFC 8908 API -------------------------------------------------------

def test_the_api_declares_the_media_type_the_rfc_defines(phone):
    """A phone that finds anything else here ignores the whole mechanism."""
    response = phone.get('/captive-portal/api', headers=CAPTIVE_API)

    assert response.mimetype == CAPTIVE_API_MEDIA_TYPE


def test_the_api_reports_captivity_and_where_to_go(phone):
    response = phone.get('/captive-portal/api', headers=CAPTIVE_API)
    payload = response.get_json(force=True)

    assert payload['captive'] is True
    assert payload['user-portal-url'].endswith('/remote')
    assert payload['user-portal-url'].startswith('http://')


def test_the_api_reports_freedom_once_the_guest_is_through(server, phone):
    release(server)

    payload = phone.get('/captive-portal/api', headers=CAPTIVE_API).get_json(force=True)

    assert payload['captive'] is False
    assert 'user-portal-url' not in payload


def test_the_portal_url_is_the_address_the_phone_itself_used(phone):
    """On a hijacked DNS, no other address is known to work from where it stands."""
    payload = phone.get(
        '/captive-portal/api',
        headers=CAPTIVE_API,
        base_url='http://192.168.4.1',
    ).get_json(force=True)

    assert payload['user-portal-url'] == 'http://192.168.4.1/remote'


def test_opening_the_api_address_in_a_browser_lands_on_the_page(phone):
    """RFC 8910 asks for this, and it keeps the advertised address usable by hand."""
    response = phone.get('/captive-portal/api', headers=BROWSER)

    assert response.status_code == 302
    assert response.headers['Location'] == '/remote'


# --- being released ---------------------------------------------------------

def test_the_guest_can_say_they_are_done(server, phone):
    assert phone.get('/generate_204').status_code == 302

    assert phone.post('/captive-portal/release').status_code == 200

    assert phone.get('/generate_204').status_code == 204


def test_sending_a_photo_releases_the_phone_on_its_own(server, phone):
    """Having uploaded is the clearest possible proof of not being stuck."""
    import cv2
    import numpy as np

    phone.get('/remote')
    photo = cv2.imencode('.jpg', np.full((60, 80, 3), 128, dtype=np.uint8))[1].tobytes()

    phone.post(
        '/remote/upload',
        data={'photo': (io.BytesIO(photo), 'phone.jpg')},
        content_type='multipart/form-data',
    )

    assert phone.get('/generate_204').status_code == 204


# --- browsing anywhere else -------------------------------------------------

def test_a_hijacked_domain_lands_on_the_portal(phone):
    """The booth answers DNS for the whole internet; a 404 reads as broken."""
    response = phone.get('/search', headers={**BROWSER, 'Host': 'www.google.com'})

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/remote')


def test_a_mistyped_address_on_the_booth_itself_still_says_not_found(phone):
    """A wrong admin URL is not a guest looking for the portal."""
    response = phone.get('/nothing-here', headers={**BROWSER, 'Host': '192.168.4.1:5000'})

    assert response.status_code == 404


def test_a_background_request_to_a_hijacked_domain_is_not_redirected(phone):
    """Only a browser navigating should be pulled to the portal, not a fetch()."""
    response = phone.get('/api/v1/thing', headers={'Accept': 'application/json', 'Host': 'example.com'})

    assert response.status_code == 404


# --- the client table -------------------------------------------------------

def test_a_release_expires_so_the_table_does_not_grow_forever():
    clock = {'now': 0.0}
    clients = CaptivePortalClients(session_seconds=60, time_source=lambda: clock['now'])

    clients.release('phone')
    assert clients.is_released('phone')

    clock['now'] = 61.0
    assert not clients.is_released('phone')
    assert clients.count() == 0


def test_the_table_is_bounded_whatever_arrives():
    clients = CaptivePortalClients(max_clients=3)

    for index in range(20):
        clients.release(f'phone-{index}')

    assert clients.count() <= 3


def test_releasing_twice_is_reported_once():
    clients = CaptivePortalClients()

    assert clients.release('phone') is True
    assert clients.release('phone') is False
