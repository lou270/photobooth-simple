"""The maintenance screen: something needs an operator."""

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.logger import Logger
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label

from libs.i18n import t
from libs.kivywidgets import ResizeLabel, RoundedButton
from libs.screens.names import ScreenNames
from libs.screens.theme import (
    CONFIRM_COLOR, ERROR_HOME_TIMEOUT_SECONDS, HOME_COLOR, ICON_ERROR, ICON_TTF,
    LARGE_FONT, SMALL_FONT, wh_bind,
)
from libs.screens.base import ColorScreen


class ErrorScreen(ColorScreen):
    """
    +-----------------+
    |  Error occured  |
    |    Continue     |
    +-----------------+
    """
    def __init__(self, app, **kwargs):
        Logger.info('ErrorScreen: __init__().')
        super(ErrorScreen, self).__init__(**kwargs)

        self.app = app
        self._show_continue = True
        self._show_restart = False
        self._home_timeout_clock = None

        layout = BoxLayout(orientation='vertical', padding=(0, dp(12), 0, dp(24)), spacing=dp(12))

        # Display error icon
        self.icon = ResizeLabel(
            size_hint=(0.4, 0.32),
            pos_hint={'center_x': 0.5, 'center_y': 0.5},
            font_name=ICON_TTF,
            text=ICON_ERROR,
            wh_fraction=0.22,
        )
        layout.add_widget(self.icon)

        self.title = Label(
            size_hint=(1, 0.10),
            text=t('error.title'),
            font_size=LARGE_FONT(),
            bold=True,
            halign='center',
            valign='middle',
        )
        wh_bind(self.title, 'font_size', LARGE_FONT)
        self.title.bind(size=self.title.setter('text_size'))
        layout.add_widget(self.title)

        self.message = Label(
            size_hint=(1, 0.24),
            text=t('error.generic'),
            font_size=SMALL_FONT(),
            halign='center',
            valign='middle',
        )
        wh_bind(self.message, 'font_size', SMALL_FONT)
        self.message.bind(size=self.message.setter('text_size'))
        layout.add_widget(self.message)

        self.actions = BoxLayout(
            orientation='horizontal',
            spacing=dp(16),
            size_hint=(1, 0.12),
            padding=(Window.width * 0.18, 0, Window.width * 0.18, 0),
        )

        self.btn_restart = RoundedButton(
            text=t('error.restart'),
            size_hint=(1, 1),
            background_color=HOME_COLOR,
            font_size=SMALL_FONT(),
            bold=True,
            halign='center',
            valign='middle',
        )
        wh_bind(self.btn_restart, 'font_size', SMALL_FONT)
        self.btn_restart.bind(size=self.btn_restart.setter('text_size'))
        self.btn_restart.bind(on_release=self.on_restart)
        self.actions.add_widget(self.btn_restart)

        self.btn_continue = RoundedButton(
            text=t('error.continue'),
            size_hint=(1, 1),
            background_color=CONFIRM_COLOR,
            font_size=SMALL_FONT(),
            bold=True,
            halign='center',
            valign='middle',
        )
        wh_bind(self.btn_continue, 'font_size', SMALL_FONT)
        self.btn_continue.bind(size=self.btn_continue.setter('text_size'))
        self.btn_continue.bind(on_release=self.on_click)
        self.actions.add_widget(self.btn_continue)

        layout.add_widget(self.actions)

        self.add_widget(layout)

    def on_entry(self, kwargs={}):
        Logger.info('ErrorScreen: on_entry().')
        self.title.text = t('error.title')
        self.icon.text = str(kwargs.get('error', ICON_ERROR))
        self.message.text = str(kwargs.get('message', t('error.generic')))
        self._show_continue = bool(kwargs.get('show_continue', True))
        self._show_restart = bool(kwargs.get('show_restart', False))
        self.btn_continue.text = str(kwargs.get('continue_text', t('error.continue')))
        self.btn_restart.text = str(kwargs.get('restart_text', t('error.restart')))
        self.btn_continue.opacity = 1 if self._show_continue else 0
        self.btn_continue.disabled = not self._show_continue
        self.btn_restart.opacity = 1 if self._show_restart else 0
        self.btn_restart.disabled = not self._show_restart
        self.actions.opacity = 1 if (self._show_continue or self._show_restart) else 0
        self._start_home_timeout()

    def _start_home_timeout(self):
        """Take the booth home from an error the next guest need not read.

        Only where continuing is offered: an error with nothing but a restart
        button is a booth waiting for an operator, and walking it back to the
        welcome screen would send the next guest straight into the same wall.
        """
        self._stop_home_timeout()
        if not self._show_continue:
            return
        self._home_timeout_clock = Clock.schedule_once(
            self._home_timeout_event, ERROR_HOME_TIMEOUT_SECONDS)

    def _stop_home_timeout(self):
        if self._home_timeout_clock:
            Clock.unschedule(self._home_timeout_clock)
            self._home_timeout_clock = None

    def _home_timeout_event(self, dt):
        Logger.info('ErrorScreen: home timeout, returning to start.')
        self._home_timeout_clock = None
        self.app.transition_to(ScreenNames.START)

    def on_exit(self, kwargs={}):
        Logger.info('ErrorScreen: on_exit().')
        self._stop_home_timeout()

    def on_click(self, obj):
        Logger.info('ErrorScreen: on_click().')
        self.app.transition_to(ScreenNames.START)

    def on_restart(self, obj):
        Logger.info('ErrorScreen: on_restart().')
        self.app.request_restart()

    def on_keyboard_action(self):
        Logger.info('ErrorScreen: on_keyboard_action().')
        if self._show_continue:
            self.app.transition_to(ScreenNames.START)
            return True
        if self._show_restart:
            self.app.request_restart()
            return True
        return False
