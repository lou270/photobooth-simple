"""What the booth does with a photo a phone sent.

The web side stops at the queue. From the moment a guest picks a photo on the
booth it must become an ordinary session: one capture in the working directory,
assembled, printed and saved like any other. These tests cover that handover,
which is the only place the two halves of the feature touch.
"""

import ipaddress
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

os.environ.setdefault('KIVY_NO_ARGS', '1')
os.environ.setdefault('KIVY_GL_BACKEND', 'mock')

sys.path.append(str(Path(__file__).resolve().parents[1]))
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.input.providers.mouse import MouseMotionEvent
from kivy.uix.floatlayout import FloatLayout

from libs.core import SessionStorage
from libs.file_utils import FileUtils
from libs.kivywidgets import SquareFloatLayout
from libs.remote_store import RemoteStore, new_sender_id
from libs.screens.names import ScreenNames
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


# --- the wall of waiting photos ------------------------------------------

class FakeRingLed:
    def start_rainbow(self):
        pass

    def clear(self):
        pass


class GalleryApp:
    """Just enough app for the screen: a queue it reads and a photo it deletes."""

    def __init__(self, entries, thumbnail):
        self.entries = list(entries)
        self.thumbnail = thumbnail
        self.ringled = FakeRingLed()
        self.deleted = []
        self.staged = []
        self.transitions = []

    def get_pending_remote_photos(self):
        return [dict(entry) for entry in self.entries]

    def get_remote_photo_path(self, entry_id, small=False):
        return self.thumbnail if any(e['id'] == entry_id for e in self.entries) else None

    def delete_remote_photo(self, entry_id):
        before = len(self.entries)
        self.entries = [entry for entry in self.entries if entry['id'] != entry_id]
        self.deleted.append(entry_id)
        return len(self.entries) < before

    def get_current_screen_name(self):
        return ScreenNames.REMOTE_GALLERY

    # The print side of the screen, so a tap that should print can be told from
    # one that should not.
    def ensure_disk_space_or_maintenance(self):
        return True

    def get_single_photo_format_index(self):
        return 0

    def stage_remote_photo(self, entry_id):
        pass

    def start_photo_task(self, task, entry_id):
        self.staged.append(entry_id)

    def transition_to(self, screen, **kwargs):
        self.transitions.append(screen)


def a_tap():
    """A stand-in for the touch the screens check before acting on a release."""
    return SimpleNamespace(last_touch=Mock(spec=MouseMotionEvent))


def make_entries(times):
    """Entries whose id says nothing about their position in the list."""
    return [
        {'id': f'20260816_{clock.replace(":", "")}00_deadbee0',
         'received_at': f'2026-08-16T{clock}:00'}
        for clock in times
    ]


@pytest.fixture
def gallery(tmp_path):
    """A gallery screen fed a queue handed to it oldest first, on purpose.

    Mounted on the real Window: the touch tests need widgets that have been
    through a layout pass and can convert their own centre to a screen position.
    """
    thumbnail = tmp_path / 'thumb.jpg'
    thumbnail.write_bytes(jpeg_bytes(120, 90))
    app = GalleryApp(make_entries(['20:00', '21:00', '22:00']), str(thumbnail))
    screen = RemoteGalleryScreen(app)
    root = FloatLayout()
    root.add_widget(screen)
    Window.add_widget(root)
    screen.size = Window.size
    yield screen
    screen.on_exit()
    Window.remove_widget(root)


def drain(screen, attempts=200):
    """Let the queue reader thread finish and the clock apply what it read."""
    for _ in range(attempts):
        Clock.tick()
        if screen._shown_entry_ids is not None:
            settle()
            return
        time.sleep(0.005)
    raise AssertionError('the queue was never applied to the grid')


def settle(ticks=20):
    """Frames enough for a layout pass and for a button to leave its down state."""
    for _ in range(ticks):
        Clock.tick()
        time.sleep(0.01)


def tap(x, y, _counter=[0]):
    """A real touch on the window, the only way to know which widget catches it."""
    _counter[0] += 1
    touch = MouseMotionEvent(
        'mouse', _counter[0],
        [x / float(Window.width), y / float(Window.height), 'left'],
        is_touch=True, type_id='touch',
    )
    Window.transform_motion_event_2d(touch)
    Window.dispatch('on_touch_down', touch)
    Window.dispatch('on_touch_up', touch)
    settle()


def bin_of(card):
    return next(widget for widget in card.walk(restrict=True) if isinstance(widget, SquareFloatLayout))


def test_the_newest_photo_is_the_first_card(gallery):
    """A guest sends theirs and walks up: it has to be in the top row, not the last."""
    gallery._refresh_photos()
    drain(gallery)

    assert [card.entry_id for card in gallery.photo_cards] == [
        entry['id'] for entry in make_entries(['22:00', '21:00', '20:00'])
    ]


def test_the_grid_is_as_tall_as_its_rows_so_it_can_be_scrolled(gallery):
    """Left at the default hint the rows past the first hang off-screen for good."""
    gallery._refresh_photos()
    drain(gallery)
    for _ in range(5):
        Clock.tick()

    container = gallery.cards_grid.parent
    assert container.size_hint_y is None
    assert container.height == pytest.approx(gallery.cards_grid.height)


def test_the_bin_wins_the_touch_it_sits_on(gallery):
    """The whole card prints; a bin drawn on top of it must not print as well."""
    gallery._refresh_photos()
    drain(gallery)
    card = gallery.photo_cards[0]
    button = bin_of(card)

    tap(*button.to_window(*button.center))

    assert gallery.confirm_popup is not None
    assert gallery.app.staged == []
    assert gallery.app.transitions == []


def test_the_photo_itself_is_still_the_print_button(gallery):
    gallery._refresh_photos()
    drain(gallery)
    card = gallery.photo_cards[0]

    tap(*card.to_window(card.center_x, card.center_y))

    assert gallery.app.staged == [card.entry_id]
    assert gallery.app.transitions == [ScreenNames.PROCESSING]
    assert gallery.confirm_popup is None


def test_the_bin_asks_before_it_removes_anything(gallery):
    gallery._refresh_photos()
    drain(gallery)
    entry_id = gallery.photo_cards[0].entry_id

    gallery.on_photo_delete(a_tap(), entry_id, gallery.app.thumbnail)

    assert gallery.confirm_popup is not None
    assert gallery.app.deleted == []


def test_answering_yes_removes_the_photo_from_the_queue(gallery):
    gallery._refresh_photos()
    drain(gallery)
    entry_id = gallery.photo_cards[0].entry_id
    gallery.on_photo_delete(a_tap(), entry_id, gallery.app.thumbnail)

    gallery.confirm_popup._confirm(a_tap())
    gallery._shown_entry_ids = None
    drain(gallery)

    assert gallery.app.deleted == [entry_id]
    assert gallery.confirm_popup is None
    assert entry_id not in [card.entry_id for card in gallery.photo_cards]


def test_answering_no_leaves_it_waiting(gallery):
    gallery._refresh_photos()
    drain(gallery)
    entry_id = gallery.photo_cards[0].entry_id
    gallery.on_photo_delete(a_tap(), entry_id, gallery.app.thumbnail)

    gallery.confirm_popup._cancel(a_tap())
    for _ in range(5):
        Clock.tick()

    assert gallery.app.deleted == []
    assert gallery.confirm_popup is None
    assert entry_id in [card.entry_id for card in gallery.photo_cards]


def test_a_photo_cannot_be_deleted_twice_by_a_double_tap(gallery):
    """The second tap lands on the confirm button before the popup is gone."""
    gallery._refresh_photos()
    drain(gallery)
    entry_id = gallery.photo_cards[0].entry_id
    gallery.on_photo_delete(a_tap(), entry_id, gallery.app.thumbnail)
    popup = gallery.confirm_popup

    popup._confirm(a_tap())
    popup._confirm(a_tap())
    gallery._shown_entry_ids = None
    drain(gallery)

    assert gallery.app.deleted == [entry_id]


def test_the_grid_stays_still_while_the_question_is_on_screen(gallery):
    """Answering about a card that just moved is how the wrong photo is deleted."""
    gallery._refresh_photos()
    drain(gallery)
    before = [card.entry_id for card in gallery.photo_cards]
    gallery.on_photo_delete(a_tap(), before[0], gallery.app.thumbnail)

    gallery.app.entries = make_entries(['23:00'])
    gallery._refresh_photos()
    for _ in range(20):
        Clock.tick()
        time.sleep(0.005)

    assert [card.entry_id for card in gallery.photo_cards] == before


def test_deleting_the_last_photo_brings_back_the_empty_message(gallery):
    gallery.app.entries = make_entries(['20:00'])
    gallery._refresh_photos()
    drain(gallery)
    entry_id = gallery.photo_cards[0].entry_id
    gallery.on_photo_delete(a_tap(), entry_id, gallery.app.thumbnail)

    gallery.confirm_popup._confirm(a_tap())
    gallery._shown_entry_ids = None
    drain(gallery)

    assert gallery.photo_cards == []
    assert gallery.empty_label.parent is not None


def test_the_booth_deletes_a_waiting_photo_and_its_files(tmp_path):
    app = make_app(tmp_path)
    entry = app.remote_store.submit(jpeg_bytes(), new_sender_id())
    assert app.get_remote_photo_path(entry['id']) is not None

    assert app.delete_remote_photo(entry['id']) is True

    assert app.get_remote_pending_count() == 0
    assert app.get_remote_photo_path(entry['id']) is None
    assert app.get_remote_photo_path(entry['id'], small=True) is None


def test_deleting_an_unknown_photo_is_not_an_error(tmp_path):
    app = make_app(tmp_path)

    assert app.delete_remote_photo('20260816_120000_deadbeef') is False


def test_nothing_is_deleted_when_the_feature_is_off(tmp_path):
    app = make_app(tmp_path, remote_capture=False)

    assert app.delete_remote_photo('20260816_120000_deadbeef') is False


def test_a_lone_photo_is_a_card_like_any_other():
    """One waiting photo used to fill the window: one column, taller than the screen."""
    from kivy.core.window import Window

    width, height, cols = RemoteGalleryScreen._card_size(None)

    assert cols >= 2
    assert width <= Window.width / 2
    # It has to fit the scroll view it lives in, which is 86% of the screen.
    assert height <= Window.height * 0.86
