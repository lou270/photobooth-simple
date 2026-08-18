"""A short thank-you before returning to the welcome screen."""

from kivy.clock import Clock
from kivy.logger import Logger
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label

from libs.i18n import t
from libs.kivywidgets import ResizeLabel
from libs.screens.names import ScreenNames
from libs.screens.theme import ICON_SUCCESS, ICON_SUCCESS2, ICON_TTF, LARGE_FONT, wh_bind
from libs.screens.base import ColorScreen


class SuccessScreen(ColorScreen):
    """
    +-----------------+
    |                 |
    |    Perfect !    |
    |                 |
    +-----------------+
    """
    def __init__(self, app, **kwargs):
        Logger.info('SuccessScreen: __init__().')
        super(SuccessScreen, self).__init__(**kwargs)

        self.app = app

        layout = BoxLayout(orientation='vertical')

        # Display success icon
        icon = ResizeLabel(
            size_hint=(0.4, 0.4),
            pos_hint={'center_x': 0.5, 'center_y': 0.5},
            font_name=ICON_TTF,
            text=ICON_SUCCESS,
            wh_fraction=0.22,
        )
        layout.add_widget(icon)

        title = Label(
            size_hint=(1, 0.10),
            text=t('success.title'),
            font_size=LARGE_FONT(),
            bold=True,
            halign='center',
            valign='middle',
        )
        wh_bind(title, 'font_size', LARGE_FONT)
        title.bind(size=title.setter('text_size'))
        layout.add_widget(title)

        # Display success2 icon
        icon2 = ResizeLabel(
            size_hint=(0.1, 0.1),
            pos_hint={'center_x': 0.5, 'y': 0.3},
            font_name=ICON_TTF,
            text=ICON_SUCCESS2,
            wh_fraction=0.055,
        )
        layout.add_widget(icon2)

        self.add_widget(layout)

    def on_entry(self, kwargs={}):
        Logger.info('SuccessScreen: on_entry().')
        self._clock = Clock.schedule_once(self.timer_event, 1)
        self.app.ringled.blink([255, 255, 255])

    def on_exit(self, kwargs={}):
        Logger.info('SuccessScreen: on_exit().')
        Clock.unschedule(self._clock)
        self.app.ringled.clear()

    def on_click_start(self, obj):
        Logger.info('SuccessScreen: on_click_start(%s).', obj)
        self.app.transition_to(ScreenNames.START)

    def timer_event(self, obj):
        Logger.info('SuccessScreen: timer_event().')
        self.app.transition_to(ScreenNames.START)
