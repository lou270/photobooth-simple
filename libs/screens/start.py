"""The welcome screen a guest touches to begin."""

import threading

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.logger import Logger
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label

from libs.i18n import t
from libs.kivywidgets import (
    BreezyBorderedLabel, FeedbackButtonBehavior, LayoutButton, make_icon_button,
    ResizeLabel, short_side,
)
from libs.version import APP_VERSION
from libs.screens.names import ScreenNames
from libs.screens.theme import (
    BADGE_COLOR, darken_rgba, ICON_QRCODE, ICON_SHOT_TAKEN, ICON_TOUCH, ICON_TTF,
    QR_POPUP_TIMEOUT_SECONDS, REMOTE_COLOR, SHARE_COLOR, TINY_FONT, wh_bind,
)
from libs.screens.base import BackgroundScreen
from libs.screens.popups import QRCodePopup


class CornerTab(FeedbackButtonBehavior, FloatLayout):
    """A coloured tab in a bottom corner, naming the round button that sits on it.

    The welcome screen is a photograph, so a caption laid straight onto it is
    only as readable as whatever the operator put there. On the shipped
    background the two bottom corners measure 148 and 191 in luminance, where
    white text falls to a contrast of 1.8 and the button's own colour to 1.2 —
    unreadable at caption size. The tab brings its own ground instead, a
    darkened cousin of the button's colour, so the words hold on any photo.

    It answers touches itself, and does what the button on it does. Every other
    pixel of this screen starts a photo session, so a tab that let touches
    through would be a place a guest presses the words "send a photo" and gets
    the camera counting down at them.
    """

    def __init__(self, text, color, flush_right=False, **kwargs):
        super(CornerTab, self).__init__(size_hint=(None, None), **kwargs)
        self.flush_right = flush_right

        with self.canvas.before:
            self._color = Color(*color)
            self._plate = RoundedRectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._redraw, size=self._redraw)

        # A plain Label, not a ResizeLabel: this one has to wrap onto a second
        # line on a screen turned upright, and ResizeLabel sizes its font from
        # the character count of the whole string, newline included.
        self.caption = Label(
            text=text,
            bold=True,
            halign='center',
            valign='middle',
            size_hint=(None, None),
        )
        self.caption.bind(size=self.caption.setter('text_size'))
        self.add_widget(self.caption)

    def _redraw(self, *args):
        self._plate.pos = self.pos
        self._plate.size = self.size
        # A half-circle on the end facing into the screen, square against the
        # two screen edges: the tab reads as growing out of the corner rather
        # than floating near it.
        radius = self.height / 2.0
        if self.flush_right:
            self._plate.radius = [radius, 0, 0, radius]
        else:
            self._plate.radius = [0, radius, radius, 0]


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
            text=t('start.title'),
            border_color=(1,1,1,1),
            border_width=short_side(0.006),
            size_hint=(0.7, 0.2),
            padding=(short_side(0.033), short_side(0.033), short_side(0.033), short_side(0.033)),
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
            text=t('start.version', version=APP_VERSION),
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
        self.tab_remote_qr = None
        self.tab_remote_queue = None
        self.qr_popup = None
        self._queue_clock = None
        self._pending_count = 0

        if self.app.has_remote_capture():
            self.tab_remote_qr = CornerTab(
                t('start.send_photo'),
                darken_rgba(SHARE_COLOR, 0.25)[:3] + (0.92,),
                flush_right=True,
                on_release=self.remote_qr_event,
            )
            overlay_layout.add_widget(self.tab_remote_qr)

            # Added after the tab so it draws on top of it.
            self.btn_remote_qr = make_icon_button(
                ICON_QRCODE,
                size=0.13,
                font=ICON_TTF,
                font_size_fraction=0.06,
                bgcolor=SHARE_COLOR,
                on_release=self.remote_qr_event,
            )
            overlay_layout.add_widget(self.btn_remote_qr)

        overlay_layout.bind(on_release=self.on_click)
        self.overlay_layout = overlay_layout

        self.add_widget(overlay_layout)

        overlay_layout.bind(size=self._layout_corners)
        Window.bind(size=self._layout_corners)
        Clock.schedule_once(self._layout_corners, 0)

    # --- the two corners -------------------------------------------------

    def _layout_corners(self, *args):
        """Place each tab against its corner, with its button on the outer end.

        In pixels rather than pos_hint, and measured against the short side, for
        the reason the review screen's buttons are: a pos_hint y is a fraction
        of the height, so a square button pinned that way sits at a different
        distance from the edge depending on which way the panel is turned.
        """
        if not self.overlay_layout.width:
            return

        inset = short_side(0.028)
        gap = short_side(0.016)
        button = short_side(0.13)
        height = button + 2 * inset
        # Capped against the window as well as the short side: on a panel turned
        # upright two tabs sized off the short side alone would meet in the
        # middle, and run under the touch icon on the way.
        width = min(short_side(0.46), self.overlay_layout.width * 0.40)

        for tab, btn, flush_right in (
            (self.tab_remote_queue, self.btn_remote_queue, False),
            (self.tab_remote_qr, self.btn_remote_qr, True),
        ):
            if tab is None or tab.parent is None:
                continue

            tab.size = (width, height)
            tab.x = self.overlay_layout.width - width if flush_right else 0
            tab.y = 0

            if btn is not None and btn.parent is not None:
                btn.pos_hint = {}
                btn.x = tab.right - inset - button if flush_right else tab.x + inset
                btn.y = tab.y + inset

            caption_width = width - button - 2 * inset - gap
            tab.caption.size = (caption_width, height - 2 * inset)
            tab.caption.x = tab.x + inset if flush_right else tab.x + inset + button + gap
            tab.caption.y = tab.y + inset
            tab.caption.font_size = short_side(0.028)

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
        if self.tab_remote_queue is not None:
            self.overlay_layout.remove_widget(self.tab_remote_queue)
            self.tab_remote_queue = None

        if count <= 0:
            return

        # The tab comes and goes with the button: this corner only means
        # anything while something is waiting in it, which is also exactly when
        # the guest who sent a photo walks up looking for it.
        self.tab_remote_queue = CornerTab(
            t('start.photos_waiting'),
            darken_rgba(REMOTE_COLOR, 0.25)[:3] + (0.92,),
            on_release=self.remote_queue_event,
        )
        self.overlay_layout.add_widget(self.tab_remote_queue)

        # Rebuilt rather than relabelled: the badge is baked into the button by
        # make_icon_button, and there is at most one rebuild every five seconds.
        self.btn_remote_queue = make_icon_button(
            ICON_SHOT_TAKEN,
            size=0.13,
            font=ICON_TTF,
            font_size_fraction=0.06,
            bgcolor=REMOTE_COLOR,
            badge=str(count) if count < 100 else '99+',
            badge_font_size=short_side(0.03),
            badge_color=BADGE_COLOR,
            on_release=self.remote_queue_event,
        )
        self.overlay_layout.add_widget(self.btn_remote_queue)
        self._layout_corners()

    def remote_qr_event(self, obj):
        Logger.info('StartScreen: remote_qr_event().')
        if getattr(self, 'qr_popup', None) is not None and self.qr_popup.parent:
            return
        steps, title, hint = self.app.get_qr_invitation(self.app.remote_url)
        # This screen has no walk-away timeout of its own — it is where the
        # booth waits — so the codes carry theirs, or a guest who left them
        # open leaves the next one tapping an overlay that answers nothing.
        self.qr_popup = QRCodePopup(
            steps,
            on_dismiss=self._dismiss_qr_popup,
            title=title,
            hint=hint,
            auto_dismiss_seconds=QR_POPUP_TIMEOUT_SECONDS,
        )
        self.add_widget(self.qr_popup)

    def _dismiss_qr_popup(self):
        popup = getattr(self, 'qr_popup', None)
        if popup is not None and popup.parent:
            self.remove_widget(popup)
        self.qr_popup = None

    def remote_queue_event(self, obj):
        Logger.info('StartScreen: remote_queue_event().')
        self.app.transition_to(ScreenNames.REMOTE_GALLERY)

    def on_click(self, obj):
        Logger.info('StartScreen: on_click().')
        self.app.start_session()

    def on_keyboard_action(self):
        Logger.info('StartScreen: on_keyboard_action().')
        self.app.start_session()
        return True
