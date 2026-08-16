"""Hardware abstractions for the photobooth.

Nothing in this package imports Kivy: it must stay usable from a test suite, a
calibration script or a future non-Kivy front-end.
"""

from libs.hardware.camera import Camera
from libs.hardware.fake import FakeCamera
from libs.hardware.led import Led, NullLed, RingLed, create_led

__all__ = ['Camera', 'FakeCamera', 'Led', 'NullLed', 'RingLed', 'create_led']
