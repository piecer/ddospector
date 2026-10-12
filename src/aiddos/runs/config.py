"""Fixed local-only PostgreSQL configuration; never consult libpq defaults."""

import os
from pathlib import Path

from aiddos.api.errors import DraftError


def parameters(socket, *, owner=False):
    if not socket:
        raise DraftError("RUN_DB_NOT_CONFIGURED")
    if any(key.startswith("PG") for key in os.environ):
        raise DraftError("RUN_DB_UNAVAILABLE")
    try:
        if (
            not isinstance(socket, str)
            or not Path(socket).is_absolute()
            or len(socket.encode("utf-8")) > 80
            or any(c.isspace() or c in "\x00," for c in socket)
            or not Path(socket).is_dir()
        ):
            raise ValueError
    except (ValueError, OSError, UnicodeError):
        raise DraftError("RUN_DB_UNAVAILABLE") from None
    return {
        "host": socket,
        "port": 5432,
        "dbname": "aiddos_s02",
        "user": "aiddos_s02_owner" if owner else "aiddos_s02",
        "passfile": "/dev/null",
        "client_encoding": "UTF8",
        "sslmode": "disable",
        "gssencmode": "disable",
        "connect_timeout": 2,
        "options": "-c statement_timeout=2000 -c lock_timeout=500 "
        "-c idle_in_transaction_session_timeout=2000 -c synchronous_commit=on",
    }


def driver():
    try:
        import psycopg
    except ImportError:
        raise DraftError("RUN_DB_NOT_READY") from None
    return psycopg
