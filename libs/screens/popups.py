"""The sharing QR code, shown on top of the screen that offers it."""

import io
import threading
import time

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.input.providers.mouse import MouseMotionEvent
from kivy.logger import Logger
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.core.image import Image as CoreImage

from libs.i18n import t
from libs.kivywidgets import ResizeLabel, make_icon_button
from libs.screens.theme import CANCEL_COLOR, ICON_CANCEL, ICON_TTF


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

    def __init__(self, steps, on_dismiss=None, title=None, hint='', **kwargs):
        """`steps` is [(payload, caption), ...], shown side by side in order.

        Two of them is the normal case on a booth with its own access point:
        joining the network and opening the page cannot be one code, and asking
        a guest to type an address in the dark is how a feature goes unused.
        """
        super(QRCodePopup, self).__init__(**kwargs)
        self.on_dismiss = on_dismiss
        self.steps = list(steps)
        if title is None:
            title = t('popups.qr.default_title')
        self._close_scheduled = False
        
        # Semi-transparent overlay
        with self.canvas.before:
            Color(0, 0, 0, 0.8)
            self.bg_rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update_bg, size=self._update_bg)
        
        from kivy.graphics import RoundedRectangle

        # Card uses size_hint so it reflows automatically on Window resize.
        # Portrait hint: 60% wide, 85% tall — FloatLayout centers it via pos_hint.
        self.card = BoxLayout(
            orientation='vertical',
            size_hint=(0.6, 0.85),
            pos_hint={'center_x': 0.5, 'center_y': 0.5},
            padding=Window.height * 0.03,
            spacing=Window.height * 0.015,
        )
        with self.card.canvas.before:
            Color(1, 1, 1, 1)
            self.card_rect = RoundedRectangle(pos=self.card.pos, size=self.card.size, radius=[Window.height * 0.022])
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
        codes_row = BoxLayout(
            orientation='horizontal',
            size_hint=(1, 1),
            spacing=Window.height * 0.02,
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
    
    def on_touch_down(self, touch):
        """Block all touch events from reaching widgets below the popup."""
        # Only allow touches on the card to be processed
        if self.card.collide_point(*touch.pos):
            return super(QRCodePopup, self).on_touch_down(touch)
        # Block all other touches
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
        if not isinstance(obj.last_touch, MouseMotionEvent): return
        if self._close_scheduled:
            return
        self._close_scheduled = True
        if self.on_dismiss:
            Clock.schedule_once(lambda dt: self.on_dismiss(), 0)
