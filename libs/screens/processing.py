"""Waiting while the collage is assembled."""

from kivy.clock import Clock
from kivy.logger import Logger
from kivy.uix.boxlayout import BoxLayout

from libs.kivywidgets import ResizeLabel, RotatingLabel
from libs.screens.names import ScreenNames
from libs.screens.theme import ICON_LOADING, ICON_PROCESSING, ICON_TTF
from libs.screens.base import ColorScreen


class ProcessingScreen(ColorScreen):
    """
    +-----------------+
    |                 |
    |   Processing    |
    |                 |
    +-----------------+
    """
    def __init__(self, app, **kwargs):
        Logger.info('ProcessingScreen: __init__().')
        super(ProcessingScreen, self).__init__(**kwargs)

        self.app = app
        self._current_format = 0

        layout = BoxLayout(orientation='vertical')

        # Display processing
        icon = ResizeLabel(
            size_hint=(0.4, 0.4),
            pos_hint={'center_x': 0.5, 'center_y': 0.5},
            font_name=ICON_TTF,
            text=ICON_PROCESSING,
            wh_fraction=0.22,
        )
        layout.add_widget(icon)

        # Display loading spinner
        loading = RotatingLabel(
            size_hint=(0.1, 0.1),
            pos_hint={'center_x': 0.5, 'y': 0.3},
            font_name=ICON_TTF,
            text=ICON_LOADING,
            wh_fraction=0.055,
        )

        layout.add_widget(loading)
        self.add_widget(layout)

    def on_entry(self, kwargs={}):
        Logger.info('ProcessingScreen: on_entry().')
        self._current_format = kwargs.get('format') if 'format' in kwargs else 0
        self._clock = Clock.schedule_once(self.timer_event, 0.2)
        self.app.ringled.start_rainbow()

        self._collage_started = False

    def on_exit(self, kwargs={}):
        Logger.info('ProcessingScreen: on_exit().')
        Clock.unschedule(self._clock)
        self.app.ringled.clear()

    def timer_event(self, obj):
        Logger.info('ProcessingScreen: timer_event().')
        if self.app.has_pending_photo_tasks():
            self._clock = Clock.schedule_once(self.timer_event, 0.2)
            return

        if self.app.get_pending_photo_error():
            Logger.error('ProcessingScreen: photo preparation failed.')
            Logger.error(self.app.get_pending_photo_error())
            self.app.transition_to(ScreenNames.ERROR, message='Photo processing failed.')
            return

        if not self._collage_started:
            self._collage_started = True
            self.app.trigger_collage(self._current_format)
            self._clock = Clock.schedule_once(self.timer_event, 0.2)
            return

        if not(self.app.is_collage_completed()):
            self._clock = Clock.schedule_once(self.timer_event, 0.5)
        elif self.app.has_process_failed('collage'):
            Logger.error('ProcessingScreen: collage generation failed.')
            error_details = self.app.get_process_error('collage')
            if error_details:
                Logger.error(error_details)
            self.app.transition_to(ScreenNames.ERROR, message='Collage creation failed.')
        else:
            self.app.transition_to(ScreenNames.REVIEW, format=self._current_format)
