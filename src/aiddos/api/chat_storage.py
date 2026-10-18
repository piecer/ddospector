"""Lazy, exclusively owned SQLite history. No draft state migration or repair."""

import fcntl
import json
import os
import sqlite3
import stat
from contextlib import contextmanager
from functools import wraps

from .chat_models import SAFE_INT, TERMINAL, Session, SessionInput, Turn, TurnInput, encoded, now
from .encoding import strict_json
from .errors import DraftError
from .models import AIModelProfile

APPLICATION_ID = 0x43484154
SCHEMA = {
    "sessions": "CREATE TABLE sessions (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, "
    "commitment TEXT NOT NULL, profile TEXT NOT NULL, data TEXT NOT NULL)",
    "turns": "CREATE TABLE turns (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, "
    "session_id TEXT NOT NULL REFERENCES sessions(id), sequence INTEGER NOT NULL, "
    "commitment TEXT NOT NULL, data TEXT NOT NULL, UNIQUE(session_id, sequence))",
}


def storage_read(method):
    """Fence the complete read, including cursor fetch/iteration, on I/O failure."""

    @wraps(method)
    def read(self, *args, **kwargs):
        if self.fenced:
            raise DraftError("CHAT_COMMIT_UNCERTAIN")
        try:
            return method(self, *args, **kwargs)
        except (OSError, sqlite3.Error):
            self.fenced = True
            raise DraftError("CHAT_COMMIT_UNCERTAIN") from None

    return read


class ChatStorage:
    def __init__(self, path):
        self.path = path.with_suffix(".chat.sqlite3")
        self.db = None
        self.owner = None
        self.fenced = False

    def open(self, *, create=False):
        if self.fenced:
            raise DraftError("CHAT_COMMIT_UNCERTAIN")
        if self.db is not None:
            return True
        if not self.path.exists() and not self.path.is_symlink() and not create:
            return False
        try:
            parent = self.path.parent.stat()
            if parent.st_uid != os.getuid() or parent.st_mode & 0o022 or not parent.st_mode & 0o200:
                raise ValueError
            lock = self.path.with_suffix(self.path.suffix + ".lock")
            self.owner = os.open(
                lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600
            )
            info = os.fstat(self.owner)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError
            fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # With no main database these entries cannot belong to this store.
            # SQLite may delete them even on first open; reject before creating
            # the main file. Existing supported databases retain hot-journal recovery.
            if not os.path.lexists(self.path) and any(
                os.path.lexists(str(self.path) + suffix) for suffix in ("-journal", "-wal", "-shm")
            ):
                raise DraftError("CHAT_STORAGE_ERROR")
            fresh = False
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
                fresh = True
            info = self.path.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
                or info.st_size > 16 * 1024 * 1024
            ):
                raise ValueError
            self.db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=0.5)
            self.db.execute("PRAGMA foreign_keys=ON")
            if fresh:
                with self.db:
                    self.db.execute("BEGIN IMMEDIATE")
                    for sql in SCHEMA.values():
                        self.db.execute(sql)
                    self.db.execute(f"PRAGMA application_id={APPLICATION_ID}")
                    self.db.execute("PRAGMA user_version=1")
            self.validate()
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA journal_mode=DELETE")
            page_size = self.db.execute("PRAGMA page_size").fetchone()[0]
            self.db.execute(f"PRAGMA max_page_count={16 * 1024 * 1024 // page_size}")
            if self.db.execute("PRAGMA user_version").fetchone()[0] == 1:
                from .chat_tool_storage import migrate

                migrate(self)
                self.validate()
            self.recover()
            return True
        except DraftError:
            self.close()
            raise
        except (OSError, ValueError, sqlite3.Error, TypeError, KeyError, RecursionError):
            self.close()
            raise DraftError("CHAT_STORAGE_ERROR") from None

    def validate(self):
        from .chat_tool_storage import TOOL_SCHEMA

        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if self.db.execute("PRAGMA application_id").fetchone()[
            0
        ] != APPLICATION_ID or version not in (1, 2):
            raise ValueError
        rows = self.db.execute(
            "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL"
        ).fetchall()
        schema = SCHEMA if version == 1 else SCHEMA | TOOL_SCHEMA
        if dict(rows) != schema or self.db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ValueError
        sessions = {}
        for identifier, request, commitment, profile, raw in self.db.execute(
            "SELECT * FROM sessions"
        ):
            session = Session.model_validate(strict_json(raw.encode())).model_dump()
            profile = AIModelProfile.model_validate(strict_json(profile.encode())).model_dump()
            consent = SessionInput.model_validate(strict_json(commitment.encode())).model_dump()
            if (
                session["id"] != identifier
                or session["request_id"] != request
                or consent["request_id"] != request
                or consent["settings_revision"] != session["settings_revision"]
                or consent["profile_id"] != session["profile_id"]
                or consent["locale"] != session["locale"]
                or consent["approved_endpoint"] != session["endpoint"]
                or session["profile_id"] != profile["id"]
                or session["model"] != profile["model"]
                or session["streaming"] != profile["streaming"]
            ):
                raise ValueError
            encoded(session)
            sessions[identifier] = session
        if len(sessions) > 32:
            raise ValueError
        sequences = {key: [] for key in sessions}
        pending = {}
        total = 0
        for identifier, request, sid, sequence, commitment, raw in self.db.execute(
            "SELECT * FROM turns"
        ):
            turn = Turn.model_validate(strict_json(raw.encode())).model_dump()
            body = strict_json(commitment.encode())
            committed_sid = body.pop("session_id")
            admission = TurnInput.model_validate(body)
            if (
                sid not in sessions
                or committed_sid != sid
                or turn["session_id"] != sid
                or turn["id"] != identifier
                or turn["request_id"] != request
                or admission.request_id != request
                or admission.text != turn["user_text"]
                or admission.expected_sequence + 1 != sequence
                or turn["sequence"] != sequence
                or (turn["status"] in TERMINAL) != (turn["finished_at"] is not None)
                or (turn["provider_stop"] == "not_dispatched")
                != (turn["transport"] == "not_started")
                or (
                    turn["status"] == "succeeded"
                    and (not turn["assistant_text"].strip() or turn["error_code"] is not None)
                )
            ):
                raise ValueError
            sequences[sid].append(sequence)
            if turn["status"] not in TERMINAL:
                if pending:
                    raise ValueError
                pending[sid] = identifier
            total += len(turn["user_text"].encode()) + len(turn["assistant_text"].encode())
        if total > 8388608:
            raise ValueError
        for sid, session in sessions.items():
            if sorted(sequences[sid]) != list(range(1, session["sequence"] + 1)) or session[
                "active_turn_id"
            ] != pending.get(sid):
                raise ValueError
        if version == 2:
            from .chat_tool_storage import ToolLedger

            ToolLedger(self).validate()

    def recover(self):
        from .chat_tool_storage import ToolLedger

        ToolLedger(self).recover()
        turns = [json.loads(row[0]) for row in self.db.execute("SELECT data FROM turns")]
        pending = [turn for turn in turns if turn["status"] not in TERMINAL]
        if not pending:
            return
        with self.transaction():
            for turn in pending:
                if turn["revision"] >= SAFE_INT:
                    raise DraftError("CHAT_STORAGE_ERROR")
                turn.update(
                    status="interrupted",
                    error_code="CHAT_INTERRUPTED",
                    finished_at=now(),
                    revision=turn["revision"] + 1,
                    transport="not_started"
                    if turn["provider_stop"] == "not_dispatched"
                    else "unknown",
                )
                self.db.execute(
                    "UPDATE turns SET data=? WHERE id=?", (encoded(turn).decode(), turn["id"])
                )
                session, _ = self.session(turn["session_id"])
                session["active_turn_id"] = None
                self.db.execute(
                    "UPDATE sessions SET data=? WHERE id=?",
                    (encoded(session).decode(), session["id"]),
                )

    @contextmanager
    def transaction(self):
        if self.fenced:
            raise DraftError("CHAT_COMMIT_UNCERTAIN")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            yield
            self.db.commit()
        except (OSError, sqlite3.Error):
            self.fenced = True
            self.rollback()
            raise DraftError("CHAT_COMMIT_UNCERTAIN") from None
        except BaseException:
            # Cleanup must preserve domain/programming errors, not reclassify them.
            self.rollback()
            raise

    def rollback(self):
        try:
            self.db.rollback()
        except (OSError, sqlite3.Error):
            self.fenced = True

    @storage_read
    def sessions(self):
        if not self.open():
            return []
        return [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT data FROM sessions ORDER BY json_extract(data,'$.created_at') DESC, id ASC"
            )
        ]

    @storage_read
    def session(self, identifier):
        if not self.open():
            raise DraftError("CHAT_NOT_FOUND")
        row = self.db.execute(
            "SELECT data, profile FROM sessions WHERE id=?", (identifier,)
        ).fetchone()
        if row is None:
            raise DraftError("CHAT_NOT_FOUND")
        return json.loads(row[0]), json.loads(row[1])

    @storage_read
    def replay(self, table, request_id, commitment):
        if table not in {"sessions", "turns"}:
            raise ValueError("Unknown replay table")
        if (
            table == "turns"
            and self.db.execute(
                "SELECT 1 FROM tool_bindings WHERE key=(SELECT id FROM turns WHERE request_id=?)",
                (request_id,),
            ).fetchone()
            is not None
        ):
            raise DraftError("CHAT_IDEMPOTENCY_CONFLICT")
        row = self.db.execute(
            f"SELECT commitment, data FROM {table} WHERE request_id=?", (request_id,)
        ).fetchone()
        if row is None:
            return None
        if json.loads(row[0]) != commitment:
            raise DraftError("CHAT_IDEMPOTENCY_CONFLICT")
        return json.loads(row[1])

    def add_session(self, session, profile, commitment):
        with self.transaction():
            if self.db.execute("SELECT count(*) FROM sessions").fetchone()[0] >= 32:
                raise DraftError("CHAT_RETENTION_FULL")
            self.db.execute(
                "INSERT INTO sessions VALUES (?,?,?,?,?)",
                (
                    session["id"],
                    session["request_id"],
                    encoded(commitment).decode(),
                    encoded(profile).decode(),
                    encoded(session).decode(),
                ),
            )

    @storage_read
    def turn(self, identifier, *, by_request=False):
        if not self.open():
            raise DraftError("CHAT_NOT_FOUND")
        column = "request_id" if by_request else "id"
        row = self.db.execute(f"SELECT data FROM turns WHERE {column}=?", (identifier,)).fetchone()
        if row is None:
            raise DraftError("CHAT_NOT_FOUND")
        return json.loads(row[0])

    @storage_read
    def turns(self, session_id):
        return [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT data FROM turns WHERE session_id=? ORDER BY sequence", (session_id,)
            )
        ]

    @storage_read
    def text_bytes(self):
        return self.db.execute(
            "SELECT coalesce(sum(length(cast(json_extract(data,'$.user_text') AS BLOB)) + "
            "length(cast(json_extract(data,'$.assistant_text') AS BLOB))), 0) FROM turns"
        ).fetchone()[0]

    def add_turn(self, session, turn, commitment):
        with self.transaction():
            self._insert_turn(session, turn, commitment)

    def _insert_turn(self, session, turn, commitment):
        """Caller owns transaction, including any companion binding/reservation."""
        if self.text_bytes() + len(turn["user_text"].encode()) + 65536 > 8388608:
            raise DraftError("CHAT_RETENTION_FULL")
        self.db.execute(
            "INSERT INTO turns VALUES (?,?,?,?,?,?)",
            (
                turn["id"],
                turn["request_id"],
                session["id"],
                turn["sequence"],
                encoded(commitment).decode(),
                encoded(turn).decode(),
            ),
        )
        self.db.execute(
            "UPDATE sessions SET data=? WHERE id=?", (encoded(session).decode(), session["id"])
        )

    def update_turn(self, turn):
        with self.transaction():
            self.db.execute(
                "UPDATE turns SET data=? WHERE id=?", (encoded(turn).decode(), turn["id"])
            )
            if turn["status"] in {"succeeded", "failed", "cancelled", "interrupted"}:
                session, _ = self.session(turn["session_id"])
                session["active_turn_id"] = None
                self.db.execute(
                    "UPDATE sessions SET data=? WHERE id=?",
                    (encoded(session).decode(), session["id"]),
                )

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        if self.owner is not None:
            os.close(self.owner)
            self.owner = None
