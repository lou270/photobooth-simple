"""Reading a CUPS job state.

The IPP values were read backwards: 9 is completed, not canceled. A successful
print was announced as a failure, and a canceled or aborted one, which is what
running out of paper produces, was announced as a success. The guest walked
away waiting for a photo that was never coming.
"""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault('KIVY_NO_ARGS', '1')
os.environ.setdefault('KIVY_GL_BACKEND', 'mock')

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.device_utils import CupsPrinter


class FakeCups:
    def __init__(self, attributes):
        self.attributes = attributes
        self.asked = []

    def getJobAttributes(self, task_id):
        self.asked.append(task_id)
        return self.attributes


def printer_seeing(state, reasons='none'):
    instance = CupsPrinter.__new__(CupsPrinter)
    instance._name = 'DS620'
    instance._instance = FakeCups({'job-state': state, 'job-state-reasons': reasons})
    return instance


def test_a_completed_job_is_done():
    """The exact case reported from the booth: state 9 with a success reason."""
    assert printer_seeing(9, 'job-completed-successfully').get_print_status(1) == 'done'


@pytest.mark.parametrize('state', [3, 4, 5])
def test_a_job_still_on_its_way_is_pending(state):
    assert printer_seeing(state).get_print_status(1) == 'pending'


def test_a_canceled_job_is_reported_as_canceled():
    with pytest.raises(RuntimeError, match='canceled'):
        printer_seeing(7, 'job-canceled-by-user').get_print_status(1)


def test_an_aborted_job_is_reported_as_aborted():
    with pytest.raises(RuntimeError, match='aborted'):
        printer_seeing(8, 'aborted-by-system').get_print_status(1)


def test_a_stopped_printer_keeps_the_job_pending():
    """Out of paper is recoverable: the operator refills and the job finishes."""
    assert printer_seeing(6, 'media-empty-warning').get_print_status(1) == 'pending'


def test_the_reason_reaches_the_message():
    with pytest.raises(RuntimeError, match='job-canceled-by-user'):
        printer_seeing(7, 'job-canceled-by-user').get_print_status(1)


def test_reasons_given_as_a_list_are_readable():
    with pytest.raises(RuntimeError, match='media-empty, media-needed'):
        printer_seeing(8, ['media-empty', 'media-needed']).get_print_status(1)


def test_a_missing_reason_does_not_hide_the_failure():
    with pytest.raises(RuntimeError, match='unknown'):
        printer_seeing(7, None).get_print_status(1)


def test_the_job_that_was_asked_about_is_the_one_given():
    printer = printer_seeing(9)
    printer.get_print_status(4242)
    assert printer._instance.asked == [4242]


# --- a queue that stopped ------------------------------------------------------

# What a DNP's Gutenprint backend leaves on the queue it stops when the printer
# reports Paper End: its ERROR line, which CUPS keeps as printer-state-message.
DNP_PAPER_END = 'Printer not ready: Paper End, please correct...'


class FakeQueue:
    """One CUPS queue as getPrinters() and getJobs() describe it."""

    def __init__(self, state=3, message='', reasons='none', jobs=1, accepting=True):
        self.printer = {
            'printer-state': state,
            'printer-state-message': message,
            'printer-state-reasons': reasons,
            'printer-is-accepting-jobs': accepting,
        }
        self.jobs = {job_id: {'job-id': job_id, 'job-printer-uri': 'ipp://localhost/printers/DS620'}
                     for job_id in range(1, jobs + 1)}
        self.enabled = 0

    def getPrinters(self):
        return {'DS620': dict(self.printer)}

    def getJobs(self, which_jobs='not-completed', requested_attributes=None):
        return dict(self.jobs)

    def enablePrinter(self, name):
        assert name == 'DS620'
        self.enabled += 1
        self.printer['printer-state'] = 3
        self.printer['printer-state-message'] = ''


def printer_on(queue):
    """A printer whose own connection, and the one it opens, are `queue`."""
    instance = CupsPrinter.__new__(CupsPrinter)
    instance._name = 'DS620'
    instance._instance = queue
    instance._connect = lambda: queue
    return instance


def test_a_dnp_out_of_paper_is_out_of_paper():
    printer = printer_on(FakeQueue(state=5, message=DNP_PAPER_END, reasons=['paused']))

    assert printer.get_problem() == 'paper'
    assert not printer.is_available()


@pytest.mark.parametrize('message, problem', [
    ('Printer not ready: Ribbon End, please correct...', 'ribbon'),
    ('Printer not ready: Paper Jam, please correct...', 'jam'),
    ('Printer not ready: Cover Open, please correct...', 'cover'),
    ('Printer reported: out of paper', 'paper'),
    ('Media empty', 'paper'),
])
def test_a_driver_stop_is_named_from_its_words(message, problem):
    """Gutenprint's dye-sub backends name no reason, only their last error."""
    assert printer_on(FakeQueue(state=5, message=message, reasons=['paused'])).get_problem() == problem


@pytest.mark.parametrize('reasons, problem', [
    (['media-empty-error'], 'paper'),
    ('paused,media-needed', 'paper'),
    (['marker-supply-empty-warning'], 'ribbon'),
    (['media-jam-error'], 'jam'),
    (['door-open-error'], 'cover'),
])
def test_an_ipp_stop_is_named_from_its_reasons(reasons, problem):
    assert printer_on(FakeQueue(state=5, reasons=reasons)).get_problem() == problem


@pytest.mark.parametrize('message', [
    'Printer not ready: Ribbon Error, please correct...',
    'Printer not ready: No Scrap Box, please correct...',
    '',
])
def test_any_other_stop_is_a_stopped_printer(message):
    assert printer_on(FakeQueue(state=5, message=message, reasons=['paused'])).get_problem() == 'stopped'


def test_the_welcome_banner_names_a_dnp_out_of_paper_too():
    """It read the reasons alone, which a DNP's backend never sets: its empty
    printer was announced as merely stopped."""
    queue = FakeQueue(state=5, message=DNP_PAPER_END, reasons=['paused'])
    queue.getJobAttributes = lambda task_id, requested_attributes=None: {'job-state': 3}

    assert printer_on(queue).get_queue_problem([7]) == ([7], 'paper')


def test_a_queue_refusing_jobs_is_unavailable():
    assert printer_on(FakeQueue(accepting=False)).get_problem() == 'unavailable'


def test_a_queue_cups_no_longer_has_is_unavailable():
    queue = FakeQueue()
    queue.getPrinters = lambda: {}

    assert printer_on(queue).get_problem() == 'unavailable'


def test_cups_not_answering_is_unavailable():
    queue = FakeQueue()

    def refuse():
        raise RuntimeError('cups is down')
    queue.getPrinters = refuse

    assert printer_on(queue).get_problem() == 'unavailable'


@pytest.mark.parametrize('state', [3, 4])
def test_a_running_queue_can_print(state):
    printer = printer_on(FakeQueue(state=state))

    assert printer.get_problem() is None
    assert printer.is_available()


# --- starting it again ---------------------------------------------------------

def test_a_queue_its_driver_stopped_is_started_again():
    """CUPS leaves it stopped: refilling the printer used to leave the photo
    waiting in a paused queue until someone ran cupsenable."""
    queue = FakeQueue(state=5, message=DNP_PAPER_END)
    printer = printer_on(queue)

    assert printer.resume_if_stopped()
    assert queue.enabled == 1


def test_a_queue_paused_by_hand_stays_paused():
    queue = FakeQueue(state=5, message='Paused', reasons=['paused'])
    printer = printer_on(queue)

    assert not printer.resume_if_stopped()
    assert queue.enabled == 0


@pytest.mark.parametrize('state', [3, 4])
def test_a_running_queue_is_left_alone(state):
    queue = FakeQueue(state=state)

    assert not printer_on(queue).resume_if_stopped()
    assert queue.enabled == 0


def test_a_queue_the_booth_may_not_start_is_reported_not_raised():
    """Resume-Printer is for CUPS administrators: a user outside lpadmin is refused."""
    queue = FakeQueue(state=5, message=DNP_PAPER_END)

    def refuse(name):
        raise RuntimeError('Forbidden')
    queue.enablePrinter = refuse

    assert not printer_on(queue).resume_if_stopped()


def test_a_queue_just_started_again_still_says_why_it_stopped():
    """The driver only finds the printer still empty once it has rendered the
    sheet again; until then the queue looks like it is printing, and the guest
    would read that their photo is coming out, every thirty seconds."""
    queue = FakeQueue(state=5, message=DNP_PAPER_END)
    printer = printer_on(queue)
    printer.resume_if_stopped(now=1000)
    queue.printer['printer-state'] = 4                  # the job is being tried again

    assert printer.get_problem(now=1010) == 'paper'
    assert printer.get_problem(now=1000 + CupsPrinter.RESUME_INTERVAL) is None


def test_a_queue_whose_jobs_came_out_after_a_restart_can_print():
    queue = FakeQueue(state=5, message=DNP_PAPER_END)
    printer = printer_on(queue)
    printer.resume_if_stopped(now=1000)

    queue.jobs = {}                                     # refilled: the photo came out
    assert printer.get_problem(now=1010) is None


def test_a_queue_stopped_again_says_so_whatever_the_last_try():
    queue = FakeQueue(state=5, message=DNP_PAPER_END)
    printer = printer_on(queue)
    printer.resume_if_stopped(now=1000)

    queue.printer.update({'printer-state': 5, 'printer-state-message': 'Printer not ready: Cover Open, please correct...'})
    assert printer.get_problem(now=1010) == 'cover'


def test_the_welcome_banner_stays_up_while_the_booth_tries_the_queue_again():
    """Or it would go and come back every thirty seconds, nobody having refilled anything."""
    queue = FakeQueue(state=5, message=DNP_PAPER_END)
    queue.getJobAttributes = lambda task_id, requested_attributes=None: {'job-state': 5}
    printer = printer_on(queue)
    printer.resume_if_stopped()
    queue.printer['printer-state'] = 4

    assert printer.get_queue_problem([7]) == ([7], 'paper')
