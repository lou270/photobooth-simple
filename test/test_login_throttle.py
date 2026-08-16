"""The admin password is the only application-level gate: attempts must be bounded."""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.login_throttle import LoginThrottle


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make_throttle(clock, max_attempts=3, lockout_seconds=60, window_seconds=300):
    return LoginThrottle(
        max_attempts=max_attempts,
        lockout_seconds=lockout_seconds,
        window_seconds=window_seconds,
        time_source=clock,
    )


def test_an_unknown_client_may_try():
    throttle = make_throttle(FakeClock())
    assert throttle.retry_after('10.0.0.1') == 0
    assert not throttle.is_locked('10.0.0.1')


def test_failures_below_the_limit_do_not_lock():
    throttle = make_throttle(FakeClock())

    assert throttle.record_failure('10.0.0.1') == 0
    assert throttle.record_failure('10.0.0.1') == 0
    assert not throttle.is_locked('10.0.0.1')


def test_reaching_the_limit_locks_the_client():
    throttle = make_throttle(FakeClock(), max_attempts=3, lockout_seconds=60)

    throttle.record_failure('10.0.0.1')
    throttle.record_failure('10.0.0.1')

    assert throttle.record_failure('10.0.0.1') == 60
    assert throttle.retry_after('10.0.0.1') == 60


def test_the_lockout_expires_on_its_own():
    clock = FakeClock()
    throttle = make_throttle(clock, max_attempts=2, lockout_seconds=60)
    throttle.record_failure('10.0.0.1')
    throttle.record_failure('10.0.0.1')

    clock.advance(59)
    assert throttle.is_locked('10.0.0.1')

    clock.advance(2)
    assert not throttle.is_locked('10.0.0.1')


def test_a_successful_login_clears_the_history():
    throttle = make_throttle(FakeClock(), max_attempts=3)
    throttle.record_failure('10.0.0.1')
    throttle.record_failure('10.0.0.1')

    throttle.record_success('10.0.0.1')

    assert throttle.record_failure('10.0.0.1') == 0
    assert not throttle.is_locked('10.0.0.1')


def test_failures_spread_beyond_the_window_do_not_accumulate():
    clock = FakeClock()
    throttle = make_throttle(clock, max_attempts=2, window_seconds=300)

    throttle.record_failure('10.0.0.1')
    clock.advance(301)

    assert throttle.record_failure('10.0.0.1') == 0
    assert not throttle.is_locked('10.0.0.1')


def test_clients_are_tracked_independently():
    throttle = make_throttle(FakeClock(), max_attempts=2)

    throttle.record_failure('10.0.0.1')
    throttle.record_failure('10.0.0.1')

    assert throttle.is_locked('10.0.0.1')
    assert not throttle.is_locked('10.0.0.2')
