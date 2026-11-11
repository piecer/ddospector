"""Closed local callback approval data, not authentication or site attestation."""

import hashlib
import json
import re
from dataclasses import dataclass

from aiddos.lab import profile

MAX_AUTHORITY_BYTES = 8192
MAX_VALIDITY_MS = 300000
_SITE = {'site_id', 'dut_id', 'sink_id', 'isolation_ref'}
_BUDGET = {
    'max_attempts': (1, 3), 'min_interval_ms': (1000, 30000), 'concurrency': (1, 1),
    'request_timeout_ms': (1, 3000), 'overall_timeout_ms': (1, 30000), 'retries': (0, 0),
}
_ROOT = {'schema_version', 'scope', 'profile_sha256', 'site', 'owner',
         'not_before_unix_ms', 'expires_unix_ms', 'budget'}


class AuthorityError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class Authority:
    sha256: str
    profile_sha256: str
    directory: str
    device: int
    inode: int
    not_before_ms: int
    expires_ms: int
    site: tuple
    budget: tuple


def _invalid(*_args):
    raise ValueError('INVALID_AUTHORITY')


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _invalid()
        result[key] = value
    return result


def _fields(value, keys):
    if (type(value) is not dict or len(value) != len(keys)
            or any(type(key) is not str for key in value) or value.keys() != keys):
        _invalid()


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        _invalid()


def _digest(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _site(value):
    _fields(value, _SITE)
    for token in value.values():
        if (type(token) is not str or not 1 <= len(token) <= 64
                or re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', token) is None):
            _invalid()
    if value['dut_id'] == value['sink_id']:
        _invalid()
    return tuple(sorted(value.items()))


def _directory(value):
    # Same literal grammar as SessionOwner's caller-path boundary. Keep that
    # boundary independent so its character-before-encode probe still observes it.
    if type(value) is not str or not 1 <= len(value) <= 4096:
        _invalid()
    if (len(value.encode('utf-8')) > 4096 or '\x00' in value or not value.startswith('/')
            or (value != '/' and any(p in ('', '.', '..') for p in value[1:].split('/')))):
        _invalid()


def parse(raw):
    """Decode only bounded exact bytes; return detached immutable observations."""
    if type(raw) is not bytes:
        raise AuthorityError('INVALID_AUTHORITY')
    if len(raw) > MAX_AUTHORITY_BYTES:
        raise AuthorityError('AUTHORITY_TOO_LARGE')
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_object,
                           parse_float=_invalid, parse_constant=_invalid)
        _fields(value, _ROOT)
        _integer(value['schema_version'], 1, 1)
        if (type(value['scope']) is not str
                or value['scope'] != 'LOCAL_BASELINE_CALLBACK_ONLY'
                or not _digest(value['profile_sha256'])):
            _invalid()
        site = _site(value['site'])
        owner, budget = value['owner'], value['budget']
        _fields(owner, {'state_directory', 'st_dev', 'st_ino'})
        _directory(owner['state_directory'])
        for key in ('st_dev', 'st_ino'):
            _integer(owner[key], 0, (1 << 64) - 1)
        _fields(budget, _BUDGET.keys())
        for key, (low, high) in _BUDGET.items():
            _integer(budget[key], low, high)
        if budget['request_timeout_ms'] > budget['overall_timeout_ms']:
            _invalid()
        for key in ('not_before_unix_ms', 'expires_unix_ms'):
            _integer(value[key], 0, (1 << 63) - 1)
        if not 0 < value['expires_unix_ms'] - value['not_before_unix_ms'] <= MAX_VALIDITY_MS:
            _invalid()
        return Authority(hashlib.sha256(profile.canonical(value)).hexdigest(),
                         value['profile_sha256'], owner['state_directory'],
                         owner['st_dev'], owner['st_ino'], value['not_before_unix_ms'],
                         value['expires_unix_ms'], site, tuple(sorted(budget.items())))
    except (ValueError, UnicodeError, RecursionError):
        raise AuthorityError('INVALID_AUTHORITY') from None


def bind(grant, confirmation, profile_sha256, budget, directory, site_binding):
    """Compare independent caller inputs; never mint approval from validation."""
    try:
        site = _site(site_binding)
    except (ValueError, UnicodeError):
        raise AuthorityError('AUTHORITY_MISMATCH') from None
    if (not _digest(confirmation) or confirmation != grant.sha256
            or grant.profile_sha256 != profile_sha256 or dict(grant.budget) != budget
            or grant.directory != directory or grant.site != site):
        raise AuthorityError('AUTHORITY_MISMATCH')
