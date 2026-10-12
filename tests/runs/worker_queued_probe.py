"""An explicitly SQL-seeded valid BEFORE_CLAIM terminal fixture."""

import json
import sys
import time
from pathlib import Path

from worker_lifecycle_probe import child, connect, h, save, seed


def main(data):
    assert h.identity_of(data["owner"]["pid"]) == data["owner"]
    with child(data, "migration", [sys.executable, "-m", "aiddos.runs.migrate"]) as process:
        assert process.wait(timeout=8) == 0
    seed(data)
    from aiddos.api.scenarios import canonical
    from aiddos.runs.repository import timestamp

    with connect(data) as db:
        with db.transaction():
            db.execute("SELECT * FROM aiddos_runs_v1.quota FOR UPDATE")
            db.execute("SELECT * FROM aiddos_runs_v1.jobs FOR UPDATE")
            row = db.execute(
                "WITH t AS (SELECT clock_timestamp() AS at) UPDATE aiddos_runs_v1.jobs j "
                "SET state='CANCELLED',cancel_requested_at=t.at,finished_at=t.at,"
                "updated_at=t.at,event_count=event_count+1 FROM t "
                "WHERE state='QUEUED' AND deadline_at>t.at RETURNING run_id,event_count,updated_at"
            ).fetchone()
            run_id, seq, at = row
            event = {
                "seq": seq,
                "at": timestamp(at),
                "type": "CANCELLED",
                "state": "CANCELLED",
                "attempt": 0,
                "generation": 0,
                "reason": "BEFORE_CLAIM",
            }
            db.execute(
                "INSERT INTO aiddos_runs_v1.events VALUES(%s,%s,%s)",
                (run_id, seq, canonical(event)),
            )
            db.execute("UPDATE aiddos_runs_v1.quota SET unfinished_count=unfinished_count-1")
        before = db.execute("SELECT * FROM aiddos_runs_v1.jobs").fetchall()
        with child(data, "worker", [sys.executable, "-m", "aiddos.runs.worker"]):
            time.sleep(1.3)
            assert db.execute("SELECT * FROM aiddos_runs_v1.jobs").fetchall() == before
            assert db.execute(
                "SELECT attempt,generation,event_count FROM aiddos_runs_v1.jobs"
            ).fetchone() == (0, 0, 2)
            assert db.execute("SELECT count(*) FROM aiddos_runs_v1.results").fetchone()[0] == 0
            assert db.execute(
                "SELECT unfinished_count,leased_count FROM aiddos_runs_v1.quota"
            ).fetchone() == (0, 0)
    save(
        Path(data["output"]) / "result.json",
        {"unchanged": True, "kind": "SQL_SEEDED_BEFORE_CLAIM_NOT_HTTP_CANCELLATION"},
    )


if __name__ == "__main__":
    main(json.loads(Path(sys.argv[1]).read_text()))
