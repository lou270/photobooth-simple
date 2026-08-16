"""Screens every other screen is built on, and the walk-away timeout they share."""

from kivy.clock import Clock
from kivy.graphics import Color, Rectangle
from kivy.input.providers.mouse import MouseMotionEvent
from kivy.logger import Logger
from kivy.uix.screenmanager import Screen

from libs.screens.names import ScreenNames
from libs.screens.theme import BACKGROUND_COLOR, BORDER_COLOR, BORDER_THINKNESS


class HomeTimeoutMixin:
    """Send an abandoned session back to the start screen.

    Several screens wait on a guest who may simply have walked away, and the ring
    drawn around the home button doubles as the visual countdown. Starting the
    timeout, animating the ring and going home are one behaviour; they used to
    be copy-pasted on each screen, differing only by the delay.

    Screens set HOME_TIMEOUT_SECONDS, and HOME_TIMEOUT_HIDES_RING when the ring
    has to disappear while something else owns the screen.
    """

    HOME_TIMEOUT_SECONDS = 60
    HOME_TIMEOUT_HIDES_RING = False

    def _init_home_timeout(self):
        self._home_timeout_clock = None
        self._home_progress_clock = None
        self._home_timeout_started_at = 0.0

    def _start_home_timeout(self):
        self._stop_home_timeout()
        self._home_timeout_started_at = Clock.get_boottime()
        self.btn_home.progress = 1.0
        if self.HOME_TIMEOUT_HIDES_RING:
            self.btn_home.show_progress = True
        self._home_timeout_clock = Clock.schedule_once(self._home_timeout_event, self.HOME_TIMEOUT_SECONDS)
        self._home_progress_clock = Clock.schedule_interval(self._update_home_progress, 1 / 30.0)

    def _stop_home_timeout(self):
        if self._home_timeout_clock:
            Clock.unschedule(self._home_timeout_clock)
            self._home_timeout_clock = None
        if self._home_progress_clock:
            Clock.unschedule(self._home_progress_clock)
            self._home_progress_clock = None
        self.btn_home.progress = 1.0
        if self.HOME_TIMEOUT_HIDES_RING:
            self.btn_home.show_progress = False

    def _update_home_progress(self, dt):
        elapsed = Clock.get_boottime() - self._home_timeout_started_at
        self.btn_home.progress = max(0, 1.0 - (elapsed / self.HOME_TIMEOUT_SECONDS))

    def _home_timeout_event(self, dt):
        Logger.info('%s: home timeout, returning to start.', type(self).__name__)
        self._stop_home_timeout()
        self.app.transition_to(ScreenNames.START)

    def home_event(self, obj):
        if obj is not None and not isinstance(obj.last_touch, MouseMotionEvent):
            return
        Logger.info('%s: home_event().', type(self).__name__)
        self._stop_home_timeout()
        self.app.transition_to(ScreenNames.START)

class BackgroundScreen(Screen):
    def __init__(self, bg='./assets/backgrounds/bg_default.jpeg', **kwargs):
        super(BackgroundScreen, self).__init__(**kwargs)
        with self.canvas.before:
            self.background_image = Rectangle(pos=self.pos, size=self.size, source=bg)

    def on_pos(self, *args):
        self.background_image.pos = self.pos

    def on_size(self, *args):
        self.background_image.size = self.size

    def on_update(self, kwargs={}):
        pass

class ColorScreen(Screen):
    def __init__(self, **kwargs):
        super(ColorScreen, self).__init__(**kwargs)
        with self.canvas.before:
            # Border
            if BORDER_THINKNESS > 0:
                Color(*BORDER_COLOR)
                self.border_rect = Rectangle(pos=self.pos, size=self.size)
            else:
                self.border_rect = None

            # Background
            Color(*BACKGROUND_COLOR)
            self.background_rect = Rectangle(pos=(self.x + BORDER_THINKNESS, self.y + BORDER_THINKNESS), size=(self.width - BORDER_THINKNESS*2, self.height - BORDER_THINKNESS*2))

    def on_pos(self, *args):
        if self.border_rect: self.border_rect.pos = self.pos
        self.background_rect.pos = (self.x + BORDER_THINKNESS, self.y + BORDER_THINKNESS)

    def on_size(self, *args):
        if self.border_rect: self.border_rect.size = self.size
        self.background_rect.size = (self.width - BORDER_THINKNESS*2, self.height - BORDER_THINKNESS*2)

    def on_update(self, kwargs={}):
        pass
