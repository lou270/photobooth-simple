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
