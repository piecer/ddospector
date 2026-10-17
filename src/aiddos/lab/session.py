"""Explicit single-use local ownership, without transport or automatic activation.

Only trusted synchronous callbacks may use this library. Parent directories are a
trusted namespace. A retained claim consumes a directory even after failed I/O.
"""

import json
import os
import re
import stat
import threading
from os import close as _close
from os import fstat as _fstat
from os import fsync as _fsync
from os import open as _open
from os import stat as _stat
from os import write as _write
from time import monotonic as _clock

from aiddos.lab import profile

_CODES = frozenset({
    'INVALID_PROFILE', 'PROFILE_TOO_LARGE', 'SITE_CONFIGURATION_REQUIRED',
    'APPROVAL_REQUIRED', 'STATE_DIRECTORY_INVALID', 'STATE_DIRECTORY_IO_ERROR',
    'UNSUPPORTED_PLATFORM', 'SESSION_ALREADY_USED', 'OWNERSHIP_LOST', 'RECORD_IO_ERROR',
    'RETIREMENT_UNCERTAIN', 'SESSION_BUSY', 'RATE_LIMITED', 'BUDGET_EXHAUSTED',
    'SESSION_CLOSED', 'CANCELLED', 'EXPIRED', 'ACTION_FAILED', 'PERMIT_RETIRED',
})


class SessionError(Exception):
    """Closed, sanitized public failure; uncertainty includes record durability."""

    def __init__(self, code, cleanup_uncertain=False):
        self.code = code if type(code) is str and code in _CODES else 'ACTION_FAILED'
        self.cleanup_uncertain = bool(cleanup_uncertain)
        super().__init__(self.code)

    def __str__(self):
        return self.code + (' cleanup_uncertain' if self.cleanup_uncertain else '')

    def __repr__(self):
        return str(self)


def _directory_input(path):
    if type(path) is not str or not 1 <= len(path) <= 4096:
        raise SessionError('STATE_DIRECTORY_INVALID')
    try:
        valid_bytes = len(path.encode('utf-8')) <= 4096
    except UnicodeError:
        valid_bytes = False
    if (not valid_bytes or '\x00' in path or not path.startswith('/')
            or (path != '/' and any(p in ('', '.', '..') for p in path[1:].split('/')))):
        raise SessionError('STATE_DIRECTORY_INVALID')


def _platform():
    if (os.name != 'posix' or not all(hasattr(os, name) for name in
            ('O_DIRECTORY', 'O_NOFOLLOW', 'O_CLOEXEC', 'geteuid'))
            or os.open not in os.supports_dir_fd or os.stat not in os.supports_follow_symlinks):
        raise SessionError('UNSUPPORTED_PLATFORM')


class _Control(SessionError):
    def __init__(self, code, permit):
        super().__init__(code)
        self._permit = permit


class AttemptPermit:
    """Read-only cooperative capability. Retaining it never retains admission."""

    __slots__ = ('_owner', '_attempt', '_deadline', '_retired')

    def __init__(self, owner, attempt, deadline):
        self._owner = owner
        self._attempt = attempt
        self._deadline = deadline
        self._retired = False

    @property
    def attempt(self):
        return self._attempt

    @property
    def deadline(self):
        return self._deadline

    @property
    def profile(self):
        return json.loads(profile.canonical(self._owner._profile))

    def checkpoint(self):
        with self._owner._lock:
            if self._retired:
                raise SessionError('PERMIT_RETIRED')
            code = self._owner._control(self._deadline)
            if code:
                raise _Control(code, self)


class SessionOwner:
    """Use admit(), then explicitly finish()/close(); no implicit FD finalizer."""

    @classmethod
    def admit(cls, raw_profile: bytes, confirmed_profile_sha256: str, state_directory: str):
        start = _clock()
        if type(raw_profile) is not bytes:
            raise SessionError('INVALID_PROFILE')
        evaluation = profile.evaluate(raw_profile)
        if evaluation['status'] == 'REFUSED':
            raise SessionError(evaluation['code'])
        if (type(confirmed_profile_sha256) is not str
                or re.fullmatch('[0-9a-f]{64}', confirmed_profile_sha256) is None
                or confirmed_profile_sha256 != evaluation['profile_sha256']):
            raise SessionError('APPROVAL_REQUIRED')
        _directory_input(state_directory)
        _platform()
        owner = cls()
        owner._lock = threading.Lock()
        owner._profile = json.loads(raw_profile)
        owner._sha = evaluation['profile_sha256']
        owner._budget = owner._profile['budget']
        owner._deadline = start + owner._budget['overall_timeout_ms'] / 1000
        owner._path = state_directory
        owner._fd = None
        owner._identity = None
        owner._state = 'READY'
        owner._code = None
        owner._uncertain = False
        owner._stop = False
        owner._active = False
        owner._retired = False
        owner._settled = False
        owner._finalizing = False
        owner._close_pending = False
        owner._admitted = owner._started = owner._completed = 0
        owner._last_entry = None
        try:
            owner._acquire_root()
            owner._record('baseline-claim.json', 'BASELINE_SESSION_CLAIM',
                          budget=owner._budget)
            owner._identity_check()
            if _clock() >= owner._deadline:
                raise SessionError('EXPIRED')
        except SessionError as failure:
            owner._retire_root()
            raise SessionError(failure.code,
                               failure.cleanup_uncertain or owner._uncertain) from None
        return owner

    def _acquire_root(self):
        try:
            self._fd = _open(self._path, os.O_RDONLY | os.O_DIRECTORY
                             | os.O_NOFOLLOW | os.O_CLOEXEC)
        except OSError:
            code = 'STATE_DIRECTORY_IO_ERROR'
            try:
                mode = _stat(self._path, follow_symlinks=False).st_mode
                if not stat.S_ISDIR(mode):
                    code = 'STATE_DIRECTORY_INVALID'
            except OSError:
                pass
            raise SessionError(code) from None
        try:
            value = _fstat(self._fd)
        except OSError:
            raise SessionError('STATE_DIRECTORY_IO_ERROR') from None
        if (not stat.S_ISDIR(value.st_mode) or value.st_uid != os.geteuid()
                or value.st_mode & 0o077):
            raise SessionError('STATE_DIRECTORY_INVALID')
        self._identity = (value.st_dev, value.st_ino)

    def _identity_check(self):
        try:
            pinned = _fstat(self._fd)
            current = _stat(self._path, follow_symlinks=False)
            good = (stat.S_ISDIR(current.st_mode)
                    and (current.st_dev, current.st_ino) == self._identity
                    and (pinned.st_dev, pinned.st_ino) == self._identity)
        except OSError:
            good = False
        if not good:
            raise SessionError('OWNERSHIP_LOST')

    def _record(self, leaf, kind, **fields):
        data = profile.canonical(dict(schema_version=1, kind=kind,
                                      profile_sha256=self._sha, **fields)) + b'\n'
        assert len(data) <= 4096
        fd = None
        code = None
        uncertain = False
        try:
            fd = _open(leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                       | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self._fd)
            offset = 0
            while offset < len(data):
                count = _write(fd, data[offset:])
                if count <= 0:
                    raise OSError()
                offset += count
            _fsync(fd)
        except FileExistsError:
            code = 'SESSION_ALREADY_USED' if leaf == 'baseline-claim.json' else 'RECORD_IO_ERROR'
            uncertain = code == 'RECORD_IO_ERROR'
        except OSError:
            code, uncertain = 'RECORD_IO_ERROR', True
        finally:
            if fd is not None:
                retiring, fd = fd, None
                try:
                    _close(retiring)
                except OSError:
                    code, uncertain = code or 'RECORD_IO_ERROR', True
        if code is None:
            try:
                _fsync(self._fd)
            except OSError:
                code, uncertain = 'RECORD_IO_ERROR', True
        if code:
            raise SessionError(code, uncertain) from None

    def _retire_root(self):
        with self._lock:
            retiring, self._fd = self._fd, None
        uncertain = False
        if retiring is not None:
            try:
                _close(retiring)
            except OSError:
                uncertain = True
        with self._lock:
            if uncertain:
                self._fail('RETIREMENT_UNCERTAIN', True)
            self._retired = True

    def _fail(self, code, uncertain=False):
        self._code = self._code or code
        self._uncertain |= uncertain
        self._state = {'CANCELLED': 'CANCELLED', 'EXPIRED': 'EXPIRED',
                       'RECORD_IO_ERROR': 'UNCERTAIN',
                       'RETIREMENT_UNCERTAIN': 'UNCERTAIN'}.get(self._code, 'FAILED')

    def _view(self):
        return dict(schema_version=1, profile_sha256=self._sha, state=self._state,
                    attempts_admitted=self._admitted, callbacks_started=self._started,
                    attempts_completed=self._completed, active=self._active,
                    stop_requested=self._stop, retired=self._retired,
                    cleanup_uncertain=self._uncertain, code=self._code)

    def snapshot(self):
        with self._lock:
            return self._view()

    def request_stop(self):
        with self._lock:
            if not self._settled:
                self._stop = True
                if self._code is None:
                    self._state = 'STOP_REQUESTED'

    def _control(self, deadline, now=None):
        if self._stop:
            return 'CANCELLED'
        if (now if now is not None else _clock()) >= deadline:
            return 'EXPIRED'
        return None

    def _attempt_check(self, permit):
        self._identity_check()
        with self._lock:
            code = self._control(permit.deadline)
            if code:
                raise SessionError(code)

    def run_attempt(self, action):
        """Execute one synchronous trusted callback, never retry or detach it."""
        with self._lock:
            if self._active or self._finalizing:
                raise SessionError('SESSION_BUSY')
            if self._settled or self._code:
                raise SessionError('SESSION_CLOSED')
            code = self._control(self._deadline)
            if code:
                self._fail(code)
                raise SessionError(code)
            if self._admitted >= self._budget['max_attempts']:
                raise SessionError('BUDGET_EXHAUSTED')
            if (self._last_entry is not None
                    and _clock() < self._last_entry + self._budget['min_interval_ms'] / 1000):
                raise SessionError('RATE_LIMITED')
            self._active = True
        permit = None
        entered = False
        original = None
        try:
            self._identity_check()
            with self._lock:
                reserved = _clock()
                code = self._control(self._deadline, reserved)
                if code:
                    raise SessionError(code)
                self._admitted += 1
                permit = AttemptPermit(self, self._admitted, min(self._deadline,
                    reserved + self._budget['request_timeout_ms'] / 1000))
                self._state = 'RUNNING'
            self._record(f'attempt-{permit.attempt}-start.json', 'ATTEMPT_START',
                         attempt=permit.attempt)
            self._attempt_check(permit)
            with self._lock:
                entry = _clock()
                code = self._control(permit.deadline, entry)
                if code:
                    raise SessionError(code)
                self._started += 1
                self._last_entry = entry
                entered = True
            try:
                result = action(permit)
                if result is not None:
                    raise SessionError('ACTION_FAILED')
            except BaseException as failure:
                with self._lock:
                    code = 'ACTION_FAILED'
                    if isinstance(failure, _Control) and failure._permit is permit:
                        code = 'CANCELLED' if self._stop else failure.code
                    self._fail(code)
                if not isinstance(failure, Exception):
                    original = failure
            self._attempt_check(permit)
        except SessionError as failure:
            with self._lock:
                self._fail(failure.code, failure.cleanup_uncertain)
        finally:
            if permit is not None:
                with self._lock:
                    outcome = {'CANCELLED': 'CANCELLED', 'EXPIRED': 'EXPIRED'}.get(
                        self._code, 'FAILED' if self._code else 'RETURNED')
                try:
                    self._record(f'attempt-{permit.attempt}-end.json', 'ATTEMPT_END',
                                 attempt=permit.attempt, outcome=outcome, callback_started=entered)
                    self._attempt_check(permit)
                except SessionError as failure:
                    with self._lock:
                        self._fail(failure.code, failure.cleanup_uncertain)
            with self._lock:
                if permit is not None:
                    permit._retired = True
                    if self._code is None:
                        self._completed += 1
                        self._state = 'READY'
                self._active = False
                finalize = self._close_pending
                if finalize:
                    self._finalizing = True
                code, uncertain = self._code, self._uncertain
            if finalize:
                settled = self._finalize()
                code, uncertain = settled['code'], settled['cleanup_uncertain']
        if original is not None:
            raise original
        if code:
            raise SessionError(code, uncertain) from None
        return permit.attempt

    def finish(self):
        with self._lock:
            if self._settled:
                return self._view()
            if self._active or self._finalizing:
                raise SessionError('SESSION_BUSY')
            self._finalizing = True
        return self._finalize()

    def _finalize(self):
        with self._lock:
            if self._stop:
                self._fail('CANCELLED')
            elif _clock() >= self._deadline:
                self._fail('EXPIRED')
            fields = dict(attempts_admitted=self._admitted, callbacks_started=self._started,
                          attempts_completed=self._completed, code=self._code)
        try:
            self._identity_check()
            self._record('terminal.json', 'RETIREMENT_INTENT', **fields)
            self._identity_check()
        except SessionError as failure:
            with self._lock:
                self._fail(failure.code, failure.cleanup_uncertain)
        self._retire_root()
        with self._lock:
            if self._stop:
                self._fail('CANCELLED')
            elif _clock() >= self._deadline:
                self._fail('EXPIRED')
            if self._code:
                self._fail(self._code)
            else:
                self._state = ('COMPLETED' if self._admitted == self._started == self._completed
                               == self._budget['max_attempts'] else 'INCOMPLETE')
            self._settled = True
            self._finalizing = False
            return self._view()

    def close(self):
        with self._lock:
            if self._settled:
                return self._retired and not self._uncertain
            self._stop = True
            if self._code is None:
                self._state = 'STOP_REQUESTED'
            if self._active or self._finalizing:
                self._close_pending = True
                return False
            self._finalizing = True
        result = self._finalize()
        return result['retired'] and not result['cleanup_uncertain']
