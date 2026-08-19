"""Choosing a print format before the first shot."""

import math

from kivy.core.window import Window
from kivy.graphics import Color
from kivy.logger import Logger
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.uix.label import Label

from libs.i18n import t
from libs.kivywidgets import FeedbackButtonBehavior, hex_to_rgba, make_icon_button, ResizeLabel, short_side
from libs.screens.names import ScreenNames
from libs.screens.theme import (
    BORDER_THINKNESS, HOME_COLOR, HOME_PROGRESS_COLOR, ICON_HOME, ICON_TTF,
    SELECT_FORMAT_HOME_TIMEOUT_SECONDS, SMALL_FONT, wh_bind,
)
from libs.screens.base import ColorScreen, HomeTimeoutMixin


class SelectFormatScreen(HomeTimeoutMixin, ColorScreen):
    """
    +-----------------+
    | [home]          |
    |  [card] [card]  |
    |  [card] [card]  |
    +-----------------+
    """

    HOME_TIMEOUT_SECONDS = SELECT_FORMAT_HOME_TIMEOUT_SECONDS

    # The band the home button lives in. Kept out of the cards' reach: a guest
    # who touched the booth by mistake used to have no way out of this screen,
    # and a way out that overlaps the first card is not one.
    HOME_BAR_FRACTION = 0.16

    # Minimum and maximum card dimensions as window fractions (evaluated at layout time)
    @property
    def MIN_CARD_WIDTH(self):  return Window.width * 0.10
    @property
    def MIN_CARD_HEIGHT(self): return Window.height * 0.20
    @property
    def MAX_CARD_WIDTH(self):  return Window.width * 0.40
    @property
    def MAX_CARD_HEIGHT(self): return Window.height * 0.92

    def __init__(self, app, **kwargs):
        Logger.info('SelectFormatScreen: __init__().')
        super(SelectFormatScreen, self).__init__(**kwargs)
        self.app = app
        self._init_home_timeout()

        # Format cards container (scrollable if needed)
        from kivy.uix.gridlayout import GridLayout
        from kivy.uix.scrollview import ScrollView
        
        scroll_view = ScrollView(
            size_hint=(1, 1 - self.HOME_BAR_FRACTION),
            pos_hint={'x': 0, 'y': 0},
            do_scroll_x=False,
            do_scroll_y=True,
        )
        
        # Grid for format cards (centered)
        self.cards_grid = GridLayout(
            cols=3,
            spacing=short_side(0.033),
            padding=short_side(0.022),
            size_hint=(None, None),
        )
        self.cards_grid.bind(minimum_height=self.cards_grid.setter('height'))
        self.cards_grid.bind(minimum_width=self.cards_grid.setter('width'))
        
        # Center the grid within the scroll view
        grid_container = AnchorLayout(
            anchor_x='center',
            anchor_y='center',
        )
        grid_container.add_widget(self.cards_grid)
        scroll_view.add_widget(grid_container)

        # Build format cards: all of them. The grid wraps and the scroll view
        # takes over past what fits, so a fourth template is reachable rather
        # than silently missing.
        self.format_cards = []
        for format_idx in range(len(self.app.print_formats)):
            card = self._create_format_card(format_idx)
            self.cards_grid.add_widget(card)
            self.format_cards.append(card)

        self.add_widget(scroll_view)

        self.btn_home = make_icon_button(
            ICON_HOME,
            size=0.12,
            pos_hint={'x': 0.03, 'top': 0.97},
            font=ICON_TTF,
            font_size_fraction=0.06,
            bgcolor=HOME_COLOR,
            progress=True,
            progress_color=HOME_PROGRESS_COLOR,
            progress_line_width_fraction=0.028,
            on_release=self.home_event,
        )
        self.add_widget(self.btn_home)

        # Bind to window resize events
        Window.bind(on_resize=self._on_window_resize)
        
        # Initial card size calculation
        self._update_card_sizes()

    def _calculate_card_size(self):
        """Calculate card size and column count that fills the screen optimally for any aspect ratio."""
        padding = short_side(0.022)
        spacing = short_side(0.033)
        border = 2 * BORDER_THINKNESS
        n_cards = len(self.format_cards)
        aspect = Window.width / Window.height  # <1 portrait, ~1 square, >1 landscape

        # Choose columns: 2 up to a squarish screen, 3 in landscape. Never one:
        # the cards are capped at 40% of the width, so a single column showed one
        # card floating in the middle of a screen turned upright with the rest
        # below the fold, where two columns show four at once.
        cols = 2 if aspect < 1.2 else 3
        cols = min(cols, n_cards)

        # Width from horizontal space
        n_spacings = max(cols - 1, 0)
        available_width = Window.width - (2 * padding) - (n_spacings * spacing) - border
        width_from_w = available_width / cols

        # Width derived from vertical space (aspect ratio 1:1.5), minus the band
        # the home button occupies and shared between rows: past three templates
        # the grid wraps, and cards sized for a single row would push the second
        # one out of sight.
        rows = math.ceil(n_cards / cols) if cols else 1
        vertical_space = Window.height * (1 - self.HOME_BAR_FRACTION) - (2 * padding) - border
        available_height = (vertical_space - spacing * (rows - 1)) / rows
        width_from_h = available_height / 1.5

        card_width = max(self.MIN_CARD_WIDTH, min(self.MAX_CARD_WIDTH, min(width_from_w, width_from_h)))
        card_height = max(self.MIN_CARD_HEIGHT, min(self.MAX_CARD_HEIGHT, card_width * 1.5))

        return (card_width, card_height, cols)

    def _update_card_sizes(self):
        """Update all card sizes based on current window size."""
        card_width, card_height, cols = self._calculate_card_size()

        self.cards_grid.cols = cols
        self.cards_grid.spacing = short_side(0.033)
        self.cards_grid.row_default_height = card_height
        self.cards_grid.row_force_default = True

        for card in self.format_cards:
            card.size = (card_width, card_height)
    
    def _on_window_resize(self, instance, width, height):
        """Handle window resize events."""
        self._update_card_sizes()

    def _create_format_card(self, format_idx):
        """Create a card for a specific format."""
        format_template = self.app.print_formats[format_idx]
        preview_path = format_template.get_preview()
        
        # Create clickable card combining ButtonBehavior and BoxLayout
        from kivy.graphics import RoundedRectangle
        
        class ClickableCard(FeedbackButtonBehavior, BoxLayout):
            pass
        
        # Initial size will be updated by _update_card_sizes
        card = ClickableCard(
            orientation='vertical',
            size_hint=(None, None),
            size=(self.MIN_CARD_WIDTH, self.MIN_CARD_HEIGHT),
            padding=short_side(0.022),
            spacing=short_side(0.011),
        )
        
        # Draw rounded card background using canvas
        with card.canvas.before:
            Color(*hex_to_rgba('#3d4f5c'))
            card_bg = RoundedRectangle(
                pos=card.pos,
                size=card.size,
                radius=[short_side(0.022),]
            )
        
        # Bind to update background when card size/pos changes
        def update_card_bg(instance, value):
            card_bg.pos = instance.pos
            card_bg.size = instance.size
        card.bind(pos=update_card_bg, size=update_card_bg)
        
        # Preview container with rounded corners and image
        preview_container = AnchorLayout(
            size_hint=(1, 0.75),
            anchor_x='center',
            anchor_y='center',
            padding=short_side(0.022),
        )
        
        # Draw rounded preview background
        with preview_container.canvas.before:
            Color(*hex_to_rgba('#4a5c6a'))
            preview_bg = RoundedRectangle(
                pos=preview_container.pos,
                size=preview_container.size,
                radius=[short_side(0.017),]
            )
        
        # Bind to update preview background
        def update_preview_bg(instance, value):
            preview_bg.pos = instance.pos
            preview_bg.size = instance.size
        preview_container.bind(pos=update_preview_bg, size=update_preview_bg)
        
        preview_image = Image(
            source=preview_path,
            size_hint=(None, None),
            fit_mode='contain',
        )
        
        # Update image size to fit within container
        def update_image_size(instance, *args):
            if preview_container.width <= short_side(0.044) or preview_container.height <= short_side(0.044):
                return
            max_width = preview_container.width - short_side(0.044)
            max_height = preview_container.height - short_side(0.044)
            preview_image.size = (max_width, max_height)
        
        preview_container.bind(size=update_image_size)
        preview_image.bind(texture=update_image_size)
        
        preview_container.add_widget(preview_image)
        card.add_widget(preview_container)
        
        # Format name
        name_label = Label(
            text=format_template.get_name(),
            size_hint=(1, 0.15),
            font_size=SMALL_FONT(),
            halign='center',
            valign='middle',
            bold=True,
        )
        wh_bind(name_label, 'font_size', SMALL_FONT)
        name_label.bind(size=name_label.setter('text_size'))
        card.add_widget(name_label)
        
        # Number of photos
        num_photos = format_template.get_photos_required()
        photo_count_key = 'select_format.photo_count_plural' if num_photos > 1 else 'select_format.photo_count_singular'
        photos_label = ResizeLabel(
            text=t(photo_count_key, count=num_photos),
            size_hint=(1, 0.1),
            wh_fraction=0.018,
            halign='center',
            valign='middle',
        )
        card.add_widget(photos_label)
        
        # Bind click event
        card.format_idx = format_idx
        card.bind(on_release=self.on_format_selected)
        
        return card
    
    def on_entry(self, kwargs={}):
        Logger.info('SelectFormatScreen: on_entry().')
        # OPTIMIZED: Previews are now cached in templates, no need to reload
        # Previously: reloaded all previews on every entry (slow)
        # Now: previews are generated once and cached in TemplateCollage
        self.app.ringled.start_rainbow()
        self._start_home_timeout()

    def on_exit(self, kwargs={}):
        Logger.info('SelectFormatScreen: on_exit().')
        self._stop_home_timeout()
        self.app.ringled.clear()

    def on_format_selected(self, obj):
        format_idx = obj.format_idx
        Logger.info(f'SelectFormatScreen: on_format_selected({format_idx}).')
        self._start_format(format_idx)

    def _start_format(self, format_idx):
        self._stop_home_timeout()
        self.app.transition_to(ScreenNames.COUNTDOWN, shot=0, format=format_idx)

    def on_keyboard_action(self):
        Logger.info('SelectFormatScreen: on_keyboard_action().')
        self._start_format(0)
        return True
