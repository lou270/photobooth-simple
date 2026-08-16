"""Applying DSLR settings: what reaches the camera, and what is skipped and why.

Silently not applying a configured aperture is worse than refusing it: the
operator sees photos that ignore the settings with nothing in the log.
"""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault('KIVY_NO_ARGS', '1')
os.environ.setdefault('KIVY_GL_BACKEND', 'mock')

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.device_utils import Gphoto2Camera


class FakeWidget:
    def __init__(self, value=None):
        self.value = value

    def get_value(self):
        return self.value

    def set_value(self, value):
        self.value = value


class FakeConfig:
    """Only exposes the widget paths it was given, like a real camera model."""

    def __init__(self, widgets):
        self.widgets = dict(widgets)

    def get_path(self, path):
        return self.widgets.get(path)


class FakeCameraHandle:
    def __init__(self, config):
        self._config = config
        self.commits = 0

    def get_config(self):
        return self._config

    def commit_config(self, config):
        self.commits += 1


def canon_config(mode='Manual', **overrides):
    widgets = {
        '/main/status/manufacturer': FakeWidget('Canon Inc.'),
        '/main/capturesettings/autoexposuremode': FakeWidget(mode),
        '/main/capturesettings/shutterspeed': FakeWidget(),
        '/main/capturesettings/aperture': FakeWidget(),
        '/main/capturesettings/focusmode': FakeWidget(),
        '/main/imgsettings/iso': FakeWidget(),
    }
    widgets.update(overrides)
    return FakeConfig(widgets)


def camera_for(config):
    camera = Gphoto2Camera.__new__(Gphoto2Camera)
    camera._instance = FakeCameraHandle(config)
    return camera


ALL_PARAMS = {'SHUTTERSPEED': '1/125', 'APERTURE': '13', 'FOCUSMODE': 'One Shot', 'ISO': '100'}


def test_settings_reach_a_canon_in_manual_mode():
    config = canon_config('Manual')
    camera = camera_for(config)

    camera._set_parameters(ALL_PARAMS)

    assert config.widgets['/main/capturesettings/shutterspeed'].value == '1/125'
    assert config.widgets['/main/capturesettings/aperture'].value == '13'
    assert config.widgets['/main/capturesettings/focusmode'].value == 'One Shot'
    assert config.widgets['/main/imgsettings/iso'].value == '100'
    assert camera._instance.commits == 1


def test_exposure_dependent_settings_are_skipped_in_the_wrong_mode():
    config = canon_config('P')  # program mode: shutter and aperture are the body's call
    camera = camera_for(config)

    camera._set_parameters(ALL_PARAMS)

    assert config.widgets['/main/capturesettings/shutterspeed'].value is None
    assert config.widgets['/main/capturesettings/aperture'].value is None
    # Focus mode and ISO do not depend on the exposure mode.
    assert config.widgets['/main/capturesettings/focusmode'].value == 'One Shot'
    assert config.widgets['/main/imgsettings/iso'].value == '100'


def test_a_widget_the_model_does_not_expose_is_skipped_without_raising():
    widgets = dict(canon_config('Manual').widgets)
    del widgets['/main/capturesettings/aperture']
    config = FakeConfig(widgets)
    camera = camera_for(config)

    camera._set_parameters(ALL_PARAMS)

    assert config.widgets['/main/capturesettings/shutterspeed'].value == '1/125'


def test_a_camera_without_a_manufacturer_widget_is_left_alone():
    config = FakeConfig({})
    camera = camera_for(config)

    camera._set_parameters(ALL_PARAMS)

    assert camera._instance.commits == 0


def test_an_unsupported_manufacturer_is_left_alone():
    config = FakeConfig({'/main/status/manufacturer': FakeWidget('Fujifilm')})
    camera = camera_for(config)

    camera._set_parameters(ALL_PARAMS)

    assert camera._instance.commits == 0


def test_nothing_is_committed_when_no_setting_applies():
    config = canon_config('P')
    camera = camera_for(config)

    camera._set_parameters({'SHUTTERSPEED': '1/125'})

    assert camera._instance.commits == 0


def test_empty_parameters_do_not_touch_the_camera():
    config = canon_config('Manual')
    camera = camera_for(config)

    camera._set_parameters({})

    assert camera._instance.commits == 0


def test_nikon_gets_the_f_number_path_and_a_prefixed_aperture():
    config = FakeConfig({
        '/main/status/manufacturer': FakeWidget('Nikon Corporation'),
        '/main/capturesettings/expprogram': FakeWidget('M'),
        '/main/capturesettings/f-number': FakeWidget(),
    })
    camera = camera_for(config)

    camera._set_parameters({'APERTURE': '2.8'})

    assert config.widgets['/main/capturesettings/f-number'].value == 'f/2.8'


@pytest.mark.parametrize('configured,expected', [('13', '13'), ('f/13', '13')])
def test_canon_accepts_an_aperture_written_either_way(configured, expected):
    config = canon_config('Manual')
    camera = camera_for(config)

    camera._set_parameters({'APERTURE': configured})

    assert config.widgets['/main/capturesettings/aperture'].value == expected
