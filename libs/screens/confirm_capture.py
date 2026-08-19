"""Keeping or retaking the shot that was just taken."""

import threading
import cv2

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.logger import Logger
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout

from libs.kivywidgets import BlurredImage, ResizeLabel, make_icon_button
from libs.file_utils import FileUtils
from libs.screens.names import ScreenNames
from libs.screens.theme import BORDER_THINKNESS, CANCEL_COLOR, CONFIRM_AUTO_KEEP_SECONDS, CONFIRM_CAPTURE_HOME_TIMEOUT_SECONDS, CONFIRM_COLOR, CONFIRM_PROGRESS_COLOR, HOME_COLOR, ICON_CANCEL, ICON_CONFIRM, ICON_HOME, ICON_SHOT_TAKEN, ICON_SHOT_TO_TAKE, ICON_TTF
from libs.screens.base import HomeTimeoutMixin, ColorScreen


class ConfirmCaptureScreen(HomeTimeoutMixin, ColorScreen):
    HOME_TIMEOUT_SECONDS = CONFIRM_CAPTURE_HOME_TIMEOUT_SECONDS

    """
    +-----------------+
    |       1/3       |
    |                 |
    | NO          YES |
    +-----------------+

    One question only: keep this one, or take it again. Choosing a look for the
    photos is the review screen's job, where it is decided once for the whole
    collage instead of once per shot, with the result in front of the guest.
    """
    def __init__(self, app, **kwargs):
        Logger.info('ConfirmCaptureScreen: __init__().')
        super(ConfirmCaptureScreen, self).__init__(**kwargs)

        self.app = app
        self._current_shot = 0
        self._current_format = 1
        self._auto_keep_clock = None
        self._auto_keep_progress_clock = None
        self._auto_keep_started_at = 0.0
        self._init_home_timeout()

        self.layout = AnchorLayout(padding=BORDER_THINKNESS, anchor_x='center', anchor_y='top')
        self.overlay_layout = FloatLayout()
        self.layout.add_widget(self.overlay_layout)

        # Display capture
        self.preview = BlurredImage(
            blur=self.app.BLUR_IMAGES,
            fit_mode='contain',
            size_hint=(1, 1),
            pos_hint={'x': 0, 'y': 0},
        )
        self.overlay_layout.add_widget(self.preview)

        # Add counter
        self.counter_layout = BoxLayout(
            orientation='horizontal',
            spacing=Window.height * 0.022,
            size_hint=(0.25, 0.1),
            pos_hint={'x': 0.375, 'y':0.85},
        )
        self.icons = []
        for _ in range(0, self.app.get_shots_to_take(self._current_format)):
            icon = ResizeLabel(
                font_name=ICON_TTF,
                text=ICON_SHOT_TO_TAKE,
                wh_fraction=0.07,
            )
            self.counter_layout.add_widget(icon)
            self.icons.append(icon)
        self.overlay_layout.add_widget(self.counter_layout)

        # Home button - top left
        # No ring on this one: the walk-away timeout is only a safety net here,
        # and the countdown a guest has to read is the one on the confirm button.
        self.btn_home = make_icon_button(ICON_HOME,
                             size=0.14,
                             pos_hint={'x': 0.05, 'top': 0.95},
                             font=ICON_TTF,
                             font_size_fraction=0.07,
                             bgcolor=HOME_COLOR,
                             on_release=self.home_event
                             )
        self.overlay_layout.add_widget(self.btn_home)

        # Cancel button - bottom left (always at same position)
        btn_cancel = make_icon_button(ICON_CANCEL,
                             size=0.14,
                             pos_hint={'x': 0.05, 'y': 0.05},
                             font=ICON_TTF,
                             font_size_fraction=0.07,
                             bgcolor=CANCEL_COLOR,
                             on_release=self.no_event
                             )
        self.overlay_layout.add_widget(btn_cancel)

        # Confirm button - bottom right (always at same position). Its ring is
        # the auto-keep countdown, drawn only while that countdown runs.
        self.btn_confirm = make_icon_button(ICON_CONFIRM,
                             size=0.14,
                             pos_hint={'right': 0.95, 'y': 0.05},
                             font=ICON_TTF,
                             font_size_fraction=0.07,
                             bgcolor=CONFIRM_COLOR,
                             progress=True,
                             progress_color=CONFIRM_PROGRESS_COLOR,
                             progress_line_width_fraction=0.028,
                             on_release=self.keep_event,
                             )
        self.btn_confirm.show_progress = False
        self.overlay_layout.add_widget(self.btn_confirm)

        self.add_widget(self.layout)

    # --- keeping the shot without being asked ----------------------------

    def _start_auto_keep(self):
        """Keep the shot on its own unless the guest says otherwise.

        Retaking is the rare case, so it is the one that gets a button. The ring
        around the confirm button is what tells the guest this is about to
        happen, and any touch on the screen gives them the whole delay back.
        """
        self._stop_auto_keep()
        self._auto_keep_started_at = Clock.get_boottime()
        self.btn_confirm.progress = 1.0
        self.btn_confirm.show_progress = True
        self._auto_keep_clock = Clock.schedule_once(self._auto_keep_event, CONFIRM_AUTO_KEEP_SECONDS)
        self._auto_keep_progress_clock = Clock.schedule_interval(self._update_auto_keep_progress, 1 / 30.0)

    def _stop_auto_keep(self):
        if self._auto_keep_clock:
            Clock.unschedule(self._auto_keep_clock)
            self._auto_keep_clock = None
        if self._auto_keep_progress_clock:
            Clock.unschedule(self._auto_keep_progress_clock)
            self._auto_keep_progress_clock = None
        self.btn_confirm.progress = 1.0
        self.btn_confirm.show_progress = False

    def _update_auto_keep_progress(self, dt):
        elapsed = Clock.get_boottime() - self._auto_keep_started_at
        self.btn_confirm.progress = max(0, 1.0 - (elapsed / CONFIRM_AUTO_KEEP_SECONDS))

    def _auto_keep_event(self, dt):
        Logger.info('ConfirmCaptureScreen: keeping shot %s on its own.', self._current_shot)
        self.keep_event(None)

    def on_touch_down(self, touch):
        # Someone still looking at their photo is not someone who walked away.
        if self._auto_keep_clock and self.collide_point(*touch.pos):
            self._start_auto_keep()
        return super(ConfirmCaptureScreen, self).on_touch_down(touch)

    def on_entry(self, kwargs={}):
        Logger.info('ConfirmCaptureScreen: on_entry().')
        self._current_shot = kwargs.get('shot') if 'shot' in kwargs else 0
        self._current_format = kwargs.get('format') if 'format' in kwargs else 0
        self._stop_auto_keep()

        # Hide counter layout when only one photo is needed
        total_shots = self.app.get_shots_to_take(self._current_format)
        if total_shots == 1:
            if self.counter_layout.parent:
                self.overlay_layout.remove_widget(self.counter_layout)
        else:
            if not self.counter_layout.parent:
                self.overlay_layout.add_widget(self.counter_layout)
            for i in range(0, total_shots): self.icons[i].text = ICON_SHOT_TO_TAKE
            for i in range(0, self._current_shot + 1): self.icons[i].text = ICON_SHOT_TAKEN

        load_id = (self._current_shot, self._current_format)

        def load_image():
            shot = self._current_shot
            small_path = FileUtils.get_small_path(self.app.get_shot(shot))
            small_im = cv2.imread(small_path)

            def apply_on_main(dt):
                if (self._current_shot, self._current_format) != load_id:
                    return
                if small_im is not None:
                    self.preview.set_image(small_im)
                else:
                    self.preview.filepath = small_path
                    self.preview.reload()
                # Counted from the moment the guest can actually see the photo,
                # not from a screen that is still loading it.
                self._start_auto_keep()

            Clock.schedule_once(apply_on_main, 0)

        threading.Thread(target=load_image, daemon=True).start()
        self._start_home_timeout()

    def on_exit(self, kwargs={}):
        Logger.info('ConfirmCaptureScreen: on_exit().')
        self._stop_auto_keep()
        self._stop_home_timeout()

    def keep_event(self, obj):
        self._stop_auto_keep()
        self._stop_home_timeout()

        if self._current_shot == self.app.get_shots_to_take(self._current_format) - 1:
            self.app.transition_to(ScreenNames.PROCESSING, format=self._current_format)
        else:
            self.app.transition_to(ScreenNames.COUNTDOWN, shot=self._current_shot + 1, format=self._current_format)

    def no_event(self, obj):
        self._stop_auto_keep()
        self._stop_home_timeout()
        self.app.transition_to(ScreenNames.COUNTDOWN, shot=self._current_shot, format=self._current_format)

    def on_keyboard_action(self):
        self.keep_event(None)
        return True
