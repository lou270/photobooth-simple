"""Photos phones sent, waiting for someone at the booth to print them.

The queue is filled from outside this process, by guests standing anywhere at
the event, so this screen never holds a list for long: it rereads it on every
entry and refreshes while it is shown. Picking a photo hands it to the ordinary
print pipeline, which is why there is nothing here about collages or printers.
"""

import threading

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.logger import Logger
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView

from libs.i18n import t
from libs.kivywidgets import FeedbackButtonBehavior, ResizeLabel, hex_to_rgba, make_icon_button
from libs.screens.base import ColorScreen, HomeTimeoutMixin
from libs.screens.names import ScreenNames
from libs.screens.theme import (
    HOME_COLOR, HOME_PROGRESS_COLOR, ICON_HOME, ICON_TTF,
    REMOTE_GALLERY_HOME_TIMEOUT_SECONDS, SMALL_FONT, wh_bind,
)


class ClickableCard(FeedbackButtonBehavior, BoxLayout):
    """One waiting photo, the whole card being the touch target."""


class RemoteGalleryScreen(HomeTimeoutMixin, ColorScreen):
    """
    +-----------------------+
    | [home]  FROM PHONES   |
    |  [photo] [photo]      |
    |  [photo] [photo]      |
    +-----------------------+
    """

    HOME_TIMEOUT_SECONDS = REMOTE_GALLERY_HOME_TIMEOUT_SECONDS

    # A queue of hundreds is possible; a wall of hundreds of textures on a Pi is
    # not, and nobody scrolls that far to find their own face anyway.
    MAX_VISIBLE_PHOTOS = 24
    REFRESH_SECONDS = 5

    def __init__(self, app, **kwargs):
        Logger.info('RemoteGalleryScreen: __init__().')
        super(RemoteGalleryScreen, self).__init__(**kwargs)

        self.app = app
        self._init_home_timeout()
        self._refresh_clock = None
        # None, not an empty list: "nothing drawn yet" has to differ from "drawn,
        # and the queue was empty", or the empty state never gets shown.
        self._shown_entry_ids = None
        self.photo_cards = []

        self.overlay_layout = FloatLayout()

        title = ResizeLabel(
            text=t('remote_gallery.title'),
            size_hint=(0.7, 0.09),
            pos_hint={'center_x': 0.5, 'top': 0.99},
            wh_fraction=0.045,
            bold=True,
            halign='center',
            valign='middle',
        )
        self.overlay_layout.add_widget(title)

        self.empty_label = Label(
            text=t('remote_gallery.empty'),
            size_hint=(0.8, 0.4),
            pos_hint={'center_x': 0.5, 'center_y': 0.5},
            font_size=SMALL_FONT(),
            halign='center',
            valign='middle',
        )
        wh_bind(self.empty_label, 'font_size', SMALL_FONT)
        self.empty_label.bind(size=self.empty_label.setter('text_size'))

        scroll_view = ScrollView(
            size_hint=(0.98, 0.86),
            pos_hint={'center_x': 0.5, 'y': 0.01},
            do_scroll_x=False,
            do_scroll_y=True,
        )

        self.cards_grid = GridLayout(
            cols=3,
            spacing=Window.height * 0.02,
            padding=Window.height * 0.02,
            size_hint=(None, None),
        )
        self.cards_grid.bind(minimum_height=self.cards_grid.setter('height'))
        self.cards_grid.bind(minimum_width=self.cards_grid.setter('width'))

        grid_container = AnchorLayout(anchor_x='center', anchor_y='top')
        grid_container.add_widget(self.cards_grid)
        scroll_view.add_widget(grid_container)
        self.overlay_layout.add_widget(scroll_view)

        self.btn_home = make_icon_button(
            ICON_HOME,
            size=0.12,
            pos_hint={'x': 0.02, 'top': 0.99},
            font=ICON_TTF,
            font_size_fraction=0.06,
            bgcolor=HOME_COLOR,
            progress=True,
            progress_color=HOME_PROGRESS_COLOR,
            progress_line_width_fraction=0.028,
            on_release=self.home_event,
        )
        self.overlay_layout.add_widget(self.btn_home)

        self.add_widget(self.overlay_layout)
        Window.bind(on_resize=self._on_window_resize)

    # --- layout ----------------------------------------------------------

    def _card_size(self):
        """Card size and column count, from the window's shape only.

        Deliberately not from how many photos there are. Sizing the columns to
        the queue turned a single waiting photo into one column the width of the
        window, and a card taller than the screen: one guest's photo blown up
        like a poster, with the clock label pushed out of sight. The grid keeps
        the columns it would have had for a full queue and a lone card simply
        sits in the first of them, at the same size as its neighbours would be.
        """
        aspect = Window.width / max(1, Window.height)
        cols = 2 if aspect < 1.0 else (3 if aspect < 1.6 else 4)

        spacing = Window.height * 0.02
        padding = Window.height * 0.02
        available_width = Window.width * 0.96 - (2 * padding) - (cols - 1) * spacing
        width = max(Window.height * 0.12, available_width / cols)
        height = width * 1.2

        # The grid sits in a scroll view 86% of the screen tall; a card taller
        # than that can only be scrolled past, never seen whole.
        max_height = Window.height * 0.78
        if height > max_height:
            height = max_height
            width = height / 1.2
        return width, height, cols

    def _update_card_sizes(self, *args):
        if not self.photo_cards:
            return

        card_width, card_height, cols = self._card_size()
        # Empty columns would still take their spacing, pushing a short row off
        # centre, so the grid only declares the columns it fills.
        self.cards_grid.cols = max(1, min(cols, len(self.photo_cards)))
        self.cards_grid.spacing = Window.height * 0.02
        self.cards_grid.row_default_height = card_height
        self.cards_grid.row_force_default = True

        for card in self.photo_cards:
            card.size = (card_width, card_height)

    def _on_window_resize(self, instance, width, height):
        self._update_card_sizes()

    def _create_photo_card(self, entry, thumbnail_path, card_size):
        card_width, card_height = card_size
        card = ClickableCard(
            orientation='vertical',
            size_hint=(None, None),
            size=(card_width, card_height),
            padding=Window.height * 0.012,
            spacing=Window.height * 0.008,
        )

        with card.canvas.before:
            Color(*hex_to_rgba('#3d4f5c'))
            card_background = RoundedRectangle(pos=card.pos, size=card.size, radius=[Window.height * 0.018])

        def update_card_background(instance, value):
            card_background.pos = instance.pos
            card_background.size = instance.size
        card.bind(pos=update_card_background, size=update_card_background)

        card.add_widget(Image(
            source=thumbnail_path,
            size_hint=(1, 0.82),
            fit_mode='contain',
        ))

        card.add_widget(ResizeLabel(
            text=self._format_time(entry.get('received_at')),
            size_hint=(1, 0.18),
            wh_fraction=0.02,
            halign='center',
            valign='middle',
        ))

        card.entry_id = entry['id']
        card.bind(on_release=self.on_photo_selected)
        return card

    @staticmethod
    def _format_time(received_at):
        """The clock time a photo arrived, which is how a guest recognises it."""
        if not received_at or 'T' not in received_at:
            return ''
        return received_at.split('T', 1)[1][:5]

    # --- the queue -------------------------------------------------------

    def _refresh_photos(self, *args):
        """Reload the queue off the UI thread, then rebuild the grid on it."""
        def read_queue():
            entries = self.app.get_pending_remote_photos()[:self.MAX_VISIBLE_PHOTOS]
            thumbnails = [
                (entry, self.app.get_remote_photo_path(entry['id'], small=True))
                for entry in entries
            ]
            # A photo withdrawn from a phone between the two calls has an entry
            # and no file left; drawing it would show a broken card.
            thumbnails = [(entry, path) for entry, path in thumbnails if path]
            Clock.schedule_once(lambda dt: self._apply_photos(thumbnails), 0)

        threading.Thread(target=read_queue, name='photobooth-remote-queue', daemon=True).start()

    def _apply_photos(self, thumbnails):
        if self.app.get_current_screen_name() != ScreenNames.REMOTE_GALLERY:
            return

        entry_ids = [entry['id'] for entry, _path in thumbnails]
        if entry_ids == self._shown_entry_ids:
            return

        self._shown_entry_ids = entry_ids
        self.cards_grid.clear_widgets()
        self.photo_cards = []

        card_width, card_height, _cols = self._card_size()
        for entry, thumbnail_path in thumbnails:
            card = self._create_photo_card(entry, thumbnail_path, (card_width, card_height))
            self.cards_grid.add_widget(card)
            self.photo_cards.append(card)

        if self.photo_cards and self.empty_label.parent is not None:
            self.overlay_layout.remove_widget(self.empty_label)
        elif not self.photo_cards and self.empty_label.parent is None:
            self.overlay_layout.add_widget(self.empty_label)

        self._update_card_sizes()

    # --- screen lifecycle -------------------------------------------------

    def on_entry(self, kwargs={}):
        Logger.info('RemoteGalleryScreen: on_entry().')
        self._start_home_timeout()
        self.app.ringled.start_rainbow()
        # Forget what was drawn last time: the same photos may be gone, and the
        # comparison in _apply_photos would otherwise keep a stale grid.
        self._shown_entry_ids = None
        self._refresh_photos()
        self._refresh_clock = Clock.schedule_interval(self._refresh_photos, self.REFRESH_SECONDS)

    def on_exit(self, kwargs={}):
        Logger.info('RemoteGalleryScreen: on_exit().')
        self._stop_home_timeout()
        if self._refresh_clock is not None:
            Clock.unschedule(self._refresh_clock)
            self._refresh_clock = None
        self.app.ringled.clear()

    def on_photo_selected(self, obj):
        entry_id = obj.entry_id
        Logger.info('RemoteGalleryScreen: on_photo_selected(%s).', entry_id)
        self._stop_home_timeout()

        if not self.app.ensure_disk_space_or_maintenance():
            return

        format_idx = self.app.get_single_photo_format_index()
        self.app.start_photo_task(self.app.stage_remote_photo, entry_id)
        self.app.transition_to(ScreenNames.PROCESSING, format=format_idx)

    def on_keyboard_action(self):
        self.home_event(None)
        return True
