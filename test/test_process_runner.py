"""ProcessRunner is polled by the UI clock: its answers must stay accurate."""

import sys
import threading
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.core import ProcessRunner


def wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_a_finished_job_reports_no_failure():
    runner = ProcessRunner()
    runner.start('shot', lambda: None)

    assert wait_until(lambda: not runner.is_running())
    assert not runner.has_failed()
    assert runner.get_error() is None


def test_a_failing_job_exposes_its_traceback():
    runner = ProcessRunner()

    def explode():
        raise IOError('camera is not responding')

    runner.start('shot', explode)

    assert wait_until(lambda: not runner.is_running())
    assert runner.has_failed('shot')
    assert 'camera is not responding' in runner.get_error('shot')


def test_failure_is_only_reported_for_the_matching_kind():
    runner = ProcessRunner()
    runner.start('shot', lambda: (_ for _ in ()).throw(IOError('boom')))

    assert wait_until(lambda: not runner.is_running())
    assert runner.has_failed('shot')
    assert not runner.has_failed('collage')
    assert runner.get_error('collage') is None


def test_arguments_reach_the_target():
    runner = ProcessRunner()
    received = {}

    runner.start('collage', lambda *args, **kwargs: received.update(args=args, kwargs=kwargs), 1, 2, out='x')

    assert wait_until(lambda: received)
    assert received == {'args': (1, 2), 'kwargs': {'out': 'x'}}


def test_a_running_job_is_reported_as_running():
    runner = ProcessRunner()
    release = threading.Event()
    runner.start('shot', release.wait)

    assert runner.is_running()
    release.set()
    assert wait_until(lambda: not runner.is_running())


def test_timeout_only_fires_while_the_job_is_still_running():
    runner = ProcessRunner()
    release = threading.Event()
    runner.start('shot', release.wait)

    assert not runner.has_timed_out('shot', timeout_seconds=10)
    assert wait_until(lambda: runner.has_timed_out('shot', timeout_seconds=0.05))
    assert not runner.has_timed_out('collage', timeout_seconds=0.05)

    release.set()
    assert wait_until(lambda: not runner.is_running())
    assert not runner.has_timed_out('shot', timeout_seconds=0.05)


def test_abandoning_a_job_frees_the_runner_immediately():
    runner = ProcessRunner()
    release = threading.Event()
    runner.start('shot', release.wait)

    assert runner.abandon('shot', reason='capture_timeout')

    assert not runner.is_running()
    assert runner.has_failed('shot')
    assert runner.get_error('shot') == 'capture_timeout'
    release.set()


def test_abandoning_another_kind_is_a_no_op():
    runner = ProcessRunner()
    release = threading.Event()
    runner.start('shot', release.wait)

    assert not runner.abandon('collage', reason='wrong kind')

    assert runner.is_running()
    assert not runner.has_failed('shot')
    release.set()


def test_an_abandoned_job_cannot_overwrite_the_next_one():
    """The thread keeps running after abandon(): its outcome must be ignored."""
    runner = ProcessRunner()
    release = threading.Event()

    def slow_failure():
        release.wait()
        raise IOError('late failure from the abandoned capture')

    runner.start('shot', slow_failure)
    runner.abandon('shot', reason='capture_timeout')
    runner.start('collage', lambda: None)

    release.set()
    assert wait_until(lambda: not runner.is_running())
    time.sleep(0.05)  # let the abandoned thread finish and try to report

    assert not runner.has_failed('collage')
    assert runner.state()['kind'] == 'collage'
