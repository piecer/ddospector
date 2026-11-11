"""Synthetic test approvals; never an operator-approval issuer or site witness."""

import hashlib
import json
from pathlib import Path
from time import time_ns

SITE = dict(site_id='fixture-site', dut_id='fixture-dut', sink_id='fixture-sink',
            isolation_ref='fixture-isolation')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False).encode('utf-8')


def document(raw_profile, directory, *, now_ms=None, identity=None):
    """Deliberately synthetic prerequisites, outside the product-effect observer."""
    if identity is None:
        try:
            info = Path(directory).stat(follow_symlinks=False)
            identity = (info.st_dev, info.st_ino)
        except OSError:
            # Missing-path refusal tests must still reach the real acquisition.
            identity = (0, 0)
    now = time_ns() // 1_000_000 if now_ms is None else now_ms
    return dict(schema_version=1, scope='LOCAL_BASELINE_CALLBACK_ONLY',
                profile_sha256=hashlib.sha256(canonical(json.loads(raw_profile))).hexdigest(),
                site=dict(SITE), owner=dict(state_directory=str(directory),
                                           st_dev=identity[0], st_ino=identity[1]),
                not_before_unix_ms=now - 1000, expires_unix_ms=now + 240000,
                budget=json.loads(raw_profile)['budget'])


def arguments(value, *, site=None):
    raw = canonical(value)
    return dict(raw_authority=raw, confirmed_authority_sha256=hashlib.sha256(raw).hexdigest(),
                site_binding=dict(SITE if site is None else site))
