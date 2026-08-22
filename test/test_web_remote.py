"""The remote capture area seen from the network.

A phone reaching these routes is an anonymous guest on the event's WiFi, so what
matters is the boundary: nothing is served while the feature is off, one phone
cannot read or remove another phone's photo, and moderation stays behind the
admin session.
"""

import io
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs import i18n
from libs.remote_store import RemoteStore
from libs.webserver import WebServer

ADMIN_PASSWORD = 'correct horse'


def jpeg_bytes(width=800, height=600):
    image = np.full((height, width, 3), (30, 90, 160), dtype=np.uint8)
    success, buffer = cv2.imencode('.jpg', image)
    assert success
    return buffer.tobytes()


def make_server(tmp_path, enabled=True, share=False, **store_kwargs):
    store = RemoteStore(str(tmp_path / 'remote'), min_upload_interval=0, **store_kwargs)
    server = WebServer(
        str(tmp_path / 'save'),
        admin_password=ADMIN_PASSWORD,
        remote_store=store,
        remote_enabled=enabled,
        share_enabled=share,
    )
    server.templates_directory = str(tmp_path / 'templates')
    server.logs_directory = str(tmp_path / 'logs')
    return server


@pytest.fixture
def server(tmp_path):
    return make_server(tmp_path)


@pytest.fixture
def phone(server):
    """A client that has loaded the page, so it carries a sender cookie."""
    client = server.app.test_client()
    client.get('/remote')
    return client


def send_photo(client, payload=None):
    return client.post(
        '/remote/upload',
        data={'photo': (io.BytesIO(payload or jpeg_bytes()), 'IMG_1.jpg')},
        content_type='multipart/form-data',
    )


def login(client):
    return client.post('/admin/login', data={'password': ADMIN_PASSWORD})


def test_a_disabled_booth_serves_nothing_of_the_feature(tmp_path):
    client = make_server(tmp_path, enabled=False).app.test_client()

    assert client.get('/remote').status_code == 404
    assert send_photo(client).status_code == 404
    assert client.get('/remote/mine').status_code == 404


def test_loading_the_page_identifies_the_phone(server):
    client = server.app.test_client()

    response = client.get('/remote')

    assert response.status_code == 200
    assert any(cookie.key == 'photobooth_sender' for cookie in client._cookies.values())


def test_a_sent_photo_reaches_the_queue(server, phone):
    response = send_photo(phone)

    assert response.status_code == 201
    photo = response.get_json()['photo']
    assert photo['status'] == 'pending'
    # The sender id is the phone's own secret; it has no business coming back.
    assert 'sender_id' not in photo
    assert server.remote_store.count_pending() == 1


def test_a_phone_without_a_cookie_is_told_to_enable_them(server):
    response = send_photo(server.app.test_client())

    assert response.status_code == 400
    assert 'cookie' in response.get_json()['error'].lower()


def test_a_request_without_a_file_is_refused(phone):
    response = phone.post('/remote/upload', data={}, content_type='multipart/form-data')

    assert response.status_code == 400


def test_something_that_is_not_a_photo_is_refused_with_a_readable_reason(phone):
    response = send_photo(phone, payload=b'this is a text file, not a photo')

    assert response.status_code == 400
    assert response.get_json()['error']


def test_a_photo_above_the_server_ceiling_still_answers_in_json(server, phone):
    """The page parses JSON; an HTML error page reads to it as a dead network."""
    oversized = b'\xff\xd8\xff' + b'x' * (server.app.config['MAX_CONTENT_LENGTH'] + 1)

    response = send_photo(phone, payload=oversized)

    assert response.status_code == 413
    assert response.is_json
    assert 'too large' in response.get_json()['error'].lower()


def test_the_json_answer_is_scoped_to_the_remote_routes(server):
    """The 413 handler is registered application-wide; the rest must not change."""
    oversized = 'y' * (server.app.config['MAX_CONTENT_LENGTH'] + 1)

    response = server.app.test_client().post('/admin/login', data={'password': oversized})

    assert response.status_code == 413
    assert response.mimetype == 'text/html'


def test_a_phone_sees_its_own_photos_and_only_those(server, phone):
    send_photo(phone)
    other_phone = server.app.test_client()
    other_phone.get('/remote')
    send_photo(other_phone)

    mine = phone.get('/remote/mine').get_json()['photos']
    theirs = other_phone.get('/remote/mine').get_json()['photos']

    assert len(mine) == 1 and len(theirs) == 1
    assert mine[0]['id'] != theirs[0]['id']


def test_a_phone_can_open_its_own_photo(phone):
    entry_id = send_photo(phone).get_json()['photo']['id']

    full = phone.get(f'/remote/photo/{entry_id}')
    thumbnail = phone.get(f'/remote/photo/{entry_id}?size=small')

    assert full.status_code == 200 and full.mimetype == 'image/jpeg'
    assert thumbnail.status_code == 200
    assert len(thumbnail.data) < len(full.data)


def test_another_phone_cannot_open_it(server, phone):
    entry_id = send_photo(phone).get_json()['photo']['id']
    stranger = server.app.test_client()
    stranger.get('/remote')

    assert stranger.get(f'/remote/photo/{entry_id}').status_code == 404


def test_a_phone_can_withdraw_its_photo_but_not_another_one(server, phone):
    entry_id = send_photo(phone).get_json()['photo']['id']
    stranger = server.app.test_client()
    stranger.get('/remote')

    assert stranger.delete(f'/remote/photo/{entry_id}').status_code == 404
    assert server.remote_store.count_pending() == 1

    assert phone.delete(f'/remote/photo/{entry_id}').status_code == 200
    assert server.remote_store.count_pending() == 0


@pytest.mark.parametrize('path', [
    '/generate_204',        # what a phone probes to detect a captive portal
    '/hotspot-detect.html',
    '/',                    # what the access point advertises as its portal
])
def test_joining_the_wifi_lands_a_phone_on_the_capture_page(server, path):
    """Every way a phone arrives after joining the WiFi has to end up here."""
    response = server.app.test_client().get(path)

    assert response.status_code == 302
    assert response.headers['Location'] == '/remote'


@pytest.mark.parametrize('path', ['/generate_204', '/'])
def test_without_the_feature_a_phone_still_lands_on_the_gallery(tmp_path, path):
    client = make_server(tmp_path, enabled=False).app.test_client()

    response = client.get(path)

    assert response.headers.get('Location') != '/remote'


def test_the_capture_page_offers_the_gallery_only_when_sharing_is_on(tmp_path):
    """It took over the captive portal landing, so it owes guests the way back."""
    shared = make_server(tmp_path / 'shared', share=True).app.test_client()
    private = make_server(tmp_path / 'private', share=False).app.test_client()

    assert b'/gallery' in shared.get('/remote').data
    assert b'/gallery' not in private.get('/remote').data


@pytest.mark.parametrize('method,path', [
    ('get', '/api/remote/photos'),
    ('post', '/api/remote/photos/20260816_120000_deadbeef/reject'),
    ('delete', '/api/remote/photos/20260816_120000_deadbeef'),
])
def test_moderation_rejects_anonymous_callers_with_401(server, method, path):
    response = getattr(server.app.test_client(), method)(path)

    assert response.status_code == 401
    assert response.get_json()['error'] == 'Authentication required'


def test_the_moderation_page_needs_the_admin_session(server):
    anonymous = server.app.test_client()

    assert anonymous.get('/admin/remote').status_code == 302

    login(anonymous)
    assert anonymous.get('/admin/remote').status_code == 200


def test_the_operator_sees_every_photo_with_a_short_sender_label(server, phone):
    send_photo(phone)
    operator = server.app.test_client()
    login(operator)

    photos = operator.get('/api/remote/photos').get_json()['photos']

    assert len(photos) == 1
    assert len(photos[0]['sender']) == 8
    assert photos[0]['status'] == 'pending'


def test_the_operator_can_reject_a_photo_without_deleting_it(server, phone):
    entry_id = send_photo(phone).get_json()['photo']['id']
    operator = server.app.test_client()
    login(operator)

    assert operator.post(f'/api/remote/photos/{entry_id}/reject').status_code == 200

    assert server.remote_store.count_pending() == 0
    assert server.remote_store.get(entry_id)['status'] == 'rejected'
    # The guest still sees what became of the photo they sent.
    assert phone.get('/remote/mine').get_json()['photos'][0]['status'] == 'rejected'


def test_the_operator_can_delete_a_photo_for_good(server, phone):
    entry_id = send_photo(phone).get_json()['photo']['id']
    operator = server.app.test_client()
    login(operator)

    assert operator.delete(f'/api/remote/photos/{entry_id}').status_code == 200

    assert server.remote_store.get(entry_id) is None
    assert phone.get(f'/remote/photo/{entry_id}').status_code == 404


def test_deleting_every_session_also_clears_what_phones_sent(server, phone):
    send_photo(phone)
    operator = server.app.test_client()
    login(operator)

    operator.post('/admin/delete-all')

    assert server.remote_store.list_entries() == []


def test_an_upload_is_counted_in_the_statistics(tmp_path):
    from libs.stats_store import StatsStore

    server = make_server(tmp_path)
    server.stats_store = StatsStore(str(tmp_path / 'stats.json'))
    client = server.app.test_client()
    client.get('/remote')

    send_photo(client)

    assert server.stats_store.load()['remote_uploads'] == 1


# --- refusals a guest can read -----------------------------------------------

REFUSAL_KEY = re.compile(r"RemoteSubmissionError\(\s*'([^']+)'")


def test_every_refusal_names_a_key_that_exists_in_every_language():
    """The store runs headless and has no language; the phone picks its own per
    request. A sentence written in the store came out English on a page that was
    otherwise entirely in the guest's language."""
    source = (Path(__file__).resolve().parents[1] / 'libs' / 'remote_store.py').read_text(encoding='utf-8')
    keys = set(REFUSAL_KEY.findall(source))

    assert keys, 'no refusal found to check'
    for lang in i18n.AVAILABLE_LANGUAGES:
        for key in keys:
            # translate() hands back the key itself when it knows no better.
            assert i18n.translate(lang, key) != key, f'{key} missing from {lang}'


def test_a_refusal_speaks_the_language_the_phone_asked_for(tmp_path):
    server = make_server(tmp_path, max_per_sender=1)
    phone = server.app.test_client()
    phone.get('/remote', headers={'Accept-Language': 'fr'})
    send_photo(phone)

    response = phone.post(
        '/remote/upload',
        data={'photo': (io.BytesIO(jpeg_bytes()), 'IMG_2.jpg')},
        content_type='multipart/form-data',
        headers={'Accept-Language': 'fr'},
    )

    assert response.status_code == 400
    assert response.get_json()['error'] == i18n.translate('fr', 'web.remote.error.sender_quota', max_per_sender=1)


def test_a_refusal_carries_the_number_it_is_about(tmp_path):
    """A quota message without the quota in it explains nothing."""
    server = make_server(tmp_path, max_per_sender=1)
    phone = server.app.test_client()
    phone.get('/remote')
    send_photo(phone)

    response = send_photo(phone)

    assert '1' in response.get_json()['error']


# --- telling a phone this network is fine ------------------------------------


def keep_wifi_card(page):
    """The opening tag of the release card, whatever else the page carries."""
    match = re.search(r'<div id="keep-wifi-card"[^>]*>', page)
    assert match, 'the release card is not on the page'
    return match.group(0)


def test_the_page_offers_a_way_out_of_the_portal(server):
    """A guest who only came to fetch their own photo never uploads, so nothing
    else on the page would ever release them: their phone keeps flagging the
    network and can drop them onto mobile data mid-visit."""
    page = server.app.test_client().get('/remote').get_data(as_text=True)

    assert 'hidden' not in keep_wifi_card(page)
    assert '/captive-portal/release' in page


def test_the_button_releases_the_phone(server):
    client = server.app.test_client()
    client.get('/remote')

    response = client.post('/captive-portal/release')

    assert response.status_code == 200
    assert client.get('/generate_204').status_code == 204


def test_a_phone_already_through_the_portal_is_not_asked_again(server):
    client = server.app.test_client()
    client.get('/remote')
    client.post('/captive-portal/release')

    page = client.get('/remote').get_data(as_text=True)

    assert 'hidden' in keep_wifi_card(page)
