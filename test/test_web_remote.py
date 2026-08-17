"""The remote capture area seen from the network.

A phone reaching these routes is an anonymous guest on the event's WiFi, so what
matters is the boundary: nothing is served while the feature is off, one phone
cannot read or remove another phone's photo, and moderation stays behind the
admin session.
"""

import io
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
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


def test_the_booth_address_alone_opens_the_capture_page(server):
    """The QR code carries the bare address, so the root has to be the page."""
    response = server.app.test_client().get('/')

    assert response.status_code == 302
    assert response.headers['Location'] == '/remote'


def test_without_the_feature_the_root_is_still_the_gallery(tmp_path):
    client = make_server(tmp_path, enabled=False).app.test_client()

    response = client.get('/')

    assert response.headers.get('Location') != '/remote'


@pytest.mark.parametrize('path', ['/generate_204', '/hotspot-detect.html', '/connecttest.txt'])
def test_connectivity_probes_are_not_answered(server, path):
    """The booth's network is local-only and must never claim otherwise.

    Answering these is how a portal tells a phone "this network has internet",
    which would move the phone's default route here and break the mobile data
    the guest is still using. Letting them fail is the whole point.
    """
    assert server.app.test_client().get(path).status_code == 404


def test_the_capture_page_offers_the_gallery_only_when_sharing_is_on(tmp_path):
    """The capture page is where guests land, so it owes them the way back."""
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
