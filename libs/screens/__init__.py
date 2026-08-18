"""Every screen the booth shows, and the manager that switches between them."""

from libs.screens.base import BackgroundScreen, ColorScreen, HomeTimeoutMixin
from libs.screens.collect import CollectScreen
from libs.screens.confirm_capture import ConfirmCaptureScreen
from libs.screens.copying import CopyingScreen
from libs.screens.countdown import CountdownScreen
from libs.screens.error import ErrorScreen
from libs.screens.manager import ScreenMgr
from libs.screens.names import ScreenNames
from libs.screens.popups import PrintStatusPopup, QRCodePopup
from libs.screens.processing import ProcessingScreen
from libs.screens.remote_gallery import RemoteGalleryScreen
from libs.screens.review import ReviewScreen
from libs.screens.select_format import SelectFormatScreen
from libs.screens.start import StartScreen

__all__ = [
    'BackgroundScreen', 'ColorScreen', 'HomeTimeoutMixin', 'ScreenMgr', 'ScreenNames',
    'StartScreen', 'SelectFormatScreen', 'ErrorScreen', 'CountdownScreen',
    'ConfirmCaptureScreen', 'ProcessingScreen', 'ReviewScreen', 'CollectScreen',
    'CopyingScreen', 'RemoteGalleryScreen', 'PrintStatusPopup', 'QRCodePopup',
]
