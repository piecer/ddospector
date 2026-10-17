"""Deterministic clock and real thread schedules for B1/B2/B3."""
import json
import os
import threading

import pytest
from test_session import admit, error
from test_session import clock as clock

from aiddos.lab import session


def test_b1_delayed_entry_interval_and_no_refund(tmp_path, clock, monkeypatch):
    owner = admit(tmp_path)
    writes = []
    real = session._write

    def delayed(fd, data):
        if json.loads(data)['kind'] == 'ATTEMPT_START' and not writes:
            writes.append('first-start')
            clock[0] = 0.9
        return real(fd, data)

    monkeypatch.setattr(session, '_write', delayed)
    observed = []

    def action(permit):
        observed.append((clock[0], permit.deadline))

    assert owner.run_attempt(action) == 1
    before = owner.snapshot()
    leaves = sorted(p.name for p in tmp_path.iterdir())
    for early in (1.0, 1.899999):
        clock[0] = early
        error('RATE_LIMITED', lambda: owner.run_attempt(action))
        assert owner.snapshot() == before
        assert sorted(p.name for p in tmp_path.iterdir()) == leaves
    clock[0] = 1.9
    assert owner.run_attempt(action) == 2
    assert observed == [(0.9, 3.0), (1.9, 4.9)]
    assert writes == ['first-start']
    assert owner.finish()['state'] == 'INCOMPLETE'


@pytest.mark.parametrize('phase,at,expected_started', [
    ('claim', 30.0, 0), ('start', 3.0, 0), ('start', 3.000001, 0),
    ('callback', 3.0, 1), ('end', 3.0, 1), ('terminal', 30.0, 1),
    ('root-close', 30.0, 1),
])
def test_original_deadline_through_io(tmp_path, clock, monkeypatch, phase, at, expected_started):
    fired = []
    real_write, real_close = session._write, session._close
    kinds = {'claim': 'BASELINE_SESSION_CLAIM', 'start': 'ATTEMPT_START',
             'end': 'ATTEMPT_END', 'terminal': 'RETIREMENT_INTENT'}

    def write(fd, data):
        result = real_write(fd, data)
        if json.loads(data)['kind'] == kinds.get(phase):
            fired.append(phase)
            clock[0] = at
        return result

    def close(fd):
        directory = os.path.isdir(f'/proc/self/fd/{fd}')
        real_close(fd)
        if phase == 'root-close' and directory:
            fired.append(phase)
            clock[0] = at

    monkeypatch.setattr(session, '_write', write)
    monkeypatch.setattr(session, '_close', close)
    calls = []
    if phase == 'claim':
        error('EXPIRED', lambda: admit(tmp_path, max_attempts=1))
    else:
        owner = admit(tmp_path, max_attempts=1)

        def action(permit):
            calls.append(permit)
            if phase == 'callback':
                fired.append(phase)
                clock[0] = at

        if phase in ('start', 'callback', 'end'):
            error('EXPIRED', lambda: owner.run_attempt(action))
            assert owner.snapshot()['attempts_admitted'] == 1
            assert owner.snapshot()['attempts_completed'] == 0
            end = json.loads((tmp_path / 'attempt-1-end.json').read_bytes())
            assert end['outcome'] == ('RETURNED' if phase == 'end' else 'EXPIRED')
        else:
            assert owner.run_attempt(action) == 1
        assert owner.finish()['code'] == 'EXPIRED'
        assert owner.snapshot()['retired'] is True
        assert owner.finish()['state'] == 'EXPIRED'
    assert fired == [phase]
    assert len(calls) == expected_started


@pytest.mark.parametrize('phase', ['start', 'callback', 'end', 'terminal'])
def test_b3_io_barriers_stop_snapshot_and_single_finalizer(tmp_path, clock, monkeypatch, phase):
    owner = admit(tmp_path, max_attempts=1)
    reached, release, controls_done = threading.Event(), threading.Event(), threading.Event()
    events, results, calls, failures = [], [], [], []
    real_write, real_close = session._write, session._close
    kinds = {'start': 'ATTEMPT_START', 'end': 'ATTEMPT_END', 'terminal': 'RETIREMENT_INTENT'}

    def barrier():
        reached.set()
        assert release.wait(5), 'verifier release missing'

    def write(fd, data):
        kind = json.loads(data)['kind']
        events.append(kind)
        if kind == kinds.get(phase):
            barrier()
        return real_write(fd, data)

    def close(fd):
        if os.path.isdir(f'/proc/self/fd/{fd}'):
            events.append('ROOT_CLOSE')
        real_close(fd)

    def action(permit):
        calls.append(permit)
        if phase == 'callback':
            barrier()

    def work():
        try:
            if phase == 'terminal':
                assert owner.run_attempt(action) == 1
                results.append(owner.finish())
            else:
                results.append(error('CANCELLED', lambda: owner.run_attempt(action)))
        except BaseException as exc:
            failures.append(exc)

    def controls():
        try:
            assert owner.snapshot()['retired'] is False
            assert owner.snapshot()['active'] is (phase != 'terminal')
            error('SESSION_BUSY', owner.finish)
            error('SESSION_BUSY', lambda: owner.run_attempt(action))
            assert owner.request_stop() is None
            assert owner.close() is False
            assert owner.snapshot()['stop_requested'] is True
            assert 'ROOT_CLOSE' not in events
        except BaseException as exc:
            failures.append(exc)
        finally:
            controls_done.set()

    monkeypatch.setattr(session, '_write', write)
    monkeypatch.setattr(session, '_close', close)
    worker = threading.Thread(target=work)
    controller = threading.Thread(target=controls)
    worker.start()
    try:
        assert reached.wait(5), 'phase barrier did not fire'
        controller.start()
        assert controls_done.wait(2), 'coordinator blocked by filesystem/callback latency'
    finally:
        release.set()
        worker.join(5)
        if controller.ident is not None:
            controller.join(5)
    assert not worker.is_alive() and not controller.is_alive()
    assert failures == []
    assert len(results) == 1
    assert len(calls) == (0 if phase == 'start' else 1)
    assert events.count('ROOT_CLOSE') == events.count('RETIREMENT_INTENT') == 1
    settled = owner.snapshot()
    assert settled['retired'] is True and settled['active'] is False
    assert settled['code'] == 'CANCELLED'
    before = events[:]
    clock[0] = 999.0
    assert owner.finish() == settled
    assert owner.close() is True
    assert owner.request_stop() is None
    assert owner.snapshot() == settled and events == before


def test_actual_entry_clock_is_the_checked_deadline(tmp_path, clock, monkeypatch):
    import sys

    owner = admit(tmp_path)
    persisted, fired, calls = [], [], []
    real_write = session._write

    def write(fd, data):
        result = real_write(fd, data)
        if json.loads(data)['kind'] == 'ATTEMPT_START':
            persisted.append(True)
        return result

    def ticking_clock():
        # Inject at the direct entry-time observation, not at reservation or
        # an earlier helper check. This semantic selector must keep firing.
        frame = sys._getframe(1)
        if persisted and frame.f_code.co_name == 'run_attempt' and not fired:
            fired.append('actual-entry-clock')
            clock[0] = 3.0
        return clock[0]

    monkeypatch.setattr(session, '_write', write)
    monkeypatch.setattr(session, '_clock', ticking_clock)
    error('EXPIRED', lambda: owner.run_attempt(lambda permit: calls.append(permit)))
    assert fired == ['actual-entry-clock'] and calls == []
    assert owner.snapshot()['callbacks_started'] == 0
    assert owner.snapshot()['attempts_admitted'] == 1
    assert owner.finish()['code'] == 'EXPIRED'


def test_completed_attempt_result_not_reclassified_by_next_caller(tmp_path, clock):
    import sys

    owner = admit(tmp_path)
    released, proceed = threading.Event(), threading.Event()
    results, failures, fired = [], [], []
    actual_lock = threading.Lock()

    class ReleaseBarrier:
        def __enter__(self):
            actual_lock.acquire()

        def __exit__(self, *args):
            should_pause = (sys._getframe(1).f_code.co_name == 'run_attempt'
                            and not owner._active and owner._completed == 1
                            and owner._admitted == 1 and not fired)
            if should_pause:
                fired.append(True)
            actual_lock.release()
            if should_pause:
                released.set()
                assert proceed.wait(5)

    owner._lock = ReleaseBarrier()

    def first():
        try:
            results.append(owner.run_attempt(lambda permit: None))
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=first)
    thread.start()
    try:
        assert released.wait(5)
        clock[0] = 1.0
        error('ACTION_FAILED', lambda: owner.run_attempt(lambda permit: 'not-None'))
    finally:
        proceed.set()
        thread.join(5)
    assert not thread.is_alive() and fired == [True]
    assert results == [1] and failures == []
    assert owner.finish()['code'] == 'ACTION_FAILED'


def test_late_reservation_spends_nothing(tmp_path, clock, monkeypatch):
    import sys

    owner = admit(tmp_path)
    fired, calls = [], []

    def clock_at_reservation():
        # The direct run_attempt observation after its identity check is the
        # reservation clock; initial gates call through _control.
        frame = sys._getframe(1)
        if frame.f_code.co_name == 'run_attempt' and not fired:
            fired.append('reservation')
            clock[0] = 30.0
        return clock[0]

    monkeypatch.setattr(session, '_clock', clock_at_reservation)
    error('EXPIRED', lambda: owner.run_attempt(lambda permit: calls.append(permit)))
    assert fired == ['reservation'] and calls == []
    assert owner.snapshot()['attempts_admitted'] == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ['baseline-claim.json']
    assert owner.finish()['code'] == 'EXPIRED'


def test_reentrant_close_latches_state_and_defers_retirement(tmp_path, clock):
    owner = admit(tmp_path)
    observations = []

    def action(permit):
        assert owner.close() is False
        observations.append(owner.snapshot())
        permit.checkpoint()

    error('CANCELLED', lambda: owner.run_attempt(action))
    assert observations[0]['state'] == 'STOP_REQUESTED'
    assert observations[0]['active'] is True and observations[0]['retired'] is False
    assert owner.finish()['retired'] is True


def test_cancel_wins_when_current_expiry_control_returns_after_stop(tmp_path, clock):
    owner = admit(tmp_path)

    def action(permit):
        clock[0] = 3.0
        try:
            permit.checkpoint()
        except session.SessionError:
            owner.request_stop()
            raise

    error('CANCELLED', lambda: owner.run_attempt(action))
    assert json.loads((tmp_path / 'attempt-1-end.json').read_bytes())['outcome'] == 'CANCELLED'
    assert owner.finish()['state'] == 'CANCELLED'


def test_old_permit_cannot_supply_current_control(tmp_path, clock):
    owner = admit(tmp_path)
    old = []
    owner.run_attempt(lambda permit: old.append(permit))
    clock[0] = 1.0
    error('ACTION_FAILED', lambda: owner.run_attempt(lambda permit: old[0].checkpoint()))
    assert owner.finish()['code'] == 'ACTION_FAILED'
