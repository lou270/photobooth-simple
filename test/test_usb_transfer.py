"""What a guest's USB drive receives from the booth."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault('KIVY_NO_ARGS', '1')

sys.path.append(str(Path(__file__).resolve().parents[1]))
import libs.usb_transfer as usb_transfer
from libs.usb_transfer import UsbTransfer


def make_transfer(save_directory):
    # The copying screen's caption is updated through the clock; a later test
    # ticking it must find something to update.
    copying_screen = SimpleNamespace(on_update=lambda kwargs: None)
    app = SimpleNamespace(sm=SimpleNamespace(get_screen=lambda name: copying_screen))
    return UsbTransfer(app, str(save_directory))


@pytest.fixture
def evening(tmp_path):
    save = tmp_path / 'save'
    session = save / '20261031_210000'
    session.mkdir(parents=True)
    (session / 'collage.jpg').write_bytes(b'collage' * 100)
    (session / 'capture-0.jpg').write_bytes(b'capture' * 100)
    (session / 'collage_small.jpg').write_bytes(b'thumbnail')
    (save / '.stats.json').write_text('{"sessions": ["20261031_210000"]}')
    (save / '.stats.json.tmp').write_text('{}')
    return save


def files_on(drive):
    return sorted(str(path.relative_to(drive)) for path in drive.rglob('*') if path.is_file())


def test_the_evening_is_copied_without_the_booths_bookkeeping(evening, tmp_path):
    drive = tmp_path / 'drive' / 'photobooth'

    copied = make_transfer(evening).copy_without_overwrite(evening, drive)

    assert copied == 2
    assert files_on(drive) == ['20261031_210000/capture-0.jpg', '20261031_210000/collage.jpg']


def test_a_drive_pulled_out_mid_copy_gets_the_photo_whole_next_time(evening, tmp_path, monkeypatch):
    """The truncated file used to keep its final name, and every later export
    skipped it because a file by that name was already there."""
    drive = tmp_path / 'drive' / 'photobooth'
    real_copy = usb_transfer.shutil.copy2

    def pulled_out(source, destination):
        Path(destination).write_bytes(Path(source).read_bytes()[:10])
        raise OSError('No such device')

    monkeypatch.setattr(usb_transfer.shutil, 'copy2', pulled_out)
    with pytest.raises(OSError):
        make_transfer(evening).copy_without_overwrite(evening, drive)

    monkeypatch.setattr(usb_transfer.shutil, 'copy2', real_copy)
    make_transfer(evening).copy_without_overwrite(evening, drive)

    session = drive / '20261031_210000'
    assert (session / 'collage.jpg').read_bytes() == b'collage' * 100
    assert (session / 'capture-0.jpg').read_bytes() == b'capture' * 100
    assert not list(drive.rglob('*.part'))
