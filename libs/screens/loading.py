"""What the window shows while the booth gets ready, before any screen exists."""

from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.logger import Logger
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.widget import Widget

from libs import event
from libs.boot_splash import VEIL_OPACITY
from libs.i18n import t
from libs.kivywidgets import RoundedButton, short_side
from libs.screens.base import BackgroundScreen
from libs.screens.theme import CONFIRM_COLOR, LARGE_FONT, SMALL_FONT, wh_bind


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
        super(LoadingScreen, self).__init__(bg=str(event.welcome_background()),
                                            fallback_bg=str(event.DEFAULT_WELCOME_BACKGROUND), **kwargs)

        with self.canvas.before:
            Color(0, 0, 0, VEIL_OPACITY)
            self._veil = Rectangle()

        layout = FloatLayout()

        label_options = {'font_name': font_name} if font_name else {}
        self._label_options = label_options
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

        self.ok_button = None
        self._on_ok = None

        self.add_widget(layout)
        self.layout = layout
        layout.bind(size=self._layout)

    def show_step(self, caption, progress):
        """Name what the booth is doing now, and how far along it is."""
        self.caption.text = caption
        self.progress_bar.set_progress(progress)

    def show_failure(self, title, message, ok_text, on_ok):
        """Say why the booth cannot start, and wait for OK to call `on_ok`.

        Enter and space press OK too: the manager that maps them for the other
        screens does not exist yet.
        """
        self._on_ok = on_ok
        self.title.text = title
        self.caption.text = message
        self.caption.color = (1, 1, 1, 1)
        self.layout.remove_widget(self.progress_bar)
        self.ok_button = RoundedButton(
            text=ok_text,
            size_hint=(None, None),
            background_color=CONFIRM_COLOR,
            font_size=SMALL_FONT(),
            bold=True,
            halign='center',
            valign='middle',
            **self._label_options
        )
        wh_bind(self.ok_button, 'font_size', SMALL_FONT)
        self.ok_button.bind(size=self.ok_button.setter('text_size'))
        self.ok_button.bind(on_release=lambda *args: self._press_ok())
        self.layout.add_widget(self.ok_button)
        Window.bind(on_key_down=self._on_key_down)
        self._layout()

    def _on_key_down(self, window, keycode, *args):
        if keycode in (13, 32):  # ENTER / SPACE
            self._press_ok()
            return True
        return False

    def _press_ok(self):
        if self._on_ok is None:
            return
        Logger.info('LoadingScreen: OK pressed after a startup failure.')
        on_ok, self._on_ok = self._on_ok, None
        Window.unbind(on_key_down=self._on_key_down)
        on_ok()

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

        if self.ok_button is not None:
            # No bar to make room for: the message comes up to the title, and
            # a shorter box leaves the button room beneath it.
            message_height = short_side(0.2)
            self.caption.size = (width * 0.9, message_height)
            self.caption.text_size = self.caption.size
            self.caption.pos = (middle_x - self.caption.width / 2.0, middle_y - message_height)
            self.ok_button.size = (min(width * 0.4, short_side(0.5)), short_side(0.1))
            self.ok_button.pos = (middle_x - self.ok_button.width / 2.0,
                                  self.caption.y - gap - self.ok_button.height)
