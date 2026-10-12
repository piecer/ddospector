"""Injected event-write barrier on actual cancellation SQL; no synthetic PG state."""

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
from http_state_probe import connect


def install(data):
    output = Path(data["output"])
    native = psycopg.AsyncConnection.execute

    async def execute(connection, query, *args, **kwargs):
        arm = output / "atomic-arm"
        if (
            arm.exists()
            and isinstance(query, str)
            and query.startswith("INSERT INTO aiddos_runs_v1.events")
        ):
            number = arm.read_text()
            arm.unlink()
            (output / ("atomic-entered-" + number)).write_text(
                "after guarded job UPDATE before event INSERT\n"
            )
            until = time.monotonic() + 1
            while not (output / ("atomic-release-" + number)).exists():
                assert time.monotonic() < until
                await asyncio.sleep(0.005)
            if number == "1":
                raise psycopg.OperationalError("injected event insertion failure")
        return await native(connection, query, *args, **kwargs)

    psycopg.AsyncConnection.execute = execute


def install_uncertain(data):
    from psycopg.transaction import AsyncTransaction

    output = Path(data["output"])
    native_execute = psycopg.AsyncConnection.execute
    native_exit = AsyncTransaction.__aexit__
    dirty = set()

    async def sql(connection, query, *args, **kwargs):
        result = await native_execute(connection, query, *args, **kwargs)
        if isinstance(query, str) and query.startswith("WITH clock AS MATERIALIZED"):
            dirty.add(id(connection))
        return result

    async def exit_tx(transaction, typ, exc, tb):
        result = await native_exit(transaction, typ, exc, tb)
        if typ is None and id(transaction.connection) in dirty:
            dirty.remove(id(transaction.connection))
            (output / "commit-ack-fault-fired").write_text(
                "native COMMIT completed before injected lost acknowledgement\n"
            )
            raise psycopg.OperationalError("injected lost commit acknowledgement")
        return result

    psycopg.AsyncConnection.execute = sql
    AsyncTransaction.__aexit__ = exit_tx


def uncertain(request, value, queued, data):
    base = "/api/v1/offline-runs/" + queued["run"]["id"]
    status, error = request(
        "POST", base + "/cancel", {}, provenance="INJECTED_ACK_LOSS_AFTER_REAL_CANCEL_COMMIT"
    )
    assert status == 503 and error["code"] == "RUN_COMMIT_UNCERTAIN"
    assert (Path(data["output"]) / "commit-ack-fault-fired").exists()
    status, detail = request("GET", base)
    assert status == 200 and detail["run"]["state"] == "CANCELLED"
    assert detail["run"]["event_count"] == 2
    assert request("POST", base + "/cancel", {}) == (200, detail)
    with connect(data) as db:
        assert db.execute(
            "SELECT unfinished_count,leased_count FROM aiddos_runs_v1.quota"
        ).fetchone() == (0, 0)
        assert db.execute("SELECT count(*) FROM aiddos_runs_v1.events").fetchone() == (2,)


def execute(request, value, queued, data):
    output = Path(data["output"])
    base = "/api/v1/offline-runs/" + queued["run"]["id"]
    observed = []
    with ThreadPoolExecutor(max_workers=1) as pool, connect(data) as db:
        for number in ("1", "2"):
            (output / "atomic-arm").write_text(number)
            pending = pool.submit(
                request,
                "POST",
                base + "/cancel",
                {},
                provenance="INJECTED_EVENT_WRITE_BARRIER_REAL_PG_TRANSACTION",
            )
            try:
                until = time.monotonic() + 0.8
                while not (output / ("atomic-entered-" + number)).exists():
                    assert time.monotonic() < until and not pending.done()
                    time.sleep(0.005)
                rows = db.execute("SELECT state,event_count FROM aiddos_runs_v1.jobs").fetchall()
                counts = db.execute(
                    "SELECT unfinished_count,leased_count FROM aiddos_runs_v1.quota"
                ).fetchone()
                events = db.execute("SELECT count(*) FROM aiddos_runs_v1.events").fetchone()
                assert rows == [("QUEUED", 1)] and counts == (1, 0) and events == (1,)
                observed.append(
                    {"number": number, "rows": rows, "counts": counts, "events": events}
                )
            finally:
                (output / ("atomic-release-" + number)).write_text("release\n")
            status, body = pending.result(timeout=5)
            if number == "1":
                assert status == 503 and body["code"] == "RUN_DB_UNAVAILABLE"
                assert request("GET", base) == (200, queued)
                assert db.execute("SELECT count(*) FROM aiddos_runs_v1.events").fetchone() == (1,)
            else:
                assert status == 200 and body["run"]["state"] == "CANCELLED"
                assert db.execute(
                    "SELECT state,event_count FROM aiddos_runs_v1.jobs"
                ).fetchall() == [("CANCELLED", 2)]
                assert db.execute(
                    "SELECT unfinished_count,leased_count FROM aiddos_runs_v1.quota"
                ).fetchone() == (0, 0)
                assert db.execute("SELECT count(*) FROM aiddos_runs_v1.events").fetchone() == (2,)
    (output / "atomic-reader.json").write_text(json.dumps(observed, indent=2) + "\n")
