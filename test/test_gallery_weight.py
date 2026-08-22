"""What a phone downloads when it opens the gallery, and what the booth pays.

The grid used to serve the full-size collage as its tile and record a statistic
for every one of them. Eighty sessions meant eighty 200 KB images and eighty
locked read-modify-write cycles on the stats file — and that lock is the one the
booth takes to save a session, so a few phones browsing made the booth stutter
at the moment a guest pressed print. These hold the page to the light version.
"""

import io
import os
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault('KIVY_NO_ARGS', '1')
os.environ.setdefault('KIVY_GL_BACKEND', 'mock')

sys.path.append(str(Path(__file__).resolve().parents[1]))
from kivy.clock import Clock

from libs.stats_store import StatsStore
from libs.webserver import WebServer
from libs.webserver import paths

ADMIN_PASSWORD = 'correct horse'

THUMBNAIL_BYTES = b'small collage bytes'
COLLAGE_BYTES = b'full size collage bytes, noticeably longer'


@pytest.fixture
def server(tmp_path):
    instance = WebServer(str(tmp_path / 'save'), admin_password=ADMIN_PASSWORD)
    instance.templates_directory = str(tmp_path / 'templates')
    instance.logs_directory = str(tmp_path / 'logs')
    instance.stats_store = StatsStore(str(tmp_path / 'stats.json'))
    return instance


@pytest.fixture
def client(server):
    return server.app.test_client()


def make_session(server, session='20260816_120000', thumbnail=True):
    directory = Path(server.save_directory, session)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'collage.jpg').write_bytes(COLLAGE_BYTES)
    (directory / 'capture-0.jpg').write_bytes(b'capture bytes')
    if thumbnail:
        (directory / 'collage_small.jpg').write_bytes(THUMBNAIL_BYTES)
    return session


# --- the grid serves the small copy ------------------------------------------

def test_the_grid_serves_the_thumbnail(client, server):
    session = make_session(server)

    response = client.get(f'/thumb/{session}')

    assert response.status_code == 200
    assert response.get_data() == THUMBNAIL_BYTES


def test_a_session_without_a_thumbnail_falls_back_to_the_collage(client, server):
    """Sessions saved before the booth kept thumbnails must not show as broken
    images: a heavy tile beats an empty one."""
    session = make_session(server, thumbnail=False)

    response = client.get(f'/thumb/{session}')

    assert response.status_code == 200
    assert response.get_data() == COLLAGE_BYTES


def test_an_unknown_session_has_no_thumbnail(client):
    assert client.get('/thumb/20260101_000000').status_code == 404


def test_a_session_name_the_booth_would_not_make_is_refused(client):
    assert client.get('/thumb/..%2F..%2Fetc').status_code in (308, 404)


def test_the_page_asks_for_the_thumbnail_route_and_defers_the_load(client, server):
    make_session(server)

    page = client.get('/gallery').get_data(as_text=True)

    assert '/thumb/20260816_120000' in page
    assert 'loading="lazy"' in page
    # The full-size collage is behind the click, not in the grid.
    assert '/image/20260816_120000/collage.jpg' not in page


# --- the thumbnail stays out of what a guest takes home -----------------------

def test_the_thumbnail_is_not_a_downloadable_photo():
    """It is deliberately absent from the pattern, so the downloads and the
    archive stay unaware it exists rather than each learning to skip it."""
    assert paths.is_valid_image_filename('collage_small.jpg') is False


def test_the_thumbnail_cannot_be_downloaded(client, server):
    session = make_session(server)

    assert client.get(f'/download/{session}/collage_small.jpg').status_code == 404
    assert client.get(f'/image/{session}/collage_small.jpg').status_code == 404


def test_the_archive_holds_the_originals_only(client, server):
    session = make_session(server)
    client.post('/admin/login', data={'password': ADMIN_PASSWORD})

    response = client.get('/download/all-photos')

    archive = zipfile.ZipFile(io.BytesIO(response.get_data()))
    assert sorted(archive.namelist()) == [
        f'{session}/capture-0.jpg', f'{session}/collage.jpg',
    ]


def test_the_gallery_listing_counts_one_entry_per_session(server):
    """collage_small.jpg must not turn one session into two tiles."""
    make_session(server)

    collages = server._get_all_collages()

    assert [entry['session'] for entry in collages] == ['20260816_120000']


# --- the booth's lock is not taken per image ---------------------------------

def test_serving_images_records_nothing(client, server):
    """This used to rewrite the whole stats file per image, under the lock the
    booth needs to save a session, for a counter no page displays."""
    session = make_session(server)
    before = server.stats_store.load()

    client.get(f'/image/{session}/collage.jpg')
    client.get(f'/thumb/{session}')
    client.get(f'/image/{session}/capture-0.jpg')

    assert server.stats_store.load() == before


def test_the_views_that_are_displayed_are_still_counted(client, server):
    """Once per page, not once per image — and both appear on the stats page."""
    session = make_session(server)

    client.get('/gallery')
    client.get(f'/collage/{session}')

    stats = server.stats_store.load()
    assert stats['gallery_views'] == 1
    assert stats['collage_views'] == 1


# --- and out of the guest's USB stick ----------------------------------------

def test_the_thumbnail_is_not_copied_to_a_usb_stick(tmp_path):
    """On a stick it would only be a second, worse copy of the collage beside
    the real one, and a guest would have to guess which to print."""
    from libs.usb_transfer import UsbTransfer

    source = tmp_path / 'save' / '20260816_120000'
    source.mkdir(parents=True)
    (source / 'collage.jpg').write_bytes(COLLAGE_BYTES)
    (source / 'collage_small.jpg').write_bytes(THUMBNAIL_BYTES)
    (source / 'capture-0.jpg').write_bytes(b'capture bytes')
    destination = tmp_path / 'stick'

    # A real enough app: the copy names each file on the copying screen through
    # the clock, and those callbacks outlive this test — with None behind them
    # they blow up in whichever test ticks the clock next.
    app = SimpleNamespace(sm=SimpleNamespace(
        get_screen=lambda _name: SimpleNamespace(on_update=lambda _kwargs: None),
    ))
    transfer = UsbTransfer(app=app, folder=str(tmp_path / 'save'))
    copied = transfer.copy_without_overwrite(str(tmp_path / 'save'), str(destination))
    Clock.tick()  # drain them here rather than leaving them for someone else

    assert copied == 2
    assert sorted(p.name for p in (destination / '20260816_120000').iterdir()) == [
        'capture-0.jpg', 'collage.jpg',
    ]
