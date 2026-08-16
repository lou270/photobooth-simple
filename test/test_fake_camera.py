"""FakeCamera behaves like a real backend, so the app can run with no hardware."""

import sys
import time
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.file_utils import FileUtils
from libs.hardware import FakeCamera


def test_preview_has_the_requested_size():
    camera = FakeCamera(size=(640, 480))
    assert camera.get_preview().shape == (480, 640, 3)


def test_preview_frame_id_advances_over_time():
    camera = FakeCamera(size=(320, 240), fps=1000)
    first = camera.get_preview_frame_id()
    time.sleep(0.02)
    assert camera.get_preview_frame_id() > first


@pytest.mark.parametrize('aspect_ratio', [1.0, 2 / 3, 3 / 2])
def test_preview_matches_the_requested_aspect_ratio(aspect_ratio):
    camera = FakeCamera(size=(1200, 800))
    height, width = camera.get_preview(aspect_ratio=aspect_ratio).shape[:2]
    assert width / height == pytest.approx(aspect_ratio, rel=0.02)


def test_capture_writes_the_photo_and_its_small_preview(tmp_path):
    camera = FakeCamera(size=(640, 480))
    output = tmp_path / 'capture-0.jpg'

    camera.capture(str(output))

    small = Path(FileUtils.get_small_path(str(output)))
    for _ in range(50):  # the small preview is built off the capture path
        if small.exists():
            break
        time.sleep(0.02)

    assert output.exists()
    assert small.exists()
    assert camera.capture_count == 1


def test_capture_drives_the_flash_when_hardware_has_none(tmp_path):
    camera = FakeCamera(size=(320, 240))
    calls = []

    camera.capture(str(tmp_path / 'capture-0.jpg'), flash_fn=lambda stop=False: calls.append(stop))

    assert calls == [False, True]


def test_capture_leaves_the_flash_alone_when_hardware_has_one(tmp_path):
    camera = FakeCamera(size=(320, 240), has_flash=True)
    calls = []

    camera.capture(str(tmp_path / 'capture-0.jpg'), flash_fn=lambda stop=False: calls.append(stop))

    assert calls == []


def test_capture_delay_reproduces_dslr_latency(tmp_path):
    camera = FakeCamera(size=(320, 240), capture_delay=0.2)

    started_at = time.monotonic()
    camera.capture(str(tmp_path / 'capture-0.jpg'))

    assert time.monotonic() - started_at >= 0.2


def test_closed_camera_reports_unhealthy():
    camera = FakeCamera(size=(320, 240))
    assert camera.is_healthy()

    camera.close()

    assert not camera.is_healthy()
