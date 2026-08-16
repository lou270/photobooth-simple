"""SessionStorage owns what a guest walks away with: saving must never lose files."""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.core import SessionStorage


def make_storage(tmp_path, **kwargs):
    return SessionStorage(str(tmp_path / 'DCIM'), **kwargs)


def write_working_files(storage, names):
    for name in names:
        Path(storage.tmp_directory, name).write_bytes(b'x')


def test_required_directories_are_created(tmp_path):
    storage = make_storage(tmp_path)

    assert Path(storage.tmp_directory).is_dir()
    assert Path(storage.save_directory).is_dir()


def test_working_paths_live_in_tmp(tmp_path):
    storage = make_storage(tmp_path)

    assert Path(storage.get_shot(2)).name == 'capture-2.jpg'
    assert Path(storage.get_collage()).name == 'collage.jpg'
    assert Path(storage.get_print_collage()).name == 'collage_print.jpg'
    assert Path(storage.get_shot(0)).parent == Path(storage.tmp_directory)


def test_saving_moves_originals_and_leaves_derived_files_behind(tmp_path):
    storage = make_storage(tmp_path)
    write_working_files(storage, [
        'capture-0.jpg', 'capture-0_small.jpg',
        'collage.jpg', 'collage_small.jpg', 'collage_print.jpg',
    ])

    session_id, moved_files = storage.save_session()

    session_directory = Path(storage.save_directory, session_id)
    assert moved_files == 2
    assert sorted(p.name for p in session_directory.iterdir()) == ['capture-0.jpg', 'collage.jpg']
    assert sorted(p.name for p in Path(storage.tmp_directory).iterdir()) == [
        'capture-0_small.jpg', 'collage_print.jpg', 'collage_small.jpg',
    ]


def test_saving_an_empty_session_reports_nothing_saved(tmp_path):
    storage = make_storage(tmp_path)

    assert storage.save_session() == (None, 0)
    assert list(Path(storage.save_directory).iterdir()) == []


def test_saving_only_derived_files_leaves_no_empty_session_behind(tmp_path):
    storage = make_storage(tmp_path)
    write_working_files(storage, ['collage_small.jpg', 'collage_print.jpg'])

    session_id, moved_files = storage.save_session()

    assert (session_id, moved_files) == (None, 0)
    assert list(Path(storage.save_directory).iterdir()) == []


def test_saved_collage_is_exposed_after_the_session_is_saved(tmp_path):
    storage = make_storage(tmp_path)
    assert storage.get_saved_collage() is None

    write_working_files(storage, ['collage.jpg'])
    storage.save_session()

    saved = storage.get_saved_collage()
    assert saved is not None
    assert Path(saved).read_bytes() == b'x'


def test_saved_collage_stays_none_when_the_session_had_no_collage(tmp_path):
    storage = make_storage(tmp_path)
    write_working_files(storage, ['capture-0.jpg'])

    storage.save_session()

    assert storage.get_saved_collage() is None


def test_purge_removes_every_working_file(tmp_path):
    storage = make_storage(tmp_path)
    write_working_files(storage, ['capture-0.jpg', 'collage_small.jpg', 'collage_print.jpg'])

    removed = storage.purge_tmp()

    assert removed == 3
    assert list(Path(storage.tmp_directory).iterdir()) == []


def test_disk_is_critical_below_the_free_space_floor(tmp_path):
    storage = make_storage(tmp_path, min_free_gb=10 ** 6, max_used_percent=100.0)
    assert storage.is_disk_space_critical()


def test_disk_is_critical_above_the_used_percentage_ceiling(tmp_path):
    storage = make_storage(tmp_path, min_free_gb=0.0, max_used_percent=0.0)
    assert storage.is_disk_space_critical()


def test_healthy_disk_is_not_critical(tmp_path):
    storage = make_storage(tmp_path, min_free_gb=0.0, max_used_percent=100.0)

    assert not storage.is_disk_space_critical()
    assert storage.get_disk_usage()['total_gb'] > 0
