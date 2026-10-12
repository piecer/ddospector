"""Explicit SQL fixtures; never presented as actual worker-produced states."""

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import psycopg

from aiddos.api.scenarios import canonical
from aiddos.runs.repository import timestamp
from tools import s02_harness as h


def connect(data, *, owner=False):
    return psycopg.connect(
        **h.connection_parameters(
            Path(data["socket"]), user="aiddos_s02_owner" if owner else "aiddos_s02"
        ),
        autocommit=True,
    )


def claim(data, run_id, *, expired=False):
    with connect(data) as db, db.transaction():
        db.execute("SELECT * FROM aiddos_runs_v1.quota FOR UPDATE")
        row = db.execute(
            "SELECT attempt,generation,event_count FROM aiddos_runs_v1.jobs WHERE "
            "run_id=%s FOR UPDATE",
            (run_id,),
        ).fetchone()
        t = db.execute("SELECT clock_timestamp()").fetchone()[0]
        attempt, generation, seq = (v + 1 for v in row)
        db.execute(
            "UPDATE aiddos_runs_v1.jobs SET "
            "state='RUNNING',attempt=%s,generation=%s,event_count=%s,started_at=coale"
            "sce(started_at,%s),updated_at=%s,owner_token=%s,lease_until=%s,step=0 "
            "WHERE run_id=%s",
            (
                attempt,
                generation,
                seq,
                t,
                t,
                str(uuid4()),
                t + timedelta(seconds=-1 if expired else 10),
                run_id,
            ),
        )
        db.execute(
            "INSERT INTO aiddos_runs_v1.events VALUES(%s,%s,%s)",
            (
                run_id,
                seq,
                canonical(
                    {
                        "seq": seq,
                        "at": timestamp(t),
                        "type": "CLAIMED",
                        "state": "RUNNING",
                        "attempt": attempt,
                        "generation": generation,
                        "reason": None,
                    }
                ),
            ),
        )
        db.execute("UPDATE aiddos_runs_v1.quota SET leased_count=leased_count+1")


def failed_snapshot(data, run_id):
    claim(data, run_id)
    with connect(data, owner=True) as db, db.transaction():
        db.execute("SELECT * FROM aiddos_runs_v1.quota FOR UPDATE")
        t = db.execute("SELECT clock_timestamp()").fetchone()[0]
        db.execute(
            "UPDATE aiddos_runs_v1.jobs SET "
            "state='FAILED',generation=2,event_count=3,updated_at=%s,finished_at=%s,f"
            "ailure_code='SNAPSHOT_INVALID',owner_token=NULL,lease_until=NULL WHERE "
            "run_id=%s",
            (t, t, run_id),
        )
        db.execute(
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
                        "reason": "SNAPSHOT_INVALID",
                    }
                ),
            ),
        )
        db.execute(
            "UPDATE aiddos_runs_v1.quota SET "
            "leased_count=leased_count-1,unfinished_count=unfinished_count-1"
        )
        db.execute("ALTER TABLE aiddos_runs_v1.inputs DISABLE TRIGGER inputs_immutable")
        db.execute("UPDATE aiddos_runs_v1.inputs SET snapshot=%s WHERE run_id=%s", (b"{}", run_id))
        db.execute("ALTER TABLE aiddos_runs_v1.inputs ENABLE TRIGGER inputs_immutable")
