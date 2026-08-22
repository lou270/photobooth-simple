"""Overlays shown on top of a screen: the sharing QR code, and the question
asked before something is thrown away."""

import io
import threading
import time

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.logger import Logger
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.core.image import Image as CoreImage

from libs.i18n import t
from libs.kivywidgets import make_icon_button, ResizeLabel, short_side
from libs.screens.theme import (
    CANCEL_COLOR, CONFIRM_COLOR, ICON_CANCEL, ICON_CONFIRM, ICON_DELETE, ICON_TTF,
    SMALL_FONT, wh_bind,
)


class QRCodePopup(FloatLayout):
    """Popup overlay to show QR code.

    What goes in the code is decided by the caller, not here: joining the WiFi
    and opening a page are different payloads, and which one a booth should hand
    out depends on whether it runs its own access point. Codes are cached per
    payload rather than one at a time, because a booth may offer several and
    building one costs a visible fraction of a second on a Pi.
    """

    # Class-level caches, shared across instances and keyed by payload.
    _qr_texture_cache = {}
    _qr_png_cache = {}
    _qr_generating = set()

    @classmethod
    def preload(cls, payload):
        """Build the QR texture on the UI thread if async preload did not finish yet."""
        if payload in cls._qr_texture_cache:
            return

        png = cls._qr_png_cache.get(payload)
        if png is not None:
            started_at = time.monotonic()
            cls._cache_texture_from_png(payload, png)
            Logger.info('QRCodePopup: QR texture cached in %.2fs', time.monotonic() - started_at)
            return

        cls.preload_async(payload)

    @classmethod
    def preload_async(cls, payload):
        """Generate QR PNG in a worker, then create the Kivy texture on the UI thread."""
        if not payload or payload in cls._qr_texture_cache or payload in cls._qr_generating:
            return

        cls._qr_generating.add(payload)

        def generate_png():
            started_at = time.monotonic()
            try:
                png = cls._build_qr_png(payload)
            except Exception as exc:
                cls._qr_generating.discard(payload)
                Logger.error('QRCodePopup: QR async generation failed: %s', exc)
                return

            def cache_on_main(dt):
                cls._qr_png_cache[payload] = png
                cls._cache_texture_from_png(payload, png)
                cls._qr_generating.discard(payload)
                Logger.info('QRCodePopup: QR code generated and cached in %.2fs', time.monotonic() - started_at)

            Clock.schedule_once(cache_on_main, 0)

        threading.Thread(target=generate_png, name='photobooth-qr-preload', daemon=True).start()

    @classmethod
    def _build_qr_png(cls, payload):
        import qrcode

        qr = qrcode.QRCode(
            # fit=True picks the version: a URL does not fit in version 1, which
            # a WiFi payload does, and pinning it would raise on the longer one.
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(payload)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()

    @classmethod
    def _cache_texture_from_png(cls, payload, png):
        buf = io.BytesIO(png)
        core_image = CoreImage(buf, ext='png')
        cls._qr_texture_cache[payload] = core_image.texture

    @classmethod
    def preload_steps(cls, steps):
        """Warm the cache for every code a popup is about to show."""
        for payload, _caption in steps:
            cls.preload_async(payload)

    def __init__(self, steps, on_dismiss=None, title=None, hint='',
                 auto_dismiss_seconds=0, **kwargs):
        """`steps` is [(payload, caption), ...], shown side by side in order.

        Two of them is the normal case on a booth with its own access point:
        joining the network and opening the page cannot be one code, and asking
        a guest to type an address in the dark is how a feature goes unused.

        `auto_dismiss_seconds` closes the popup on its own. Screens that time
        out on their own can leave it at zero; the welcome screen cannot, and
        an overlay that swallows every touch is a booth nobody else can use.
        """
        super(QRCodePopup, self).__init__(**kwargs)
        self.on_dismiss = on_dismiss
        self.steps = list(steps)
        if title is None:
            title = t('popups.qr.default_title')
        self._close_scheduled = False
        self._auto_dismiss_seconds = auto_dismiss_seconds
        self._auto_dismiss_clock = None
        
        # Semi-transparent overlay
        with self.canvas.before:
            Color(0, 0, 0, 0.8)
            self.bg_rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update_bg, size=self._update_bg)
        
        from kivy.graphics import RoundedRectangle

        # Card uses size_hint so it reflows automatically on Window resize, and
        # takes more of the width on a screen turned upright, where 60% of a
        # narrow side leaves the codes too small to scan comfortably.
        portrait = Window.height > Window.width
        self.card = BoxLayout(
            orientation='vertical',
            size_hint=(0.86 if portrait else 0.6, 0.85),
            pos_hint={'center_x': 0.5, 'center_y': 0.5},
            padding=short_side(0.03),
            spacing=short_side(0.015),
        )
        with self.card.canvas.before:
            Color(1, 1, 1, 1)
            self.card_rect = RoundedRectangle(pos=self.card.pos, size=self.card.size, radius=[short_side(0.022)])
        self.card.bind(pos=self._update_card, size=self._update_card)

        scan_label = ResizeLabel(
            text=title,
            size_hint=(1, 0.1),
            wh_fraction=0.055,
            bold=True,
            color=(0, 0, 0, 1),
            halign='center',
            valign='middle',
        )
        self.card.add_widget(scan_label)

        # The codes fill the remaining space, side by side and in order.
        self.qr_images = []
        # Side by side on a wide screen, stacked on a tall one: two codes in a
        # row of a portrait card end up small and swimming in empty space.
        codes_row = BoxLayout(
            orientation='vertical' if portrait else 'horizontal',
            size_hint=(1, 1),
            spacing=short_side(0.02),
        )
        for payload, caption in self.steps:
            column = BoxLayout(orientation='vertical')
            image = Image(size_hint=(1, 1), fit_mode='contain')
            column.add_widget(image)
            if caption:
                column.add_widget(ResizeLabel(
                    text=caption,
                    size_hint=(1, 0.16),
                    wh_fraction=0.022,
                    bold=True,
                    color=(0, 0, 0, 1),
                    halign='center',
                    valign='middle',
                ))
            codes_row.add_widget(column)
            self.qr_images.append((payload, image))
        self.card.add_widget(codes_row)

        hint_label = ResizeLabel(
            text=hint,
            size_hint=(1, 0.08),
            wh_fraction=0.022,
            bold=True,
            color=(0, 0, 0, 1),
            halign='center',
            valign='middle',
        )
        self.card.add_widget(hint_label)

        btn_close = make_icon_button(
            ICON_CANCEL,
            size=0.10,
            pos_hint={'center_x': 0.5, 'center_y': 0.5},
            font=ICON_TTF,
            font_size_fraction=0.055,
            bgcolor=CANCEL_COLOR,
            on_release=self._close
        )
        # Wrap in a fixed-height anchor so the button doesn't stretch
        btn_container = AnchorLayout(
            size_hint=(1, 0.15),
            anchor_x='center',
            anchor_y='center',
        )
        btn_container.add_widget(btn_close)
        self.card.add_widget(btn_container)

        self.add_widget(self.card)
        self._generate_qr_code()
        self._arm_auto_dismiss()

    # --- closing on its own ----------------------------------------------

    def _arm_auto_dismiss(self):
        """Start, or restart, the delay after which the codes close themselves.

        Restarted by every touch: two scans and a phone joining a network take
        longer than any fixed delay should assume, and a touch is what says
        someone is still standing in front of the codes.
        """
        if not self._auto_dismiss_seconds:
            return
        self._cancel_auto_dismiss()
        self._auto_dismiss_clock = Clock.schedule_once(
            self._auto_dismiss_event, self._auto_dismiss_seconds)

    def _cancel_auto_dismiss(self):
        if self._auto_dismiss_clock is not None:
            Clock.unschedule(self._auto_dismiss_clock)
            self._auto_dismiss_clock = None

    def _auto_dismiss_event(self, dt):
        self._auto_dismiss_clock = None
        # Taken off the screen by whoever owns it while the delay ran.
        if self.parent is None:
            return
        Logger.info('QRCodePopup: closing on its own after %ss.', self._auto_dismiss_seconds)
        self._close(None)

    def on_touch_down(self, touch):
        """Nothing under an overlay ever sees a touch, wherever it lands.

        Passing on what the card returned was not enough: a tap that landed on
        the card but on none of its widgets — a code, a caption, the space
        around them — was reported unhandled and went through to the screen
        behind, where the welcome screen reads any touch as "start a session".
        Closing the codes started a photo session.
        """
        self._arm_auto_dismiss()
        super(QRCodePopup, self).on_touch_down(touch)
        return True

    def on_touch_move(self, touch):
        super(QRCodePopup, self).on_touch_move(touch)
        return True

    def on_touch_up(self, touch):
        super(QRCodePopup, self).on_touch_up(touch)
        return True
    
    def _update_bg(self, *args):
        self.bg_rect.pos = self.pos
        self.bg_rect.size = self.size
    
    def _update_card(self, instance, *args):
        self.card_rect.pos = instance.pos
        self.card_rect.size = instance.size
    
    def _generate_qr_code(self):
        """Fill every code this popup shows, from the cache where possible."""
        for payload, image in self.qr_images:
            QRCodePopup.preload(payload)
            texture = QRCodePopup._qr_texture_cache.get(payload)
            if texture is not None:
                image.texture = texture
                Logger.info('QRCodePopup: Using cached QR code')
    
    def _close(self, obj):
        if self._close_scheduled:
            return
        self._close_scheduled = True
        self._cancel_auto_dismiss()
        if self.on_dismiss:
            Clock.schedule_once(lambda dt: self.on_dismiss(), 0)


class ConfirmPopup(FloatLayout):
    """The question asked before something is destroyed for good.

    Anyone can walk up to the booth, so an action that cannot be undone is never
    one tap away. The photo it is about to remove is shown inside the popup: on a
    wall of similar faces the thumbnail is what tells a guest whether the tap
    landed on their own photo or on the one next to it.
    """

    def __init__(self, title, message, on_confirm, on_dismiss=None,
                 image_source=None, icon=ICON_DELETE, **kwargs):
        super(ConfirmPopup, self).__init__(**kwargs)
        self.on_confirm = on_confirm
        self.on_dismiss = on_dismiss
        self._answered = False

        with self.canvas.before:
            Color(0, 0, 0, 0.8)
            self.bg_rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update_bg, size=self._update_bg)

        from kivy.graphics import RoundedRectangle

        self.card = BoxLayout(
            orientation='vertical',
            size_hint=(0.72, 0.62),
            pos_hint={'center_x': 0.5, 'center_y': 0.5},
            padding=short_side(0.03),
            spacing=short_side(0.018),
        )
        with self.card.canvas.before:
            Color(1, 1, 1, 1)
            self.card_rect = RoundedRectangle(pos=self.card.pos, size=self.card.size, radius=[short_side(0.022)])
        self.card.bind(pos=self._update_card, size=self._update_card)

        if image_source:
            self.card.add_widget(Image(
                source=image_source,
                size_hint=(1, 0.38),
                fit_mode='contain',
            ))
        else:
            self.card.add_widget(ResizeLabel(
                text=icon,
                font_name=ICON_TTF,
                size_hint=(1, 0.38),
                wh_fraction=0.14,
                color=(0, 0, 0, 1),
                halign='center',
                valign='middle',
            ))

        self.card.add_widget(ResizeLabel(
            text=title,
            size_hint=(1, 0.16),
            wh_fraction=0.05,
            bold=True,
            color=(0, 0, 0, 1),
            halign='center',
            valign='middle',
        ))

        message_label = Label(
            text=message,
            size_hint=(1, 0.24),
            font_size=SMALL_FONT(),
            color=(0, 0, 0, 1),
            halign='center',
            valign='middle',
        )
        wh_bind(message_label, 'font_size', SMALL_FONT)
        message_label.bind(size=message_label.setter('text_size'))
        self.card.add_widget(message_label)

        buttons = BoxLayout(
            orientation='horizontal',
            size_hint=(1, 0.22),
            spacing=short_side(0.02),
        )
        # Cancel sits first, under the thumb that is already moving away.
        buttons.add_widget(self._button_container(make_icon_button(
            ICON_CANCEL,
            size=0.11,
            pos_hint={'center_x': 0.5, 'center_y': 0.5},
            font=ICON_TTF,
            font_size_fraction=0.055,
            bgcolor=CANCEL_COLOR,
            on_release=self._cancel,
        )))
        buttons.add_widget(self._button_container(make_icon_button(
            ICON_CONFIRM,
            size=0.11,
            pos_hint={'center_x': 0.5, 'center_y': 0.5},
            font=ICON_TTF,
            font_size_fraction=0.055,
            bgcolor=CONFIRM_COLOR,
            on_release=self._confirm,
        )))
        self.card.add_widget(buttons)

        self.add_widget(self.card)

    @staticmethod
    def _button_container(button):
        container = AnchorLayout(anchor_x='center', anchor_y='center')
        container.add_widget(button)
        return container

    def on_touch_down(self, touch):
        """Swallow every touch, including one on the card that hits no widget.

        Reporting those as unhandled sent them on to the wall of photos behind,
        where the card under the question would have been picked for printing.
        """
        super(ConfirmPopup, self).on_touch_down(touch)
        return True

    def on_touch_move(self, touch):
        super(ConfirmPopup, self).on_touch_move(touch)
        return True

    def on_touch_up(self, touch):
        super(ConfirmPopup, self).on_touch_up(touch)
        return True

    def _update_bg(self, *args):
        self.bg_rect.pos = self.pos
        self.bg_rect.size = self.size

    def _update_card(self, instance, *args):
        self.card_rect.pos = instance.pos
        self.card_rect.size = instance.size

    def _answer(self, obj, confirmed):
        # Both buttons close the popup, so a double tap must not delete twice.
        if self._answered:
            return
        self._answered = True
        if confirmed and self.on_confirm:
            Clock.schedule_once(lambda dt: self.on_confirm(), 0)
        if self.on_dismiss:
            Clock.schedule_once(lambda dt: self.on_dismiss(), 0)

    def _cancel(self, obj):
        self._answer(obj, False)

    def _confirm(self, obj):
        self._answer(obj, True)
