"""The queue phones send photos to: what it accepts, and what it refuses.

Everything here is reachable by anyone within WiFi range of the booth, so the
limits are the feature: without them one phone fills the disk, and an id that
escapes the remote directory reads any file the booth can.
"""

import io
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.remote_store import RemoteStore, RemoteSubmissionError, is_valid_sender_id, new_sender_id


SENDER = 'a' * 32


def make_store(tmp_path, **kwargs):
    return RemoteStore(str(tmp_path / 'remote'), min_upload_interval=0, **kwargs)


def jpeg_bytes(width=1200, height=900, color=(20, 120, 200)):
    image = np.full((height, width, 3), color, dtype=np.uint8)
    success, buffer = cv2.imencode('.jpg', image)
    assert success
    return buffer.tobytes()


def test_a_submitted_photo_becomes_a_pending_entry(tmp_path):
    store = make_store(tmp_path)

    entry = store.submit(jpeg_bytes(), SENDER, source_name='IMG_0042.JPG')

    assert entry['status'] == RemoteStore.STATUS_PENDING
    assert entry['sender_id'] == SENDER
    assert entry['source_name'] == 'IMG_0042.JPG'
    assert store.count_pending() == 1
    assert store.list_entries(sender_id=SENDER)[0]['id'] == entry['id']


def test_the_photo_and_its_thumbnail_are_written(tmp_path):
    store = make_store(tmp_path)

    entry = store.submit(jpeg_bytes(), SENDER)

    photo_path = store.photo_path(entry['id'])
    thumbnail_path = store.photo_path(entry['id'], small=True)
    assert photo_path is not None and thumbnail_path is not None
    assert cv2.imread(photo_path) is not None
    thumbnail = cv2.imread(thumbnail_path)
    assert max(thumbnail.shape[:2]) <= 480


def test_an_oversized_photo_is_downscaled_to_the_configured_limit(tmp_path):
    store = make_store(tmp_path, max_image_pixels=800)

    entry = store.submit(jpeg_bytes(width=3000, height=2000), SENDER)

    stored = cv2.imread(store.photo_path(entry['id']))
    assert max(stored.shape[:2]) == 800


@pytest.mark.parametrize('payload', [
    b'',
    b'not an image at all',
    b'GIF89a' + b'\x00' * 64,
])
def test_what_is_not_a_photo_is_refused(tmp_path, payload):
    store = make_store(tmp_path)

    with pytest.raises(RemoteSubmissionError):
        store.submit(payload, SENDER)

    assert store.count_pending() == 0


def test_a_file_that_only_starts_like_a_jpeg_is_refused(tmp_path):
    store = make_store(tmp_path)

    with pytest.raises(RemoteSubmissionError):
        store.submit(b'\xff\xd8\xff' + b'garbage' * 64, SENDER)

    # The refused upload must not leave the temporary file behind.
    assert sorted(p.name for p in Path(store.remote_directory).iterdir()) == []


def test_a_photo_larger_than_the_limit_is_refused(tmp_path):
    store = make_store(tmp_path, max_upload_bytes=1024)

    with pytest.raises(RemoteSubmissionError):
        store.submit(jpeg_bytes(), SENDER)


def test_an_unidentified_sender_is_refused(tmp_path):
    store = make_store(tmp_path)

    with pytest.raises(RemoteSubmissionError):
        store.submit(jpeg_bytes(), 'not-a-sender-id')


def test_one_phone_cannot_fill_the_queue_on_its_own(tmp_path):
    store = make_store(tmp_path, max_per_sender=2)

    store.submit(jpeg_bytes(), SENDER)
    store.submit(jpeg_bytes(), SENDER)

    with pytest.raises(RemoteSubmissionError):
        store.submit(jpeg_bytes(), SENDER)

    # Another phone is unaffected by the first one's quota.
    other_sender = new_sender_id()
    assert store.submit(jpeg_bytes(), other_sender)['status'] == RemoteStore.STATUS_PENDING


def test_printing_gives_a_phone_its_quota_back(tmp_path):
    """The limit is on the queue, not on how much one guest may print all evening."""
    store = make_store(tmp_path, max_per_sender=1)
    entry = store.submit(jpeg_bytes(), SENDER)

    store.set_status(entry['id'], RemoteStore.STATUS_PRINTED)

    assert store.submit(jpeg_bytes(), SENDER)['status'] == RemoteStore.STATUS_PENDING


def test_the_queue_stops_accepting_once_it_is_full(tmp_path):
    store = make_store(tmp_path, max_pending=1)

    store.submit(jpeg_bytes(), SENDER)

    with pytest.raises(RemoteSubmissionError):
        store.submit(jpeg_bytes(), new_sender_id())


def test_a_printed_photo_frees_room_in_the_queue(tmp_path):
    store = make_store(tmp_path, max_pending=1)
    entry = store.submit(jpeg_bytes(), SENDER)

    store.set_status(entry['id'], RemoteStore.STATUS_PRINTED)

    assert store.count_pending() == 0
    assert store.submit(jpeg_bytes(), new_sender_id())['status'] == RemoteStore.STATUS_PENDING


def test_sending_twice_in_a_row_is_throttled(tmp_path):
    store = RemoteStore(str(tmp_path / 'remote'), min_upload_interval=60)

    store.submit(jpeg_bytes(), SENDER)

    with pytest.raises(RemoteSubmissionError):
        store.submit(jpeg_bytes(), SENDER)


def test_only_pending_photos_are_offered_to_the_booth(tmp_path):
    store = make_store(tmp_path)
    printed = store.submit(jpeg_bytes(), SENDER)
    waiting = store.submit(jpeg_bytes(), new_sender_id())
    store.set_status(printed['id'], RemoteStore.STATUS_PRINTED)

    pending = store.list_entries(status=RemoteStore.STATUS_PENDING)

    assert [entry['id'] for entry in pending] == [waiting['id']]


def test_a_sender_can_only_delete_its_own_photo(tmp_path):
    store = make_store(tmp_path)
    entry = store.submit(jpeg_bytes(), SENDER)

    assert store.delete(entry['id'], sender_id=new_sender_id()) is False
    assert store.get(entry['id']) is not None

    assert store.delete(entry['id'], sender_id=SENDER) is True
    assert store.get(entry['id']) is None
    assert store.photo_path(entry['id']) is None


def test_purging_removes_every_entry_and_file(tmp_path):
    store = make_store(tmp_path)
    store.submit(jpeg_bytes(), SENDER)
    store.submit(jpeg_bytes(), new_sender_id())

    assert store.purge() == 2
    assert store.list_entries() == []
    assert sorted(p.name for p in Path(store.remote_directory).iterdir()) == ['index.json']


@pytest.mark.parametrize('entry_id', [
    '../../etc/passwd',
    '20260816_120000',                     # no random suffix
    '20260816_120000_deadbeef/../secret',
    'index.json',
    '',
])
def test_an_id_that_is_not_one_of_ours_resolves_to_nothing(tmp_path, entry_id):
    store = make_store(tmp_path)

    assert store.photo_path(entry_id) is None


def test_a_corrupted_index_leaves_the_booth_running(tmp_path):
    store = make_store(tmp_path)
    store.submit(jpeg_bytes(), SENDER)
    Path(store.index_file).write_text('{ this is not json', encoding='utf-8')

    assert store.list_entries() == []
    # And a new send rebuilds a usable index rather than failing forever.
    assert store.submit(jpeg_bytes(), new_sender_id())['status'] == RemoteStore.STATUS_PENDING


def test_sender_ids_are_recognisable_and_unique():
    first, second = new_sender_id(), new_sender_id()

    assert is_valid_sender_id(first) and is_valid_sender_id(second)
    assert first != second
    assert not is_valid_sender_id('short')
    assert not is_valid_sender_id(None)


def test_an_upright_photo_survives_a_round_trip(tmp_path):
    """A landscape photo must not come back portrait, whatever the re-encoding."""
    store = make_store(tmp_path)

    entry = store.submit(jpeg_bytes(width=1600, height=900), SENDER)

    height, width = cv2.imread(store.photo_path(entry['id'])).shape[:2]
    assert width > height
