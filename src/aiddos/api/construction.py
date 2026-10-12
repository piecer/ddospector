"""Serialize framework composition, never storage preparation or requests.

Native model-field construction temporarily changes process-wide warning filters.
All app/router composition shares this reentrant boundary; callers must prepare
stores before entering it. No warning policy is changed here.
"""

from functools import wraps
from threading import RLock

_CONSTRUCTION_LOCK = RLock()


def serialized(builder):
    @wraps(builder)
    def guarded(*args, **kwargs):
        with _CONSTRUCTION_LOCK:
            return builder(*args, **kwargs)

    return guarded
