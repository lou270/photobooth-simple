"""Live preview, countdown, and the capture itself."""

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.input.providers.mouse import MouseMotionEvent
from kivy.logger import Logger
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout

from libs.i18n import t
from libs.kivywidgets import KivyCamera, BackgroundBoxLayout, ResizeLabel, LabelRoundButton, RotatingLabel, CircularProgressCounter, make_icon_button
from libs.screens.names import ScreenNames
from libs.screens.theme import BORDER_COLOR, BORDER_THINKNESS, CANCEL_COLOR, CONFIRM_COLOR, COUNTDOWN_HOME_TIMEOUT_SECONDS, HOME_COLOR, HOME_PROGRESS_COLOR, ICON_CANCEL, ICON_HOME, ICON_LOADING, ICON_PROCESSING, ICON_TRIGGER, ICON_TTF, SHOT_AUTOSTART_SECONDS, SHOT_TIMEOUT_SECONDS
from libs.screens.base import HomeTimeoutMixin, ColorScreen


class CountdownScreen(HomeTimeoutMixin, ColorScreen):
    HOME_TIMEOUT_SECONDS = COUNTDOWN_HOME_TIMEOUT_SECONDS
    # The ring is the countdown timer while a shot is being taken, so it must
    # not also be showing the walk-away timeout.
    HOME_TIMEOUT_HIDES_RING = True

    """
    +-----------------+
    |                 |
    |        5        |
    |                 |
    +-----------------+
    """
    def __init__(self, app, **kwargs):
        Logger.info('CountdownScreen: __init__().')
        super(CountdownScreen, self).__init__(**kwargs)

        self.app = app
        self._current_shot = 0
        self._current_format = 0
        self._timer_active = False
        self._clock_autostart = None
        self._init_home_timeout()

        self.time_remaining = self.app.COUNTDOWN
        self.total_countdown = self.app.COUNTDOWN

        # Display camera preview
        self.layout = AnchorLayout(padding=BORDER_THINKNESS, anchor_x='center', anchor_y='center')
        
        self.camera = KivyCamera(
            app=self.app,
            fps=self.app.devices.get_preview_fps(),
            blur=self.app.BLUR_CAMERA,
            blur_refresh_frames=self.app.PREVIEW_BLUR_REFRESH_FRAMES,
            fit_mode='contain',
        )
        self.layout.add_widget(self.camera)
        
        # Create overlay layout for buttons (on top of camera)
        self.overlay_layout = FloatLayout()
        self.layout.add_widget(self.overlay_layout)

        # Display countdown with circular progress
        self.circular_counter = CircularProgressCounter(
            size_hint=(None, None),
            size=(min(Window.size) * 0.45, min(Window.size) * 0.45),
            pos_hint={'center_x': 0.5, 'center_y': 0.5},
            circle_size=min(Window.size) * 0.38,
            line_width=min(Window.size) * 0.01,
            progress_color=BORDER_COLOR
        )

        # Declare color background
        self.color_background = BackgroundBoxLayout(background_color=(1,1,1,1))

        # Display loading
        self.loading_layout = BoxLayout(orientation='vertical')
        icon = ResizeLabel(
            size_hint=(0.4, 0.4),
            pos_hint={'center_x': 0.5, 'center_y': 0.5},
            font_name=ICON_TTF,
            text=ICON_PROCESSING,
            wh_fraction=0.22,
        )
        self.loading_layout.add_widget(icon)

        loading = RotatingLabel(
            size_hint=(0.1, 0.1),
            pos_hint={'center_x': 0.5, 'y': 0.3},
            font_name=ICON_TTF,
            text=ICON_LOADING,
            wh_fraction=0.055,
        )
        self.loading_layout.add_widget(loading)

        # Home button (visible only when timer is not active) - top left
        self.btn_home = make_icon_button(ICON_HOME,
            size=0.14,
            pos_hint={'x': 0.05, 'top': 0.95},
            font=ICON_TTF,
            font_size_fraction=0.07,
            bgcolor=HOME_COLOR,
            progress=True,
            progress_color=HOME_PROGRESS_COLOR,
            progress_line_width_fraction=0.028,
            on_release=self.home_event
        )

        # Trigger/Cancel button - center bottom as round icon button
        self.btn_trigger = make_icon_button(ICON_TRIGGER,
            size=0.14,
            pos_hint={'center_x': 0.5, 'y': 0.05},
            font=ICON_TTF,
            font_size_fraction=0.07,
            bgcolor=CONFIRM_COLOR,
            on_release=self.trigger_event
        )

        self.add_widget(self.layout)

    def on_entry(self, kwargs={}):
        Logger.info('CountdownScreen: on_entry().')
        self.time_remaining = self.app.COUNTDOWN
        self.total_countdown = self.app.COUNTDOWN
        self._timer_active = False
        self._current_shot = kwargs.get('shot') if 'shot' in kwargs else 0
        self._current_format = kwargs.get('format') if 'format' in kwargs else 0
        aspect_ratio = self.app.get_format_aspect_ratio(self._current_format)
        self.camera.start(aspect_ratio)
        
        # Reset button icon and color (access child button from parent layout)
        for child in self.btn_trigger.children:
            if isinstance(child, LabelRoundButton):
                child.text = ICON_TRIGGER
                child.background_color = CONFIRM_COLOR
                break
        
        # Show home button and trigger button, hide circular counter
        if not self.btn_home.parent:
            self.overlay_layout.add_widget(self.btn_home)
        if not self.btn_trigger.parent:
            self.overlay_layout.add_widget(self.btn_trigger)
        if self.circular_counter.parent:
            self.overlay_layout.remove_widget(self.circular_counter)
        self._start_home_timeout()
        
        self._clock = None
        self._clock_progress = None
        self._clock_trigger = None
        self._clock_autostart = None

        # Only the first shot waits to be asked. From the second on, the guest
        # has already kept a photo and is standing in front of the camera: the
        # countdown starts itself, and the button under it turns into cancel.
        if self._current_shot > 0:
            self._clock_autostart = Clock.schedule_once(self._autostart_event, SHOT_AUTOSTART_SECONDS)

    def on_exit(self, kwargs={}):
        Logger.info('CountdownScreen: on_exit().')
        self.camera.opacity = 1
        if self._clock:
            Clock.unschedule(self._clock)
        if self._clock_progress:
            Clock.unschedule(self._clock_progress)
        if self._clock_trigger:
            Clock.unschedule(self._clock_trigger)
        self._cancel_autostart()
        self._stop_home_timeout()
        self.app.ringled.clear()
        if self.loading_layout.parent:
            self.overlay_layout.remove_widget(self.loading_layout)
        if self.btn_home.parent:
            self.overlay_layout.remove_widget(self.btn_home)
        if self.btn_trigger.parent:
            self.overlay_layout.remove_widget(self.btn_trigger)
        self.camera.stop()

    def timer_progress(self, dt):
        """Update progress bar smoothly every 0.05 seconds"""
        elapsed_time = Clock.get_boottime() - self.start_time
        remaining_progress = max(0, 1.0 - (elapsed_time / self.total_countdown))
        self.circular_counter.set_progress(remaining_progress)

    def timer_event(self, obj):
        Logger.info('CountdownScreen: timer_event(%s)', obj)
        
        # Check if timer is still active (not cancelled)
        if not self._timer_active:
            Logger.info('CountdownScreen: timer_event cancelled.')
            return
        
        self.time_remaining -= 1
        if self.time_remaining:
            self.circular_counter.set_text(str(self.time_remaining))
            self._clock = Clock.schedule_once(self.timer_event, 1)
        else:
            # Stop progressive update
            if self._clock_progress:
                Clock.unschedule(self._clock_progress)
                self._clock_progress = None
            self.circular_counter.set_progress(0)
            
            # Trigger shot
            try:
                # Make screen blink
                self.layout.add_widget(self.color_background)
                self.app.trigger_shot(self._current_shot, self._current_format)
                self._clock_trigger = Clock.schedule_once(self.timer_trigger, 1.2)
                Clock.schedule_once(self.timer_bg, 0.2)

                # Display loading
                self.overlay_layout.remove_widget(self.circular_counter)
                if self.btn_trigger.parent:
                    self.overlay_layout.remove_widget(self.btn_trigger)
                self.overlay_layout.add_widget(self.loading_layout)
            except:
                return self.app.transition_to(ScreenNames.ERROR, message=t('countdown.capture_start_failed'))

    def timer_bg(self, obj):
        self.camera.opacity = 0
        # Remove flash background
        self.layout.remove_widget(self.color_background)

    def timer_trigger(self, obj):
        if not(self.app.is_shot_completed(self._current_shot)):
            if self.app.has_process_timed_out('shot', SHOT_TIMEOUT_SECONDS):
                Logger.error('CountdownScreen: capture timed out after countdown.')
                if hasattr(self.app, 'recover_devices_and_return_home'):
                    self.app.recover_devices_and_return_home(reason='capture_timeout')
                else:
                    self.app.transition_to(ScreenNames.ERROR, message=t('countdown.capture_timeout'))
            else:
                # Retry after 1sec
                self._clock_trigger = Clock.schedule_once(self.timer_trigger, 1)
        elif self.app.has_process_failed('shot'):
            Logger.error('CountdownScreen: capture failed after countdown.')
            error_details = self.app.get_process_error('shot')
            if error_details:
                Logger.error(error_details)
            if hasattr(self.app, 'recover_devices_and_return_home'):
                self.app.recover_devices_and_return_home(reason='capture_failure')
            else:
                self.app.transition_to(ScreenNames.ERROR, message=t('countdown.capture_failed'))
        else:
            # Display photo for validation
            self.app.transition_to(ScreenNames.CONFIRM_CAPTURE, shot=self._current_shot, format=self._current_format)

    def _cancel_autostart(self):
        if self._clock_autostart:
            Clock.unschedule(self._clock_autostart)
            self._clock_autostart = None

    def _autostart_event(self, dt):
        Logger.info('CountdownScreen: autostart shot %s.', self._current_shot)
        self._clock_autostart = None
        if self._timer_active:
            return
        self.trigger_event(None)

    def trigger_event(self, obj):
        if obj is not None and not isinstance(obj.last_touch, MouseMotionEvent): return
        Logger.info('CountdownScreen: trigger_event().')
        # A guest quicker than the autostart must not have it cancel the
        # countdown they just started themselves.
        self._cancel_autostart()
        
        if not self._timer_active:
            # Start the countdown
            self._timer_active = True
            self.start_countdown()
        else:
            # Cancel the countdown
            self._timer_active = False
            self.cancel_countdown()

    def on_keyboard_action(self):
        self.trigger_event(None)
        return True

    def start_countdown(self):
        Logger.info('CountdownScreen: start_countdown().')
        self._stop_home_timeout()

        # Hide home button
        if self.btn_home.parent:
            self.overlay_layout.remove_widget(self.btn_home)
        
        # Show circular counter
        if not self.circular_counter.parent:
            self.overlay_layout.add_widget(self.circular_counter)
        
        # Update button icon and color (access child button from parent layout)
        for child in self.btn_trigger.children:
            if isinstance(child, LabelRoundButton):
                child.text = ICON_CANCEL
                child.background_color = CANCEL_COLOR
                break
        
        # Reset timer
        self.time_remaining = self.app.COUNTDOWN
        self.total_countdown = self.app.COUNTDOWN
        self.start_time = Clock.get_boottime()
        self.circular_counter.set_text(str(self.time_remaining))
        self.circular_counter.set_progress(1.0)
        
        # Start countdown
        self._clock = Clock.schedule_once(self.timer_event, 1)
        self._clock_progress = Clock.schedule_interval(self.timer_progress, 1/30.0)
        self.app.ringled.start_countdown(self.time_remaining)

    def cancel_countdown(self):
        Logger.info('CountdownScreen: cancel_countdown().')
        # Stop timers
        if self._clock:
            Clock.unschedule(self._clock)
            self._clock = None
        if self._clock_progress:
            Clock.unschedule(self._clock_progress)
            self._clock_progress = None
        
        # Hide circular counter
        if self.circular_counter.parent:
            self.overlay_layout.remove_widget(self.circular_counter)
        
        # Show home button again
        if not self.btn_home.parent:
            self.overlay_layout.add_widget(self.btn_home)
        self._start_home_timeout()
        
        # Update button icon and color (access child button from parent layout)
        for child in self.btn_trigger.children:
            if isinstance(child, LabelRoundButton):
                child.text = ICON_TRIGGER
                child.background_color = CONFIRM_COLOR
                break
        
        # Clear LED
        self.app.ringled.clear()
