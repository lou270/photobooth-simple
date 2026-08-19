"""The row of filter thumbnails a guest picks from.

It sits on the review screen, once the collage is on display: choosing a look
for the whole strip beats choosing one per shot, both because there is only one
decision to make and because the guest can see what they are deciding on.
"""

import cv2

from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.graphics.texture import Texture
from kivy.logger import Logger
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.uix.scrollview import ScrollView

from libs.imaging import DEFAULT_FILTER, FILTERS, apply_filter
from libs.kivywidgets import FeedbackButtonBehavior, hex_to_rgba
from libs.screens.theme import BORDER_COLOR


class ClickableCard(FeedbackButtonBehavior, BoxLayout):
    """One filter, the whole card being the touch target."""


def build_thumbnails(image, size=None):
    """Every filter applied to a small copy of `image`, in FILTERS order.

    Off the UI thread, please: this is a handful of OpenCV passes, and one of
    the filters runs a bilateral blur.
    """
    if image is None:
        return []

    if size is None:
        side = int(Window.height * 0.12)
        size = (side, side)

    height, width = image.shape[:2]
    aspect = width / height
    if aspect > 1:
        new_w, new_h = size[0], int(size[0] / aspect)
    else:
        new_h, new_w = size[1], int(size[1] * aspect)

    thumbnail = cv2.resize(image, (max(1, new_w), max(1, new_h)), interpolation=cv2.INTER_AREA)
    return [apply_filter(thumbnail.copy(), filter_def['key']) for filter_def in FILTERS]


class FilterStrip(AnchorLayout):
    """
    +--------------------------------+
    |  [thumb] [thumb] [thumb] ...   |
    +--------------------------------+
    """

    def __init__(self, on_select, **kwargs):
        kwargs.setdefault('anchor_x', 'center')
        kwargs.setdefault('anchor_y', 'center')
        super(FilterStrip, self).__init__(**kwargs)

        self._on_select = on_select
        self._enabled = True
        self.selected = DEFAULT_FILTER
        self.max_width = Window.width * 0.7

        self.scroll = ScrollView(size_hint=(None, 1), do_scroll_x=True, do_scroll_y=False)
        self.container = BoxLayout(
            orientation='horizontal',
            spacing=Window.height * 0.017,
            padding=(Window.height * 0.022, Window.height * 0.011, Window.height * 0.022, Window.height * 0.011),
            size_hint=(None, 1),
        )
        self.container.bind(minimum_width=self.container.setter('width'))
        self.container.bind(minimum_width=self._fit_scroll)
        self.scroll.add_widget(self.container)
        self.add_widget(self.scroll)

        self.cards = []
        for filter_def in FILTERS:
            card = self._create_card(filter_def)
            self.container.add_widget(card)
            self.cards.append(card)

        self.set_selected(DEFAULT_FILTER)

    # --- layout -----------------------------------------------------------

    def set_max_width(self, width):
        """Keep the strip clear of whatever else the screen puts beside it."""
        self.max_width = max(Window.width * 0.2, width)
        self._fit_scroll(self.container, self.container.minimum_width)

    def _fit_scroll(self, instance, value):
        self.scroll.width = min(self.max_width, value)

    def _create_card(self, filter_def):
        card_size = Window.height * 0.18
        card = ClickableCard(
            orientation='vertical',
            size_hint=(None, None),
            size=(card_size, card_size),
            padding=Window.height * 0.009,
        )

        with card.canvas.before:
            Color(*hex_to_rgba('#3d4f5c'))
            card_bg = RoundedRectangle(pos=card.pos, size=card.size, radius=[Window.height * 0.017,])
            card.selection_color = Color(0, 0, 0, 0)
            card.selection_rect = RoundedRectangle(pos=card.pos, size=card.size, radius=[Window.height * 0.017,])

        def update_card_bg(instance, value):
            card_bg.pos = instance.pos
            card_bg.size = instance.size
            card.selection_rect.pos = instance.pos
            card.selection_rect.size = instance.size
        card.bind(pos=update_card_bg, size=update_card_bg)

        preview_container = AnchorLayout(size_hint=(1, 1), anchor_x='center', anchor_y='center')
        card.thumbnail = Image(
            size_hint=(None, None),
            size=(card_size - Window.height * 0.011, card_size - Window.height * 0.011),
            fit_mode='contain',
        )
        preview_container.add_widget(card.thumbnail)
        card.add_widget(preview_container)

        card.filter_key = filter_def['key']
        card.bind(on_release=self._card_released)
        return card

    # --- content ----------------------------------------------------------

    def set_thumbnails(self, thumbnails):
        """Attach the images built by build_thumbnails(), in the same order."""
        for card, thumbnail in zip(self.cards, thumbnails):
            flipped = cv2.flip(thumbnail, 0)
            texture = Texture.create(size=(thumbnail.shape[1], thumbnail.shape[0]), colorfmt='bgr')
            texture.blit_buffer(flipped.flatten(), colorfmt='bgr', bufferfmt='ubyte')
            card.thumbnail.texture = texture

    def set_selected(self, filter_key):
        self.selected = filter_key
        for card in self.cards:
            card.selection_color.rgba = BORDER_COLOR if card.filter_key == filter_key else (0, 0, 0, 0)

    def set_enabled(self, enabled):
        """Grey the strip out once the choice can no longer change anything."""
        self._enabled = bool(enabled)
        self.opacity = 1.0 if self._enabled else 0.35

    def _card_released(self, card):
        if not self._enabled:
            return
        Logger.info('FilterStrip: %s selected.', card.filter_key)
        self.set_selected(card.filter_key)
        if self._on_select:
            self._on_select(card.filter_key)
