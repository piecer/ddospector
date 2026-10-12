"""SQL-seeded valid terminal traces; explicitly not separate-worker production."""

import json
from uuid import uuid4

from http_state_probe import connect

from aiddos.api.scenarios import canonical
from aiddos.runs.offline import compile_manifest
from aiddos.runs.repository import timestamp


def seed(data, detail, state):
    run_id = detail["run"]["id"]
    with connect(data) as db, db.transaction():
        db.execute("SELECT * FROM aiddos_runs_v1.quota FOR UPDATE")
        db.execute("SELECT run_id FROM aiddos_runs_v1.jobs WHERE run_id=%s FOR UPDATE", (run_id,))
        t = db.execute("SELECT clock_timestamp()").fetchone()[0]
        seq, generation = 1, 0
        for attempt in (1, 2, 3):
            generation += 1
            for kind in ("CLAIMED", "SNAPSHOT_VERIFIED", "MANIFEST_COMPILED"):
                seq += 1
                event = {
                    "seq": seq,
                    "at": timestamp(t),
                    "type": kind,
                    "state": "RUNNING",
                    "attempt": attempt,
                    "generation": generation,
                    "reason": None,
                }
                db.execute(
                    "INSERT INTO aiddos_runs_v1.events VALUES(%s,%s,%s)",
                    (run_id, seq, canonical(event)),
                )
            generation += 1
            seq += 1
            kind = "REQUEUED" if attempt < 3 else state
            next_state = "QUEUED" if attempt < 3 else state
            reason = (
                "LEASE_EXPIRED"
                if attempt < 3
                else ("RETRY_EXHAUSTED" if state == "FAILED" else None)
            )
            event = {
                "seq": seq,
                "at": timestamp(t),
                "type": kind,
                "state": next_state,
                "attempt": attempt,
                "generation": generation,
                "reason": reason,
            }
            db.execute(
                "INSERT INTO aiddos_runs_v1.events VALUES(%s,%s,%s)",
                (run_id, seq, canonical(event)),
            )
        assert seq == 13 and generation == 6
        db.execute(
            "UPDATE aiddos_runs_v1.jobs SET "
            "state=%s,attempt=3,generation=6,event_count=13,started_at=%s,updated_at="
            "%s,finished_at=%s,failure_code=%s,step=2 WHERE run_id=%s",
            (state, t, t, t, "RETRY_EXHAUSTED" if state == "FAILED" else None, run_id),
        )
        if state == "SUCCEEDED":
            db.execute(
                "INSERT INTO aiddos_runs_v1.results VALUES(%s,%s)",
                (run_id, compile_manifest(detail["snapshot"])),
            )
        db.execute("UPDATE aiddos_runs_v1.quota SET unfinished_count=unfinished_count-1")


def execute(request, value, queued, data):
    base = "/api/v1/offline-runs"
    for state in ("SUCCEEDED", "FAILED"):
        if state == "FAILED":
            code, queued = request("POST", base, {**value, "request_id": str(uuid4())})
            assert code == 202
        seed(data, queued, state)
        path = base + "/" + queued["run"]["id"]
        label = "SQL_SEEDED_THREE_ATTEMPT_TERMINAL_NOT_WORKER"
        status, detail = request("GET", path, provenance=label)
        assert status == 200 and detail["run"]["state"] == state
        if state == "SUCCEEDED":
            assert detail["result"]["evaluation"] == "NOT_EVALUATED"
            assert detail["result"]["defense_verdict"] is detail["result"]["measurements"] is None
        else:
            assert detail["result"] is None and detail["run"]["failure_code"] == "RETRY_EXHAUSTED"
        for _ in range(3):
            assert request("POST", path + "/cancel", {}, provenance=label) == (200, detail)
        seqs = []
        after = 0
        while after is not None:
            status, page = request("GET", path + f"/events?after={after}&limit=3", provenance=label)
            assert status == 200 and page["total"] == 13
            seqs.extend(event["seq"] for event in page["items"])
            after = page["next_after"]
        assert seqs == list(range(1, 14))
        assert request("GET", path + "/events?after=16", provenance=label)[1]["items"] == []
        with connect(data) as db:
            raw = db.execute(
                "SELECT event FROM aiddos_runs_v1.events WHERE run_id=%s ORDER BY seq",
                (queued["run"]["id"],),
            ).fetchall()
            assert [json.loads(row[0])["seq"] for row in raw] == seqs
    code, page = request("GET", base, provenance="SQL_SEEDED_TERMINAL_SUMMARIES")
    assert code == 200 and [row["state"] for row in page["items"]] == ["SUCCEEDED", "FAILED"]
