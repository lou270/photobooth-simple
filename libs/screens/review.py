"""The finished collage: choose a look, how many copies, then print or share."""

import threading
import cv2

from kivy.clock import Clock
from kivy.logger import Logger
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label

from libs.i18n import t
from libs.imaging import DEFAULT_FILTER
from libs.kivywidgets import (
    BackgroundBoxLayout, BlurredImage, icon_button_label, make_icon_button, short_side,
)
from libs.file_utils import FileUtils
from libs.screens.filter_strip import FilterStrip, build_thumbnails
from libs.screens.theme import (
    BORDER_THINKNESS, CONFIRM_COLOR, HOME_COLOR, HOME_PROGRESS_COLOR, ICON_HOME, ICON_PRINT,
    ICON_SHARE, ICON_TTF, REVIEW_HOME_TIMEOUT_SECONDS, SHARE_COLOR, SMALL_FONT,
    STEPPER_COLOR, wh_bind,
)
from libs.screens.base import HomeTimeoutMixin, ColorScreen
from libs.screens.names import ScreenNames
from libs.screens.popups import ConfirmPopup, QRCodePopup


class ReviewScreen(HomeTimeoutMixin, ColorScreen):
    """Final action screen: the saved collage, with the choices still open.

    +---------------------------+
    | [home]                    |
    |                           |
    |          collage   (share)|
    |               (x2)(print) |
    |   [filter][filter]        |
    +---------------------------+

    Everything a guest can still decide lives here rather than earlier in the
    flow: the look, because it applies to the whole collage and they can see
    what they are choosing; the number of copies, because it is the last thing
    anyone thinks about.
    """

    HOME_TIMEOUT_SECONDS = REVIEW_HOME_TIMEOUT_SECONDS

    # All as fractions of the short side, so the screen looks the same whichever
    # way the panel is turned. The print button is the biggest: it is what the
    # guest came for.
    FILTER_BAND_FRACTION = 0.22
    PRINT_BUTTON_SIZE = 0.17
    SHARE_BUTTON_SIZE = 0.14
    COPIES_BUTTON_SIZE = 0.12

    def __init__(self, app, **kwargs):
        Logger.info('ReviewScreen: __init__().')
        super(ReviewScreen, self).__init__(**kwargs)

        self.app = app
        self._current_format = 0
        self._init_home_timeout()
        self._print_state = None
        self._print_remaining = None
        self._selected_filter = DEFAULT_FILTER
        self._preview_token = None
        self._copies = 1
        self._finalized = False
        self.lbl_copies = None
        self.confirm_popup = None
        self.layout = AnchorLayout(padding=BORDER_THINKNESS, anchor_x='center', anchor_y='top')
        self.overlay_layout = FloatLayout()
        self.layout.add_widget(self.overlay_layout)

        self.preview = BlurredImage(
            blur=self.app.BLUR_COLLAGE,
            fit_mode='contain',
            size_hint=(1, 1),
            pos_hint={'x': 0, 'y': 0},
        )
        self.overlay_layout.add_widget(self.preview)

        self.btn_home = make_icon_button(
            ICON_HOME,
            size=0.14,
            pos_hint={'x': 0.05, 'top': 0.95},
            font=ICON_TTF,
            font_size_fraction=0.07,
            bgcolor=HOME_COLOR,
            progress=True,
            progress_color=HOME_PROGRESS_COLOR,
            progress_line_width_fraction=0.028,
            on_release=self.home_event,
        )
        self.overlay_layout.add_widget(self.btn_home)

        self.filters = None
        if self.app.FILTERS_ENABLED:
            self.filters = FilterStrip(
                self.on_filter_selected,
                size_hint=(1, None),
                height=short_side(self.FILTER_BAND_FRACTION),
                pos_hint={'x': 0, 'y': 0},
            )
            self.overlay_layout.add_widget(self.filters)

        # Round icon buttons like every other button in the booth. They were an
        # icon beside a word, the one shape in the interface that was not a
        # circle, and the only one whose proportions had to be argued with every
        # time the screen changed shape.
        self.btn_print = make_icon_button(
            ICON_PRINT,
            size=self.PRINT_BUTTON_SIZE,
            pos_hint={},
            font=ICON_TTF,
            font_size_fraction=0.08,
            bgcolor=CONFIRM_COLOR,
            on_release=self.print_event,
        )
        self.overlay_layout.add_widget(self.btn_print)

        # How many copies: one button showing what will come out, tapped to go
        # round. A number between a minus and a plus was three widgets and a
        # caption to place, and they overlapped each other on a narrow screen.
        self.btn_copies = make_icon_button(
            'x1',
            size=self.COPIES_BUTTON_SIZE,
            pos_hint={},
            font_size_fraction=0.045,
            bgcolor=STEPPER_COLOR,
            on_release=self.copies_event,
        )
        self.lbl_copies = icon_button_label(self.btn_copies)

        # Why the print button is greyed out, or missing. A disabled control
        # with nothing beside it reads as a broken booth: a guest tapped the
        # grey printer over and over and left, when the honest answer was that
        # the evening's quota was spent and an operator could refill it.
        self.print_status = BackgroundBoxLayout(
            orientation='vertical',
            size_hint=(None, None),
            pos_hint={},
            padding=short_side(0.018),
            background_color=(0, 0, 0, 0.55),
        )
        self.lbl_print_status = Label(
            text='',
            font_size=SMALL_FONT(),
            halign='center',
            valign='middle',
        )
        wh_bind(self.lbl_print_status, 'font_size', SMALL_FONT)
        self.lbl_print_status.bind(size=self.lbl_print_status.setter('text_size'))
        self.print_status.add_widget(self.lbl_print_status)

        self.btn_share = None
        if self.app.SHARE:
            self.btn_share = make_icon_button(
                ICON_SHARE,
                size=self.SHARE_BUTTON_SIZE,
                pos_hint={},
                font=ICON_TTF,
                font_size_fraction=0.07,
                bgcolor=SHARE_COLOR,
                on_release=self.share_event,
            )
            self.overlay_layout.add_widget(self.btn_share)

        self.overlay_layout.bind(size=self._layout_action_buttons)
        Clock.schedule_once(self._layout_action_buttons, 0)
        self.add_widget(self.layout)

    # --- layout -----------------------------------------------------------

    def _action_buttons(self):
        """Bottom of the stack first: printing is what a guest reaches for."""
        buttons = []
        if self.btn_print.parent is not None:
            buttons.append(self.btn_print)
        if self.btn_share is not None:
            buttons.append(self.btn_share)
        return buttons

    def _layout_action_buttons(self, *args):
        """Place the buttons in pixels, up the right edge above the filters.

        Positions used to be fractions of the width, which moves a square button
        around as the screen changes shape: on a panel turned upright the copies
        control landed on top of itself.
        """
        if not self.overlay_layout.width:
            return

        margin = short_side(0.03)
        gap = short_side(0.02)
        band = self.filters.height if self.filters is not None else 0
        right = self.overlay_layout.width - margin

        y = band + margin
        for btn in self._action_buttons():
            btn.pos_hint = {}
            btn.x = right - btn.width
            btn.y = y
            y = btn.top + gap

        if self.btn_copies.parent is not None and self.btn_print.parent is not None:
            # Beside the print button, on the same line: the two are one decision.
            self.btn_copies.pos_hint = {}
            self.btn_copies.x = self.btn_print.x - gap - self.btn_copies.width
            self.btn_copies.y = self.btn_print.y + (self.btn_print.height - self.btn_copies.height) / 2

        if self.print_status.parent is not None:
            # Left of the button column, on the print button's own line: the
            # message explains that button, so it has to sit where the eye
            # already is rather than at the top of the screen.
            column = max((btn.width for btn in self._action_buttons()), default=0)
            available = self.overlay_layout.width - margin - column - (gap if column else 0) - margin
            self.print_status.x = margin
            self.print_status.y = band + margin
            self.print_status.width = max(short_side(0.35), available)
            self.print_status.height = short_side(0.16)

        if self.filters is not None:
            # The buttons stack above the band, not beside it, so the strip has
            # the whole width. Reserving room for them squeezed it to a single
            # visible filter on a screen turned upright.
            self.filters.set_max_width(self.overlay_layout.width * 0.94)

    # --- printer state ----------------------------------------------------

    def _sync_print_button(self):
        """Refresh the print button without blocking the UI thread.

        has_printer() is a CUPS round trip and the print limit reads the stats
        file. Both used to run straight from the clock, so entering this screen
        stalled on a printer that was slow to answer, right after a capture.
        The last known state is shown immediately and corrected when the probe
        comes back.
        """
        if self._print_state is not None:
            self._apply_print_state(*self._print_state)

        def probe():
            state = (self.app.has_printer(), self.app.can_start_print(), self.app.get_print_limit_info())
            Clock.schedule_once(lambda dt: self._apply_print_state(*state), 0)

        threading.Thread(target=probe, name='photobooth-printer-probe', daemon=True).start()

    def _apply_print_state(self, printer_available, print_available, limit_info=None):
        self._print_state = (printer_available, print_available, limit_info)
        if limit_info is not None:
            self._print_remaining = limit_info['remaining'] if limit_info['enabled'] else None

        if printer_available and self.btn_print.parent is None:
            self.overlay_layout.add_widget(self.btn_print)
        elif not printer_available and self.btn_print.parent is not None:
            self.overlay_layout.remove_widget(self.btn_print)

        self.btn_print.disabled = not print_available
        self.btn_print.opacity = 1.0 if print_available else 0.45
        self._sync_print_status(printer_available, print_available)
        self._sync_copies(printer_available and print_available)
        self._layout_action_buttons()

    def _sync_print_status(self, printer_available, print_available):
        """Say why printing is not on offer, but only where a guest expected it.

        A booth configured without a printer is not missing anything, and
        announcing an absent feature on every session is noise. A booth that has
        one and cannot use it is a different story, and the guest standing in
        front of a grey button is the person who needs to hear it.
        """
        if not self.app.PRINTER:
            message = ''
        elif not printer_available:
            message = t('review.printer_unavailable')
        elif not print_available:
            message = t('review.print_limit_reached')
        else:
            message = ''

        self.lbl_print_status.text = message
        if message and self.print_status.parent is None:
            self.overlay_layout.add_widget(self.print_status)
        elif not message and self.print_status.parent is not None:
            self.overlay_layout.remove_widget(self.print_status)

    # --- copies -----------------------------------------------------------

    def _copies_limit(self):
        """Never more than the operator allows, nor more than the quota has left."""
        limit = max(1, int(getattr(self.app, 'MAX_COPIES', 1)))
        if self._print_remaining is not None:
            limit = max(1, min(limit, self._print_remaining))
        return limit

    def _sync_copies(self, printing_possible=True):
        limit = self._copies_limit()
        self._copies = max(1, min(self._copies, limit))
        if self.lbl_copies is not None:
            # Photos, not sheets: a strip template prints two of them per sheet,
            # and a guest who reads x1 and is handed two of everything has been
            # told the booth's arithmetic instead of their own.
            per_sheet = self.app.get_copies_per_sheet(self._current_format)
            self.lbl_copies.text = 'x%d' % (self._copies * per_sheet)

        # One possible copy is not a choice, and no printer is not a question.
        visible = printing_possible and limit > 1
        if visible and self.btn_copies.parent is None:
            self.overlay_layout.add_widget(self.btn_copies)
        elif not visible and self.btn_copies.parent is not None:
            self.overlay_layout.remove_widget(self.btn_copies)

    def copies_event(self, obj):
        """Round and round: 1, 2, 3, back to 1.

        A count that only goes up would strand a guest who overshot, and the
        highest it goes is three.
        """
        limit = self._copies_limit()
        self._copies = (self._copies % limit) + 1 if limit > 1 else 1
        Logger.info('ReviewScreen: copies=%s.', self._copies)
        self._reset_timeout()
        self._sync_copies()

    # --- filters ----------------------------------------------------------

    def on_filter_selected(self, filter_key):
        if self._finalized:
            return
        Logger.info('ReviewScreen: filter %s selected.', filter_key)
        self._selected_filter = filter_key
        self._reset_timeout()
        self._rebuild_preview()

    def _rebuild_preview(self):
        """Redraw the collage with the chosen look, off the UI thread.

        Built from the small captures, so trying five filters in a row costs
        five small collages rather than five full-size ones. What is on disk is
        only rewritten once the guest is done choosing.
        """
        token = object()
        self._preview_token = token
        format_idx, filter_key = self._current_format, self._selected_filter

        def work():
            try:
                collage = self.app.build_preview_collage(format_idx, filter_key)
            except Exception as exc:
                Logger.error('ReviewScreen: could not rebuild the preview: %s', exc)
                return

            def apply_on_main(dt):
                if self._preview_token is not token:
                    return
                self.preview.set_image(collage)

            Clock.schedule_once(apply_on_main, 0)

        threading.Thread(target=work, name='photobooth-review-preview', daemon=True).start()

    def _refresh_filter_thumbnails(self):
        if self.filters is None:
            return
        path = FileUtils.get_small_path(self.app.get_shot(0))

        def work():
            thumbnails = build_thumbnails(cv2.imread(path))
            if not thumbnails:
                return
            Clock.schedule_once(lambda dt: self.filters.set_thumbnails(thumbnails), 0)

        threading.Thread(target=work, name='photobooth-review-thumbs', daemon=True).start()

    # --- the session ------------------------------------------------------

    def _finalize_once(self):
        """Write the session out, in the form the guest settled on.

        Deliberately late: saving on arrival would file away a collage they had
        not finished choosing a look for. Whichever comes first — printing or
        leaving — closes the choice, which is why the strip greys out here.
        """
        if self._finalized:
            return
        self._finalized = True
        if self.filters is not None:
            self.filters.set_enabled(False)
        self.app.start_photo_task(self.app.finalize_session, self._current_format, self._selected_filter)

    # --- screen lifecycle -------------------------------------------------

    def on_entry(self, kwargs={}):
        Logger.info('ReviewScreen: on_entry().')
        self._current_format = kwargs.get('format') if 'format' in kwargs else 0
        self._selected_filter = DEFAULT_FILTER
        self._preview_token = None
        self._copies = 1
        self._finalized = False
        self._start_home_timeout()
        self.app.ringled.start_rainbow()
        self._sync_print_button()
        self._load_preview_async(FileUtils.get_small_path(self.app.get_collage()))
        if self.filters is not None:
            self.filters.set_selected(DEFAULT_FILTER)
            self.filters.set_enabled(True)
            self._refresh_filter_thumbnails()
        if self.app.SHARE:
            QRCodePopup.preload_steps(self.app.get_qr_invitation(self.app.gallery_url)[0])

    def _load_preview_async(self, path):
        def load_image():
            im = cv2.imread(path)

            def apply_on_main(dt):
                if im is not None:
                    self.preview.set_image(im)
                else:
                    Logger.warning('ReviewScreen: cannot load preview %s', path)

            Clock.schedule_once(apply_on_main, 0)

        threading.Thread(target=load_image, daemon=True).start()

    def on_exit(self, kwargs={}):
        Logger.info('ReviewScreen: on_exit().')
        self._stop_home_timeout()
        self._close_confirm_popup()
        self._finalize_once()
        if hasattr(self, 'qr_popup') and self.qr_popup.parent:
            self.layout.remove_widget(self.qr_popup)
        self.app.ringled.clear()

    def _reset_timeout(self):
        self._start_home_timeout()

    # --- leaving without printing -----------------------------------------

    def _printing_was_offered(self):
        """Whether the guest could have printed, from the last probe's answer."""
        if self._print_state is None:
            return False
        printer_available, print_available, _limit_info = self._print_state
        return bool(printer_available and print_available)

    def home_event(self, obj):
        """Ask before walking away from a photo that could still be printed.

        Leaving finalises the session: the collage is written as it stands, the
        filter strip closes, and there is no route back to this screen. It is
        also the one button on it a guest presses by mistake, reading the house
        as "back". Every other irreversible action in the booth asks first —
        taking a photo out of the phone queue does, with its thumbnail in the
        question — and the one that throws away a print did not.

        Only asked where printing was actually on offer and went unused: a booth
        with no printer has nothing to warn about. The walk-away timeout does
        not come through here at all, which is right — nobody is left to answer.
        """
        if self.confirm_popup is not None:
            return
        if not self._printing_was_offered():
            return super(ReviewScreen, self).home_event(obj)

        Logger.info('ReviewScreen: asking before leaving without printing.')
        self._stop_home_timeout()
        self.confirm_popup = ConfirmPopup(
            title=t('review.leave.title'),
            message=t('review.leave.message'),
            icon=ICON_PRINT,
            on_confirm=self._leave_without_printing,
            on_dismiss=self._dismiss_confirm_popup,
        )
        self.layout.add_widget(self.confirm_popup)

    def _leave_without_printing(self):
        Logger.info('ReviewScreen: leaving without printing.')
        super(ReviewScreen, self).home_event(None)

    def _dismiss_confirm_popup(self):
        self._close_confirm_popup()
        # Confirming schedules this alongside the answer, so it also runs just
        # after the screen has left. Restarting the timeout then would arm a
        # clock that drags whatever screen came next back to the start.
        if self.app.get_current_screen_name() == ScreenNames.REVIEW:
            self._reset_timeout()

    def _close_confirm_popup(self):
        if self.confirm_popup is None:
            return
        if self.confirm_popup.parent is not None:
            self.layout.remove_widget(self.confirm_popup)
        self.confirm_popup = None

    def print_event(self, obj):
        Logger.info('ReviewScreen: print_event(copies=%s).', self._copies)
        # The session is written first and the printing screen waits on it, so
        # the printer gets the collage the guest chose, not the one it started
        # as. Pressing print ends the session: the booth moves on rather than
        # dropping the guest back here with nothing left to do.
        self._finalize_once()
        self.app.transition_to(
            ScreenNames.PRINTING,
            format=self._current_format,
            copies=self._copies,
        )

    def share_event(self, obj):
        Logger.info('ReviewScreen: share_event().')
        self._reset_timeout()
        if hasattr(self, 'qr_popup') and self.qr_popup.parent:
            return
        steps, title, hint = self.app.get_qr_invitation(self.app.gallery_url)
        self.qr_popup = QRCodePopup(steps, on_dismiss=self._dismiss_qr_popup, title=title, hint=hint)
        self.layout.add_widget(self.qr_popup)

    def _dismiss_qr_popup(self):
        if hasattr(self, 'qr_popup') and self.qr_popup.parent:
            self.layout.remove_widget(self.qr_popup)
        self._reset_timeout()

    def on_keyboard_action(self):
        if self.confirm_popup is not None:
            self._dismiss_confirm_popup()
            return True
        self.home_event(None)
        return True
