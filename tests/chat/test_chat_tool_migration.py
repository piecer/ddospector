"""Real SQLite version admission, migration atomicity and preservation."""

import json
import sqlite3

import pytest

from aiddos.api.chat_models import encoded
from aiddos.api.chat_storage import APPLICATION_ID, SCHEMA, ChatStorage
from aiddos.api.errors import DraftError


def test_new_store_is_v2_without_changing_legacy_tables(tmp_path):
    storage = ChatStorage(tmp_path / "draft.json")
    try:
        assert storage.open(create=True)
        assert storage.db.execute("PRAGMA user_version").fetchone() == (2,)
        tables = dict(
            storage.db.execute("SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL")
        )
        assert all(tables[name] == sql for name, sql in SCHEMA.items())
        assert storage.db.execute("PRAGMA application_id").fetchone() == (APPLICATION_ID,)
    finally:
        storage.close()


def v1_database(tmp_path):
    path = tmp_path / "draft.chat.sqlite3"
    with sqlite3.connect(path) as db:
        for sql in SCHEMA.values():
            db.execute(sql)
        db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        db.execute("PRAGMA user_version=1")
    path.chmod(0o600)
    return path


@pytest.mark.parametrize(
    "mutation",
    [
        "orphan",
        "extra",
        "duplicate",
        "reservation",
        "fence",
        "schema",
        "index",
        "grant",
        "slot",
        "missing_exchange",
        "column",
    ],
)
def test_v2_corruption_refused_without_modification(tmp_path, mutation):
    from test_chat_tool_storage_intents import prepared

    storage, _, _, call, _ = prepared(tmp_path)
    path = storage.path
    storage.close()
    with sqlite3.connect(path) as db:
        if mutation == "orphan":
            row = json.loads(db.execute("SELECT data FROM tool_calls").fetchone()[0])
            row["turn_id"] = call["id"]
            db.execute("UPDATE tool_calls SET data=?", (encoded(row).decode(),))
        elif mutation == "extra":
            row = json.loads(db.execute("SELECT data FROM tool_bindings").fetchone()[0])
            row["foreign"] = True
            db.execute("UPDATE tool_bindings SET data=?", (encoded(row).decode(),))
        elif mutation == "duplicate":
            row = db.execute("SELECT data FROM tool_calls").fetchone()[0]
            db.execute("UPDATE tool_calls SET data=?", (row[:-1] + ',"turn_id":"bad"}',))
        elif mutation == "reservation":
            row = json.loads(db.execute("SELECT data FROM tool_reservations").fetchone()[0])
            row["remaining"] = 1048577
            db.execute("UPDATE tool_reservations SET data=?", (encoded(row).decode(),))
        elif mutation == "fence":
            db.execute(
                "INSERT INTO tool_fence VALUES ('singleton',?)",
                (
                    json.dumps(
                        dict(schema_version=1, generation=1, fenced=True, call_ids=[call["id"]])
                    ),
                ),
            )
        elif mutation == "index":
            row = json.loads(db.execute("SELECT data FROM tool_calls").fetchone()[0])
            row["call"]["index"] = 1
            db.execute("UPDATE tool_calls SET data=?", (encoded(row).decode(),))
        elif mutation == "grant":
            row = json.loads(db.execute("SELECT data FROM tool_grants").fetchone()[0])
            row["turn_request_id"] = call["id"]
            db.execute("UPDATE tool_grants SET data=?", (encoded(row).decode(),))
        elif mutation == "slot":
            row = json.loads(db.execute("SELECT data FROM tool_bindings").fetchone()[0])
            row["write_slot"] = True
            db.execute("UPDATE tool_bindings SET data=?", (encoded(row).decode(),))
        elif mutation == "missing_exchange":
            db.execute("DELETE FROM tool_exchanges")
        elif mutation == "column":
            db.execute("ALTER TABLE tool_grants ADD COLUMN uncharged TEXT")
        else:
            db.execute("CREATE TABLE alien (value TEXT)")
    before = path.read_bytes()
    store = ChatStorage(tmp_path / "draft.json")
    try:
        with pytest.raises(DraftError) as error:
            store.open()
        assert error.value.code == "CHAT_STORAGE_ERROR"
        assert path.read_bytes() == before
    finally:
        store.close()


def test_full_v1_validation_precedes_any_migration_ddl(tmp_path):
    from test_chat_tool_storage import setup_store

    from aiddos.api.chat_tool_storage import TABLES

    storage, _ = setup_store(tmp_path)
    path = storage.path
    storage.close()
    with sqlite3.connect(path) as db:
        for table in TABLES:
            db.execute(f"DROP TABLE {table}")
        db.execute("PRAGMA user_version=1")
        db.execute("UPDATE sessions SET data='{}'")
    before = path.read_bytes()
    store = ChatStorage(tmp_path / "draft.json")
    with pytest.raises(DraftError):
        store.open()
    assert path.read_bytes() == before
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (1,)


def test_migration_begins_before_ddl_and_rollback_preserves_v1(tmp_path, monkeypatch):
    path = v1_database(tmp_path)
    before = path.read_bytes()
    real_connect = sqlite3.connect
    trace, fired = [], []

    class Fault:
        def __init__(self, db):
            self.db = db
            db.set_trace_callback(trace.append)

        def __getattr__(self, name):
            return getattr(self.db, name)

        def execute(self, sql, *args):
            if sql.startswith("CREATE TABLE tool_calls"):
                fired.append(True)
                raise sqlite3.OperationalError("DDL fault")
            return self.db.execute(sql, *args)

    monkeypatch.setattr(sqlite3, "connect", lambda *a, **kw: Fault(real_connect(*a, **kw)))
    store = ChatStorage(tmp_path / "draft.json")
    with pytest.raises(DraftError):
        store.open()
    assert fired == [True]
    ddl_index = next(i for i, sql in enumerate(trace) if sql.startswith("CREATE TABLE"))
    assert any(sql.startswith("PRAGMA max_page_count=") for sql in trace[:ddl_index])
    assert trace.index("BEGIN IMMEDIATE") < next(
        i for i, sql in enumerate(trace) if sql.startswith("CREATE TABLE")
    )
    assert path.read_bytes() == before
    with real_connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (1,)
        assert (
            dict(db.execute("SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL")) == SCHEMA
        )


def test_migration_preserves_legacy_row_commitment_and_utf8_bytes(tmp_path):
    from test_chat_tool_storage import STAMP, admission, setup_store

    from aiddos.api.chat_tool_storage import TABLES, ToolLedger

    storage, session = setup_store(tmp_path)
    updated, turn, commitment = admission(session)
    storage.add_turn(updated, turn, commitment)
    turn.update(status="succeeded", assistant_text='한😀"', finished_at=STAMP, revision=2)
    storage.update_turn(turn)
    path = storage.path
    storage.close()
    with sqlite3.connect(path) as db:
        for table in TABLES:
            db.execute(f"DROP TABLE {table}")
        db.execute("PRAGMA user_version=1")
        # Old JSON and commitment bytes are valid but deliberately noncanonical.
        db.execute(
            "UPDATE turns SET commitment=?", (json.dumps(commitment, indent=2, ensure_ascii=True),)
        )
        before = {table: db.execute(f"SELECT * FROM {table}").fetchall() for table in SCHEMA}
    store = ChatStorage(tmp_path / "draft.json")
    try:
        store.open()
        after = {table: store.db.execute(f"SELECT * FROM {table}").fetchall() for table in SCHEMA}
        assert before == after
        assert store.db.execute("PRAGMA user_version").fetchone() == (2,)
        assert ToolLedger(store).transcript(turn["id"]) == dict(
            schema_version=1, turn_id=turn["id"], revision=0, calls=[]
        )
        assert store.replay("turns", turn["request_id"], commitment) == turn
        store.validate()
    finally:
        store.close()
