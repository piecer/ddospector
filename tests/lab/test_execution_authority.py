"""Execution-authority admission, not transport or physical-stop acceptance."""

import copy
import json
import os
import sys

import pytest
from authority_support import arguments, document
from test_session import configured

from aiddos.lab import session


def test_profile_confirmation_alone_cannot_admit_callback(tmp_path):
    raw, confirmation = configured(max_attempts=1)
    owner = None
    callbacks = []
    try:
        try:
            owner = session.SessionOwner.admit(raw, confirmation, str(tmp_path))
        except session.SessionError as failure:
            assert failure.code == 'AUTHORITY_REQUIRED'
            assert list(tmp_path.iterdir()) == []
        else:
            owner.run_attempt(lambda permit: callbacks.append(permit.attempt))
            pytest.fail(f'Profile-only approval reached callback: {callbacks}')
    finally:
        if owner is not None:
            owner.close()
    assert callbacks == []


def refuse(raw, confirmation, directory, inputs, code):
    owner = None
    try:
        with pytest.raises(session.SessionError) as caught:
            owner = session.SessionOwner.admit(raw, confirmation, str(directory), **inputs)
        assert caught.value.code == code
        assert caught.value.__cause__ is None
        assert caught.value.cleanup_uncertain is False
    finally:
        if owner is not None:
            owner.close()


def test_exact_authority_binds_all_v2_records_without_mutating_inputs(tmp_path):
    raw, confirmation = configured(max_attempts=1)
    value = document(raw, tmp_path)
    inputs = arguments(value)
    before = copy.deepcopy(inputs)
    owner = session.SessionOwner.admit(raw, confirmation, str(tmp_path), **inputs)
    try:
        assert owner.snapshot()['schema_version'] == 2
        assert owner.snapshot()['authority_sha256'] == inputs['confirmed_authority_sha256']
        assert inputs == before
        inputs['site_binding']['site_id'] = 'caller-changed-after-admission'
        assert owner.run_attempt(lambda permit: permit.checkpoint()) == 1
        assert owner.finish()['state'] == 'COMPLETED'
        for path in tmp_path.iterdir():
            record = json.loads(path.read_bytes())
            assert record['schema_version'] == 2
            assert record['authority_sha256'] == before['confirmed_authority_sha256']
            assert len(path.read_bytes()) <= 4096
            assert b'fixture-site' not in path.read_bytes()
            assert b'PRIVATE_SENTINEL' not in path.read_bytes()
        refuse(raw, confirmation, tmp_path, before, 'SESSION_ALREADY_USED')
    finally:
        owner.close()


@pytest.mark.parametrize('fault,code', [
    ('document', 'INVALID_AUTHORITY'), ('scope', 'INVALID_AUTHORITY'),
    ('confirmation', 'AUTHORITY_MISMATCH'), ('profile', 'AUTHORITY_MISMATCH'),
    ('budget', 'AUTHORITY_MISMATCH'), ('site', 'AUTHORITY_MISMATCH'),
    ('directory', 'AUTHORITY_MISMATCH'), ('device', 'AUTHORITY_MISMATCH'),
    ('inode', 'AUTHORITY_MISMATCH'), ('expired', 'EXPIRED'),
])
def test_rejects_unconfirmed_foreign_or_expired_authority_before_claim(tmp_path, fault, code):
    raw, confirmation = configured(max_attempts=1)
    value = document(raw, tmp_path)
    if fault == 'scope':
        value['scope'] = 'LIVE'
    elif fault == 'profile':
        value['profile_sha256'] = '0' * 64
    elif fault == 'budget':
        value['budget']['max_attempts'] = 2
    elif fault == 'site':
        value['site']['site_id'] = 'different-site'
    elif fault == 'directory':
        value['owner']['state_directory'] = str(tmp_path / 'different')
    elif fault in ('device', 'inode'):
        value['owner']['st_dev' if fault == 'device' else 'st_ino'] += 1
    elif fault == 'expired':
        value.update(not_before_unix_ms=0, expires_unix_ms=1)
    inputs = arguments(value)
    if fault == 'document':
        inputs['raw_authority'] = b'{}'
    elif fault == 'confirmation':
        inputs['confirmed_authority_sha256'] = '0' * 64
    refuse(raw, confirmation, tmp_path, inputs, code)
    assert list(tmp_path.iterdir()) == []


@pytest.fixture
def authority_clock(monkeypatch):
    now = dict(mono=100.0, wall=1000000)
    monkeypatch.setattr(session, '_clock', lambda: now['mono'])
    monkeypatch.setattr(session, '_wall_ms', lambda: now['wall'])
    return now


@pytest.mark.parametrize('wall,code', [
    (999, 'AUTHORITY_NOT_YET_VALID'), (1000, None), (1999, None),
    (2000, 'EXPIRED'), (2001, 'EXPIRED'),
])
def test_authority_window_exact_boundaries(tmp_path, authority_clock, wall, code):
    raw, confirmation = configured(max_attempts=1)
    value = document(raw, tmp_path, now_ms=2000)
    value.update(not_before_unix_ms=1000, expires_unix_ms=2000)
    inputs = arguments(value)
    authority_clock['wall'] = wall
    if code:
        refuse(raw, confirmation, tmp_path, inputs, code)
        assert list(tmp_path.iterdir()) == []
    else:
        owner = session.SessionOwner.admit(raw, confirmation, str(tmp_path), **inputs)
        assert owner.close() is True


@pytest.mark.parametrize('phase', ['idle', 'start', 'actual-entry', 'callback',
                                  'end', 'terminal', 'root-close'])
def test_forward_wall_expiry_reaches_real_lifecycle_boundaries(
    tmp_path, authority_clock, monkeypatch, phase,
):
    raw, confirmation = configured(max_attempts=1)
    value = document(raw, tmp_path, now_ms=authority_clock['wall'])
    inputs = arguments(value)
    owner = session.SessionOwner.admit(raw, confirmation, str(tmp_path), **inputs)
    fired, calls, starts = [], [], []
    real_write, real_close = session._write, session._close

    def expire():
        fired.append(phase)
        authority_clock['wall'] = value['expires_unix_ms']

    def write(fd, data):
        result = real_write(fd, data)
        kind = json.loads(data)['kind']
        if kind == 'ATTEMPT_START':
            starts.append(True)
        if kind == {'start': 'ATTEMPT_START', 'end': 'ATTEMPT_END',
                    'terminal': 'RETIREMENT_INTENT'}.get(phase):
            expire()
        return result

    def clock():
        if (phase == 'actual-entry' and starts and not fired
                and sys._getframe(1).f_code.co_name == 'run_attempt'):
            expire()
        return authority_clock['mono']

    def close(fd):
        root = os.path.isdir(f'/proc/self/fd/{fd}')
        real_close(fd)
        if root and phase == 'root-close':
            expire()

    def action(permit):
        calls.append(permit.attempt)
        if phase == 'callback':
            expire()
        permit.checkpoint()

    monkeypatch.setattr(session, '_write', write)
    monkeypatch.setattr(session, '_clock', clock)
    monkeypatch.setattr(session, '_close', close)
    try:
        if phase == 'idle':
            expire()
        if phase in ('terminal', 'root-close'):
            assert owner.run_attempt(action) == 1
        else:
            with pytest.raises(session.SessionError, match='^EXPIRED$'):
                owner.run_attempt(action)
        result = owner.finish()
        assert result['state'] == 'EXPIRED' and result['code'] == 'EXPIRED'
        assert result['retired'] is True and result['cleanup_uncertain'] is False
        assert fired == [phase]
        assert len(calls) == (0 if phase in ('idle', 'start', 'actual-entry') else 1)
        assert result['attempts_admitted'] == (0 if phase == 'idle' else 1)
        assert result['attempts_completed'] == (1 if phase in ('terminal', 'root-close') else 0)
    finally:
        owner.close()


def test_wall_rollback_cannot_extend_initial_monotonic_authority_lease(
    tmp_path, authority_clock,
):
    raw, confirmation = configured(max_attempts=1)
    value = document(raw, tmp_path, now_ms=authority_clock['wall'])
    value['expires_unix_ms'] = authority_clock['wall'] + 2000
    owner = session.SessionOwner.admit(raw, confirmation, str(tmp_path), **arguments(value))
    calls = []
    try:
        authority_clock['wall'] = 0
        authority_clock['mono'] += 2.0
        with pytest.raises(session.SessionError, match='^EXPIRED$'):
            owner.run_attempt(lambda permit: calls.append(permit.attempt))
        assert calls == [] and owner.snapshot()['attempts_admitted'] == 0
        assert owner.finish()['state'] == 'EXPIRED'
    finally:
        owner.close()


@pytest.mark.parametrize('stop', [False, True])
def test_observed_expiry_cannot_be_caught_and_rolled_back_into_success(
    tmp_path, authority_clock, stop,
):
    raw, confirmation = configured(max_attempts=1)
    value = document(raw, tmp_path, now_ms=authority_clock['wall'])
    owner = session.SessionOwner.admit(raw, confirmation, str(tmp_path), **arguments(value))
    observed = []

    def action(permit):
        authority_clock['wall'] = value['expires_unix_ms']
        with pytest.raises(session.SessionError, match='^EXPIRED$'):
            permit.checkpoint()
        observed.append(True)
        authority_clock['wall'] = value['not_before_unix_ms']
        if stop:
            owner.request_stop()

    try:
        code = 'CANCELLED' if stop else 'EXPIRED'
        with pytest.raises(session.SessionError, match=f'^{code}$'):
            owner.run_attempt(action)
        assert observed == [True] and owner.snapshot()['attempts_completed'] == 0
        assert owner.finish()['code'] == code
    finally:
        owner.close()


@pytest.mark.parametrize('phase', ['validation', 'acquisition', 'claim'])
@pytest.mark.parametrize('axis', ['mono', 'wall'])
def test_expiry_during_actual_admission_keeps_origin_and_retires_fds(
    tmp_path, authority_clock, monkeypatch, phase, axis,
):
    from aiddos.lab import profile

    raw, confirmation = configured(max_attempts=1)
    value = document(raw, tmp_path, now_ms=authority_clock['wall'])
    value['expires_unix_ms'] = authority_clock['wall'] + 2000
    inputs = arguments(value)
    real_evaluate, real_open = profile.evaluate, session._open
    real_write, real_close = session._write, session._close
    opened, closed, fired = [], [], []

    def expire():
        fired.append((phase, axis))
        if axis == 'mono':
            authority_clock['mono'] += 2.0
        else:
            authority_clock['wall'] = value['expires_unix_ms']

    def evaluate(data):
        result = real_evaluate(data)
        if phase == 'validation':
            expire()
        return result

    def open_fd(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        opened.append(fd)
        if phase == 'acquisition' and kwargs.get('dir_fd') is None:
            expire()
        return fd

    def write(fd, data):
        count = real_write(fd, data)
        if phase == 'claim' and not fired:
            assert json.loads(data)['kind'] == 'BASELINE_SESSION_CLAIM'
            expire()
        return count

    def close(fd):
        closed.append(fd)
        real_close(fd)

    with monkeypatch.context() as patcher:
        patcher.setattr(profile, 'evaluate', evaluate)
        patcher.setattr(session, '_open', open_fd)
        patcher.setattr(session, '_write', write)
        patcher.setattr(session, '_close', close)
        refuse(raw, confirmation, tmp_path, inputs, 'EXPIRED')
    assert fired == [(phase, axis)]
    assert closed == list(reversed(opened))
    assert len(opened) == {'validation': 0, 'acquisition': 1, 'claim': 2}[phase]
    for fd in opened:
        with pytest.raises(OSError):
            os.fstat(fd)
    if phase == 'claim':
        original = (tmp_path / 'baseline-claim.json').read_bytes()
        renewed = arguments(document(raw, tmp_path, now_ms=authority_clock['wall']))
        refuse(raw, confirmation, tmp_path, renewed, 'SESSION_ALREADY_USED')
        assert (tmp_path / 'baseline-claim.json').read_bytes() == original
    else:
        assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('fault,expected', [
    ('ordinary', 'ACTION_FAILED'), ('end', 'RECORD_IO_ERROR'),
    ('root-close', 'RETIREMENT_UNCERTAIN'),
])
def test_wall_expiry_does_not_replace_primary_or_retirement_failure(
    tmp_path, authority_clock, monkeypatch, fault, expected,
):
    raw, confirmation = configured(max_attempts=1)
    value = document(raw, tmp_path, now_ms=authority_clock['wall'])
    owner = session.SessionOwner.admit(raw, confirmation, str(tmp_path), **arguments(value))
    real_write, real_close = session._write, session._close
    fired, root_closes = [], []

    def expire():
        fired.append(fault)
        authority_clock['wall'] = value['expires_unix_ms']

    def write(fd, data):
        if fault == 'end' and json.loads(data)['kind'] == 'ATTEMPT_END':
            expire()
            raise OSError('PRIVATE_SENTINEL')
        return real_write(fd, data)

    def close(fd):
        root = os.path.isdir(f'/proc/self/fd/{fd}')
        real_close(fd)
        if root:
            root_closes.append(fd)
            if fault == 'root-close':
                expire()
                raise OSError('PRIVATE_SENTINEL')

    def action(permit):
        if fault == 'ordinary':
            expire()
            raise ValueError('PRIVATE_SENTINEL')
        permit.checkpoint()

    monkeypatch.setattr(session, '_write', write)
    monkeypatch.setattr(session, '_close', close)
    try:
        if fault == 'root-close':
            assert owner.run_attempt(action) == 1
        else:
            with pytest.raises(session.SessionError) as caught:
                owner.run_attempt(action)
            assert caught.value.code == expected
        result = owner.finish()
        assert result['code'] == expected and result['retired'] is True
        assert result['cleanup_uncertain'] is (fault != 'ordinary')
        assert fired == [fault] and len(root_closes) == 1
        assert owner.finish() == result
    finally:
        owner.close()


def test_approved_path_with_replaced_inode_is_not_adopted(tmp_path):
    state = tmp_path / 'state'
    state.mkdir(mode=0o700)
    raw, confirmation = configured(max_attempts=1)
    inputs = arguments(document(raw, state))
    moved = tmp_path / 'original'
    state.rename(moved)
    state.mkdir(mode=0o700)
    caller = state / 'caller'
    caller.write_bytes(b'untouched')
    assert state.stat().st_ino != moved.stat().st_ino
    refuse(raw, confirmation, state, inputs, 'AUTHORITY_MISMATCH')
    assert list(moved.iterdir()) == []
    assert list(state.iterdir()) == [caller] and caller.read_bytes() == b'untouched'


@pytest.mark.parametrize('section,key,replacement', [
    ('target', 'connect_ipv4', '127.0.0.2'), ('target', 'port', 8081),
    ('target', 'scheme', 'https'), ('target', 'http_host', 'Different.test'),
    ('target', 'path', '/different'), ('source', 'bind_ipv4', '127.0.0.2'),
    ('source', 'interface', 'fixture-nic'), ('expected', 'http_status', 201),
    ('expected', 'body_sha256', '0' * 64),
])
def test_new_profile_confirmation_cannot_reuse_old_execution_authority(
    tmp_path, section, key, replacement,
):
    import hashlib

    from authority_support import canonical

    raw, _ = configured(max_attempts=1)
    inputs = arguments(document(raw, tmp_path))
    changed = json.loads(raw)
    changed[section][key] = replacement
    new_raw = canonical(changed)
    refuse(new_raw, hashlib.sha256(new_raw).hexdigest(), tmp_path,
           inputs, 'AUTHORITY_MISMATCH')
    assert list(tmp_path.iterdir()) == []
