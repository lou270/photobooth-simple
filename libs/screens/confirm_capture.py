"""Keeping or retaking the shot that was just taken, and picking a filter."""

import threading
import cv2

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color
from kivy.graphics.texture import Texture
from kivy.input.providers.mouse import MouseMotionEvent
from kivy.logger import Logger
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image

from libs.kivywidgets import BlurredImage, FeedbackButtonBehavior, ResizeLabel, make_icon_button, hex_to_rgba
from libs.file_utils import FileUtils
from libs.imaging import DEFAULT_FILTER, FILTERS, apply_filter
from libs.screens.names import ScreenNames
from libs.screens.theme import BORDER_COLOR, BORDER_THINKNESS, CANCEL_COLOR, CONFIRM_CAPTURE_HOME_TIMEOUT_SECONDS, CONFIRM_COLOR, HOME_COLOR, HOME_PROGRESS_COLOR, ICON_CANCEL, ICON_CONFIRM, ICON_HOME, ICON_SHOT_TAKEN, ICON_SHOT_TO_TAKE, ICON_TTF
from libs.screens.base import HomeTimeoutMixin, ColorScreen


class ConfirmCaptureScreen(HomeTimeoutMixin, ColorScreen):
    HOME_TIMEOUT_SECONDS = CONFIRM_CAPTURE_HOME_TIMEOUT_SECONDS

    """
    +-----------------+
    |       1/3       |
    |                 |
    | NO          YES |
    +-----------------+
    """
    def __init__(self, app, **kwargs):
        Logger.info('ConfirmCaptureScreen: __init__().')
        super(ConfirmCaptureScreen, self).__init__(**kwargs)

        self.app = app
        self._current_shot = 0
        self._current_format = 1
        self._selected_filter = DEFAULT_FILTER  # Default filter
        self._original_image = None  # Store original image
        self._init_home_timeout()

        self.layout = AnchorLayout(padding=BORDER_THINKNESS, anchor_x='center', anchor_y='top')
        self.overlay_layout = FloatLayout()
        self.layout.add_widget(self.overlay_layout)

        # Display capture - always full size regardless of filters
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

        # Filter cards container at bottom (always created in absolute position)
        from kivy.uix.scrollview import ScrollView
        
        # Outer container to center the scroll view - in absolute position
        self.filter_outer = AnchorLayout(
            size_hint=(1, 0.20),
            pos_hint={'x': 0, 'y': 0},
            anchor_x='center',
            anchor_y='center',
            opacity=1 if self.app.FILTERS_ENABLED else 0,
        )
        
        self.filter_scroll = ScrollView(
            size_hint=(None, 1),
            do_scroll_x=True,
            do_scroll_y=False,
        )
        
        self.filter_container = BoxLayout(
            orientation='horizontal',
            spacing=Window.height * 0.017,
            padding=(Window.height * 0.022, Window.height * 0.011, Window.height * 0.022, Window.height * 0.011),
            size_hint=(None, 1),
        )
        self.filter_container.bind(minimum_width=self.filter_container.setter('width'))
        
        # Update scroll view width based on container width
        def update_scroll_width(instance, value):
            # Limit scroll view width to avoid overlapping with confirm/cancel buttons
            # Buttons are 14% of width each, positioned at edges with 5% margin
            # So we need to leave space for: 5% + 14% on each side = 38% total
            # Plus some padding: use 70% of window width maximum
            max_available_width = Window.width * 0.70
            max_width = min(max_available_width, value)
            self.filter_scroll.width = max_width
        
        self.filter_container.bind(minimum_width=update_scroll_width)
        
        self.filter_scroll.add_widget(self.filter_container)
        self.filter_outer.add_widget(self.filter_scroll)
        self.overlay_layout.add_widget(self.filter_outer)
        
        # Create filter cards (even if filters are disabled, to maintain consistent layout)
        self.filter_cards = []
        if self.app.FILTERS_ENABLED:
            for filter_def in FILTERS:
                card = self._create_filter_card(filter_def)
                self.filter_container.add_widget(card)
                self.filter_cards.append(card)

        # Home button - top left
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

        # Confirm button - bottom right (always at same position)
        btn_confirm = make_icon_button(ICON_CONFIRM,
                             size=0.14,
                             pos_hint={'right': 0.95, 'y': 0.05},
                             font=ICON_TTF,
                             font_size_fraction=0.07,
                             bgcolor=CONFIRM_COLOR,
                             on_release=self.keep_event,
                             )
        self.overlay_layout.add_widget(btn_confirm)

        self.add_widget(self.layout)

    def _create_filter_card(self, filter_def):
        """Create a card for a specific filter."""
        from kivy.graphics import RoundedRectangle
        
        class ClickableCard(FeedbackButtonBehavior, BoxLayout):
            pass
        
        card_size = Window.height * 0.18
        card = ClickableCard(
            orientation='vertical',
            size_hint=(None, None),
            size=(card_size, card_size),
            padding=Window.height * 0.009,
        )
        
        # Draw rounded card background
        with card.canvas.before:
            Color(*hex_to_rgba('#3d4f5c'))
            card_bg = RoundedRectangle(
                pos=card.pos,
                size=card.size,
                radius=[Window.height * 0.017,]
            )
            # Selection indicator (initially hidden)
            card.selection_color = Color(0, 0, 0, 0)
            card.selection_rect = RoundedRectangle(
                pos=card.pos,
                size=card.size,
                radius=[Window.height * 0.017,]
            )
        
        # Bind to update background when card size/pos changes
        def update_card_bg(instance, value):
            card_bg.pos = instance.pos
            card_bg.size = instance.size
            card.selection_rect.pos = instance.pos
            card.selection_rect.size = instance.size
        card.bind(pos=update_card_bg, size=update_card_bg)
        
        # Preview container for filter thumbnail
        preview_container = AnchorLayout(
            size_hint=(1, 1),
            anchor_x='center',
            anchor_y='center',
        )
        
        # Thumbnail image (will be generated on entry)
        card.thumbnail = Image(
            size_hint=(None, None),
            size=(card_size - Window.height * 0.011, card_size - Window.height * 0.011),
            fit_mode='contain',
        )
        
        preview_container.add_widget(card.thumbnail)
        card.add_widget(preview_container)
        
        # Store filter info
        card.filter_key = filter_def['key']
        card.bind(on_release=self.on_filter_selected)
        
        return card
    
    def _generate_thumbnail(self, img, filter_key, size=None):
        """Generate a thumbnail with the filter applied."""
        if size is None:
            thumb = int(Window.height * 0.12)
            size = (thumb, thumb)
        # Resize image for thumbnail
        h, w = img.shape[:2]
        aspect = w / h
        if aspect > 1:
            new_w = size[0]
            new_h = int(size[0] / aspect)
        else:
            new_h = size[1]
            new_w = int(size[1] * aspect)
        
        thumbnail = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        
        # Apply filter
        filtered = apply_filter(thumbnail, filter_key)
        
        return filtered
    
    def _update_filter_thumbnails(self):
        """Generate thumbnails for all filters based on current image."""
        if self._original_image is None:
            return

        thumbnails = []
        for card in self.filter_cards:
            thumbnails.append(self._generate_thumbnail(self._original_image, card.filter_key))

        self._set_filter_thumbnails(thumbnails)

    def _set_filter_thumbnails(self, thumbnails):
        for card, thumbnail in zip(self.filter_cards, thumbnails):
            # Convert to texture
            thumbnail_flipped = cv2.flip(thumbnail, 0)
            texture = Texture.create(size=(thumbnail.shape[1], thumbnail.shape[0]), colorfmt='bgr')
            texture.blit_buffer(thumbnail_flipped.flatten(), colorfmt='bgr', bufferfmt='ubyte')
            card.thumbnail.texture = texture
    
    def _update_selection_indicator(self):
        """Update visual indicator for selected filter."""
        for card in self.filter_cards:
            if card.filter_key == self._selected_filter:
                # Show selection with border color
                card.selection_color.rgba = BORDER_COLOR
            else:
                # Hide selection
                card.selection_color.rgba = (0, 0, 0, 0)
    
    def on_filter_selected(self, obj):
        """Handle filter selection."""
        if not isinstance(obj.last_touch, MouseMotionEvent): return
        Logger.info(f'ConfirmCaptureScreen: on_filter_selected({obj.filter_key}).')
        
        self._selected_filter = obj.filter_key
        self._update_selection_indicator()
        
        # Apply filter to preview
        if self._original_image is not None:
            filtered_image = apply_filter(self._original_image.copy(), self._selected_filter)

            # Update preview directly in memory to avoid temp files.
            self.preview.set_image(filtered_image)

    def on_entry(self, kwargs={}):
        Logger.info('ConfirmCaptureScreen: on_entry().')
        self._current_shot = kwargs.get('shot') if 'shot' in kwargs else 0
        self._current_format = kwargs.get('format') if 'format' in kwargs else 0
        self._selected_filter = DEFAULT_FILTER  # Reset to default filter
        self._original_image = None

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

        def load_images():
            shot, fmt = self._current_shot, self._current_format
            small_path = FileUtils.get_small_path(self.app.get_shot(shot))
            full_path = self.app.get_shot(shot)
            small_im = cv2.imread(small_path)
            full_im = cv2.imread(full_path) if self.app.FILTERS_ENABLED else None
            thumbnails = []
            if self.app.FILTERS_ENABLED and full_im is not None:
                thumbnails = [self._generate_thumbnail(full_im, card.filter_key) for card in self.filter_cards]

            def apply_on_main(dt):
                if (self._current_shot, self._current_format) != load_id:
                    return
                self._original_image = full_im
                if small_im is not None:
                    self.preview.set_image(small_im)
                else:
                    self.preview.filepath = small_path
                    self.preview.reload()
                if thumbnails:
                    self._set_filter_thumbnails(thumbnails)
                    self._update_selection_indicator()

            Clock.schedule_once(apply_on_main, 0)

        threading.Thread(target=load_images, daemon=True).start()
        self._start_home_timeout()

    def _save_selected_filter(self, shot, filter_key, original_image):
        filtered_image = apply_filter(original_image.copy(), filter_key)
        shot_path = self.app.get_shot(shot)
        FileUtils.write_image(shot_path, filtered_image)
        small_path = FileUtils.get_small_path(shot_path)
        small_filtered = cv2.resize(filtered_image, (0, 0), fx=0.3, fy=0.3)
        FileUtils.write_image(small_path, small_filtered)

    def on_exit(self, kwargs={}):
        Logger.info('ConfirmCaptureScreen: on_exit().')
        self._stop_home_timeout()

    def keep_event(self, obj):
        if obj is not None and not isinstance(obj.last_touch, MouseMotionEvent): return
        self._stop_home_timeout()
        
        # Apply selected filter off the UI thread; Processing waits before building the collage.
        if self.app.FILTERS_ENABLED and self._selected_filter != DEFAULT_FILTER and self._original_image is not None:
            self.app.start_photo_task(self._save_selected_filter, self._current_shot, self._selected_filter, self._original_image)
        
        if self._current_shot == self.app.get_shots_to_take(self._current_format) - 1:
            self.app.transition_to(ScreenNames.PROCESSING, format=self._current_format)
        else:
            self.app.transition_to(ScreenNames.COUNTDOWN, shot=self._current_shot + 1, format=self._current_format)

    def no_event(self, obj):
        if not isinstance(obj.last_touch, MouseMotionEvent): return
        self._stop_home_timeout()
        self.app.transition_to(ScreenNames.COUNTDOWN, shot=self._current_shot, format=self._current_format)

    def on_keyboard_action(self):
        self.keep_event(None)
        return True
