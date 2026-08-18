"""The last thing a guest sees: their print is on its way.

Replaces the congratulation screen that used to flash here for a second. It is
shown only when a print was actually sent, because the one thing a guest still
needs at that point is to know the photo is coming and where to pick it up: a
dye-sub printer takes a good ten seconds to hand it over, and nothing else in
the booth says so.
"""

from kivy.clock import Clock
from kivy.input.providers.mouse import MouseMotionEvent
from kivy.logger import Logger
from kivy.uix.boxlayout import BoxLayout

from libs.i18n import t
from libs.kivywidgets import LayoutButton, ResizeLabel
from libs.screens.names import ScreenNames
from libs.screens.theme import COLLECT_SECONDS, ICON_PRINT, ICON_TTF
from libs.screens.base import ColorScreen


class CollectScreen(ColorScreen):
    """
    +----------------------+
    |        [print]       |
    |  Your photo is coming|
    |  Take it from the    |
    |  printer             |
    +----------------------+
    """
    def __init__(self, app, **kwargs):
        Logger.info('CollectScreen: __init__().')
        super(CollectScreen, self).__init__(**kwargs)

        self.app = app
        self._clock = None

        # The whole screen is the way out: a guest who has their print in hand
        # should not have to find a button to free the booth for the next one.
        layout = LayoutButton()

        content = BoxLayout(
            orientation='vertical',
            size_hint=(0.9, 0.8),
            pos_hint={'center_x': 0.5, 'center_y': 0.5},
            spacing=0,
        )

        icon = ResizeLabel(
            size_hint=(1, 0.4),
            font_name=ICON_TTF,
            text=ICON_PRINT,
            wh_fraction=0.20,
        )
        content.add_widget(icon)

        title = ResizeLabel(
            size_hint=(1, 0.16),
            text=t('collect.title'),
            wh_fraction=0.065,
            bold=True,
            halign='center',
            valign='middle',
        )
        content.add_widget(title)

        message = ResizeLabel(
            size_hint=(1, 0.16),
            text=t('collect.message'),
            wh_fraction=0.04,
            halign='center',
            valign='middle',
        )
        content.add_widget(message)

        hint = ResizeLabel(
            size_hint=(1, 0.12),
            text=t('collect.hint'),
            wh_fraction=0.025,
            halign='center',
            valign='middle',
        )
        content.add_widget(hint)

        layout.add_widget(content)
        layout.bind(on_release=self.on_click)
        self.add_widget(layout)

    def on_entry(self, kwargs={}):
        Logger.info('CollectScreen: on_entry().')
        self._clock = Clock.schedule_once(self.timer_event, COLLECT_SECONDS)
        self.app.ringled.wave([255, 255, 255])

    def on_exit(self, kwargs={}):
        Logger.info('CollectScreen: on_exit().')
        if self._clock:
            Clock.unschedule(self._clock)
            self._clock = None
        self.app.ringled.clear()

    def on_click(self, obj):
        if obj is not None and not isinstance(obj.last_touch, MouseMotionEvent): return
        Logger.info('CollectScreen: on_click().')
        self.app.transition_to(ScreenNames.START)

    def timer_event(self, obj):
        Logger.info('CollectScreen: timer_event().')
        self.app.transition_to(ScreenNames.START)

    def on_keyboard_action(self):
        self.on_click(None)
        return True
