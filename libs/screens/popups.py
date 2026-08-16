"""Overlays shown on top of a screen: printing progress and the sharing QR code."""

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
from kivy.uix.label import Label
from kivy.core.image import Image as CoreImage

from libs.kivywidgets import ResizeLabel, make_icon_button, make_icon_text_button
from libs.screens.theme import CANCEL_COLOR, CONFIRM_COLOR, ICON_CANCEL, ICON_CONFIRM, ICON_ERROR_PRINTING, ICON_PRINT, ICON_SUCCESS, ICON_TTF, SMALL_FONT, wh_bind


class PrintStatusPopup(FloatLayout):
    """Non-blocking print overlay; the underlying confirm screen keeps all actions available after closing."""

    def __init__(self, app, format_idx, on_dismiss=None, **kwargs):
        super(PrintStatusPopup, self).__init__(**kwargs)
        self.app = app
        self.format_idx = format_idx
        self.on_dismiss = on_dismiss
        self._clock = None
        self._close_scheduled = False
        self._started_at = time.monotonic()
        self._print_started = False
        self._print_counted = False
        self._print_task_id = None
        self._printer_wait_started_at = None
        self._timeout = getattr(self.app, 'PRINTER_WAIT_TIMEOUT', 45)

        with self.canvas.before:
            Color(0, 0, 0, 0.8)
            self.bg_rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update_bg, size=self._update_bg)

        from kivy.graphics import RoundedRectangle

        self.card = BoxLayout(
            orientation='vertical',
            size_hint=(0.68, 0.55),
            pos_hint={'center_x': 0.5, 'center_y': 0.5},
            padding=Window.height * 0.03,
            spacing=Window.height * 0.018,
        )
        with self.card.canvas.before:
            Color(1, 1, 1, 1)
            self.card_rect = RoundedRectangle(pos=self.card.pos, size=self.card.size, radius=[Window.height * 0.022])
        self.card.bind(pos=self._update_card, size=self._update_card)

        self.icon = ResizeLabel(
            text=ICON_PRINT,
            font_name=ICON_TTF,
            size_hint=(1, 0.28),
            wh_fraction=0.14,
            color=(0, 0, 0, 1),
            halign='center',
            valign='middle',
        )
        self.card.add_widget(self.icon)

        self.title = ResizeLabel(
            text='PRINTING',
            size_hint=(1, 0.15),
            wh_fraction=0.05,
            bold=True,
            color=(0, 0, 0, 1),
            halign='center',
            valign='middle',
        )
        self.card.add_widget(self.title)

        self.message = Label(
            text='Saving photo before printing...',
            size_hint=(1, 0.28),
            font_size=SMALL_FONT(),
            color=(0, 0, 0, 1),
            halign='center',
            valign='middle',
        )
        wh_bind(self.message, 'font_size', SMALL_FONT)
        self.message.bind(size=self.message.setter('text_size'))
        self.card.add_widget(self.message)

        self.btn_close = make_icon_text_button(
            icon=ICON_CONFIRM,
            text='OK',
            size_hint=(0.24, 0.13),
            pos_hint={'center_x': 0.5},
            icon_font=ICON_TTF,
            icon_font_size_fraction=0.055,
            text_font_size_fraction=0.035,
            bgcolor=CONFIRM_COLOR,
            on_release=self._close,
        )
        self.btn_close.opacity = 0
        self.btn_close.disabled = True
        self.card.add_widget(self.btn_close)

        self.add_widget(self.card)
        self._clock = Clock.schedule_once(self._tick, 0.2)

    def on_touch_down(self, touch):
        if self.card.collide_point(*touch.pos):
            return super(PrintStatusPopup, self).on_touch_down(touch)
        return True

    def _update_bg(self, *args):
        self.bg_rect.pos = self.pos
        self.bg_rect.size = self.size

    def _update_card(self, instance, *args):
        self.card_rect.pos = instance.pos
        self.card_rect.size = instance.size

    def _set_done(self, title, message, error=False):
        self.title.text = title
        self.message.text = message
        self.icon.text = ICON_ERROR_PRINTING if error else ICON_SUCCESS
        self.btn_close.opacity = 1
        self.btn_close.disabled = False
        self._clock = None

    def _set_print_error(self, detail=None):
        message = 'Printing failed but the photo has been saved.'
        if detail:
            message = f'{message}\n{detail}'
        Logger.error('PrintStatusPopup: print failed: %s', detail or '-')
        self._set_done('PRINT FAILED', message, error=True)

    def _tick(self, obj):
        if self.app.has_pending_photo_tasks():
            self.message.text = 'Saving photo before printing...'
            self._clock = Clock.schedule_once(self._tick, 0.2)
            return

        pending_error = self.app.get_pending_photo_error()
        if pending_error:
            Logger.error('PrintStatusPopup: save before print failed.')
            Logger.error(pending_error)
            self._set_done('SAVE FAILED', 'The photo could not be saved, so printing was stopped.', error=True)
            return

        if time.monotonic() - self._started_at >= self._timeout:
            self._set_print_error('The print operation timed out.')
            return

        if not self._print_started:
            self.message.text = 'Sending photo to printer...'
            try:
                print_task_id = self.app.trigger_print(1, self.format_idx)
                if print_task_id is None:
                    raise RuntimeError('Printer did not return a task id')
                self._print_task_id = print_task_id
                self._print_started = True
                Logger.info('PrintStatusPopup: print started task=%s', self._print_task_id)
            except Exception as exc:
                self._set_print_error(str(exc))
                return

        if not self.app.has_printer():
            if self._printer_wait_started_at is None:
                self._printer_wait_started_at = time.monotonic()
                Logger.warning('PrintStatusPopup: printer unavailable, waiting for recovery')
            waited = time.monotonic() - self._printer_wait_started_at
            remaining = max(0, int(self._timeout - waited))
            self.message.text = f'Printer unavailable. Waiting for reconnection... {remaining}s'
            if waited >= self._timeout:
                self._set_print_error('The printer did not reconnect in time.')
                return
            self._clock = Clock.schedule_once(self._tick, 1)
            return

        if self._printer_wait_started_at is not None:
            Logger.info('PrintStatusPopup: printer recovered after %.2fs', time.monotonic() - self._printer_wait_started_at)
            self._printer_wait_started_at = None

        try:
            status = self.app.devices.get_print_status(self._print_task_id)
        except Exception as exc:
            self._set_print_error(str(exc))
            return

        Logger.info('PrintStatusPopup: print status task=%s status=%s', self._print_task_id, status)
        if status == 'done':
            if not self._print_counted:
                self.app.track_print_sent()
                self._print_counted = True
            self._set_done('PRINT SENT', 'The print job was sent to the printer.')
            Clock.schedule_once(lambda dt: self._close(None), 2)
        else:
            self.message.text = 'Printing...'
            self._clock = Clock.schedule_once(self._tick, 1)

    def _close(self, obj):
        if obj is not None and not isinstance(obj.last_touch, MouseMotionEvent): return
        if self._close_scheduled:
            return
        self._close_scheduled = True
        if self._clock:
            Clock.unschedule(self._clock)
            self._clock = None
        if self.on_dismiss:
            self.on_dismiss()

class QRCodePopup(FloatLayout):
    """Popup overlay to show QR code."""
    
    # Class-level cache for QR code texture (shared across all instances)
    _qr_texture_cache = None
    _qr_png_cache = None
    _qr_generating = False

    @classmethod
    def preload(cls):
        """Build the QR texture on the UI thread if async preload did not finish yet."""
        if cls._qr_texture_cache is not None:
            return

        if cls._qr_png_cache is not None:
            started_at = time.monotonic()
            cls._cache_texture_from_png(cls._qr_png_cache)
            Logger.info('QRCodePopup: QR texture cached in %.2fs', time.monotonic() - started_at)
            return

        cls.preload_async()

    @classmethod
    def preload_async(cls):
        """Generate QR PNG in a worker, then create the Kivy texture on the UI thread."""
        if cls._qr_texture_cache is not None or cls._qr_generating:
            return

        cls._qr_generating = True

        def generate_png():
            started_at = time.monotonic()
            try:
                png = cls._build_qr_png()
            except Exception as exc:
                cls._qr_generating = False
                Logger.error('QRCodePopup: QR async generation failed: %s', exc)
                return

            def cache_on_main(dt):
                cls._qr_png_cache = png
                cls._cache_texture_from_png(png)
                cls._qr_generating = False
                Logger.info('QRCodePopup: QR code generated and cached in %.2fs', time.monotonic() - started_at)

            Clock.schedule_once(cache_on_main, 0)

        threading.Thread(target=generate_png, name='photobooth-qr-preload', daemon=True).start()

    @classmethod
    def _build_qr_png(cls):
        import qrcode

        wifi_qr_data = "WIFI:T:nopass;S:PhotoBooth;P:;H:false;;"

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(wifi_qr_data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()

    @classmethod
    def _cache_texture_from_png(cls, png):
        buf = io.BytesIO(png)
        core_image = CoreImage(buf, ext='png')
        cls._qr_texture_cache = core_image.texture
    
    def __init__(self, on_dismiss=None, **kwargs):
        super(QRCodePopup, self).__init__(**kwargs)
        self.on_dismiss = on_dismiss
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
            text='SCAN ME',
            size_hint=(1, 0.1),
            wh_fraction=0.055,
            bold=True,
            color=(0, 0, 0, 1),
            halign='center',
            valign='middle',
        )
        self.card.add_widget(scan_label)

        # QR Code image fills remaining space
        self.qr_image = Image(
            size_hint=(1, 1),
            fit_mode='contain',
        )
        self.card.add_widget(self.qr_image)

        hint_label = ResizeLabel(
            text='Go to http://192.168.4.1',
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
        """Generate WiFi QR code with caching for better performance."""
        QRCodePopup.preload()
        if QRCodePopup._qr_texture_cache is not None:
            self.qr_image.texture = QRCodePopup._qr_texture_cache
            Logger.info('QRCodePopup: Using cached QR code')
    
    def _close(self, obj):
        if not isinstance(obj.last_touch, MouseMotionEvent): return
        if self._close_scheduled:
            return
        self._close_scheduled = True
        if self.on_dismiss:
            Clock.schedule_once(lambda dt: self.on_dismiss(), 0)
