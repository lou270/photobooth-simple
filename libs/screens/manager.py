"""The screen manager: which screens exist and how a key press moves between them."""

from kivy.core.window import Window
from kivy.logger import Logger
from kivy.uix.screenmanager import ScreenManager

from libs.screens.confirm_capture import ConfirmCaptureScreen
from libs.screens.copying import CopyingScreen
from libs.screens.countdown import CountdownScreen
from libs.screens.error import ErrorScreen
from libs.screens.names import ScreenNames
from libs.screens.processing import ProcessingScreen
from libs.screens.remote_gallery import RemoteGalleryScreen
from libs.screens.review import ReviewScreen
from libs.screens.select_format import SelectFormatScreen
from libs.screens.start import StartScreen
from libs.screens.success import SuccessScreen


class ScreenMgr(ScreenNames, ScreenManager):
    """Screen Manager for the photobooth screens.

    The identifiers come from ScreenNames rather than being declared here, so a
    screen can name where it is going without importing the class that builds
    every screen. Inheriting them keeps ScreenMgr.START working for callers
    outside this package.
    """

    def __init__(self, app, **kwargs):
        Logger.info('ScreenMgr: __init__().')
        super(ScreenMgr, self).__init__(**kwargs)
        self.app = app
        self.pb_screens = {
            self.START              : StartScreen(app, name=self.START),
            self.SELECT_FORMAT      : SelectFormatScreen(app, name=self.SELECT_FORMAT),
            self.ERROR              : ErrorScreen(app, name=self.ERROR),
            self.COUNTDOWN          : CountdownScreen(app, name=self.COUNTDOWN),
            self.CONFIRM_CAPTURE    : ConfirmCaptureScreen(app, name=self.CONFIRM_CAPTURE),
            self.PROCESSING         : ProcessingScreen(app, name=self.PROCESSING),
            self.REVIEW             : ReviewScreen(app, name=self.REVIEW),
            self.SUCCESS            : SuccessScreen(app, name=self.SUCCESS),
            self.COPYING            : CopyingScreen(app, name=self.COPYING),
        }
        # Only built where it can be reached: the welcome screen offers the way
        # in under the same condition, and an unused screen still costs textures.
        if app.has_remote_capture():
            self.pb_screens[self.REMOTE_GALLERY] = RemoteGalleryScreen(app, name=self.REMOTE_GALLERY)

        for screen in self.pb_screens.values(): self.add_widget(screen)

        self.current = self.START
        if self.app.FULLSCREEN: Window.fullscreen = True
        Window.bind(on_key_down=self._on_key_down)

    def _on_key_down(self, window, keycode, scancode, codepoint, modifiers):
        if keycode == 27:  # ESC: kiosk keyboard back/home, never quit Kivy.
            if self.current != self.START:
                self.app.transition_to(self.START)
            return True
        if keycode in (13, 32):  # ENTER / SPACE: activate the screen's primary button.
            action = getattr(self.current_screen, 'on_keyboard_action', None)
            return bool(action and action())
        return False
