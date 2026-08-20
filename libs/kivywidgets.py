from kivy.clock import Clock
from kivy.animation import Animation
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.graphics.texture import Texture
from kivy.properties import ColorProperty, StringProperty, ListProperty, NumericProperty, BooleanProperty
from kivy.metrics import dp, sp
from kivy.logger import Logger
from kivy.core.window import Window
import time
import weakref
import numpy as np
import cv2


from libs.file_utils import FileUtils


class _WindowSizeRegistry:
    """Widgets that resize themselves with the window, held weakly and pruned.

    Every one of these used to call Window.bind(size=...) for itself. Kivy holds
    the bound method weakly, so the widget is still collected — but the dead
    entry stays on Window's observer list for the life of the process, and
    nothing ever takes it off, a resize included. Screens that rebuild their
    widgets rather than relabel them (the queue of photos from phones rebuilds
    every card each time it changes, once every five seconds) therefore grew
    that list without bound over an evening.

    One binding on Window, one list here, and the dead are dropped both as the
    list is walked and, for a booth in kiosk mode that never resizes at all, on
    a counter as entries are added.
    """

    PRUNE_AFTER_ADDS = 64

    def __init__(self):
        self._entries = []
        self._adds_since_prune = 0

    def add(self, widget, apply):
        """Call apply(widget) on every window resize, while `widget` lives.

        `apply` takes the widget as its argument and must not close over it,
        or the weak reference here would be pointless.
        """
        self._entries.append((weakref.ref(widget), apply))
        self._adds_since_prune += 1
        if self._adds_since_prune >= self.PRUNE_AFTER_ADDS:
            self._adds_since_prune = 0
            self._entries = [entry for entry in self._entries if entry[0]() is not None]

    def dispatch(self, *args):
        survivors = []
        for reference, apply in self._entries:
            widget = reference()
            if widget is None:
                continue
            survivors.append((reference, apply))
            apply(widget)
        self._entries = survivors
        self._adds_since_prune = 0

    def __len__(self):
        return len(self._entries)


window_size_registry = _WindowSizeRegistry()
Window.bind(size=window_size_registry.dispatch)


def short_side(fraction=1.0):
    """Pixels, as a fraction of the window's shortest side.

    Every distance in the interface goes through here: paddings, spacings,
    corner radii, card sizes. Measuring them against Window.height instead is
    what made a booth on a screen turned upright look inflated — the tall side
    is the wrong ruler, and on a 1080x1920 panel it made every gap and every
    card almost twice the size it is on the same panel lying flat. The shortest
    side is the one that constrains what fits, in either orientation, which is
    why the font scale has always used it.
    """
    return min(Window.size) * fraction


def is_offscreen(widget):
    """True when the widget belongs to a screen the ScreenManager is not showing.

    Every screen is built once at startup and kept by the ScreenManager, so a
    widget animating itself from __init__ keeps running on screens nobody can
    see. Only the current screen is attached to the window, so a widget with no
    root window is not being drawn.
    """
    return widget.get_root_window() is None

# Widget to display camera
class KivyCamera(Image):
    # Preview cost is logged periodically: it is the one number worth watching
    # on the booth itself, and it cannot be measured from a workstation.
    STATS_INTERVAL_SECONDS = 10.0

    def __init__(self, app, fps=30, blur=False, blur_refresh_frames=1, **kwargs):
        super(KivyCamera, self).__init__(**kwargs)
        self._app = app
        self._fps = fps
        self._reuse_texture = None  # reused so a texture is not allocated per frame
        self._reset_stats()
        self._blur = blur
        self._blur_refresh_frames = max(1, int(blur_refresh_frames))
        self._blur_cache = None
        self._frame_count = 0
        self._stop = False
        self._last_frame_id = None
        self._last_frame_size = None
        self._bound_parent = None
        self.size_hint = (None, None)
        self.create_empty_texture()

    def on_parent(self, instance, parent):
        if self._bound_parent is not None:
            self._bound_parent.unbind(size=self._on_parent_resize)
        self._bound_parent = parent
        if parent is not None:
            parent.bind(size=self._on_parent_resize)
        self._sync_display_size()

    def _on_parent_resize(self, *args):
        self._sync_display_size()

    def _get_display_size(self, frame_width, frame_height):
        if frame_width <= 0 or frame_height <= 0:
            return (1, 1)

        parent = self.parent
        if parent is None or parent.width <= 1 or parent.height <= 1:
            return (frame_width, frame_height)

        scale = min(parent.width / frame_width, parent.height / frame_height)
        return (
            max(1, int(frame_width * scale)),
            max(1, int(frame_height * scale)),
        )

    def _get_parent_size(self):
        parent = self.parent
        if parent is None or parent.width <= 1 or parent.height <= 1:
            return None
        return (max(1, int(parent.width)), max(1, int(parent.height)))

    def _sync_display_size(self):
        if self._last_frame_size is None:
            return
        if self._blur:
            parent_size = self._get_parent_size()
            if parent_size is not None:
                self.size = parent_size
                return
        self.size = self._get_display_size(*self._last_frame_size)

    def start(self, aspect_ratio=None):
        self._stop = False
        self._aspect_ratio = aspect_ratio
        self._blur_cache = None
        self._frame_count = 0
        self._last_frame_id = None
        self._reset_stats()
        self._clock = Clock.schedule_once(self._update, 1.0 / self._fps)

    def _reset_stats(self):
        self._stats_frames = 0
        self._stats_time = 0.0
        self._stats_camera_time = 0.0
        self._stats_since = time.perf_counter()

    def _record_frame(self, duration, camera_duration):
        self._stats_frames += 1
        self._stats_time += duration
        self._stats_camera_time += camera_duration

        if time.perf_counter() - self._stats_since >= self.STATS_INTERVAL_SECONDS:
            self._flush_stats()

    def _flush_stats(self):
        """Report the preview cost, split between the camera and the display.

        The split is what makes the number actionable: a slow DSLR over USB and
        a slow blur pipeline look identical in a single figure.
        """
        elapsed = time.perf_counter() - self._stats_since
        if not self._stats_frames or elapsed <= 0:
            return

        texture_size = self._reuse_texture.size if self._reuse_texture is not None else (0, 0)
        camera_ms = 1000.0 * self._stats_camera_time / self._stats_frames
        total_ms = 1000.0 * self._stats_time / self._stats_frames
        Logger.info(
            'KivyCamera: preview %.1f fps, %.1f ms/frame (camera %.1f, display %.1f), '
            'texture %sx%s, blur=%s',
            self._stats_frames / elapsed,
            total_ms, camera_ms, total_ms - camera_ms,
            texture_size[0], texture_size[1], self._blur,
        )
        self._reset_stats()

    def stop(self):
        # Flush before resetting: a countdown is shorter than the reporting
        # interval, so without this a whole preview session goes unmeasured.
        self._flush_stats()
        self._stop = True
        Clock.unschedule(self._clock)
        self._blur_cache = None
        self._frame_count = 0
        self._reuse_texture = None
        self._last_frame_size = None

    def create_empty_texture(self):
        width, height = max(1, int(self.size[0])), max(1, int(self.size[1]))
        # Create a numpy array in 'bgr' format
        black_color = np.zeros((height, width, 3), dtype=np.uint8)

        # Create a texture
        texture = Texture.create(size=(width, height), colorfmt='bgr')
        texture.blit_buffer(black_color.tobytes(), colorfmt='bgr', bufferfmt='ubyte')
        texture.flip_vertical()

        self.texture = texture

    def _update(self, args):
        started_at = time.perf_counter()
        try:
            frame_id = self._app.devices.get_preview_frame_id()
            if frame_id == self._last_frame_id:
                return
            camera_started_at = time.perf_counter()
            im = self._app.devices.get_preview(self._aspect_ratio)
            camera_duration = time.perf_counter() - camera_started_at
            if im is None:
                return
            self._last_frame_id = frame_id
            frame_h, frame_w = im.shape[:2]
            self._last_frame_size = (frame_w, frame_h)
            display_size = self._get_display_size(frame_w, frame_h)

            # Generate blurry borders (réduire la résolution avant blur pour plus de fluidité)
            if self._blur:
                target_size = self._get_parent_size() or display_size
                if target_size[0] <= 1 or target_size[1] <= 1:
                    return
                max_w, max_h = 1280, 720
                if frame_w > max_w or frame_h > max_h:
                    scale = min(max_w / frame_w, max_h / frame_h)
                    im = cv2.resize(im, (int(frame_w * scale), int(frame_h * scale)), interpolation=cv2.INTER_LINEAR)
                refresh_blur = (self._frame_count % self._blur_refresh_frames) == 0
                im, self._blur_cache = FileUtils.blurry_borders(
                    im,
                    target_size,
                    blur_cache=self._blur_cache,
                    refresh_blur=refresh_blur,
                    return_cache=True,
                    # Live preview: speed over the last bit of downscale quality.
                    interpolation=cv2.INTER_LINEAR,
                )
                self._frame_count += 1
            elif im.shape[1] > display_size[0] or im.shape[0] > display_size[1]:
                # Never upload more pixels than the widget actually draws. A 1080p
                # frame is 6 MB copied by tobytes() and 6 MB pushed to the GPU on
                # every frame, and the GPU would only scale the surplus away. The
                # blur path already resizes to the widget, hence the elif.
                # INTER_LINEAR, not INTER_AREA: measured on this pipeline, AREA
                # costs more CPU than the upload it saves, LINEAR halves it.
                im = cv2.resize(im, display_size, interpolation=cv2.INTER_LINEAR)

            # Réutiliser la texture si la taille est identique (évite Texture.create à chaque frame)
            w, h = im.shape[1], im.shape[0]
            if self._reuse_texture is not None and self._reuse_texture.size == (w, h):
                self._reuse_texture.blit_buffer(im.tobytes(), colorfmt='bgr', bufferfmt='ubyte')
                # Forcer le rafraîchissement du canvas car la référence de texture n'a pas changé
                self.canvas.ask_update()
            else:
                self._reuse_texture = Texture.create(size=(w, h), colorfmt='bgr')
                self._reuse_texture.blit_buffer(im.tobytes(), colorfmt='bgr', bufferfmt='ubyte')
                self.texture = self._reuse_texture

            self._sync_display_size()
            self._record_frame(time.perf_counter() - started_at, camera_duration)

        except Exception as e:
            Logger.error('Cannot read camera stream.')
            Logger.error(e)
        finally:
            if not self._stop:
                self._clock = Clock.schedule_once(self._update, 1.0 / self._fps)

class BlurredImage(Image):
    filepath = StringProperty('')

    def __init__(self, blur=False, **kwargs):
        super(BlurredImage, self).__init__(**kwargs)
        self._blur = blur
        self._last_size = None
        if blur:
            self.bind(size=self.update_texture)
            self.create_empty_texture()

    def create_empty_texture(self):
        width, height = max(1, int(self.size[0])), max(1, int(self.size[1]))
        black_color = np.zeros((height, width, 3), dtype=np.uint8)
        texture = Texture.create(size=(width, height), colorfmt='bgr')
        texture.blit_buffer(black_color.tobytes(), colorfmt='bgr', bufferfmt='ubyte')
        texture.flip_vertical()
        self.texture = texture

    def update_texture(self, *args):
        # Only reload if size actually changed significantly (avoid micro-updates)
        if self.filepath and self._blur:
            current_size = (int(self.size[0]), int(self.size[1]))
            if self._last_size is None or \
               abs(current_size[0] - self._last_size[0]) > dp(10) or \
               abs(current_size[1] - self._last_size[1]) > dp(10):
                self._last_size = current_size
                self.reload()

    def set_image(self, im):
        """Met à jour l'affichage à partir d'un tableau numpy (BGR). Appel thread-safe via Clock.schedule_once."""
        if im is None: return
        try:
            im = cv2.flip(im, 0)
            if self._blur: im = FileUtils.blurry_borders(im, self.size)
            image_texture = Texture.create(size=(im.shape[1], im.shape[0]), colorfmt='bgr')
            image_texture.blit_buffer(im.tobytes(), colorfmt='bgr', bufferfmt='ubyte')
            self.texture = image_texture
        except Exception as e:
            Logger.error('BlurredImage.set_image: %s', e)

    def reload(self):
        try:
            im = cv2.imread(self.filepath)
            if im is None: return
            im = cv2.flip(im, 0)
            if self._blur: im = FileUtils.blurry_borders(im, self.size)
            image_texture = Texture.create(size=(im.shape[1], im.shape[0]), colorfmt='bgr')
            image_texture.blit_buffer(im.tobytes(), colorfmt='bgr', bufferfmt='ubyte')
            self.texture = image_texture
        except Exception as e:
            Logger.error(f'Cannot open image {self.filepath}.')
            Logger.error(e)
            super().reload()

Builder.load_string(
"""
<BackgroundBoxLayout@BoxLayout>:
    background_color: 0, 0, 0, 0

    canvas:
        Color:
            rgba: self.background_color
        Rectangle:
            pos: self.pos
            size: self.size
""")
class BackgroundBoxLayout(BoxLayout):
    background_color = ColorProperty()

class FeedbackButtonBehavior(ButtonBehavior):
    """Tiny press feedback: opacity only, no ripple/canvas work on weak hardware."""
    feedback_opacity = NumericProperty(0.72)

    def on_state(self, instance, value):
        Animation.cancel_all(self, 'opacity')
        Animation(opacity=self.feedback_opacity if value == 'down' else 1, d=0.06).start(self)

class LayoutButton(FeedbackButtonBehavior, FloatLayout):
    pass

class ResizeLabel(Label):
    max_font_size = NumericProperty(sp(16))
    # If set (0..1), max_font_size tracks min(Window.width, Window.height) * wh_fraction on every
    # resize — uses the shortest side so the font stays visible in both landscape and portrait.
    wh_fraction = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.wh_fraction:
            self.max_font_size = min(Window.size) * self.wh_fraction
            window_size_registry.add(self, lambda widget: widget._update_max_font())

    def _update_max_font(self, *args):
        if self.wh_fraction:
            self.max_font_size = min(Window.size) * self.wh_fraction
            self.on_size()

    def on_size(self, *args):
        if not self.text:
            return
        font_size = self.width / len(self.text) * 1.5
        self.font_size = min(self.size[1] if font_size > self.size[1] else font_size, self.max_font_size)

Builder.load_string("""
<SquareFloatLayout>:
    size_hint: None, None
    background_color: 0, 0, 0, 0
    show_progress: False
    progress: 1
    progress_color: 1, 1, 1, 1
    progress_line_width: 1

    canvas:
        Color:
            rgba: self.background_color
        Rectangle:
            pos: self.pos
            size: self.size
    canvas.after:
        Color:
            rgba: self.progress_color if self.show_progress else (0, 0, 0, 0)
        Line:
            circle: (self.center_x, self.center_y, min(self.size) * 0.5 + self.progress_line_width / 2, 0, 360 * self.progress)
            width: self.progress_line_width
            cap: 'round'
""")
class SquareFloatLayout(FloatLayout):
    size_square = NumericProperty(100)
    background_color = ColorProperty()
    use_parent_size = BooleanProperty(False)
    show_progress = BooleanProperty(False)
    progress = NumericProperty(1)
    progress_color = ColorProperty([1, 1, 1, 1])
    progress_line_width = NumericProperty(1)
    progress_line_width_fraction = NumericProperty(0)
    
    def __init__(self, use_parent_size=False, **kwargs):
        self.use_parent_size = use_parent_size
        super(SquareFloatLayout, self).__init__(**kwargs)
        if not use_parent_size:
            self._update_size()
            window_size_registry.add(self, lambda widget: widget._on_window_resize(None, None))
        else:
            self.bind(parent=self._on_parent_change)
    
    def _on_window_resize(self, instance, value):
        if not self.use_parent_size:
            self._update_size()
    
    def _on_parent_change(self, instance, parent):
        if parent and self.use_parent_size:
            parent.bind(size=self._update_size_from_parent)
            self._update_size_from_parent()
    
    def _update_size(self, *args):
        # Use Window size for consistent button sizing across all screens
        window_min = min(Window.size)
        button_size = window_min * self.size_square
        self.size = (button_size, button_size)
        self._update_progress_line_width()
    
    def _update_size_from_parent(self, *args):
        # Use parent size for buttons in BoxLayouts
        if self.parent:
            parent_min = min(self.parent.size) if self.parent.size[0] > 0 and self.parent.size[1] > 0 else short_side(0.17)
            button_size = parent_min * self.size_square
            self.size = (button_size, button_size)
            self._update_progress_line_width()

    def _update_progress_line_width(self):
        if self.progress_line_width_fraction:
            self.progress_line_width = min(self.size) * self.progress_line_width_fraction

Builder.load_string("""
<LabelRoundButton>:
    background_color: 0, 0, 0, 0
    padding: (0.2, 0.2, 0.2, 0.2)
    canvas.before:
        Color:
            rgba: self.background_color
        Ellipse:
            size: self.size
            pos: self.pos
""")
class LabelRoundButton(FeedbackButtonBehavior, ResizeLabel):
    text = StringProperty('')
    font_name = StringProperty('Roboto')
    background_color = ListProperty([0, 0, 0, 0])
    max_font_size = NumericProperty(sp(16))

    def __init__(self, **kwargs):
        max_font_size = kwargs.pop('max_font_size', None)
        super(LabelRoundButton, self).__init__(**kwargs)
        # Only override max_font_size if no wh_fraction was set (wh_fraction takes priority)
        if max_font_size is not None and not self.wh_fraction:
            self.max_font_size = max_font_size

Builder.load_string("""
<BreezyBorderedLabel@Label>:
    color : 1,1,1,1
    border_color: (0,0,0,1)
    border_width: .1
    breeze_width: 0
    breeze_alpha: 0
    canvas.before:
        Color:
            rgba: self.border_color
        Line:
            width: self.border_width
            rectangle: (self.pos[0], self.pos[1], self.size[0], self.size[1])
        Color:
            rgba: self.border_color[0], self.border_color[1], self.border_color[2], self.breeze_alpha
        Line:
            width: self.border_width * 4
            rectangle: (self.pos[0] - self.breeze_width - self.border_width, self.pos[1] - self.breeze_width - self.border_width, self.size[0] + 2 * (self.breeze_width + self.border_width), self.size[1] + 2 * (self.breeze_width + self.border_width))
""")
class BreezyBorderedLabel(Label):
    border_color = ColorProperty([0, 0, 0, 1])
    border_width = NumericProperty(dp(0.1))
    breeze_width = NumericProperty(0)
    breeze_alpha = NumericProperty(0)
    
    def __init__(self, **kwargs):
        super(BreezyBorderedLabel, self).__init__(**kwargs)
        self._animation_event = None
        self.start_breeze()

    def on_size(self, *args):
        # Same guard ResizeLabel has: an empty caption is a division by zero,
        # and a missing translation key is one edit away from producing one.
        if not self.text:
            return
        self.font_size = self.width / len(self.text) * 1.5

    def start_breeze(self):
        if self._animation_event is None:
            self._animation_event = Clock.schedule_interval(self._update_breeze, 1/30.0)
    
    def stop_breeze(self):
        if self._animation_event is not None:
            Clock.unschedule(self._animation_event)
            self._animation_event = None
            self.breeze_width = 0
            self.breeze_alpha = 0
    
    def _update_breeze(self, dt):
        if is_offscreen(self):
            return

        max_width = dp(100)
        min_alpha = 0.4
        speed = dp(30)
        
        self.breeze_width += speed * dt
        
        if self.breeze_width >= max_width:
            self.breeze_width = 0
        
        progress = self.breeze_width / max_width
        self.breeze_alpha = min_alpha * (1 - progress)

Builder.load_string("""
<ShadowLabel>:
    canvas.before:
        Color:
            rgba: root.tint

        Rectangle:
            pos:
                int(self.center_x - self.texture_size[0] / 2.) + root.decal[0],\
                int(self.center_y - self.texture_size[1] / 2.) + root.decal[1]

            size: root.texture_size
            texture: root.texture

        Color:
            rgba: 1, 1, 1, 1
""")
class ShadowLabel(Label):
    decal = ListProperty([dp(7), -dp(7)])
    tint = ListProperty([.5, .5, 1, .5])

Builder.load_string('''
<RotatingLabel>:
    canvas.before:
        PushMatrix
        Rotate:
            angle: root.angle
            axis: 0, 0, 1
            origin: root.center
    canvas.after:
        PopMatrix
''')
class RotatingLabel(ResizeLabel):
    angle = NumericProperty()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.angle = 0
        Clock.schedule_interval(self.update, 1/30)

    def update(self, dt):
        if is_offscreen(self):
            return
        self.angle -= 4  # Was 2 at 60fps, now 4 at 30fps for same visual speed
        self.angle %= 360

def hex_to_rgba(hex_color):
    # Enlève le caractère '#' si présent
    hex_color = hex_color.lstrip('#')

    # Convertit les valeurs hexadécimales en décimales
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0

    # Retourne le tuple avec alpha à 1
    return (r, g, b, 1.0)

Builder.load_string('''
<CircularProgressCounter>:
    canvas.before:
        # Cercle de fond semi-transparent
        Color:
            rgba: 0, 0, 0, 0.5
        Ellipse:
            pos: self.center_x - (self.circle_size * root.circle_scale)/2, self.center_y - (self.circle_size * root.circle_scale)/2
            size: self.circle_size * root.circle_scale, self.circle_size * root.circle_scale
        
        # Arc de progression
        Color:
            rgba: root.progress_color
        Line:
            circle: (self.center_x, self.center_y, (self.circle_size * root.circle_scale)/2, 0, 360 * root.progress)
            width: root.line_width
            cap: 'round'
''')
class CircularProgressCounter(FloatLayout):
    progress = NumericProperty(0)  # 0 à 1
    progress_color = ColorProperty([1, 1, 1, 1])
    circle_size = NumericProperty(300)
    line_width = NumericProperty(8)
    # ponytail: min/max in window-height fractions, not dp — dp lies on Retina/high-DPI screens
    min_circle_size = NumericProperty(0)   # set dynamically in __init__
    max_circle_size = NumericProperty(0)   # set dynamically in __init__
    circle_scale = NumericProperty(0.88)
    size_ratio = NumericProperty(0.55)
    small_screen_ratio = NumericProperty(0.38)
    outer_padding = NumericProperty(0)     # set dynamically in __init__
    small_screen_padding = NumericProperty(0)  # set dynamically in __init__
    
    def __init__(self, **kwargs):
        super(CircularProgressCounter, self).__init__(**kwargs)
        # Use min(Window.size) fractions — stays correct in both landscape and portrait
        self.min_circle_size = min(Window.size) * 0.20
        self.max_circle_size = min(Window.size) * 0.40
        self.outer_padding = min(Window.size) * 0.06
        self.small_screen_padding = min(Window.size) * 0.035
        self.label = ShadowLabel(
            text='',
            halign='center',
            valign='middle',
            font_size=min(Window.size) * 0.13,
            size_hint=(1, 1),
            pos_hint={'center_x': 0.5, 'center_y': 0.5}
        )
        self.add_widget(self.label)
        self.bind(circle_size=self._update_label_size)
        window_size_registry.add(self, lambda widget: widget._on_window_resize())
        Clock.schedule_once(self._update_responsive_size, 0)

    def _on_window_resize(self, *args):
        self.min_circle_size = min(Window.size) * 0.20
        self.max_circle_size = min(Window.size) * 0.40
        self.outer_padding = min(Window.size) * 0.06
        self.small_screen_padding = min(Window.size) * 0.035
        self._update_responsive_size()

    # Below this the screen is genuinely small and the counter has to give room
    # back to the preview behind it. It is an absolute size on purpose: the old
    # test compared the short side to the tall one, which only ever asked
    # whether the booth was in portrait.
    SMALL_SCREEN_SIDE = 480

    def _update_responsive_size(self, *args):
        window_min = min(Window.size)
        is_small_screen = window_min < self.SMALL_SCREEN_SIDE
        size_ratio = self.small_screen_ratio if is_small_screen else self.size_ratio
        responsive_circle_size = min(self.max_circle_size, window_min * size_ratio)
        self.circle_size = max(self.min_circle_size, responsive_circle_size)
        padding = self.small_screen_padding if is_small_screen else self.outer_padding
        widget_size = self.circle_size + padding
        self.size = (widget_size, widget_size)

    def _update_label_size(self, *args):
        self.label.font_size = max(min(Window.size) * 0.13, min(min(Window.size) * 0.24, self.circle_size * 0.82))
    
    def set_text(self, text):
        self.label.text = str(text)
    
    def set_progress(self, value):
        """Set progress from 0 to 1"""
        self.progress = max(0, min(1, value))

Builder.load_string("""
<RoundedButton>:
    background_color: 1, 1, 1, 1
    canvas.before:
        Color:
            rgba: self.background_color
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [20,]
""")
class RoundedButton(FeedbackButtonBehavior, Label):
    background_color = ListProperty([1, 1, 1, 1])

def icon_button_label(button):
    """The label inside a round icon button, for callers that relabel one.

    make_icon_button() hands back the square wrapper, and the text lives on a
    child of it. Three screens were each digging it out with the same loop.
    """
    # Last in children is first added, which is the icon: a badge goes on after
    # it and would otherwise be the one handed back.
    for child in reversed(button.children):
        if isinstance(child, LabelRoundButton):
            return child
    return None


def make_icon_button(icon, size, pos_hint={}, font='Roboto', font_size=sp(10), font_size_fraction=0, bgcolor=(1,1,1,1), badge=None, badge_font_size=sp(10), badge_color=(1,0,0,1), on_release=None, progress=False, progress_color=(1,1,1,1), progress_line_width_fraction=0.045):
    # If size >= 1, use parent size (for buttons in BoxLayouts), otherwise use Window size
    use_parent = (size >= 1.0)
    parent = SquareFloatLayout(
        size_square=size,
        pos_hint=pos_hint,
        use_parent_size=use_parent,
        show_progress=progress,
        progress_color=progress_color,
        progress_line_width_fraction=progress_line_width_fraction,
    )
    ic = LabelRoundButton(
        font_name=font,
        text=icon,
        size_hint=(1, 1),
        pos_hint={'center_x': 0.5, 'center_y': 0.5},
        background_color=bgcolor,
        max_font_size=font_size,
        wh_fraction=font_size_fraction,
    )
    parent.add_widget(ic)
    if badge:
        bg = LabelRoundButton(
            text=badge,
            bold=True,
            size_hint=(0.4, 0.4),
            pos_hint={'right': 1, 'top': 1},
            background_color=badge_color,
            max_font_size=badge_font_size,
        )
        parent.add_widget(bg)
    ic.bind(on_release=on_release)
    return parent



Builder.load_string('''
<PaperFeedAnimation>:
    canvas.before:
        Color:
            rgba: (root.sheet_color[0], root.sheet_color[1], root.sheet_color[2], root.sheet_color[3] * root.sheet_alpha)
        RoundedRectangle:
            pos: (root.sheet_x, root.sheet_y - root.sheet_travel * root.progress)
            size: (root.sheet_width, root.sheet_height)
            radius: [max(1.0, root.sheet_height * 0.08),]
''')
class PaperFeedAnimation(FloatLayout):
    """A printer icon with a sheet sliding out from under it.

    It draws the icon itself rather than taking one from the caller, because the
    sheet has to be measured against the glyph: the icon is a font character
    drawn at its own size, which has nothing to do with the box the widget was
    given, and a sheet measured against the box came out several times too wide
    for the printer it was supposed to be leaving. Children are drawn after
    canvas.before, so the icon covers the sheet on its way out.

    Driven by the clock rather than an Animation, like every other moving widget
    here, so it can skip itself when its screen is not the one being shown.
    """

    progress = NumericProperty(0)
    sheet_alpha = NumericProperty(0)
    sheet_color = ColorProperty([1, 1, 1, 1])
    speed = NumericProperty(0.55)  # sheets per second

    # Geometry taken from the glyph, recomputed whenever it is redrawn.
    sheet_x = NumericProperty(0)
    sheet_y = NumericProperty(0)
    sheet_width = NumericProperty(0)
    sheet_height = NumericProperty(0)
    sheet_travel = NumericProperty(0)

    def __init__(self, icon_text='', icon_font='Roboto', icon_wh_fraction=0.16,
                 icon_color=(1, 1, 1, 1), **kwargs):
        super().__init__(**kwargs)
        self._clock = None
        self.icon = ResizeLabel(
            text=icon_text,
            font_name=icon_font,
            wh_fraction=icon_wh_fraction,
            color=icon_color,
            size_hint=(1, 1),
            pos_hint={'x': 0, 'y': 0},
            halign='center',
            valign='middle',
        )
        self.add_widget(self.icon)
        self.icon.bind(texture_size=self._sync_sheet, pos=self._sync_sheet, size=self._sync_sheet)
        self.bind(pos=self._sync_sheet, size=self._sync_sheet)

    def _sync_sheet(self, *args):
        """Cut the sheet to the size of the printer it comes out of."""
        glyph_width, glyph_height = self.icon.texture_size
        if glyph_width <= 1 or glyph_height <= 1:
            return
        self.sheet_width = glyph_width * 0.5
        self.sheet_height = glyph_height * 0.34
        self.sheet_x = self.icon.center_x - self.sheet_width / 2
        # Starts hidden behind the printer body and ends half out below it.
        self.sheet_y = self.icon.center_y - self.sheet_height
        self.sheet_travel = max(0.0, glyph_height * 0.5 - self.sheet_height * 0.5)

    def start(self):
        """Feed sheets until told otherwise. Idempotent: screens are reused."""
        if self._clock is None:
            self.progress = 0
            self._clock = Clock.schedule_interval(self.update, 1 / 30.0)

    def update(self, dt):
        if is_offscreen(self):
            return
        self.progress = (self.progress + dt * self.speed) % 1.0
        # Fades in as it appears and out as it leaves, so the loop does not jump.
        self.sheet_alpha = max(0.0, min(1.0, self.progress * 6, (1.0 - self.progress) * 4))

    def stop(self):
        """Park the sheet: the job is over, one way or another."""
        if self._clock:
            Clock.unschedule(self._clock)
            self._clock = None
        self.sheet_alpha = 0
