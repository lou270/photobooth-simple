"""The welcome screen a guest touches to begin."""

import threading

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.input.providers.mouse import MouseMotionEvent
from kivy.logger import Logger
from kivy.uix.label import Label

from libs.kivywidgets import LayoutButton, ResizeLabel, BreezyBorderedLabel, make_icon_button
from libs.version import APP_VERSION
from libs.screens.names import ScreenNames
from libs.screens.theme import (
    BADGE_COLOR, ICON_QRCODE, ICON_SHOT_TAKEN, ICON_TOUCH, ICON_TTF,
    REMOTE_COLOR, SHARE_COLOR, TINY_FONT, wh_bind,
)
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

        # Sending photos from a phone: the QR code is how a guest learns the
        # feature exists at all, and the queue button only appears once a phone
        # has actually sent something.
        self.btn_remote_qr = None
        self.btn_remote_queue = None
        self.qr_popup = None
        self._queue_clock = None
        self._pending_count = 0

        if self.app.has_remote_capture():
            self.btn_remote_qr = make_icon_button(
                ICON_QRCODE,
                size=0.13,
                pos_hint={'right': 0.98, 'y': 0.03},
                font=ICON_TTF,
                font_size_fraction=0.06,
                bgcolor=SHARE_COLOR,
                on_release=self.remote_qr_event,
            )
            overlay_layout.add_widget(self.btn_remote_qr)

        overlay_layout.bind(on_release=self.on_click)
        self.overlay_layout = overlay_layout

        self.add_widget(overlay_layout)

    def on_entry(self, kwargs={}):
        Logger.info('StartScreen: on_entry().')
        if self._version_label is not None:
            Animation(opacity=0, duration=1.5, t='in_quad').start(self._version_label)
            self._version_label = None  # only the first time, at power-up
        self.app.ringled.start_rainbow()
        self._purge_when_idle()

        if self.app.has_remote_capture():
            QRCodePopup.preload_steps(self.app.get_qr_invitation(self.app.remote_url)[0])
            self._refresh_pending_count()
            self._queue_clock = Clock.schedule_interval(self._refresh_pending_count, 5)

    def _purge_when_idle(self, *args):
        if self.app.get_current_screen_name() != ScreenNames.START:
            return
        if self.app.has_pending_photo_tasks() or self.app.has_background_processes():
            Clock.schedule_once(self._purge_when_idle, 0.5)
        else:
            self.app.clear_pending_photo_error()
            self.app.purge_tmp()
            if self.app.SHARE:
                QRCodePopup.preload_steps(self.app.get_qr_invitation(self.app.gallery_url)[0])

    def on_exit(self, kwargs={}):
        Logger.info('StartScreen: on_exit().')
        if self._queue_clock is not None:
            Clock.unschedule(self._queue_clock)
            self._queue_clock = None
        self._dismiss_qr_popup()
        self.app.ringled.clear()

    # --- photos waiting from phones --------------------------------------

    def _refresh_pending_count(self, *args):
        """Count the queue off the UI thread: it is a file read, on every tick."""
        def read_count():
            count = self.app.get_remote_pending_count()
            Clock.schedule_once(lambda dt: self._apply_pending_count(count), 0)

        threading.Thread(target=read_count, name='photobooth-remote-count', daemon=True).start()

    def _apply_pending_count(self, count):
        if count == self._pending_count:
            return
        self._pending_count = count

        if self.btn_remote_queue is not None:
            self.overlay_layout.remove_widget(self.btn_remote_queue)
            self.btn_remote_queue = None

        if count <= 0:
            return

        # Rebuilt rather than relabelled: the badge is baked into the button by
        # make_icon_button, and there is at most one rebuild every five seconds.
        self.btn_remote_queue = make_icon_button(
            ICON_SHOT_TAKEN,
            size=0.13,
            pos_hint={'x': 0.02, 'y': 0.03},
            font=ICON_TTF,
            font_size_fraction=0.06,
            bgcolor=REMOTE_COLOR,
            badge=str(count) if count < 100 else '99+',
            badge_font_size=Window.height * 0.03,
            badge_color=BADGE_COLOR,
            on_release=self.remote_queue_event,
        )
        self.overlay_layout.add_widget(self.btn_remote_queue)

    def remote_qr_event(self, obj):
        if not isinstance(obj.last_touch, MouseMotionEvent): return
        Logger.info('StartScreen: remote_qr_event().')
        if getattr(self, 'qr_popup', None) is not None and self.qr_popup.parent:
            return
        steps, title, hint = self.app.get_qr_invitation(self.app.remote_url)
        self.qr_popup = QRCodePopup(
            steps,
            on_dismiss=self._dismiss_qr_popup,
            title=title,
            hint=hint,
        )
        self.add_widget(self.qr_popup)

    def _dismiss_qr_popup(self):
        popup = getattr(self, 'qr_popup', None)
        if popup is not None and popup.parent:
            self.remove_widget(popup)
        self.qr_popup = None

    def remote_queue_event(self, obj):
        if not isinstance(obj.last_touch, MouseMotionEvent): return
        Logger.info('StartScreen: remote_queue_event().')
        self.app.transition_to(ScreenNames.REMOTE_GALLERY)

    def on_click(self, obj):
        if not isinstance(obj.last_touch, MouseMotionEvent): return
        Logger.info('StartScreen: on_click().')
        self.app.transition_to(ScreenNames.SELECT_FORMAT)

    def on_keyboard_action(self):
        Logger.info('StartScreen: on_keyboard_action().')
        self.app.transition_to(ScreenNames.SELECT_FORMAT)
        return True
