"""B3: refuse unowned sidecars on fresh creation, allow real owned recovery."""

import os
import sqlite3
import stat
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from test_chat_runtime import configure
from test_chat_sessions import start

from aiddos.api.app import create_app


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
@pytest.mark.parametrize("kind", ["regular", "symlink", "dangling", "directory"])
def test_absent_database_preserves_all_foreign_sidecars(tmp_path, suffix, kind):
    database = tmp_path / "draft.chat.sqlite3"
    sidecar = tmp_path / (database.name + suffix)
    caller = tmp_path / "caller-sentinel"
    sentinel = b"CALLER ENTRY MUST REMAIN UNCHANGED"
    if kind == "regular":
        sidecar.write_bytes(sentinel)
        sidecar.chmod(0o600)
    elif kind in {"symlink", "dangling"}:
        if kind == "symlink":
            caller.write_bytes(sentinel)
            caller.chmod(0o600)
        sidecar.symlink_to(caller)
    else:
        sidecar.mkdir(mode=0o700)
        (sidecar / "sentinel").write_bytes(sentinel)
    before = sidecar.lstat()
    target = os.readlink(sidecar) if sidecar.is_symlink() else None
    with TestClient(
        create_app(state_path=tmp_path / "draft.json"),
        base_url="http://localhost",
        raise_server_exceptions=False,
    ) as client:
        # Missing reads remain lazy and do not acquire/create an owner lock.
        assert client.get("/api/v1/chat/sessions").json()["sessions"] == []
        assert not (tmp_path / "draft.chat.sqlite3.lock").exists()
        configure(client)
        response, _ = start(client)
    assert os.path.lexists(sidecar), response.text
    after = sidecar.lstat()
    assert (stat.S_IFMT(after.st_mode), after.st_ino, after.st_mode) == (
        stat.S_IFMT(before.st_mode),
        before.st_ino,
        before.st_mode,
    )
    if target is not None:
        assert os.readlink(sidecar) == target
        if kind == "symlink":
            assert caller.read_bytes() == sentinel
        else:
            assert not caller.exists()
    elif kind == "regular":
        assert sidecar.read_bytes() == sentinel
    else:
        assert (sidecar / "sentinel").read_bytes() == sentinel
    assert response.status_code == 503
    assert response.json()["code"] == "CHAT_STORAGE_ERROR"
    assert not database.exists(), "refuse before creating the main database"


def test_existing_supported_database_recovers_genuine_hot_journal(tmp_path):
    path = tmp_path / "draft.json"
    with TestClient(create_app(state_path=path), base_url="http://localhost") as client:
        configure(client)
        original = start(client)[0].json()
    database = tmp_path / "draft.chat.sqlite3"
    # Force SQLite's own pager to spill an uncommitted write, then exit without
    # connection cleanup. No fabricated journal format or production monkeypatch.
    script = """
import os, sqlite3, sys
connection = sqlite3.connect(sys.argv[1])
assert connection.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
connection.execute('PRAGMA synchronous=FULL')
connection.execute('PRAGMA cache_size=1')
connection.execute('PRAGMA cache_spill=ON')
connection.execute('BEGIN IMMEDIATE')
connection.execute('UPDATE sessions SET data=?', ('uncommitted' * 50000,))
os._exit(0)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(database)],
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    journal = tmp_path / "draft.chat.sqlite3-journal"
    raw = journal.read_bytes()
    assert len(raw) > 512 and raw[:8] == b"\xd9\xd5\x05\xf9\x20\xa1\x63\xd7"
    with TestClient(create_app(state_path=path), base_url="http://localhost") as client:
        response = client.get("/api/v1/chat/sessions")
        assert response.status_code == 200, response.text
        assert response.json()["sessions"] == [original]
        assert start(client)[0].status_code == 201
    assert not journal.exists(), "SQLite must actually complete owned crash recovery"
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
