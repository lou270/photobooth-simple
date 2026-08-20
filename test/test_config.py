"""A malformed config.ini must never keep the booth from starting on site."""

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
import libs.config as config_module
from libs.config import Config


def write_config(tmp_path, monkeypatch, body):
    config_path = tmp_path / 'config.ini'
    config_path.write_text(textwrap.dedent(body), encoding='utf-8')
    monkeypatch.setattr(config_module, 'CONFIG_PATH', config_path)
    return Config()


def test_missing_config_file_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, 'CONFIG_PATH', tmp_path / 'absent.ini')
    with pytest.raises(FileNotFoundError):
        Config()


@pytest.mark.parametrize('raw', ['not-a-tuple', '(1.5, 0)', '[[[', ''])
def test_invalid_calibration_is_disabled_instead_of_raising(tmp_path, monkeypatch, raw):
    config = write_config(tmp_path, monkeypatch, f"""
        [Capture]
        CALIBRATION = {raw}
    """)
    assert config.get_calibration() is None


def test_valid_calibration_is_returned_as_a_triple(tmp_path, monkeypatch):
    config = write_config(tmp_path, monkeypatch, """
        [Capture]
        CALIBRATION = (1.4, 10, -5)
    """)
    assert config.get_calibration() == (1.4, 10, -5)


def test_invalid_max_prints_falls_back_to_unlimited(tmp_path, monkeypatch):
    config = write_config(tmp_path, monkeypatch, """
        [Print]
        MAX_PRINTS = beaucoup
    """)
    assert config.get_max_prints() is None


def test_valid_max_prints_is_returned(tmp_path, monkeypatch):
    config = write_config(tmp_path, monkeypatch, """
        [Print]
        MAX_PRINTS = 120
    """)
    assert config.get_max_prints() == 120


def test_unknown_camera_backend_falls_back_to_auto(tmp_path, monkeypatch):
    config = write_config(tmp_path, monkeypatch, """
        [Capture]
        CAMERA = quantum
    """)
    assert config.get_camera_backend() == 'auto'


def test_camera_backend_is_case_insensitive(tmp_path, monkeypatch):
    config = write_config(tmp_path, monkeypatch, """
        [Capture]
        CAMERA = Fake
    """)
    assert config.get_camera_backend() == 'fake'


def test_camera_backend_defaults_to_auto_when_absent(tmp_path, monkeypatch):
    config = write_config(tmp_path, monkeypatch, """
        [Global]
        SHARE = True
    """)
    assert config.get_camera_backend() == 'auto'


def test_remote_capture_is_off_when_the_section_is_absent(tmp_path, monkeypatch):
    """An existing installation upgrading must not start accepting uploads."""
    config = write_config(tmp_path, monkeypatch, """
        [Global]
        SHARE = True
    """)
    assert config.get_remote_capture() is False
    assert config.get_remote_url() is None


def test_remote_url_none_means_derive_it(tmp_path, monkeypatch):
    config = write_config(tmp_path, monkeypatch, """
        [Remote]
        REMOTE_URL = None
    """)
    assert config.get_remote_url() is None


def test_remote_url_is_returned_when_set(tmp_path, monkeypatch):
    config = write_config(tmp_path, monkeypatch, """
        [Remote]
        REMOTE_URL = photobooth.local:5000
    """)
    assert config.get_remote_url() == 'photobooth.local:5000'


def test_remote_limits_are_clamped_to_something_usable(tmp_path, monkeypatch):
    """A zero or negative limit would refuse every photo, or store none of it."""
    config = write_config(tmp_path, monkeypatch, """
        [Remote]
        REMOTE_MAX_UPLOAD_MB = 0
        REMOTE_MAX_IMAGE_PIXELS = 10
        REMOTE_MAX_PER_SENDER = 0
        REMOTE_MAX_PENDING = -5
        REMOTE_MIN_UPLOAD_INTERVAL = -1
    """)
    assert config.get_remote_max_upload_mb() == 1
    assert config.get_remote_max_image_pixels() == 640
    assert config.get_remote_max_per_sender() == 1
    assert config.get_remote_max_pending() == 1
    assert config.get_remote_min_upload_interval() == 0


def test_the_booth_address_on_its_own_access_point_has_a_default(tmp_path, monkeypatch):
    """It cannot be guessed: that network carries no default route on purpose."""
    config = write_config(tmp_path, monkeypatch, """
        [Global]
        SHARE = True
    """)
    assert config.get_wifi_ap_address() == '192.168.4.1'


def test_an_empty_booth_address_falls_back_to_guessing(tmp_path, monkeypatch):
    """For a booth sitting on somebody else's WiFi rather than running its own."""
    config = write_config(tmp_path, monkeypatch, """
        [WiFi]
        WIFI_AP_ADDRESS =
    """)
    assert config.get_wifi_ap_address() == ''


def test_max_copies_defaults_to_three(tmp_path, monkeypatch):
    config = write_config(tmp_path, monkeypatch, """
        [Print]
    """)

    assert config.get_max_copies() == 3


def test_max_copies_is_clamped_to_something_a_guest_could_want(tmp_path, monkeypatch):
    config = write_config(tmp_path, monkeypatch, """
        [Print]
        MAX_COPIES = 99
    """)

    assert config.get_max_copies() == 10


@pytest.mark.parametrize('raw', ['abc', '', '5s', '1,5'])
def test_a_malformed_number_falls_back_instead_of_raising(tmp_path, monkeypatch, raw):
    """The admin form rewrites this file on site; a typo must not brick the booth.

    ROTATION, MAX_PRINTS, CALIBRATION and the window sides each grew their own
    guard after being bitten. Every other number went straight to configparser,
    which raises, and the booth would not start at all.
    """
    config = write_config(tmp_path, monkeypatch, f"""
        [Capture]
        COUNTDOWN = {raw}
    """)

    assert config.get_countdown() == 5


def test_a_malformed_web_port_falls_back_too(tmp_path, monkeypatch):
    config = write_config(tmp_path, monkeypatch, """
        [Web]
        WEB_PORT = eighty
    """)

    assert config.get_web_port() == 5000


def test_a_malformed_float_falls_back_too(tmp_path, monkeypatch):
    config = write_config(tmp_path, monkeypatch, """
        [Storage]
        DISK_MIN_FREE_GB = plenty
    """)

    assert config.get_disk_min_free_gb() == 2.0


def test_countdown_defaults_to_five(tmp_path, monkeypatch):
    config = write_config(tmp_path, monkeypatch, """
        [Capture]
    """)

    assert config.get_countdown() == 5


def test_a_countdown_of_zero_is_kept(tmp_path, monkeypatch):
    """It is the minimum the admin form offers, and it means "shoot on demand"."""
    config = write_config(tmp_path, monkeypatch, """
        [Capture]
        COUNTDOWN = 0
    """)

    assert config.get_countdown() == 0


def test_a_negative_countdown_is_floored_at_zero(tmp_path, monkeypatch):
    config = write_config(tmp_path, monkeypatch, """
        [Capture]
        COUNTDOWN = -3
    """)

    assert config.get_countdown() == 0


def test_window_size_defaults_to_the_reference_panel(tmp_path, monkeypatch):
    config = write_config(tmp_path, monkeypatch, """
        [Global]
        FULLSCREEN = False
    """)
    assert config.get_window_size() == (1024, 600)


def test_window_size_is_read_from_the_file(tmp_path, monkeypatch):
    config = write_config(tmp_path, monkeypatch, """
        [Global]
        WINDOW_WIDTH = 1920
        WINDOW_HEIGHT = 1080
    """)
    assert config.get_window_size() == (1920, 1080)


@pytest.mark.parametrize('raw', ['grand', '', '64'])
def test_an_unusable_window_side_falls_back_instead_of_raising(tmp_path, monkeypatch, raw):
    config = write_config(tmp_path, monkeypatch, f"""
        [Global]
        WINDOW_WIDTH = {raw}
        WINDOW_HEIGHT = 1080
    """)
    assert config.get_window_size() == (1024, 1080)


def test_the_window_settings_helper_survives_a_missing_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, 'CONFIG_PATH', tmp_path / 'absent.ini')
    assert config_module.window_settings_from_config() == (1024, 600, 0)


def test_rotation_defaults_to_none(tmp_path, monkeypatch):
    config = write_config(tmp_path, monkeypatch, """
        [Global]
        FULLSCREEN = False
    """)
    assert config.get_window_rotation() == 0


@pytest.mark.parametrize('raw', ['0', '90', '180', '270'])
def test_every_quarter_turn_is_accepted(tmp_path, monkeypatch, raw):
    config = write_config(tmp_path, monkeypatch, f"""
        [Global]
        ROTATION = {raw}
    """)
    assert config.get_window_rotation() == int(raw)


@pytest.mark.parametrize('raw', ['portrait', '45', '-90', ''])
def test_an_impossible_rotation_leaves_the_screen_alone(tmp_path, monkeypatch, raw):
    config = write_config(tmp_path, monkeypatch, f"""
        [Global]
        ROTATION = {raw}
    """)
    assert config.get_window_rotation() == 0


def test_a_rotated_booth_keeps_the_panel_mode_unswapped(tmp_path, monkeypatch):
    """The size is what the panel runs at; Kivy is what turns the interface."""
    config = write_config(tmp_path, monkeypatch, """
        [Global]
        WINDOW_WIDTH = 1920
        WINDOW_HEIGHT = 1080
        ROTATION = 90
    """)
    assert config.get_window_size() == (1920, 1080)
    assert config.get_window_rotation() == 90
