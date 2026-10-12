"""HTTP cancellation vs independent SQL fixture transactions, NOT worker races."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import psycopg
from http_state_probe import claim, connect

from aiddos.api.scenarios import canonical
from aiddos.runs.repository import timestamp


def wait_blocked(reader):
    until = time.monotonic() + 0.4
    while True:
        rows = reader.execute(
            "SELECT pid,wait_event_type,query FROM pg_stat_activity WHERE "
            "datname=current_database() AND usename=current_user AND "
            "wait_event_type='Lock' AND query LIKE 'SELECT%%FOR UPDATE%%'"
        ).fetchall()
        if rows:
            return rows
        assert time.monotonic() < until, "SQL lock barrier did not fire"
        time.sleep(0.005)


def execute(request, value, queued, data):
    base = "/api/v1/offline-runs"
    evidence = []
    label = "SQL_FIXTURE_TRANSACTION_RACE_NOT_COMBINED_WORKER"

    def fresh():
        code, detail = request("POST", base, {**value, "request_id": str(uuid4())})
        assert code == 202
        claim(data, detail["run"]["id"])
        return detail["run"]["id"]

    # Completion-side transaction wins quota/job locks. No partial terminal is visible.
    run_id = queued["run"]["id"]
    claim(data, run_id)
    with (
        ThreadPoolExecutor(max_workers=1) as pool,
        connect(data) as writer,
        connect(data) as reader,
    ):
        with writer.transaction():
            writer.execute("SELECT * FROM aiddos_runs_v1.quota FOR UPDATE")
            writer.execute(
                "SELECT * FROM aiddos_runs_v1.jobs WHERE run_id=%s FOR UPDATE", (run_id,)
            )
            t = writer.execute("SELECT clock_timestamp()").fetchone()[0]
            writer.execute(
                "UPDATE aiddos_runs_v1.jobs SET "
                "state='FAILED',generation=2,event_count=3,updated_at=%s,finished_at=%s,o"
                "wner_token=NULL,lease_until=NULL,failure_code='OFFLINE_PREPARATION_FAILE"
                "D' WHERE run_id=%s",
                (t, t, run_id),
            )
            writer.execute(
                "INSERT INTO aiddos_runs_v1.events VALUES(%s,3,%s)",
                (
                    run_id,
                    canonical(
                        {
                            "seq": 3,
                            "at": timestamp(t),
                            "type": "FAILED",
                            "state": "FAILED",
                            "attempt": 1,
                            "generation": 2,
                            "reason": "OFFLINE_PREPARATION_FAILED",
                        }
                    ),
                ),
            )
            writer.execute(
                "UPDATE aiddos_runs_v1.quota SET "
                "unfinished_count=unfinished_count-1,leased_count=leased_count-1"
            )
            assert reader.execute(
                "SELECT state,event_count FROM aiddos_runs_v1.jobs WHERE run_id=%s", (run_id,)
            ).fetchone() == ("RUNNING", 2)
            assert reader.execute(
                "SELECT count(*) FROM aiddos_runs_v1.events WHERE run_id=%s", (run_id,)
            ).fetchone() == (2,)
            pending = pool.submit(
                request, "POST", base + "/" + run_id + "/cancel", {}, provenance=label
            )
            evidence.append({"order": "SQL_TERMINAL_FIRST", "blocked": wait_blocked(reader)})
        status, terminal = pending.result(timeout=5)
        assert status == 200 and terminal["run"]["state"] == "FAILED"
        assert terminal["run"]["event_count"] == 3
        assert request("POST", base + "/" + run_id + "/cancel", {}, provenance=label) == (
            200,
            terminal,
        )
        assert reader.execute(
            "SELECT unfinished_count,leased_count FROM aiddos_runs_v1.quota"
        ).fetchone() == (0, 0)
        # Cancel obtains quota while a row-only barrier holds its job lock.
        run_id = fresh()
        with writer.transaction():
            writer.execute(
                "SELECT * FROM aiddos_runs_v1.jobs WHERE run_id=%s FOR UPDATE", (run_id,)
            )
            pending = pool.submit(
                request, "POST", base + "/" + run_id + "/cancel", {}, provenance=label
            )
            evidence.append({"order": "CANCEL_FIRST", "blocked": wait_blocked(reader)})
            try:
                with reader.transaction():
                    reader.execute("SELECT * FROM aiddos_runs_v1.quota FOR UPDATE NOWAIT")
            except psycopg.errors.LockNotAvailable as exc:
                evidence[-1]["quota_owned_by_cancel_sqlstate"] = exc.sqlstate
            else:
                raise AssertionError("cancel did not acquire quota before job")
        status, intent = pending.result(timeout=5)
        assert status == 202 and intent["run"]["state"] == "CANCEL_REQUESTED"
        with writer.transaction():
            writer.execute("SELECT * FROM aiddos_runs_v1.quota FOR UPDATE")
            state = writer.execute(
                "SELECT state FROM aiddos_runs_v1.jobs WHERE run_id=%s FOR UPDATE", (run_id,)
            ).fetchone()[0]
            assert state == "CANCEL_REQUESTED"
            # Simulated stale SQL publisher guards RUNNING; no event/quota publication.
            assert (
                writer.execute(
                    "UPDATE aiddos_runs_v1.jobs SET step=step WHERE run_id=%s AND "
                    "state='RUNNING' RETURNING run_id",
                    (run_id,),
                ).fetchall()
                == []
            )
        assert request("GET", base + "/" + run_id, provenance=label) == (200, intent)
        # Lease is live at statement/transaction start, expires during an actual row lock wait.
        other = fresh()
        writer.execute(
            "UPDATE aiddos_runs_v1.jobs SET lease_until=clock_timestamp()+interval "
            "'0.2 seconds' WHERE run_id=%s",
            (other,),
        )
        with writer.transaction():
            writer.execute("SELECT * FROM aiddos_runs_v1.jobs WHERE run_id=%s FOR UPDATE", (other,))
            pending = pool.submit(
                request, "POST", base + "/" + other + "/cancel", {}, provenance=label
            )
            evidence.append({"order": "LEASE_EDGE_AFTER_ROW_WAIT", "blocked": wait_blocked(reader)})
            until = time.monotonic() + 0.35
            while not reader.execute(
                "SELECT lease_until<=clock_timestamp() FROM aiddos_runs_v1.jobs WHERE run_id=%s",
                (other,),
            ).fetchone()[0]:
                assert time.monotonic() < until
                time.sleep(0.005)
        status, revoked = pending.result(timeout=5)
        assert status == 200 and revoked["run"]["state"] == "CANCELLED"
        assert revoked["run"]["generation"] == 2
        # Actual quota lock timeout: API must not emit an event or partial update.
        code, untouched = request("POST", base, {**value, "request_id": str(uuid4())})
        assert code == 202
        with writer.transaction():
            writer.execute("SELECT * FROM aiddos_runs_v1.quota FOR UPDATE")
            code, error = request("POST", base + "/" + untouched["run"]["id"] + "/cancel", {})
            assert code == 429 and error["code"] == "RUN_BUSY"
        assert request("GET", base + "/" + untouched["run"]["id"]) == (200, untouched)
    (Path(data["output"]) / "sql-lock-witnesses.json").write_text(
        json.dumps(evidence, indent=2) + "\n"
    )
