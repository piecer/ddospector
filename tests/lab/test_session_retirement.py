"""Remaining lifecycle boundary and persistence combinations."""
import json
import os
import stat
import threading
from types import SimpleNamespace

import pytest
from test_session import admit, configured, error
from test_session import clock as clock

from aiddos.lab import profile, session


@pytest.mark.parametrize('phase', ['validation', 'acquisition'])
def test_admission_clock_origin_precedes_all_work(tmp_path, clock, monkeypatch, phase):
    fired = []
    real_evaluate, real_open = profile.evaluate, session._open

    def evaluate(raw):
        result = real_evaluate(raw)
        if phase == 'validation':
            clock[0] = 30.0
            fired.append(phase)
        return result

    def open_fd(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        if phase == 'acquisition' and kwargs.get('dir_fd') is None:
            clock[0] = 30.0
            fired.append(phase)
        return fd

    monkeypatch.setattr(profile, 'evaluate', evaluate)
    monkeypatch.setattr(session, '_open', open_fd)
    error('EXPIRED', lambda: admit(tmp_path))
    assert fired == [phase]


@pytest.mark.parametrize('early', ['stop', 'expired'])
def test_pre_attempt_control_spends_nothing(tmp_path, clock, early):
    owner = admit(tmp_path)
    calls = []
    if early == 'stop':
        owner.request_stop()
    else:
        clock[0] = 30.0
    code = 'CANCELLED' if early == 'stop' else 'EXPIRED'
    error(code, lambda: owner.run_attempt(lambda permit: calls.append(permit)))
    assert calls == []
    assert owner.snapshot()['attempts_admitted'] == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ['baseline-claim.json']
    assert owner.finish()['code'] == code


@pytest.mark.parametrize('primary', ['fstat', 'mode', 'uid', 'not-directory'])
def test_preclaim_primary_survives_root_close_error(tmp_path, monkeypatch, primary):
    fired, opened, closed = [], [], []
    real_open = session._open

    def open_fd(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        opened.append(fd)
        return fd

    def fstat(fd):
        fired.append(primary)
        real = os.fstat(fd)
        if primary == 'fstat':
            raise OSError('PRIVATE_SENTINEL')
        return SimpleNamespace(st_mode=(stat.S_IFREG | 0o600 if primary == 'not-directory'
            else real.st_mode | (0o040 if primary == 'mode' else 0)),
            st_uid=real.st_uid + (1 if primary == 'uid' else 0))

    def close(fd):
        os.close(fd)
        closed.append(fd)
        fired.append('close')
        raise OSError('PRIVATE_SENTINEL')

    monkeypatch.setattr(session, '_open', open_fd)
    monkeypatch.setattr(session, '_fstat', fstat)
    monkeypatch.setattr(session, '_close', close)
    failure = error('STATE_DIRECTORY_IO_ERROR' if primary == 'fstat'
                    else 'STATE_DIRECTORY_INVALID', lambda: admit(tmp_path))
    assert failure.cleanup_uncertain is True
    assert fired == [primary, 'close'] and closed == opened and len(opened) == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('leaf', ['attempt-1-start.json', 'attempt-1-end.json', 'terminal.json'])
@pytest.mark.parametrize('kind', ['file', 'directory', 'symlink'])
def test_record_collisions_are_retained_and_fail_closed(tmp_path, clock, leaf, kind):
    owner = admit(tmp_path, max_attempts=1)
    path = tmp_path / leaf
    if kind == 'file':
        path.write_bytes(b'PRIVATE_SENTINEL')
    elif kind == 'directory':
        path.mkdir()
    else:
        path.symlink_to('missing')
    before = path.lstat()
    calls = []
    if leaf == 'terminal.json':
        assert owner.run_attempt(lambda permit: calls.append(permit)) == 1
    else:
        failure = error('RECORD_IO_ERROR', lambda: owner.run_attempt(
            lambda permit: calls.append(permit)))
        assert failure.cleanup_uncertain is True
    result = owner.finish()
    assert result['state'] == 'UNCERTAIN' and result['code'] == 'RECORD_IO_ERROR'
    assert result['retired'] is True and result['cleanup_uncertain'] is True
    assert len(calls) == (0 if leaf == 'attempt-1-start.json' else 1)
    after = path.lstat()
    assert (before.st_ino, before.st_mode, before.st_size, before.st_mtime_ns) == (
        after.st_ino, after.st_mode, after.st_size, after.st_mtime_ns)
    if kind == 'file':
        assert path.read_bytes() == b'PRIVATE_SENTINEL'
    assert owner.close() is False


def test_partial_success_durable_exact_records_and_no_fs_under_lock(tmp_path, clock, monkeypatch):
    real_open = session._open
    opened, fsynced, closed, writes = [], [], [], []
    owner_ref = []

    def outside_lock():
        if owner_ref:
            assert owner_ref[0]._lock.acquire(blocking=False)
            owner_ref[0]._lock.release()

    def open_fd(name, flags, *args, **kwargs):
        outside_lock()
        fd = real_open(name, flags, *args, **kwargs)
        opened.append((fd, name, os.fstat(fd).st_ino))
        if kwargs:
            assert flags & (os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC) == (
                os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC)
        return fd

    def write(fd, data):
        outside_lock()
        writes.append(len(data))
        return os.write(fd, data[:19])

    def fsync(fd):
        outside_lock()
        fsynced.append((stat.S_ISDIR(os.fstat(fd).st_mode), os.fstat(fd).st_ino))
        os.fsync(fd)

    def close(fd):
        outside_lock()
        closed.append(os.fstat(fd).st_ino)
        os.close(fd)

    monkeypatch.setattr(session, '_open', open_fd)
    monkeypatch.setattr(session, '_write', write)
    monkeypatch.setattr(session, '_fsync', fsync)
    monkeypatch.setattr(session, '_close', close)
    owner = admit(tmp_path, max_attempts=1)
    owner_ref.append(owner)
    assert owner.run_attempt(lambda permit: None) == 1
    result = owner.finish()
    assert result['state'] == 'COMPLETED'
    root_inode = opened[0][2]
    assert len(opened) == 5
    assert closed == [v[2] for v in opened[1:]] + [root_inode]
    assert fsynced == [item for v in opened[1:] for item in
                      ((False, v[2]), (True, root_inode))]
    assert len(writes) > 4 and all(n <= 4096 for n in writes)
    digest = configured(max_attempts=1)[1]
    assert json.loads((tmp_path / 'attempt-1-start.json').read_bytes()) == dict(
        schema_version=1, kind='ATTEMPT_START', profile_sha256=digest, attempt=1)
    assert json.loads((tmp_path / 'attempt-1-end.json').read_bytes()) == dict(
        schema_version=1, kind='ATTEMPT_END', profile_sha256=digest, attempt=1,
        outcome='RETURNED', callback_started=True)


@pytest.mark.parametrize('fault', ['end', 'terminal', 'root-close'])
def test_baseexception_survives_close_pending_secondary_failure(
    tmp_path, clock, monkeypatch, fault,
):
    owner = admit(tmp_path)
    real_write = session._write
    fired, permits = [], []
    original = KeyboardInterrupt('PRIVATE_SENTINEL')

    def write(fd, data):
        if json.loads(data)['kind'] == {'end': 'ATTEMPT_END',
                                       'terminal': 'RETIREMENT_INTENT'}.get(fault):
            fired.append(fault)
            raise OSError('PRIVATE_SENTINEL')
        return real_write(fd, data)

    def close(fd):
        directory = stat.S_ISDIR(os.fstat(fd).st_mode)
        os.close(fd)
        if directory and fault == 'root-close':
            fired.append(fault)
            raise OSError('PRIVATE_SENTINEL')

    def action(permit):
        permits.append(permit)
        assert owner.close() is False
        raise original

    monkeypatch.setattr(session, '_write', write)
    monkeypatch.setattr(session, '_close', close)
    with pytest.raises(KeyboardInterrupt) as caught:
        owner.run_attempt(action)
    assert caught.value is original
    error('PERMIT_RETIRED', permits[0].checkpoint)
    assert fired == [fault]
    assert owner.snapshot()['retired'] is True
    assert owner.snapshot()['code'] == 'ACTION_FAILED'
    assert owner.snapshot()['cleanup_uncertain'] is True
    assert owner.finish() == owner.snapshot()


def test_root_close_barrier_keeps_single_finalizer_and_stop_live(tmp_path, clock, monkeypatch):
    owner = admit(tmp_path, max_attempts=1)
    owner.run_attempt(lambda permit: None)
    reached, release, controlled = threading.Event(), threading.Event(), threading.Event()
    results, failures, root_closes = [], [], []

    def close(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            root_closes.append(fd)
            reached.set()
            assert release.wait(5)
        os.close(fd)

    def finish():
        try:
            results.append(owner.finish())
        except BaseException as exc:
            failures.append(exc)

    def control():
        try:
            assert owner.snapshot()['retired'] is False
            error('SESSION_BUSY', owner.finish)
            assert owner.close() is False
            owner.request_stop()
            assert owner.snapshot()['stop_requested'] is True
        except BaseException as exc:
            failures.append(exc)
        finally:
            controlled.set()

    monkeypatch.setattr(session, '_close', close)
    worker, controller = threading.Thread(target=finish), threading.Thread(target=control)
    worker.start()
    try:
        assert reached.wait(5)
        controller.start()
        assert controlled.wait(2), 'root close blocked state coordination'
    finally:
        release.set()
        worker.join(5)
        if controller.ident is not None:
            controller.join(5)
    assert not worker.is_alive() and not controller.is_alive()
    assert failures == [] and len(root_closes) == 1
    assert results[0]['state'] == 'CANCELLED' and results[0]['retired'] is True
    assert owner.finish() == results[0]
