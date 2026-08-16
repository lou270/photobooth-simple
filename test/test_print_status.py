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
