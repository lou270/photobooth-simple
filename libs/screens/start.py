"""The welcome screen a guest touches to begin."""

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.input.providers.mouse import MouseMotionEvent
from kivy.logger import Logger
from kivy.uix.label import Label

from libs.kivywidgets import LayoutButton, ResizeLabel, BreezyBorderedLabel
from libs.version import APP_VERSION
from libs.screens.names import ScreenNames
from libs.screens.theme import ICON_TOUCH, ICON_TTF, TINY_FONT, wh_bind
from libs.screens.base import BackgroundScreen
from libs.screens.popups import QRCodePopup


class StartScreen(BackgroundScreen):
    """
    +-----------------+
    |                 |
    | Press to begin  |
    |                 |
    +-----------------+
    """
    def __init__(self, app, **kwargs):
        Logger.info('StartScreen: __init__().')
        super(StartScreen, self).__init__(bg='./assets/backgrounds/bg_waiting.jpeg', **kwargs)

        self.app = app

        overlay_layout = LayoutButton()

        start = BreezyBorderedLabel(
            text='PHOTO BOOTH',
            border_color=(1,1,1,1),
            border_width=Window.height * 0.006,
            size_hint=(0.7, 0.2),
            padding=(Window.height * 0.033, Window.height * 0.033, Window.height * 0.033, Window.height * 0.033),
            pos_hint={'x': 0.15, 'y': 0.4},
        )
        # BreezyBorderedLabel.on_size() recomputes font_size from width — no wh_bind needed
        overlay_layout.add_widget(start)
        self.start_label = start

        # Touch icon
        icon = ResizeLabel(
            size_hint=(0.15, 0.2),
            pos_hint={'x': 0.42, 'y': 0.1},
            font_name=ICON_TTF,
            text=ICON_TOUCH,
            wh_fraction=0.22,
        )
        overlay_layout.add_widget(icon)

        # Version: useful to the operator powering the booth up, and to nobody
        # else. Shown at startup, then faded out before the first guest arrives.
        self._version_label = Label(
            text=f'Version {APP_VERSION}',
            font_size=TINY_FONT(),
            halign='left',
            valign='middle',
            size_hint=(0.1, 0.05),
            pos_hint={'x': 0.9, 'y': 0.95},
        )
        wh_bind(self._version_label, 'font_size', TINY_FONT)
        overlay_layout.add_widget(self._version_label)

        overlay_layout.bind(on_release=self.on_click)

        self.add_widget(overlay_layout)

    def on_entry(self, kwargs={}):
        Logger.info('StartScreen: on_entry().')
        if self._version_label is not None:
            Animation(opacity=0, duration=1.5, t='in_quad').start(self._version_label)
            self._version_label = None  # only the first time, at power-up
        self.app.ringled.start_rainbow()
        self._purge_when_idle()

    def _purge_when_idle(self, *args):
        if self.app.get_current_screen_name() != ScreenNames.START:
            return
        if self.app.has_pending_photo_tasks() or self.app.has_background_processes():
            Clock.schedule_once(self._purge_when_idle, 0.5)
        else:
            self.app.clear_pending_photo_error()
            self.app.purge_tmp()
            if self.app.SHARE:
                QRCodePopup.preload_async()

    def on_exit(self, kwargs={}):
        Logger.info('StartScreen: on_exit().')
        self.app.ringled.clear()

    def on_click(self, obj):
        if not isinstance(obj.last_touch, MouseMotionEvent): return
        Logger.info('StartScreen: on_click().')
        self.app.transition_to(ScreenNames.SELECT_FORMAT)

    def on_keyboard_action(self):
        Logger.info('StartScreen: on_keyboard_action().')
        self.app.transition_to(ScreenNames.SELECT_FORMAT)
        return True
