"""The welcome screen a guest touches to begin."""

import math
import threading

import cv2
import numpy as np
from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.graphics.texture import Texture
from kivy.logger import Logger
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label

from libs import event
from libs.i18n import t
from libs.kivywidgets import (
    FeedbackButtonBehavior, LayoutButton, make_icon_button, short_side,
)
from libs.version import APP_VERSION
from libs.screens.names import ScreenNames
from libs.screens.theme import (
    BADGE_COLOR, darken_rgba, ICON_QRCODE, ICON_SHOT_TAKEN, ICON_TOUCH, ICON_TTF,
    REMOTE_COLOR, SHARE_COLOR, TIMINGS, TINY_FONT, wh_bind,
)
from libs.screens.base import BackgroundScreen
from libs.screens.popups import QRCodePopup
from libs.screens.slideshow import Slideshow


class CornerTab(FeedbackButtonBehavior, FloatLayout):
    """A coloured tab in a bottom corner, naming the round button that sits on it.

    The welcome screen is a photograph, so a caption laid straight onto it is
    only as readable as whatever the operator put there. On the shipped
    background the two bottom corners measure 148 and 191 in luminance, where
    white text falls to a contrast of 1.8 and the button's own colour to 1.2 —
    unreadable at caption size. The tab brings its own ground instead, a
    darkened cousin of the button's colour, so the words hold on any photo.

    It answers touches itself, and does what the button on it does. Every other
    pixel of this screen starts a photo session, so a tab that let touches
    through would be a place a guest presses the words "send a photo" and gets
    the camera counting down at them.
    """

    def __init__(self, text, color, flush_right=False, **kwargs):
        super(CornerTab, self).__init__(size_hint=(None, None), **kwargs)
        self.flush_right = flush_right

        with self.canvas.before:
            self._color = Color(*color)
            self._plate = RoundedRectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._redraw, size=self._redraw)

        # A plain Label, not a ResizeLabel: this one has to wrap onto a second
        # line on a screen turned upright, and ResizeLabel sizes its font from
        # the character count of the whole string, newline included.
        self.caption = Label(
            text=text,
            bold=True,
            halign='center',
            valign='middle',
            size_hint=(None, None),
        )
        self.caption.bind(size=self.caption.setter('text_size'))
        self.add_widget(self.caption)

    def _redraw(self, *args):
        self._plate.pos = self.pos
        self._plate.size = self.size
        # A half-circle on the end facing into the screen, square against the
        # two screen edges: the tab reads as growing out of the corner rather
        # than floating near it.
        radius = self.height / 2.0
        if self.flush_right:
            self._plate.radius = [radius, 0, 0, radius]
        else:
            self._plate.radius = [0, radius, radius, 0]


def break_lines(words, line_width, space_width, line_height, box_width, box_height,
                max_lines=4, max_scale=float('inf')):
    """Split words into lines, and say how large they can be drawn in a box.

    Widths and the line height are measured once at one reference size: text
    scales linearly, so the best size for a given split is whichever of the
    box's width and height runs out first. Each line count gets its most even
    split - the one whose longest line is shortest - and the count that draws
    the words largest wins. A new line has to earn its place, though, by a
    tenth: two lines only a hair larger than one read as a stray break. Past
    max_scale every count draws the same size, and the fewest lines win. Uneven
    lines count against a split too, so "de" is not left alone on a line of
    its own just to gain a few pixels.

    Returns (lines, scale), scale being relative to the measuring size.
    """
    count = len(words)
    if not count:
        return [], 0

    widths = [line_width(word) for word in words]

    def width_of(start, end):
        return sum(widths[start:end]) + space_width * (end - start - 1)

    best_lines, best_scale, best_score = None, 0, 0
    for lines in range(1, min(max_lines, count) + 1):
        # longest[k][i]: the shortest possible longest line, placing the first
        # i words on k lines; cut[k][i] where the last of those lines starts.
        longest = [[float('inf')] * (count + 1) for _ in range(lines + 1)]
        cut = [[0] * (count + 1) for _ in range(lines + 1)]
        longest[0][0] = 0
        for k in range(1, lines + 1):
            for i in range(k, count + 1):
                for j in range(k - 1, i):
                    candidate = max(longest[k - 1][j], width_of(j, i))
                    if candidate < longest[k][i]:
                        longest[k][i], cut[k][i] = candidate, j

        split, end = [], count
        for k in range(lines, 0, -1):
            start = cut[k][end]
            split.insert(0, ' '.join(words[start:end]))
            end = start

        split_widths = [line_width(line) for line in split]
        widest = max(split_widths)
        scale = min(box_width / widest, box_height / (lines * line_height), max_scale)
        evenness = min(split_widths) / widest
        score = scale * (1 - 0.3 * (1 - evenness))
        if best_lines is None or score > best_score * 1.1:
            best_lines, best_scale, best_score = split, scale, score

    return best_lines, best_scale


class WelcomeText(Label):
    """Words laid straight onto the event's photo, sized to fill their box.

    fit() breaks the text between words and picks the largest size at which
    every line fits, so "Photo Booth" and a whole sentence both fill the room
    they are given. The text carries a soft shadow rather than an outline or a
    frame: it has to hold on any photo the operator chooses, bright bokeh
    included, without looking like a caption on a video.
    """

    MEASURING_SIZE = 100
    # A hair under the exact fit: the measure and the render round apart.
    FIT_MARGIN = 0.97

    def __init__(self, source_text, max_lines=4, **kwargs):
        # split() rather than split(' '): runs of spaces, tabs and a stray
        # space at either end are all one gap between two words.
        words = source_text.split()
        super(WelcomeText, self).__init__(
            text=' '.join(words), halign='center', valign='middle', size_hint=(None, None), **kwargs)
        self.words = words
        self.max_lines = max_lines
        self._shadow_padding = 0
        with self.canvas.before:
            Color(1, 1, 1, 1)
            self._shadow = Rectangle(size=(0, 0))
        self.bind(texture=self._build_shadow, pos=self._place_shadow, size=self._place_shadow)

    def fit(self, box_width, box_height, max_font_size):
        """Set the lines and the size for a box; returns the size used."""
        if not self.words:
            self.text = ''
            self.size = (box_width, 0)
            return 0

        measure = CoreLabel(font_name=self.font_name, font_size=self.MEASURING_SIZE)

        def line_width(text):
            return measure.get_extents(text)[0]

        space_width = line_width('x x') - 2 * line_width('x')
        line_height = measure.get_extents('Hg')[1] * self.line_height
        lines, scale = break_lines(
            self.words, line_width, space_width, line_height,
            box_width, box_height, self.max_lines,
            max_scale=max_font_size / self.MEASURING_SIZE / self.FIT_MARGIN,
        )
        font_size = self.MEASURING_SIZE * scale * self.FIT_MARGIN

        self.text = '\n'.join(lines)
        self.font_size = font_size
        self.text_size = (box_width, None)
        self.texture_update()
        self.size = (box_width, self.texture_size[1])
        return font_size

    def _build_shadow(self, *args):
        """Blur the letters' own shapes into a dark halo, once per text.

        Built from the rendered texture, so it follows any font, and blurred on
        the CPU when the text changes rather than by a shader on every frame:
        the booth's Pi has better things to draw.
        """
        texture = self.texture
        self._shadow.size = (0, 0)
        if texture is None or not all(texture.size):
            return
        try:
            width, height = texture.size
            alpha = np.frombuffer(texture.pixels, dtype=np.uint8).reshape(height, width, 4)[:, :, 3]
        except Exception as exc:  # no pixels to read back, as under a mock GL
            Logger.debug('WelcomeText: no shadow: %s', exc)
            return

        padding = int(math.ceil(self.font_size * 0.2))
        alpha = cv2.copyMakeBorder(alpha, padding, padding, padding, padding, cv2.BORDER_CONSTANT, value=0)
        alpha = alpha.astype(np.float32)
        # A close, darker blur for the edges, and a wide faint one that lifts
        # the words off a busy photo.
        near = cv2.GaussianBlur(alpha, (0, 0), max(1.0, self.font_size * 0.025))
        wide = cv2.GaussianBlur(alpha, (0, 0), max(1.0, self.font_size * 0.07))
        shade = np.clip(near * 0.45 + wide * 0.55, 0, 255).astype(np.uint8)

        pixels = np.zeros((shade.shape[0], shade.shape[1], 4), dtype=np.uint8)
        pixels[:, :, 3] = shade
        shadow = Texture.create(size=(shade.shape[1], shade.shape[0]), colorfmt='rgba')
        shadow.blit_buffer(pixels.tobytes(), colorfmt='rgba', bufferfmt='ubyte')
        if texture.tex_coords[1] != 0:
            # Label textures come flipped: read back, the rows are upside down.
            shadow.flip_vertical()
        self._shadow.texture = shadow
        self._shadow_padding = padding
        self._place_shadow()

    def _place_shadow(self, *args):
        texture = self._shadow.texture
        if texture is None or self.texture is None:
            return
        width, height = self.texture.size
        padding = self._shadow_padding
        # Down a little, as a light from above would throw it.
        drop = self.font_size * 0.03
        self._shadow.size = (width + 2 * padding, height + 2 * padding)
        self._shadow.pos = (
            int(self.center_x - width / 2.0) - padding,
            int(self.center_y - height / 2.0) - padding - drop,
        )


class StartScreen(BackgroundScreen):
    """
    +-----------------+
    |                 |
    | Press to begin  |
    |                 |
    +-----------------+
    """
    def __init__(self, app, **kwargs):
        Logger.info('StartScreen: __init__().')
        # The event's own photo when the operator uploaded one from the admin.
        super(StartScreen, self).__init__(bg=str(event.welcome_background()), **kwargs)

        self.app = app

        overlay_layout = LayoutButton()

        title_font, subtitle_font = event.welcome_fonts(self.app.WELCOME_FONT)

        # Placed and sized in pixels by _layout_welcome, which knows how much
        # room the words have once the window has a size.
        self.start_label = WelcomeText(
            self.app.WELCOME_TITLE or t('start.title'),
            font_name=title_font,
        )
        overlay_layout.add_widget(self.start_label)

        # A rule and a line under the title, only when the operator wrote one.
        self.subtitle_label = None
        self._rule = None
        if self.app.WELCOME_SUBTITLE:
            with overlay_layout.canvas:
                Color(0, 0, 0, 0.12)
                self._rule_shadow = Rectangle()
                Color(1, 1, 1, 0.9)
                self._rule = Rectangle()
            self.subtitle_label = WelcomeText(
                self.app.WELCOME_SUBTITLE,
                max_lines=2,
                font_name=subtitle_font,
            )
            overlay_layout.add_widget(self.subtitle_label)

        # The touch icon, between the two corner tabs.
        self.touch_icon = Label(
            size_hint=(None, None),
            font_name=ICON_TTF,
            text=ICON_TOUCH,
        )
        overlay_layout.add_widget(self.touch_icon)
        self._touch_pulse = None

        # Version: useful to the operator powering the booth up, and to nobody
        # else. Shown at startup, then faded out before the first guest arrives.
        self._version_label = Label(
            text=t('start.version', version=APP_VERSION),
            font_size=TINY_FONT(),
            halign='left',
            valign='middle',
            size_hint=(0.1, 0.05),
            pos_hint={'x': 0.9, 'y': 0.95},
        )
        wh_bind(self._version_label, 'font_size', TINY_FONT)
        overlay_layout.add_widget(self._version_label)

        # Sending photos from a phone: the QR code is how a guest learns the
        # feature exists at all, and the queue button only appears once a phone
        # has actually sent something.
        self.btn_remote_qr = None
        self.btn_remote_queue = None
        self.tab_remote_qr = None
        self.tab_remote_queue = None
        self.qr_popup = None
        self._queue_clock = None
        self._pending_count = 0

        if self.app.has_remote_capture():
            self.tab_remote_qr = CornerTab(
                t('start.send_photo'),
                darken_rgba(SHARE_COLOR, 0.25)[:3] + (0.92,),
                flush_right=True,
                on_release=self.remote_qr_event,
            )
            overlay_layout.add_widget(self.tab_remote_qr)

            # Added after the tab so it draws on top of it.
            self.btn_remote_qr = make_icon_button(
                ICON_QRCODE,
                size=0.13,
                font=ICON_TTF,
                font_size_fraction=0.06,
                bgcolor=SHARE_COLOR,
                on_release=self.remote_qr_event,
            )
            overlay_layout.add_widget(self.btn_remote_qr)

        overlay_layout.bind(on_release=self.on_click)
        self.overlay_layout = overlay_layout

        self.add_widget(overlay_layout)

        # Added to the screen rather than to the layout, and only while it
        # runs: the queue button is rebuilt into the layout every few seconds,
        # and would otherwise land on top of the photos.
        self.slideshow = None
        self._slideshow_clock = None
        if self.app.SLIDESHOW:
            self.slideshow = Slideshow(self.app.SLIDESHOW_PHOTO_SECONDS, on_dismiss=self._stop_slideshow)

        overlay_layout.bind(size=self._layout_corners)
        Window.bind(size=self._layout_corners)
        Clock.schedule_once(self._layout_corners, 0)

        overlay_layout.bind(size=self._layout_welcome)
        Clock.schedule_once(self._layout_welcome, 0)

    # --- the words in the middle -------------------------------------------

    def _layout_welcome(self, *args):
        """Stack the title, the rule and the subtitle, centred above the tabs.

        The block is sized from the words it holds rather than from fixed
        boxes: a two-word title and a sentence on four lines both sit in the
        middle of the free space, with the subtitle right under the last line.
        """
        layout = self.overlay_layout
        width, height = layout.size
        if not width or not height:
            return

        side = min(width, height)
        # The tabs and the touch icon take the bottom of the screen; the
        # version label and some air, the top.
        bottom = side * 0.22
        top = height - side * 0.07
        room = top - bottom
        text_width = width * 0.84

        has_subtitle = self.subtitle_label is not None
        rule_gap = side * 0.035
        subtitle_room = side * 0.075 if has_subtitle else 0
        # Capped, so a long sentence settles on fewer, wider lines with air
        # around them rather than a wall of words from edge to edge.
        title_room = min(room - (subtitle_room + 2 * rule_gap if has_subtitle else 0), side * 0.5)

        title_size = self.start_label.fit(text_width, title_room, max_font_size=side * 0.24)
        block = self.start_label.height

        if has_subtitle:
            self.subtitle_label.fit(
                text_width, subtitle_room,
                max_font_size=min(side * 0.05, title_size * 0.45),
            )
            block += 2 * rule_gap + self.subtitle_label.height

        # A little above the middle of the free space: the eye's centre of a
        # screen sits higher than its geometric one.
        y = bottom + (room - block) / 2.0 + room * 0.03
        y = min(y, top - block)

        self.start_label.center_x = width / 2.0
        self.start_label.top = y + block
        if has_subtitle:
            self.subtitle_label.center_x = width / 2.0
            self.subtitle_label.y = y
            rule_width = min(side * 0.22, text_width)
            rule_thickness = max(1.0, side * 0.003)
            rule_y = y + self.subtitle_label.height + rule_gap - rule_thickness / 2.0
            self._rule.size = (rule_width, rule_thickness)
            self._rule.pos = (width / 2.0 - rule_width / 2.0, rule_y)
            self._rule_shadow.size = (rule_width, rule_thickness * 3)
            self._rule_shadow.pos = (width / 2.0 - rule_width / 2.0, rule_y - rule_thickness * 1.5)

        icon = side * 0.13
        self.touch_icon.size = (icon, icon)
        self.touch_icon.font_size = side * 0.11
        self.touch_icon.center_x = width / 2.0
        self.touch_icon.y = side * 0.05

    def _pulse_touch_icon(self):
        """A slow breath on the icon: the one thing moving says "touch me"."""
        self._stop_touch_pulse()
        self.touch_icon.opacity = 1
        pulse = (Animation(opacity=0.45, duration=1.2, t='in_out_sine')
                 + Animation(opacity=1, duration=1.2, t='in_out_sine'))
        pulse.repeat = True
        pulse.start(self.touch_icon)
        self._touch_pulse = pulse

    def _stop_touch_pulse(self):
        if self._touch_pulse is not None:
            self._touch_pulse.cancel(self.touch_icon)
            self._touch_pulse = None
        self.touch_icon.opacity = 1

    # --- the two corners -------------------------------------------------

    def _layout_corners(self, *args):
        """Place each tab against its corner, with its button on the outer end.

        In pixels rather than pos_hint, and measured against the short side, for
        the reason the review screen's buttons are: a pos_hint y is a fraction
        of the height, so a square button pinned that way sits at a different
        distance from the edge depending on which way the panel is turned.
        """
        if not self.overlay_layout.width:
            return

        inset = short_side(0.028)
        gap = short_side(0.016)
        button = short_side(0.13)
        height = button + 2 * inset
        # Capped against the window as well as the short side: on a panel turned
        # upright two tabs sized off the short side alone would meet in the
        # middle, and run under the touch icon on the way.
        width = min(short_side(0.46), self.overlay_layout.width * 0.40)

        for tab, btn, flush_right in (
            (self.tab_remote_queue, self.btn_remote_queue, False),
            (self.tab_remote_qr, self.btn_remote_qr, True),
        ):
            if tab is None or tab.parent is None:
                continue

            tab.size = (width, height)
            tab.x = self.overlay_layout.width - width if flush_right else 0
            tab.y = 0

            if btn is not None and btn.parent is not None:
                btn.pos_hint = {}
                btn.x = tab.right - inset - button if flush_right else tab.x + inset
                btn.y = tab.y + inset

            caption_width = width - button - 2 * inset - gap
            tab.caption.size = (caption_width, height - 2 * inset)
            tab.caption.x = tab.x + inset if flush_right else tab.x + inset + button + gap
            tab.caption.y = tab.y + inset
            tab.caption.font_size = short_side(0.028)

    # --- the slideshow ----------------------------------------------------

    def _arm_slideshow(self, *args):
        """Start counting the idle time again, from now."""
        self._disarm_slideshow()
        if self.slideshow is not None:
            self._slideshow_clock = Clock.schedule_once(self._start_slideshow, self.app.SLIDESHOW_IDLE_SECONDS)

    def _disarm_slideshow(self):
        if self._slideshow_clock is not None:
            Clock.unschedule(self._slideshow_clock)
            self._slideshow_clock = None

    def _start_slideshow(self, *args):
        self._slideshow_clock = None
        if self.slideshow is None or self.slideshow.running:
            return
        if self.app.get_current_screen_name() != ScreenNames.START:
            return
        if self.qr_popup is not None:
            # A guest is reading the codes: try again once they have had time.
            self._arm_slideshow()
            return

        def list_photos():
            photos = self.app.get_slideshow_photos()
            Clock.schedule_once(lambda dt: self._show_slideshow(photos), 0)

        # A directory listing, off the UI thread like the queue count.
        threading.Thread(target=list_photos, name='photobooth-slideshow-list', daemon=True).start()

    def _show_slideshow(self, photos):
        if self.app.get_current_screen_name() != ScreenNames.START or self.qr_popup is not None:
            self._arm_slideshow()
            return
        if not photos:
            # Nothing taken yet this evening: the welcome screen is the better
            # thing to look at. Ask again later, once a session may exist.
            self._arm_slideshow()
            return
        Logger.info('StartScreen: nobody around, showing %s photos.', len(photos))
        self.add_widget(self.slideshow)
        self.slideshow.start(photos)

    def _stop_slideshow(self, rearm=True):
        if self.slideshow is None:
            return
        self.slideshow.stop()
        if self.slideshow.parent is not None:
            self.remove_widget(self.slideshow)
        if rearm:
            self._arm_slideshow()

    def on_entry(self, kwargs={}):
        Logger.info('StartScreen: on_entry().')
        self._arm_slideshow()
        if self._version_label is not None:
            Animation(opacity=0, duration=1.5, t='in_quad').start(self._version_label)
            self._version_label = None  # only the first time, at power-up
        self.app.ringled.start_rainbow()
        self._pulse_touch_icon()
        self._purge_when_idle()

        if self.app.has_remote_capture():
            QRCodePopup.preload_steps(self.app.get_qr_invitation(self.app.get_remote_url())[0])
            self._refresh_pending_count()
            self._queue_clock = Clock.schedule_interval(self._refresh_pending_count, 5)

    def _purge_when_idle(self, *args):
        if self.app.get_current_screen_name() != ScreenNames.START:
            return
        if self.app.has_pending_photo_tasks() or self.app.has_background_processes():
            Clock.schedule_once(self._purge_when_idle, 0.5)
        else:
            self.app.clear_pending_photo_error()
            self.app.purge_tmp()

    def on_exit(self, kwargs={}):
        Logger.info('StartScreen: on_exit().')
        if self._queue_clock is not None:
            Clock.unschedule(self._queue_clock)
            self._queue_clock = None
        self._dismiss_qr_popup()
        # After the popup, whose dismissal starts the idle count again.
        self._stop_slideshow(rearm=False)
        self._disarm_slideshow()
        self._stop_touch_pulse()
        self.app.ringled.clear()

    # --- photos waiting from phones --------------------------------------

    def _refresh_pending_count(self, *args):
        """Count the queue off the UI thread: it is a file read, on every tick."""
        def read_count():
            count = self.app.get_remote_pending_count()
            Clock.schedule_once(lambda dt: self._apply_pending_count(count), 0)

        threading.Thread(target=read_count, name='photobooth-remote-count', daemon=True).start()

    def _apply_pending_count(self, count):
        if count == self._pending_count:
            return
        self._pending_count = count

        if self.btn_remote_queue is not None:
            self.overlay_layout.remove_widget(self.btn_remote_queue)
            self.btn_remote_queue = None
        if self.tab_remote_queue is not None:
            self.overlay_layout.remove_widget(self.tab_remote_queue)
            self.tab_remote_queue = None

        if count <= 0:
            return

        # The tab comes and goes with the button: this corner only means
        # anything while something is waiting in it, which is also exactly when
        # the guest who sent a photo walks up looking for it.
        self.tab_remote_queue = CornerTab(
            t('start.photos_waiting'),
            darken_rgba(REMOTE_COLOR, 0.25)[:3] + (0.92,),
            on_release=self.remote_queue_event,
        )
        self.overlay_layout.add_widget(self.tab_remote_queue)

        # Rebuilt rather than relabelled: the badge is baked into the button by
        # make_icon_button, and there is at most one rebuild every five seconds.
        self.btn_remote_queue = make_icon_button(
            ICON_SHOT_TAKEN,
            size=0.13,
            font=ICON_TTF,
            font_size_fraction=0.06,
            bgcolor=REMOTE_COLOR,
            badge=str(count) if count < 100 else '99+',
            badge_font_size=short_side(0.03),
            badge_color=BADGE_COLOR,
            on_release=self.remote_queue_event,
        )
        self.overlay_layout.add_widget(self.btn_remote_queue)
        self._layout_corners()

    def remote_qr_event(self, obj):
        Logger.info('StartScreen: remote_qr_event().')
        if getattr(self, 'qr_popup', None) is not None and self.qr_popup.parent:
            return
        steps, title, hint = self.app.get_qr_invitation(self.app.get_remote_url())
        # This screen has no walk-away timeout of its own — it is where the
        # booth waits — so the codes carry theirs, or a guest who left them
        # open leaves the next one tapping an overlay that answers nothing.
        self.qr_popup = QRCodePopup(
            steps,
            on_dismiss=self._dismiss_qr_popup,
            title=title,
            hint=hint,
            auto_dismiss_seconds=TIMINGS.qr_popup,
        )
        self.add_widget(self.qr_popup)

    def _dismiss_qr_popup(self):
        popup = getattr(self, 'qr_popup', None)
        if popup is not None and popup.parent:
            self.remove_widget(popup)
        self.qr_popup = None
        # Somebody was here: the idle time starts over.
        self._arm_slideshow()

    def remote_queue_event(self, obj):
        Logger.info('StartScreen: remote_queue_event().')
        self.app.transition_to(ScreenNames.REMOTE_GALLERY)

    def on_click(self, obj):
        Logger.info('StartScreen: on_click().')
        self.app.start_session()

    def on_keyboard_action(self):
        """A physical button is pressed on purpose, slideshow or not: it starts."""
        Logger.info('StartScreen: on_keyboard_action().')
        self.app.start_session()
        return True
