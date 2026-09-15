"""What the window shows while the booth gets ready, before any screen exists."""

from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.logger import Logger
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.widget import Widget

from libs import event
from libs.boot_splash import VEIL_OPACITY
from libs.i18n import t
from libs.kivywidgets import short_side
from libs.screens.base import BackgroundScreen
from libs.screens.theme import LARGE_FONT, SMALL_FONT, wh_bind


class StepBar(Widget):
    """A thin rounded bar, filled to `progress` (0..1).

    Not called ProgressBar: Kivy styles widgets by class name, and its own
    ProgressBar rule would be applied to this one.
    """

    def __init__(self, **kwargs):
        super(StepBar, self).__init__(**kwargs)
        self.progress = 0.0
        with self.canvas:
            Color(1, 1, 1, 0.25)
            self._track = RoundedRectangle()
            Color(1, 1, 1, 0.9)
            self._fill = RoundedRectangle()
        self.bind(pos=self._redraw, size=self._redraw)

    def set_progress(self, progress):
        self.progress = max(0.0, min(1.0, progress))
        self._redraw()

    def _redraw(self, *args):
        radius = [self.height / 2.0]
        self._track.pos = (self.x, self.y)
        self._track.size = (self.width, self.height)
        self._track.radius = radius
        self._fill.pos = (self.x, self.y)
        # Never narrower than it is tall: a sliver of a rounded bar draws as a
        # smudge, where a dot reads as "just started".
        self._fill.size = (max(self.height, self.width * self.progress), self.height)
        self._fill.radius = radius


class LoadingScreen(BackgroundScreen):
    """
    +-----------------+
    |                 |
    |  Getting ready  |
    |   ==========    |
    |  Camera...      |
    +-----------------+

    Shown by PhotoboothApp while it opens the camera, loads the templates and
    builds the other screens, which takes seconds on a Pi. The picture is the
    welcome background under the same veil as the boot splash, so the screen
    reads as the boot splash going on rather than as a new one.

    Not a screen of the ScreenMgr: it exists precisely because the manager does
    not yet.
    """

    def __init__(self, font_name=None, **kwargs):
        Logger.info('LoadingScreen: __init__().')
        super(LoadingScreen, self).__init__(bg=str(event.welcome_background()), **kwargs)

        with self.canvas.before:
            Color(0, 0, 0, VEIL_OPACITY)
            self._veil = Rectangle()

        layout = FloatLayout()

        label_options = {'font_name': font_name} if font_name else {}
        # Held against the bar from above and below: see _layout.
        self.title = Label(text=t('loading.title'), font_size=LARGE_FONT(), halign='center', valign='bottom',
                           **label_options)
        wh_bind(self.title, 'font_size', LARGE_FONT)
        layout.add_widget(self.title)

        self.progress_bar = StepBar(size_hint=(None, None))
        layout.add_widget(self.progress_bar)

        self.caption = Label(text='', font_size=SMALL_FONT(), halign='center', valign='top',
                             color=(1, 1, 1, 0.8), **label_options)
        wh_bind(self.caption, 'font_size', SMALL_FONT)
        layout.add_widget(self.caption)

        self.add_widget(layout)
        self.layout = layout
        layout.bind(size=self._layout)

    def show_step(self, caption, progress):
        """Name what the booth is doing now, and how far along it is."""
        self.caption.text = caption
        self.progress_bar.set_progress(progress)

    def on_size(self, *args):
        super(LoadingScreen, self).on_size(*args)
        self._veil.size = self.size

    def _layout(self, *args):
        # Read from the layout's own size: in a size callback its centre still
        # holds the previous value.
        width, height = self.layout.size
        if not width or not height:
            return

        middle_x = width / 2.0
        middle_y = height / 2.0
        gap = short_side(0.05)
        # Tall boxes, with the words held against the bar: on a screen stood
        # upright the title wraps, and its second line has to grow away from
        # the bar rather than into it.
        box_height = short_side(0.3)

        self.title.size_hint = (None, None)
        self.title.size = (width * 0.9, box_height)
        self.title.text_size = self.title.size
        self.title.pos = (middle_x - self.title.width / 2.0, middle_y + gap)

        bar_width = min(width * 0.6, short_side(0.9))
        self.progress_bar.size = (bar_width, short_side(0.016))
        self.progress_bar.pos = (middle_x - bar_width / 2.0, middle_y - self.progress_bar.height / 2.0)

        self.caption.size_hint = (None, None)
        self.caption.size = (width * 0.9, box_height)
        self.caption.text_size = self.caption.size
        self.caption.pos = (middle_x - self.caption.width / 2.0, middle_y - gap - box_height)
