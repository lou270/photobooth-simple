"""What the booth does with a photo a phone sent.

The web side stops at the queue. From the moment a guest picks a photo on the
booth it must become an ordinary session: one capture in the working directory,
assembled, printed and saved like any other. These tests cover that handover,
which is the only place the two halves of the feature touch.
"""

import ipaddress
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.core import SessionStorage
from libs.file_utils import FileUtils
from libs.remote_store import RemoteStore, new_sender_id
from libs.screens.remote_gallery import RemoteGalleryScreen
from photoboothapp import PhotoboothApp


class FakeFormat:
    def __init__(self, photos_required):
        self._photos_required = photos_required

    def get_photos_required(self):
        return self._photos_required


def jpeg_bytes(width=1200, height=900):
    image = np.full((height, width, 3), (40, 110, 180), dtype=np.uint8)
    return cv2.imencode('.jpg', image)[1].tobytes()


def make_app(tmp_path, remote_capture=True):
    app = PhotoboothApp.__new__(PhotoboothApp)
    app.REMOTE_CAPTURE = remote_capture
    app.storage = SessionStorage(str(tmp_path / 'DCIM'))
    app.remote_store = RemoteStore(str(tmp_path / 'DCIM' / 'remote'), min_upload_interval=0) if remote_capture else None
    return app


def test_a_photo_from_a_phone_is_printed_alone_when_a_format_allows_it(tmp_path):
    app = make_app(tmp_path)
    app.print_formats = [FakeFormat(4), FakeFormat(1), FakeFormat(2)]

    assert app.get_single_photo_format_index() == 1


def test_without_a_single_photo_format_the_first_one_is_used(tmp_path):
    """Better a face repeated across a strip than a crash in front of a guest."""
    app = make_app(tmp_path)
    app.print_formats = [FakeFormat(3), FakeFormat(4)]

    assert app.get_single_photo_format_index() == 0


def test_the_feature_is_off_without_a_queue(tmp_path):
    app = make_app(tmp_path, remote_capture=False)

    assert app.has_remote_capture() is False
    assert app.get_remote_pending_count() == 0
    assert app.get_pending_remote_photos() == []
    assert app.get_remote_photo_path('20260816_120000_deadbeef') is None


def test_staging_puts_the_photo_where_a_capture_would_be(tmp_path):
    app = make_app(tmp_path)
    entry = app.remote_store.submit(jpeg_bytes(), new_sender_id())

    app.stage_remote_photo(entry['id'])

    staged = app.get_shot(0)
    assert os.path.isfile(staged)
    assert cv2.imread(staged) is not None


def test_staging_clears_whatever_the_previous_session_left(tmp_path):
    app = make_app(tmp_path)
    leftover = Path(app.storage.tmp_directory, 'capture-1.jpg')
    leftover.write_bytes(b'previous session')
    entry = app.remote_store.submit(jpeg_bytes(), new_sender_id())

    app.stage_remote_photo(entry['id'])

    # Otherwise a four-photo strip would print three faces from the session
    # before and one from the phone.
    assert not leftover.exists()
    # The phone's photo and the small copy the review screen previews from.
    assert sorted(p.name for p in Path(app.storage.tmp_directory).iterdir()) == [
        'capture-0.jpg', 'capture-0_small.jpg',
    ]


def test_a_staged_photo_brings_its_small_copy(tmp_path):
    """The review screen builds its filter previews from the small copy."""
    app = make_app(tmp_path)
    entry = app.remote_store.submit(jpeg_bytes(), new_sender_id())

    app.stage_remote_photo(entry['id'])

    small = FileUtils.get_small_path(app.get_shot(0))
    assert os.path.isfile(small)
    assert cv2.imread(small) is not None


def test_a_staged_photo_leaves_the_queue(tmp_path):
    """Two guests must not walk off with a print of the same photo."""
    app = make_app(tmp_path)
    entry = app.remote_store.submit(jpeg_bytes(), new_sender_id())

    app.stage_remote_photo(entry['id'])

    assert app.get_remote_pending_count() == 0
    assert app.remote_store.get(entry['id'])['status'] == RemoteStore.STATUS_PRINTED


def test_a_photo_withdrawn_before_printing_is_reported(tmp_path):
    """The sender can remove it from their phone between the tap and the copy."""
    app = make_app(tmp_path)
    entry = app.remote_store.submit(jpeg_bytes(), new_sender_id())
    app.remote_store.delete(entry['id'])

    with pytest.raises(FileNotFoundError):
        app.stage_remote_photo(entry['id'])


def test_only_waiting_photos_are_offered_at_the_booth(tmp_path):
    app = make_app(tmp_path)
    first = app.remote_store.submit(jpeg_bytes(), new_sender_id())
    second = app.remote_store.submit(jpeg_bytes(), new_sender_id())
    app.stage_remote_photo(first['id'])

    waiting = app.get_pending_remote_photos()

    assert [entry['id'] for entry in waiting] == [second['id']]
    assert app.get_remote_pending_count() == 1


@pytest.mark.parametrize('received_at,expected', [
    ('2026-08-16T21:47:03', '21:47'),
    ('2026-08-16T09:05:00', '09:05'),
    ('2026-08-16', ''),
    ('', ''),
    (None, ''),
])
def test_a_card_is_labelled_with_the_time_the_photo_arrived(received_at, expected):
    """The clock time is how a guest recognises their own photo on the wall."""
    assert RemoteGalleryScreen._format_time(received_at) == expected


def test_the_guest_is_given_two_codes_in_order(tmp_path):
    """Joining and opening cannot be one code, and the network opens nothing itself."""
    app = make_app(tmp_path)
    app.wifi_payload = 'WIFI:T:nopass;S:PhotoBooth;P:;H:false;;'

    steps, _title, hint = app.get_qr_invitation('http://192.168.4.1:5000/remote')

    assert [payload for payload, _caption in steps] == [
        app.wifi_payload,
        'http://192.168.4.1:5000/remote',
    ]
    assert steps[0][1].startswith('1.') and steps[1][1].startswith('2.')
    assert hint == 'http://192.168.4.1:5000/remote'


def test_the_second_code_never_carries_a_name_to_resolve(tmp_path):
    """With no default route here, a phone asks its cellular resolver instead."""
    app = make_app(tmp_path)
    app.wifi_payload = 'WIFI:T:nopass;S:PhotoBooth;P:;H:false;;'

    steps, _title, _hint = app.get_qr_invitation('http://192.168.4.1:5000/remote')

    host = steps[1][0].split('//', 1)[1].split(':', 1)[0]
    ipaddress.ip_address(host)  # raises if the booth ever hands out a hostname


def test_without_an_access_point_a_single_code_carries_the_address(tmp_path):
    """Nothing to join means the guest is already on a network of their own."""
    app = make_app(tmp_path)
    app.wifi_payload = None

    steps, _title, hint = app.get_qr_invitation('http://192.168.1.20:5000/remote')

    assert steps == [('http://192.168.1.20:5000/remote', '')]
    assert hint == 'http://192.168.1.20:5000/remote'


# --- the wall of waiting photos --------------------------------------------

def test_a_lone_photo_is_a_card_like_any_other():
    """One waiting photo used to fill the window: one column, taller than the screen."""
    from kivy.core.window import Window

    width, height, cols = RemoteGalleryScreen._card_size(None)

    assert cols >= 2
    assert width <= Window.width / 2
    # It has to fit the scroll view it lives in, which is 86% of the screen.
    assert height <= Window.height * 0.86
