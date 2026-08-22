"""The booth printing, and nothing else.

Its own screen rather than an overlay on the review screen: sending a photo to
the printer ends the session, and a guest who pressed the last button has to see
the booth move on, or they keep looking for what else there is to do. When the
sheet is on its way this screen hands the booth to the next guest by itself; a
failure is the only thing that needs a person, and that is what the error screen
is for.
"""

import time

from kivy.clock import Clock
from kivy.logger import Logger
from kivy.uix.boxlayout import BoxLayout

from libs.i18n import t
from libs.kivywidgets import PaperFeedAnimation, ResizeLabel
from libs.screens.names import ScreenNames
from libs.screens.theme import (
    ICON_ERROR_PRINTING, ICON_PRINT, ICON_TTF, PRINT_DONE_SECONDS, PRINT_MIN_SECONDS,
    PRINT_SHEET_TIMEOUT_SECONDS,
)
from libs.screens.base import ColorScreen


class PrintingScreen(ColorScreen):
    """
    +-----------------+
    |     [printer]   |
    |       [sheet]   |
    |   IMPRESSION    |
    | Your photo is   |
    | coming out      |
    +-----------------+
    """

    def __init__(self, app, **kwargs):
        Logger.info('PrintingScreen: __init__().')
        super(PrintingScreen, self).__init__(**kwargs)

        self.app = app
        self._current_format = 0
        self._copies = 1
        self._clock = None
        self._can_leave = False

        layout = BoxLayout(orientation='vertical', size_hint=(0.9, 0.9), pos_hint={'center_x': 0.5, 'center_y': 0.5})

        self.animation = PaperFeedAnimation(
            icon_text=ICON_PRINT,
            icon_font=ICON_TTF,
            icon_wh_fraction=0.20,
            sheet_color=[1, 1, 1, 1],
            size_hint=(1, 0.55),
        )
        layout.add_widget(self.animation)

        self.title = ResizeLabel(
            text=t('printing.title'),
            size_hint=(1, 0.14),
            wh_fraction=0.06,
            bold=True,
            halign='center',
            valign='middle',
        )
        layout.add_widget(self.title)

        self.message = ResizeLabel(
            text=t('printing.saving'),
            size_hint=(1, 0.14),
            wh_fraction=0.035,
            halign='center',
            valign='middle',
        )
        layout.add_widget(self.message)

        self.add_widget(layout)

    def on_entry(self, kwargs={}):
        Logger.info('PrintingScreen: on_entry().')
        self._current_format = kwargs.get('format') if 'format' in kwargs else 0
        self._copies = max(1, int(kwargs.get('copies', 1)))
        self._started_at = time.monotonic()
        self._print_started = False
        self._print_counted = False
        self._print_task_ids = []
        self._print_started_at = None
        self._printer_wait_started_at = None
        self._can_leave = False
        self._timeout = getattr(self.app, 'PRINTER_WAIT_TIMEOUT', 45)
        self.title.text = t('printing.title')
        self.message.text = t('printing.saving')
        self.animation.start()
        self.app.ringled.wave([255, 255, 255])
        self._clock = Clock.schedule_once(self._tick, 0.2)

    def on_exit(self, kwargs={}):
        Logger.info('PrintingScreen: on_exit().')
        if self._clock:
            Clock.unschedule(self._clock)
            self._clock = None
        self.animation.stop()
        self.app.ringled.clear()

    # --- getting the job to the printer -----------------------------------

    def _fail(self, message, detail=None):
        """Hand the guest to the error screen: this one has nothing to press."""
        Logger.error('PrintingScreen: print failed: %s', detail or '-')
        if detail:
            message = f'{message}\n{detail}'
        self._clock = None
        self.app.transition_to(
            ScreenNames.ERROR,
            message=message,
            error=ICON_ERROR_PRINTING,
            show_continue=True,
            show_restart=False,
        )

    def _done(self):
        """The printer has the job; the booth belongs to the next guest.

        Not immediately, though: CUPS calls a job done well before the sheet is
        out, and a screen that flashes past leaves the guest walking away from a
        printer they were never told to go to. The sheet keeps moving until the
        screen goes, because so does the real one.
        """
        self._can_leave = True
        elapsed = time.monotonic() - self._started_at
        delay = max(PRINT_DONE_SECONDS, PRINT_MIN_SECONDS - elapsed)
        self._clock = Clock.schedule_once(self._leave, delay)

    def _leave(self, *args):
        # A guest tapping to skip the delay gets here with the timer _done() set
        # still pending, and on_exit only unschedules what _clock still points
        # at. Left behind, it fired seconds later and sent the *next* guest back
        # to the welcome screen, mid-countdown.
        if self._clock:
            Clock.unschedule(self._clock)
        self._clock = None
        self.app.transition_to(ScreenNames.START)

    def on_touch_down(self, touch):
        # A guest who has understood should not have to wait out the delay.
        if self._can_leave:
            self._leave()
            return True
        return super(PrintingScreen, self).on_touch_down(touch)

    def _tick(self, obj):
        if self.app.has_pending_photo_tasks():
            self.message.text = t('printing.saving')
            self._clock = Clock.schedule_once(self._tick, 0.2)
            return

        pending_error = self.app.get_pending_photo_error()
        if pending_error:
            Logger.error('PrintingScreen: save before print failed.')
            Logger.error(pending_error)
            self._fail(t('printing.save_failed'))
            return

        if not self._print_started:
            # PRINTER_WAIT_TIMEOUT bounds getting the job to the printer, which
            # is what an operator sets it for. It used to bound the printing as
            # well, and a dye-sub taking its usual minute a sheet was reported
            # to the guest as a failure while the sheets were coming out — with
            # the print quota left uncounted on top of it.
            if time.monotonic() - self._started_at >= self._timeout:
                self._fail(t('printing.print_failed'), t('printing.timed_out'))
                return

            self.message.text = t('printing.sending')
            try:
                # One task per sheet: the booth queues the copies itself, so
                # the screen is only done once every one of them is through.
                self._print_task_ids = list(self.app.trigger_print(self._copies, self._current_format) or [])
                if not self._print_task_ids:
                    raise RuntimeError('Printer did not return a task id')
                self._print_started = True
                self._print_started_at = time.monotonic()
                Logger.info('PrintingScreen: print started tasks=%s copies=%s', self._print_task_ids, self._copies)
            except Exception as exc:
                self._fail(t('printing.print_failed'), str(exc))
                return

        # A ceiling on the printing itself, budgeted per sheet. Only a safety
        # net against a job CUPS never finishes; nobody should ever reach it.
        printing_deadline = PRINT_SHEET_TIMEOUT_SECONDS * max(1, len(self._print_task_ids))
        if time.monotonic() - self._print_started_at >= printing_deadline:
            self._fail(t('printing.print_failed'), t('printing.timed_out'))
            return

        if not self.app.has_printer():
            if self._printer_wait_started_at is None:
                self._printer_wait_started_at = time.monotonic()
                Logger.warning('PrintingScreen: printer unavailable, waiting for recovery')
            waited = time.monotonic() - self._printer_wait_started_at
            remaining = max(0, int(self._timeout - waited))
            self.message.text = t('printing.printer_unavailable', remaining=remaining)
            if waited >= self._timeout:
                self._fail(t('printing.print_failed'), t('printing.printer_reconnect_failed'))
                return
            self._clock = Clock.schedule_once(self._tick, 1)
            return

        if self._printer_wait_started_at is not None:
            Logger.info('PrintingScreen: printer recovered after %.2fs', time.monotonic() - self._printer_wait_started_at)
            self._printer_wait_started_at = None

        try:
            statuses = [self.app.devices.get_print_status(task_id) for task_id in self._print_task_ids]
        except Exception as exc:
            self._fail(t('printing.print_failed'), str(exc))
            return

        Logger.info('PrintingScreen: print status tasks=%s statuses=%s', self._print_task_ids, statuses)
        if all(status == 'done' for status in statuses):
            if not self._print_counted:
                self.app.track_print_sent(self._copies)
                self._print_counted = True
            self._done()
        else:
            self.message.text = t('printing.printing')
            self._clock = Clock.schedule_once(self._tick, 1)
