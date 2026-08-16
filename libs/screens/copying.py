"""Progress while sessions are copied to a USB drive."""

from kivy.logger import Logger
from kivy.uix.boxlayout import BoxLayout

from libs.kivywidgets import ResizeLabel, RotatingLabel
from libs.screens.theme import ICON_LOADING, ICON_TTF, ICON_USB
from libs.screens.base import ColorScreen


class CopyingScreen(ColorScreen):
    """
    +-----------------+
    |                 |
    |     Copying     |
    |                 |
    +-----------------+
    """
    def __init__(self, app, **kwargs):
        Logger.info('CopyingScreen: __init__().')
        super(CopyingScreen, self).__init__(**kwargs)

        self.app = app
        self._count = 0

        layout = BoxLayout(orientation='vertical')

        # Display USB icon
        icon = ResizeLabel(
            size_hint=(0.4, 0.4),
            pos_hint={'center_x': 0.5, 'center_y': 0.5},
            font_name=ICON_TTF,
            text=ICON_USB,
            wh_fraction=0.22,
        )
        layout.add_widget(icon)
        info = ResizeLabel(
            size_hint=(0.9, 0.1),
            pos_hint={'center_x': 0.5, 'center_y': 0.6},
            text='Do not disconnect your USB dongle before this screen disapears !',
            wh_fraction=0.07,
        )
        layout.add_widget(info)

        # Display progress
        self.progress = ResizeLabel(
            size_hint=(0.9, 0.2),
            pos_hint={'center_x': 0.5, 'center_y': 0.35},
            text='-',
            wh_fraction=0.07,
        )
        layout.add_widget(self.progress)

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
        Logger.info('CopyingScreen: on_entry().')
        self.app.ringled.wave([255, 255, 255])

    def on_exit(self, kwargs={}):
        Logger.info('CopyingScreen: on_exit().')
        self.app.ringled.clear()

    def on_update(self, kwargs={}):
        if not 'label' in kwargs: return
        self.progress.text = f"Copying {kwargs.get('label')}"
