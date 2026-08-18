"""Two threads write these counters: the booth and the web server."""

import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.stats_store import StatsStore


@pytest.fixture
def store(tmp_path):
    return StatsStore(str(tmp_path / 'stats' / '.stats.json'))


def test_a_missing_file_reads_as_defaults(store):
    assert store.load()['photos_taken'] == 0
    assert store.load()['sessions'] == []


def test_a_corrupted_file_does_not_take_a_session_down(tmp_path):
    stats_file = tmp_path / '.stats.json'
    stats_file.write_text('{ not json', encoding='utf-8')
    store = StatsStore(str(stats_file))

    assert store.load()['photos_taken'] == 0
    store.track_event('download')  # must not raise


def test_events_increment_their_own_counter(store):
    store.track_event('download')
    store.track_event('download')
    store.track_event('gallery_view')

    stats = store.load()
    assert stats['downloads'] == 2
    assert stats['gallery_views'] == 1
    assert stats['last_download_date'] is not None


def test_an_unknown_event_is_ignored(store):
    store.track_event('teleportation')
    assert store.load() == store.get_default_stats()


def test_a_session_records_its_photos_once(store):
    store.track_session('20260816_120000', photos=3)
    store.track_session('20260816_120000', photos=3)

    stats = store.load()
    assert stats['photos_taken'] == 6
    assert stats['sessions'] == ['20260816_120000']  # the id is not duplicated
    assert stats['first_photo_date'] is not None


def test_a_session_without_photos_is_not_recorded(store):
    store.track_session('20260816_120000', photos=0)

    assert store.load()['photos_taken'] == 0
    assert store.load()['sessions'] == []


def test_the_first_photo_date_is_kept(store):
    store.track_session('a', photos=1)
    first = store.load()['first_photo_date']

    store.track_session('b', photos=1)

    assert store.load()['first_photo_date'] == first


def test_reset_clears_everything(store):
    store.track_session('a', photos=2)
    store.track_event('print')

    store.reset()

    assert store.load() == store.get_default_stats()


def test_concurrent_updates_are_not_lost(store):
    """The booth and the web server write from different threads.

    Read and write used to happen under separate locks, so whichever update
    landed second silently overwrote the other.
    """
    iterations = 40
    barrier = threading.Barrier(2)

    def record_downloads():
        barrier.wait()
        for _ in range(iterations):
            store.track_event('download')

    def record_sessions():
        barrier.wait()
        for index in range(iterations):
            store.track_session(f'session-{index}', photos=1)

    threads = [threading.Thread(target=record_downloads), threading.Thread(target=record_sessions)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    stats = store.load()
    assert stats['downloads'] == iterations
    assert stats['photos_taken'] == iterations
    assert len(stats['sessions']) == iterations


def test_the_file_stays_valid_json_under_concurrency(store):
    threads = [threading.Thread(target=store.track_event, args=('image_view',)) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    json.loads(Path(store.stats_file).read_text(encoding='utf-8'))


# --- print limit -----------------------------------------------------------

def test_printing_is_unlimited_without_a_maximum(store):
    assert store.can_print()
    assert store.get_print_limit_info()['enabled'] is False


def test_the_print_limit_is_reached_after_enough_prints(tmp_path):
    store = StatsStore(str(tmp_path / '.stats.json'), max_prints=2)

    store.track_print()
    assert store.can_print()
    store.track_print()

    assert not store.can_print()
    assert store.get_print_limit_info() == {
        'enabled': True, 'max_prints': 2, 'prints': 2, 'remaining': 0, 'reached': True,
    }


def test_a_job_of_three_copies_counts_three_prints(tmp_path):
    """MAX_PRINTS counts paper, and three copies is three sheets."""
    store = StatsStore(str(tmp_path / 'stats.json'), max_prints=4)

    store.track_print(3)

    assert store.get_print_limit_info()['prints'] == 3
    assert store.get_print_limit_info()['remaining'] == 1
    assert store.can_print()

    store.track_print(1)
    assert store.can_print() is False
