"""The evening's photos, shown on the welcome screen while nobody uses the booth."""

import threading

import cv2
from kivy.animation import Animation
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle
from kivy.logger import Logger
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label

from libs.i18n import t
from libs.kivywidgets import BlurredImage, short_side
from libs.screens.theme import BACKGROUND_COLOR


class Slideshow(FloatLayout):
    """A full-screen cover that cycles through photos until it is touched.

    It swallows the touch that dismisses it: the welcome screen underneath
    starts a session on any touch, and a guest who taps to wake the booth up
    expects to see the booth, not a countdown already running at them.

    Photos are read off the UI thread, one at a time, as they come up: an
    evening's worth decoded up front would be seconds of stutter and a few
    hundred megabytes on a Pi.
    """

    FADE_SECONDS = 0.6

    def __init__(self, photo_seconds, on_dismiss, **kwargs):
        super(Slideshow, self).__init__(**kwargs)
        self.photo_seconds = photo_seconds
        self.on_dismiss = on_dismiss
        self.photos = []
        self._index = 0
        self._clock = None
        self._running = False

        with self.canvas.before:
            Color(*BACKGROUND_COLOR[:3], 1)
            self._ground = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._redraw, size=self._redraw)

        self.image = BlurredImage(fit_mode='contain', size_hint=(1, 1), pos_hint={'x': 0, 'y': 0})
        self.image.opacity = 0
        self.add_widget(self.image)

        self.hint = Label(
            text=t('slideshow.hint'),
            bold=True,
            size_hint=(1, 0.1),
            pos_hint={'x': 0, 'y': 0.02},
            font_size=short_side(0.04),
            outline_width=2,
            outline_color=(0, 0, 0, 1),
        )
        self.add_widget(self.hint)

    def _redraw(self, *args):
        self._ground.pos = self.pos
        self._ground.size = self.size
        self.hint.font_size = short_side(0.04)

    @property
    def running(self):
        return self._running

    def start(self, photos):
        """Show `photos` in turn, newest first. Returns False when there is nothing to show."""
        if not photos:
            return False
        self.photos = list(photos)
        self._index = 0
        self._running = True
        self._show_current()
        self._clock = Clock.schedule_interval(self._advance, self.photo_seconds)
        return True

    def stop(self):
        self._running = False
        if self._clock is not None:
            Clock.unschedule(self._clock)
            self._clock = None
        Animation.cancel_all(self.image)
        self.image.opacity = 0

    def _advance(self, dt):
        self._index = (self._index + 1) % len(self.photos)
        self._show_current()

    def _show_current(self):
        path = self.photos[self._index]

        def load():
            image = cv2.imread(path)
            if image is None:
                Logger.warning('Slideshow: cannot read %s', path)
                return
            Clock.schedule_once(lambda dt: self._apply(image), 0)

        threading.Thread(target=load, name='photobooth-slideshow', daemon=True).start()

    def _apply(self, image):
        if not self._running:
            return
        self.image.set_image(image)
        self.image.opacity = 0
        Animation(opacity=1, duration=self.FADE_SECONDS).start(self.image)

    def on_touch_down(self, touch):
        if not self._running:
            return False
        if self.collide_point(*touch.pos):
            Logger.info('Slideshow: touched, back to the welcome screen.')
            self.on_dismiss()
            return True
        return False

    def on_touch_move(self, touch):
        return self._running

    def on_touch_up(self, touch):
        return self._running
