"""The finished collage, with print and share offered independently."""

import threading
import cv2

from kivy.clock import Clock
from kivy.input.providers.mouse import MouseMotionEvent
from kivy.logger import Logger
from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.floatlayout import FloatLayout

from libs.i18n import t
from libs.kivywidgets import BlurredImage, make_icon_button, make_icon_text_button
from libs.file_utils import FileUtils
from libs.screens.names import ScreenNames
from libs.screens.theme import BORDER_THINKNESS, CONFIRM_COLOR, HOME_COLOR, HOME_PROGRESS_COLOR, ICON_HOME, ICON_PRINT, ICON_SHARE, ICON_TTF, REVIEW_HOME_TIMEOUT_SECONDS, SHARE_COLOR
from libs.screens.base import HomeTimeoutMixin, ColorScreen
from libs.screens.popups import PrintStatusPopup, QRCodePopup


class ReviewScreen(HomeTimeoutMixin, ColorScreen):
    """Final action screen: saved collage preview with independent print/share/done actions."""

    HOME_TIMEOUT_SECONDS = REVIEW_HOME_TIMEOUT_SECONDS

    def __init__(self, app, **kwargs):
        Logger.info('ReviewScreen: __init__().')
        super(ReviewScreen, self).__init__(**kwargs)

        self.app = app
        self._current_format = 0
        self._init_home_timeout()
        self._print_state = None
        self.layout = AnchorLayout(padding=BORDER_THINKNESS, anchor_x='center', anchor_y='top')
        self.overlay_layout = FloatLayout()
        self.layout.add_widget(self.overlay_layout)

        self.preview = BlurredImage(
            blur=self.app.BLUR_COLLAGE,
            fit_mode='contain',
            size_hint=(1, 1),
            pos_hint={'x': 0, 'y': 0},
        )
        self.overlay_layout.add_widget(self.preview)

        self.btn_home = make_icon_button(
            ICON_HOME,
            size=0.14,
            pos_hint={'x': 0.05, 'top': 0.95},
            font=ICON_TTF,
            font_size_fraction=0.07,
            bgcolor=HOME_COLOR,
            progress=True,
            progress_color=HOME_PROGRESS_COLOR,
            progress_line_width_fraction=0.028,
            on_release=self.home_event,
        )
        self.overlay_layout.add_widget(self.btn_home)

        self.btn_print = make_icon_text_button(
            icon=ICON_PRINT,
            text=t('review.print'),
            size_hint=(0.16, 0.09),
            pos_hint={},
            icon_font=ICON_TTF,
            icon_font_size_fraction=0.07,
            text_font_size_fraction=0.035,
            bgcolor=CONFIRM_COLOR,
            on_release=self.print_event,
        )
        self.overlay_layout.add_widget(self.btn_print)

        self.btn_share = None
        if self.app.SHARE:
            self.btn_share = make_icon_text_button(
                icon=ICON_SHARE,
                text=t('review.share'),
                size_hint=(0.16, 0.09),
                pos_hint={},
                icon_font=ICON_TTF,
                icon_font_size_fraction=0.07,
                text_font_size_fraction=0.035,
                bgcolor=SHARE_COLOR,
                on_release=self.share_event,
            )
            self.overlay_layout.add_widget(self.btn_share)

        self.overlay_layout.bind(size=self._layout_action_buttons)
        Clock.schedule_once(self._layout_action_buttons, 0)
        self.add_widget(self.layout)

    def _action_buttons(self):
        buttons = []
        if self.btn_share is not None:
            buttons.append(self.btn_share)
        if self.btn_print.parent is not None:
            buttons.append(self.btn_print)
        return buttons

    def _sync_print_button(self):
        """Refresh the print button without blocking the UI thread.

        has_printer() is a CUPS round trip and can_start_print() reads the stats
        file. Both used to run straight from the clock, so entering this screen
        stalled on a printer that was slow to answer, right after a capture.
        The last known state is shown immediately and corrected when the probe
        comes back.
        """
        if self._print_state is not None:
            self._apply_print_state(*self._print_state)

        def probe():
            state = (self.app.has_printer(), self.app.can_start_print())
            Clock.schedule_once(lambda dt: self._apply_print_state(*state), 0)

        threading.Thread(target=probe, name='photobooth-printer-probe', daemon=True).start()

    def _apply_print_state(self, printer_available, print_available):
        self._print_state = (printer_available, print_available)

        if printer_available and self.btn_print.parent is None:
            self.overlay_layout.add_widget(self.btn_print)
        elif not printer_available and self.btn_print.parent is not None:
            self.overlay_layout.remove_widget(self.btn_print)

        self.btn_print.disabled = not print_available
        self.btn_print.opacity = 1.0 if print_available else 0.45
        self._layout_action_buttons()

    def _layout_action_buttons(self, *args):
        buttons = self._action_buttons()
        if not buttons:
            return
        bottom = max(dp(4), self.overlay_layout.height * 0.05)
        gap = max(dp(4), self.overlay_layout.height * 0.02)
        top = max(dp(4), self.overlay_layout.height * 0.05)
        max_h = max(dp(18), (self.overlay_layout.height - bottom - top - gap * (len(buttons) - 1)) / len(buttons))
        y = bottom
        for btn in buttons:
            if btn.height > max_h:
                btn.height = max_h
            btn.pos_hint = {}
            btn.x = max(0, min(self.overlay_layout.width * 0.95 - btn.width, self.overlay_layout.width - btn.width))
            btn.y = y
            y = btn.top + gap

    def on_entry(self, kwargs={}):
        Logger.info('ReviewScreen: on_entry().')
        self._current_format = kwargs.get('format') if 'format' in kwargs else 0
        self._start_home_timeout()
        self.app.ringled.start_rainbow()
        self._sync_print_button()
        self._load_preview_async(FileUtils.get_small_path(self.app.get_collage()))
        self.app.start_photo_task(self.app.save_collage)
        if self.app.SHARE:
            QRCodePopup.preload_steps(self.app.get_qr_invitation(self.app.gallery_url)[0])

    def _load_preview_async(self, path):
        def load_image():
            im = cv2.imread(path)

            def apply_on_main(dt):
                if im is not None:
                    self.preview.set_image(im)
                else:
                    Logger.warning('ReviewScreen: cannot load preview %s', path)

            Clock.schedule_once(apply_on_main, 0)

        threading.Thread(target=load_image, daemon=True).start()

    def on_exit(self, kwargs={}):
        Logger.info('ReviewScreen: on_exit().')
        self._stop_home_timeout()
        if hasattr(self, 'qr_popup') and self.qr_popup.parent:
            self.layout.remove_widget(self.qr_popup)
        if hasattr(self, 'print_popup') and self.print_popup.parent:
            self.layout.remove_widget(self.print_popup)
        self.app.ringled.clear()

    def _reset_timeout(self):
        self._start_home_timeout()

    def home_event(self, obj):
        if obj is not None and not isinstance(obj.last_touch, MouseMotionEvent): return
        Logger.info('ReviewScreen: home_event().')
        self._stop_home_timeout()
        self.app.transition_to(ScreenNames.SUCCESS)

    def print_event(self, obj):
        if obj is not None and not isinstance(obj.last_touch, MouseMotionEvent): return
        Logger.info('ReviewScreen: print_event().')
        self._reset_timeout()
        if hasattr(self, 'print_popup') and self.print_popup.parent:
            return
        self.print_popup = PrintStatusPopup(self.app, self._current_format, on_dismiss=self._dismiss_print_popup)
        self.layout.add_widget(self.print_popup)

    def share_event(self, obj):
        if obj is not None and not isinstance(obj.last_touch, MouseMotionEvent): return
        Logger.info('ReviewScreen: share_event().')
        self._reset_timeout()
        if hasattr(self, 'qr_popup') and self.qr_popup.parent:
            return
        steps, title, hint = self.app.get_qr_invitation(self.app.gallery_url)
        self.qr_popup = QRCodePopup(steps, on_dismiss=self._dismiss_qr_popup, title=title, hint=hint)
        self.layout.add_widget(self.qr_popup)

    def _dismiss_print_popup(self):
        if hasattr(self, 'print_popup') and self.print_popup.parent:
            self.layout.remove_widget(self.print_popup)
        self._sync_print_button()
        self._reset_timeout()

    def _dismiss_qr_popup(self):
        if hasattr(self, 'qr_popup') and self.qr_popup.parent:
            self.layout.remove_widget(self.qr_popup)
        self._reset_timeout()

    def on_keyboard_action(self):
        self.home_event(None)
        return True
