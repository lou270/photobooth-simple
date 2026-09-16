"""Images of designed templates: stored by content, served to the editor, cleaned up."""

import io
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.webserver import WebServer
from libs.webserver import api

ADMIN_PASSWORD = 'correct horse'


@pytest.fixture
def server(tmp_path):
    instance = WebServer(str(tmp_path / 'save'), admin_password=ADMIN_PASSWORD)
    instance.templates_directory = str(tmp_path / 'templates')
    return instance


@pytest.fixture
def client(server):
    client = server.app.test_client()
    client.post('/admin/login', data={'password': ADMIN_PASSWORD})
    return client


def png_bytes(width=40, height=30, alpha=128):
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[:, :] = (0, 0, 255, alpha)
    return cv2.imencode('.png', image)[1].tobytes()


def upload(client, data, name='frame.png'):
    return client.post('/api/template-assets', data={'image': (io.BytesIO(data), name)},
                       content_type='multipart/form-data')


def test_an_uploaded_image_is_stored_as_sent_under_its_content_name(client, server):
    data = png_bytes()

    response = upload(client, data)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['filename'].startswith('assets/') and payload['filename'].endswith('.png')
    assert (payload['width'], payload['height']) == (40, 30)
    assert Path(server.templates_directory, payload['filename']).read_bytes() == data


def test_the_same_image_twice_is_one_file(client, server):
    first = upload(client, png_bytes()).get_json()['filename']
    second = upload(client, png_bytes(), name='copy.png').get_json()['filename']

    assert first == second
    assert len(os.listdir(Path(server.templates_directory, 'assets'))) == 1


@pytest.mark.parametrize('data', [b'', b'not an image', b'GIF89a' + b'\0' * 20])
def test_what_is_not_an_image_the_booth_can_draw_is_refused(client, server, data):
    response = upload(client, data)

    assert response.status_code == 400
    assert not Path(server.templates_directory, 'assets').exists()


def test_an_image_claiming_more_pixels_than_the_booth_allows_is_refused(client, monkeypatch):
    monkeypatch.setattr(api, 'MAX_ASSET_PIXELS', 100)

    response = upload(client, png_bytes(20, 20))

    assert response.status_code == 400
    assert 'too large' in response.get_json()['error']


def test_a_stored_image_is_served_back_to_the_editor(client):
    data = png_bytes()
    name = upload(client, data).get_json()['filename'].split('/', 1)[1]

    response = client.get(f'/api/template-assets/{name}')

    assert response.status_code == 200
    assert response.mimetype == 'image/png'
    assert response.get_data() == data


@pytest.mark.parametrize('name', ['..%2Fconfig.ini', 'frame.png', '0' * 32 + '.gif', '0' * 32 + '.png'])
def test_only_stored_asset_names_are_served(client, name):
    assert client.get(f'/api/template-assets/{name}').status_code == 404


@pytest.mark.parametrize('method,path', [
    ('post', '/api/template-assets'),
    ('get', '/api/template-assets/' + '0' * 32 + '.png'),
    ('post', '/api/template-assets/cleanup'),
    ('post', '/api/templates/preview'),
])
def test_asset_routes_reject_anonymous_callers(server, method, path):
    assert getattr(server.app.test_client(), method)(path).status_code == 401


def age(path, seconds):
    old = time.time() - seconds
    os.utime(path, (old, old))


def test_cleanup_removes_old_images_no_template_mentions(client, server):
    used = upload(client, png_bytes(alpha=10)).get_json()['filename']
    unused = upload(client, png_bytes(alpha=20)).get_json()['filename']
    recent = upload(client, png_bytes(alpha=30)).get_json()['filename']
    for filename in (used, unused):
        age(Path(server.templates_directory, filename), api.ASSET_GRACE_SECONDS + 60)
    Path(server.templates_directory, 'party.json').write_text(
        json.dumps({'design': {'levels': [{'elements': [{'src': used}]}]}}), encoding='utf-8')

    response = client.post('/api/template-assets/cleanup')

    assert response.get_json()['deleted'] == [unused.split('/', 1)[1]]
    assert Path(server.templates_directory, used).exists()
    assert Path(server.templates_directory, recent).exists()
    assert not Path(server.templates_directory, unused).exists()


def test_the_booth_draws_a_template_whose_image_is_an_asset(client, server):
    filename = upload(client, png_bytes(300, 200, alpha=255)).get_json()['filename']
    template = {
        'name': 'Designed',
        'page': {'width': 300, 'height': 200},
        'photos': [{'x': 0, 'y': 0, 'width': 100, 'height': 100}],
        'stack': [{'type': 'photo', 'index': 0},
                  {'type': 'image', 'src': filename, 'x': 150, 'y': 0, 'width': 150, 'height': 200}],
    }

    response = client.post('/api/templates/preview', json={'template': template})

    assert response.status_code == 200
    assert response.mimetype == 'image/jpeg'
    preview = cv2.imdecode(np.frombuffer(response.get_data(), np.uint8), cv2.IMREAD_COLOR)
    assert preview.shape[:2] == (200, 300)
    blue, green, red = (int(value) for value in preview[100, 250])
    assert red > 200 and green < 60 and blue < 60


def test_a_preview_of_an_invalid_template_says_why(client):
    response = client.post('/api/templates/preview', json={'template': {'name': 'Broken'}})

    assert response.status_code == 400
    assert 'page' in response.get_json()['error']
