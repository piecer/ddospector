"""Admission syntax, actual inode lifetime, and fired syscall-failure regressions."""
import json
import os
import stat
import sys

import pytest
from test_session import admit, configured, error
from test_session import clock as clock

from aiddos.lab import profile, session


@pytest.mark.parametrize('value', [None, 1, b'/tmp', '', 'relative', '//root', '/a//b',
    '/a/./b', '/a/../b', '/a/', '/a/.', '/a/..', '/a\x00b', '/\ud800',
    '/' + 'x' * 4096, '/' + 'é' * 2048, '/' + 'x' * 1_000_000],
    ids=[f'path-{n}' for n in range(17)])
def test_b4_directory_input_rejected_before_os(tmp_path, monkeypatch, value):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(args)
        raise AssertionError('OS reached for invalid input')

    monkeypatch.setattr(session, '_open', forbidden)
    monkeypatch.setattr(session, '_stat', forbidden)
    error('STATE_DIRECTORY_INVALID', lambda: session.SessionOwner.admit(*configured(), value))
    assert calls == [] and list(tmp_path.iterdir()) == []


def test_character_cap_precedes_encoding_with_positive_control(tmp_path, monkeypatch):
    huge = '/' + 'x' * 1_000_000
    bounded = '/' + 'x' * 4095
    encoded, opened = [], []
    previous = sys.getprofile()

    def observer(frame, event, arg):
        if (event == 'c_call' and frame.f_code.co_name == '_directory_input'
                and getattr(arg, '__name__', '') == 'encode'):
            encoded.append(len(arg.__self__))

    def refused_open(*args, **kwargs):
        opened.append(args[0])
        raise OSError('PRIVATE_SENTINEL')

    def absent_stat(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(session, '_open', refused_open)
    monkeypatch.setattr(session, '_stat', absent_stat)
    sys.setprofile(observer)
    try:
        error('STATE_DIRECTORY_INVALID', lambda: session.SessionOwner.admit(*configured(), huge))
        assert encoded == [] and opened == []
        error('STATE_DIRECTORY_IO_ERROR',
              lambda: session.SessionOwner.admit(*configured(), bounded))
    finally:
        sys.setprofile(previous)
    assert encoded == [4096] and opened == [bounded]


def test_exact_types_before_encode_or_path_protocol(tmp_path):
    class String(str):
        def encode(self, *args):
            raise AssertionError('subclass encoding invoked')

    class PathLike:
        def __fspath__(self):
            raise AssertionError('path protocol invoked')

    for value in (String(str(tmp_path)), PathLike()):
        error('STATE_DIRECTORY_INVALID',
              lambda v=value: session.SessionOwner.admit(*configured(), v))
    error('APPROVAL_REQUIRED', lambda: session.SessionOwner.admit(
        configured()[0], String(configured()[1]), str(tmp_path)))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('case,code', [('file', 'STATE_DIRECTORY_INVALID'),
    ('symlink', 'STATE_DIRECTORY_INVALID'), ('mode', 'STATE_DIRECTORY_INVALID'),
    ('uid', 'STATE_DIRECTORY_INVALID'), ('missing', 'STATE_DIRECTORY_IO_ERROR'),
    ('fstat', 'STATE_DIRECTORY_IO_ERROR'), ('unsupported', 'UNSUPPORTED_PLATFORM')])
def test_actual_directory_checks_and_single_retirement(tmp_path, monkeypatch, case, code):
    path = tmp_path / 'state'
    target = tmp_path / 'target'
    target.mkdir(mode=0o700)
    if case == 'file':
        path.write_bytes(b'caller')
    elif case == 'symlink':
        path.symlink_to(target)
    elif case != 'missing':
        path.mkdir(mode=0o700)
    if case == 'mode':
        path.chmod(0o750)
    elif case == 'uid':
        uid = os.geteuid()
        monkeypatch.setattr(os, 'geteuid', lambda: uid + 1)
    elif case == 'unsupported':
        monkeypatch.setattr(os, 'supports_dir_fd', set())
    opened, closed, fired = [], [], []
    real_open, real_fstat = session._open, session._fstat

    def open_fd(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        opened.append(fd)
        assert not os.get_inheritable(fd)
        return fd

    def fstat(fd):
        if case == 'fstat':
            fired.append('fstat')
            raise OSError('PRIVATE_SENTINEL')
        return real_fstat(fd)

    def close(fd):
        assert sys._getframe(1).f_locals['self']._fd is None
        closed.append(fd)
        os.close(fd)

    monkeypatch.setattr(session, '_open', open_fd)
    monkeypatch.setattr(session, '_fstat', fstat)
    monkeypatch.setattr(session, '_close', close)
    error(code, lambda: admit(path))
    assert opened == closed
    assert len(opened) == (1 if case in ('mode', 'uid', 'fstat') else 0)
    assert fired == (['fstat'] if case == 'fstat' else [])
    assert list(target.iterdir()) == []
    if case == 'file':
        assert path.read_bytes() == b'caller'
    elif case == 'symlink':
        assert path.is_symlink()


@pytest.mark.parametrize('kind', ['file', 'directory', 'symlink', 'identical'])
def test_claim_collision_never_inspects_or_changes_entry(tmp_path, kind):
    leaf = tmp_path / 'baseline-claim.json'
    target = tmp_path / 'caller'
    target.write_bytes(b'PRIVATE_SENTINEL')
    if kind == 'directory':
        leaf.mkdir()
    elif kind == 'symlink':
        leaf.symlink_to(target)
    else:
        data = (profile.canonical(dict(schema_version=1, kind='BASELINE_SESSION_CLAIM',
            profile_sha256=configured()[1], budget=json.loads(configured()[0])['budget'])) + b'\n'
            if kind == 'identical' else b'caller')
        leaf.write_bytes(data)
    before = leaf.lstat()
    error('SESSION_ALREADY_USED', lambda: admit(tmp_path))
    after = leaf.lstat()
    assert (before.st_ino, before.st_mode, before.st_size, before.st_mtime_ns) == (
        after.st_ino, after.st_mode, after.st_size, after.st_mtime_ns)
    if kind in ('file', 'identical'):
        assert leaf.read_bytes() == data
    assert target.read_bytes() == b'PRIVATE_SENTINEL'


@pytest.mark.parametrize('phase', ['before-attempt', 'after-start', 'after-end', 'terminal'])
def test_pinned_root_replacement_preserves_both_directories(tmp_path, clock, monkeypatch, phase):
    path = tmp_path / 'state'
    path.mkdir(mode=0o700)
    moved = tmp_path / 'old'
    captured = []
    real_open, real_write = session._open, session._write

    def open_fd(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        if str(args[0]) == str(path):
            captured.append((fd, os.fstat(fd)))
        return fd

    monkeypatch.setattr(session, '_open', open_fd)
    owner = admit(path)
    calls, fired = [], []

    def replace():
        fired.append(phase)
        path.rename(moved)
        path.mkdir(mode=0o700)
        (path / 'caller').write_bytes(b'PRIVATE_SENTINEL')
        assert os.fstat(captured[0][0]).st_ino == captured[0][1].st_ino

    def write(fd, data):
        result = real_write(fd, data)
        if json.loads(data)['kind'] == {'after-start': 'ATTEMPT_START',
                'after-end': 'ATTEMPT_END', 'terminal': 'RETIREMENT_INTENT'}.get(phase):
            replace()
        return result

    monkeypatch.setattr(session, '_write', write)
    if phase == 'before-attempt':
        replace()
    if phase == 'terminal':
        assert owner.run_attempt(lambda permit: calls.append(permit)) == 1
    else:
        error('OWNERSHIP_LOST', lambda: owner.run_attempt(lambda permit: calls.append(permit)))
    result = owner.finish()
    assert result['code'] == 'OWNERSHIP_LOST' and result['retired'] is True
    assert fired == [phase]
    assert len(calls) == (1 if phase in ('after-end', 'terminal') else 0)
    assert (path / 'caller').read_bytes() == b'PRIVATE_SENTINEL'
    assert sorted(p.name for p in path.iterdir()) == ['caller']
    assert (moved / 'baseline-claim.json').is_file()
    with pytest.raises(OSError):
        os.fstat(captured[0][0])


@pytest.mark.parametrize('fault', ['partial', 'zero', 'file-fsync', 'file-close', 'dir-fsync'])
@pytest.mark.parametrize('root_close_fails', [False, True])
def test_failed_claim_consumed_and_single_close(tmp_path, monkeypatch, fault, root_close_fails):
    real_open, real_write = session._open, session._write
    opened, closed, fired = [], [], []
    root_fd = []
    leaf_fd = []

    def open_fd(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        opened.append(fd)
        (leaf_fd if kwargs.get('dir_fd') is not None else root_fd).append(fd)
        return fd

    def write(fd, data):
        if fault == 'partial':
            if not fired:
                fired.append('partial')
                return real_write(fd, data[:17])
            raise OSError('PRIVATE_SENTINEL')
        if fault == 'zero':
            fired.append('zero')
            return 0
        return real_write(fd, data)

    def fsync(fd):
        target = 'dir-fsync' if fd == root_fd[0] else 'file-fsync'
        if target == fault:
            fired.append(target)
            raise OSError('PRIVATE_SENTINEL')
        os.fsync(fd)

    def close(fd):
        frame = sys._getframe(1)
        assert (frame.f_locals['self']._fd is None if fd == root_fd[0]
                else frame.f_locals['fd'] is None)
        closed.append(fd)
        os.close(fd)
        target = 'root-close' if fd == root_fd[0] else 'file-close'
        if target == fault or (target == 'root-close' and root_close_fails):
            fired.append(target)
            raise OSError('PRIVATE_SENTINEL')

    with monkeypatch.context() as patcher:
        patcher.setattr(session, '_open', open_fd)
        patcher.setattr(session, '_write', write)
        patcher.setattr(session, '_fsync', fsync)
        patcher.setattr(session, '_close', close)
        failure = error('RECORD_IO_ERROR', lambda: admit(tmp_path))
        assert failure.cleanup_uncertain is True
    assert opened == root_fd + leaf_fd and closed == leaf_fd + root_fd
    assert fired == [fault] + (['root-close'] if root_close_fails else [])
    raw = (tmp_path / 'baseline-claim.json').read_bytes()
    assert len(raw) <= 4096
    if fault in ('partial', 'zero'):
        assert len(raw) == (17 if fault == 'partial' else 0)
    error('SESSION_ALREADY_USED', lambda: admit(tmp_path))
    assert (tmp_path / 'baseline-claim.json').read_bytes() == raw


@pytest.mark.parametrize('primary', ['none', 'ordinary', 'cancel', 'base'])
@pytest.mark.parametrize('fault', ['end', 'terminal', 'root-close'])
def test_primary_precedence_uncertainty_and_settlement(
    tmp_path, clock, monkeypatch, primary, fault,
):
    owner = admit(tmp_path, max_attempts=1)
    real_write, real_close = session._write, session._close
    fired, closed, permits = [], [], []
    original = SystemExit('PRIVATE_SENTINEL')
    replacement = []

    def write(fd, data):
        kind = json.loads(data)['kind']
        if kind == {'end': 'ATTEMPT_END', 'terminal': 'RETIREMENT_INTENT'}.get(fault):
            fired.append(fault)
            raise OSError('PRIVATE_SENTINEL')
        return real_write(fd, data)

    def close(fd):
        is_root = stat.S_ISDIR(os.fstat(fd).st_mode)
        real_close(fd)
        if is_root:
            closed.append(fd)
            assert owner._fd is None
            if fault == 'root-close':
                fired.append(fault)
                # Prove the ambiguous close is not retried against a reused number.
                new = os.open(tmp_path / 'verifier-fd', os.O_CREAT | os.O_RDWR, 0o600)
                assert new == fd
                replacement.append(new)
                raise OSError('PRIVATE_SENTINEL')

    def action(permit):
        permits.append(permit)
        if primary == 'ordinary':
            owner.request_stop()
            raise RuntimeError('PRIVATE_SENTINEL')
        if primary == 'cancel':
            owner.request_stop()
            permit.checkpoint()
        if primary == 'base':
            raise original

    monkeypatch.setattr(session, '_write', write)
    monkeypatch.setattr(session, '_close', close)
    expected = {'ordinary': 'ACTION_FAILED', 'base': 'ACTION_FAILED',
                'cancel': 'CANCELLED'}.get(primary)
    if primary == 'base':
        with pytest.raises(SystemExit) as caught:
            owner.run_attempt(action)
        assert caught.value is original
    elif expected or fault == 'end':
        error(expected or 'RECORD_IO_ERROR', lambda: owner.run_attempt(action))
    else:
        assert owner.run_attempt(action) == 1
    error('PERMIT_RETIRED', permits[0].checkpoint)
    settled = owner.finish()
    assert settled['code'] == (expected or ('RETIREMENT_UNCERTAIN' if fault == 'root-close'
                                           else 'RECORD_IO_ERROR'))
    assert settled['cleanup_uncertain'] is True and settled['retired'] is True
    assert settled['state'] == ({'ordinary': 'FAILED', 'base': 'FAILED',
                                'cancel': 'CANCELLED'}.get(primary, 'UNCERTAIN'))
    clock[0] = 999.0
    assert owner.finish() == settled
    assert owner.close() is False
    assert owner.request_stop() is None
    assert owner.snapshot() == settled
    assert fired == [fault] and len(closed) == 1
    for fd in replacement:
        assert stat.S_ISREG(os.fstat(fd).st_mode)
        os.close(fd)
