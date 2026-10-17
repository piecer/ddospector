"""Local ownership contract; inert callbacks are not service acceptance."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from aiddos.lab import profile, session

KEYS = {'schema_version', 'profile_sha256', 'state', 'attempts_admitted',
        'callbacks_started', 'attempts_completed', 'active', 'stop_requested',
        'retired', 'cleanup_uncertain', 'code'}


def configured(**budget):
    value = profile.template()
    value['target'].update(connect_ipv4='127.0.0.1', port=8080, scheme='http',
                           http_host='Example.test', path='/PRIVATE_SENTINEL?secret=hidden')
    value['source'].update(bind_ipv4='127.0.0.1', interface='lo')
    value['expected']['http_status'] = 200
    value['budget'].update(budget)
    raw = profile.canonical(value)
    return raw, hashlib.sha256(raw).hexdigest()


def admit(path, **budget):
    assert hasattr(session, 'SessionOwner'), 'explicit admission API is absent'
    return session.SessionOwner.admit(*configured(**budget), str(path))


def error(code, call):
    with pytest.raises(session.SessionError) as caught:
        call()
    assert caught.value.code == code
    assert 'PRIVATE_SENTINEL' not in str(caught.value) + repr(caught.value)
    assert caught.value.__cause__ is None
    return caught.value


def test_admit_claim_and_idle_retirement(tmp_path):
    owner = admit(tmp_path)
    value = owner.snapshot()
    assert set(value) == KEYS
    assert value == dict(schema_version=1, profile_sha256=configured()[1], state='READY',
                        attempts_admitted=0, callbacks_started=0, attempts_completed=0,
                        active=False, stop_requested=False, retired=False,
                        cleanup_uncertain=False, code=None)
    expected = dict(schema_version=1, kind='BASELINE_SESSION_CLAIM',
                    profile_sha256=configured()[1], budget=json.loads(configured()[0])['budget'])
    claim = tmp_path / 'baseline-claim.json'
    assert claim.read_bytes() == profile.canonical(expected) + b'\n'
    assert claim.stat().st_mode & 0o777 == 0o600
    assert owner.close() is True
    assert owner.snapshot()['state'] == 'CANCELLED'
    assert owner.snapshot()['retired'] is True
    assert owner.finish() == owner.snapshot()
    assert owner.close() is True
    assert owner.request_stop() is None
    error('SESSION_ALREADY_USED', lambda: admit(tmp_path))


@pytest.mark.parametrize('raw,code', [(None, 'INVALID_PROFILE'), ('x', 'INVALID_PROFILE'),
    (bytearray(b'{}'), 'INVALID_PROFILE'), (b'{}', 'INVALID_PROFILE'),
    (b'x' * 16385, 'PROFILE_TOO_LARGE'),
    (profile.canonical(profile.template()), 'SITE_CONFIGURATION_REQUIRED')])
def test_profile_rejection_before_directory(tmp_path, raw, code):
    assert hasattr(session, 'SessionOwner'), 'explicit admission API is absent'
    error(code, lambda: session.SessionOwner.admit(raw, None, object()))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('approval', [None, 1, 'A' * 64, 'f' * 64, '0' * 63, '0' * 65])
def test_approval_precedes_invalid_directory(tmp_path, approval):
    assert hasattr(session, 'SessionOwner'), 'explicit admission API is absent'
    error('APPROVAL_REQUIRED', lambda: session.SessionOwner.admit(
        configured()[0], approval, object()))
    assert list(tmp_path.iterdir()) == []


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(session, '_clock', lambda: now[0])
    return now


def test_three_attempts_detached_readonly_permit_and_finish(tmp_path, clock):
    owner = admit(tmp_path)
    assert hasattr(owner, 'run_attempt'), 'bounded callback entry is absent'
    permits = []

    def action(permit):
        permits.append(permit)
        assert permit.attempt == len(permits)
        assert permit.deadline == clock[0] + 3.0
        assert permit.checkpoint() is None
        for key in ('attempt', 'deadline', 'profile'):
            with pytest.raises(AttributeError):
                setattr(permit, key, None)
        detached = permit.profile
        detached['budget']['max_attempts'] = 99
        assert permit.profile['budget']['max_attempts'] == 3
        error('SESSION_BUSY', lambda: owner.run_attempt(action))
        error('SESSION_BUSY', owner.finish)

    for n in (1, 2, 3):
        clock[0] = float(n - 1)
        assert owner.run_attempt(action) == n
        error('PERMIT_RETIRED', permits[-1].checkpoint)
    error('BUDGET_EXHAUSTED', lambda: owner.run_attempt(action))
    result = owner.finish()
    assert result['state'] == 'COMPLETED'
    assert result['retired'] is True and result['cleanup_uncertain'] is False
    assert (result['attempts_admitted'] == result['callbacks_started']
            == result['attempts_completed'] == 3)
    result['state'] = 'changed'
    assert owner.finish()['state'] == 'COMPLETED'
    error('SESSION_CLOSED', lambda: owner.run_attempt(action))
    assert len(list(tmp_path.iterdir())) == 8
    for path in tmp_path.iterdir():
        raw = path.read_bytes()
        assert len(raw) <= 4096 and raw == profile.canonical(json.loads(raw)) + b'\n'
        assert b'PRIVATE_SENTINEL' not in raw
    assert json.loads((tmp_path / 'terminal.json').read_bytes()) == dict(
        schema_version=1, kind='RETIREMENT_INTENT', profile_sha256=configured()[1],
        attempts_admitted=3, callbacks_started=3, attempts_completed=3, code=None)


@pytest.mark.parametrize('case,code,outcome', [
    ('ordinary', 'ACTION_FAILED', 'FAILED'), ('self-created', 'ACTION_FAILED', 'FAILED'),
    ('return', 'ACTION_FAILED', 'FAILED'), ('base', 'ACTION_FAILED', 'FAILED'),
    ('checkpoint', 'CANCELLED', 'CANCELLED'), ('caught', 'CANCELLED', 'CANCELLED'),
    ('expired', 'EXPIRED', 'EXPIRED'), ('both', 'CANCELLED', 'CANCELLED'),
])
def test_callback_classification_halts_and_retires(tmp_path, clock, case, code, outcome):
    owner = admit(tmp_path)
    assert hasattr(owner, 'run_attempt'), 'bounded callback entry is absent'
    permits = []
    original = KeyboardInterrupt('PRIVATE_SENTINEL')

    def action(permit):
        permits.append(permit)
        if case == 'ordinary':
            owner.request_stop()
            raise ValueError('PRIVATE_SENTINEL')
        if case == 'self-created':
            raise session.SessionError('CANCELLED')
        if case == 'return':
            return 'PRIVATE_SENTINEL'
        if case == 'base':
            raise original
        if case in ('expired', 'both'):
            clock[0] = 3.0
        if case != 'expired':
            owner.request_stop()
        if case == 'caught':
            error('CANCELLED', permit.checkpoint)
        else:
            permit.checkpoint()
        return None

    if case == 'base':
        with pytest.raises(KeyboardInterrupt) as caught:
            owner.run_attempt(action)
        assert caught.value is original
    else:
        error(code, lambda: owner.run_attempt(action))
    state = owner.snapshot()
    assert state['code'] == code and state['active'] is False
    assert state['retired'] is False and state['attempts_completed'] == 0
    error('PERMIT_RETIRED', permits[0].checkpoint)
    error('SESSION_CLOSED', lambda: owner.run_attempt(action))
    assert len(permits) == 1
    assert json.loads((tmp_path / 'attempt-1-end.json').read_bytes()) == dict(
        schema_version=1, kind='ATTEMPT_END', profile_sha256=configured()[1],
        attempt=1, outcome=outcome, callback_started=True)
    assert owner.finish()['code'] == code
    assert owner.snapshot()['retired'] is True


def test_public_session_namespace_is_explicit_reexport():
    assert importlib.util.find_spec('ddospector.lab.session') is not None
    public = importlib.import_module('ddospector.lab.session')
    assert public.__all__ == ['SessionOwner', 'SessionError', 'AttemptPermit']
    for name in public.__all__:
        assert getattr(public, name) is getattr(session, name)


def test_explicit_session_module_exists_without_cli_activation():
    assert importlib.util.find_spec('aiddos.lab.session') is not None
    root = Path(__file__).resolve().parents[2]
    for name in ('src/aiddos/lab/__init__.py', 'src/aiddos/lab/cli.py',
                 'src/ddospector/lab/__init__.py', 'src/ddospector/lab/__main__.py'):
        assert 'lab.session' not in (root / name).read_text()
