"""Quota-first, single-transaction worker publication over exact claim tuples."""

from uuid import uuid4

from aiddos.api.errors import DraftError
from aiddos.api.scenarios import canonical

from .contracts import identifier
from .repository import begin, commit, quota, timestamp


class StaleClaim(Exception):
    """The caller owns no publication authority; never clean up another owner."""


async def recover(op):
    candidates = await op.execute(
        "SELECT j.run_id FROM aiddos_runs_v1.jobs j JOIN aiddos_runs_v1.inputs i "
        "ON i.run_id=j.run_id WHERE (j.state IN ('RUNNING','CANCEL_REQUESTED') "
        "AND j.lease_until<=clock_timestamp()) "
        "OR (j.state IN ('RUNNING','QUEUED') AND j.deadline_at<=clock_timestamp()) "
        "ORDER BY i.ordinal LIMIT 16"
    )
    for (run_id,) in candidates:
        op.affected = run_id
        await begin(op)
        await quota(op, lock=True)
        await op.execute(
            "SELECT run_id FROM aiddos_runs_v1.jobs WHERE run_id=%s FOR UPDATE", (run_id,)
        )
        cancelled = await op.execute(
            "WITH t AS (SELECT clock_timestamp() AS at) UPDATE aiddos_runs_v1.jobs j "
            "SET state='CANCELLED',generation=generation+1,owner_token=NULL,lease_until=NULL,"
            "finished_at=t.at,updated_at=t.at,event_count=event_count+1 FROM t "
            "WHERE run_id=%s AND state='CANCEL_REQUESTED' AND lease_until<=t.at "
            "RETURNING attempt,generation,updated_at,event_count",
            (run_id,),
        )
        if cancelled:
            attempt, generation, at, seq = cancelled[0]
            event = {
                "seq": seq,
                "at": timestamp(at),
                "type": "CANCELLED",
                "state": "CANCELLED",
                "attempt": attempt,
                "generation": generation,
                "reason": "LEASE_REVOKED",
            }
            await op.execute(
                "INSERT INTO aiddos_runs_v1.events VALUES(%s,%s,%s)",
                (run_id, seq, canonical(event)),
            )
            await op.execute(
                "UPDATE aiddos_runs_v1.quota SET leased_count=leased_count-1,"
                "unfinished_count=unfinished_count-1"
            )
            await commit(op, mutation=True)
            continue
        expired = await op.execute(
            "WITH t AS (SELECT clock_timestamp() AS at), old AS ("
            "SELECT run_id,state IN ('RUNNING','CANCEL_REQUESTED') AS owned "
            "FROM aiddos_runs_v1.jobs WHERE run_id=%s) "
            "UPDATE aiddos_runs_v1.jobs j SET state='TIMED_OUT',"
            "generation=generation+old.owned::integer,owner_token=NULL,lease_until=NULL,"
            "failure_code='DEADLINE_EXCEEDED',finished_at=t.at,updated_at=t.at,"
            "event_count=event_count+1 FROM t,old WHERE j.run_id=old.run_id "
            "AND j.state IN ('QUEUED','RUNNING') AND j.deadline_at<=t.at "
            "RETURNING attempt,generation,updated_at,event_count,old.owned",
            (run_id,),
        )
        if expired:
            attempt, generation, at, seq, owned = expired[0]
            event = {
                "seq": seq,
                "at": timestamp(at),
                "type": "TIMED_OUT",
                "state": "TIMED_OUT",
                "attempt": attempt,
                "generation": generation,
                "reason": "DEADLINE_EXCEEDED",
            }
            await op.execute(
                "INSERT INTO aiddos_runs_v1.events VALUES(%s,%s,%s)",
                (run_id, seq, canonical(event)),
            )
            await op.execute(
                "UPDATE aiddos_runs_v1.quota SET leased_count=leased_count-%s,"
                "unfinished_count=unfinished_count-1",
                (int(owned),),
            )
            await commit(op, mutation=True)
            continue
        changed = await op.execute(
            "WITH t AS (SELECT clock_timestamp() AS at) UPDATE aiddos_runs_v1.jobs j "
            "SET state=CASE WHEN attempt=3 THEN 'FAILED' ELSE 'QUEUED' END,"
            "generation=generation+1,owner_token=NULL,lease_until=NULL,"
            "failure_code=CASE WHEN attempt=3 THEN 'RETRY_EXHAUSTED' ELSE NULL END,"
            "finished_at=CASE WHEN attempt=3 THEN t.at ELSE NULL END,"
            "step=CASE WHEN attempt=3 THEN step ELSE 0 END,"
            "updated_at=t.at,event_count=event_count+1 FROM t "
            "WHERE run_id=%s AND state='RUNNING' AND lease_until<=t.at AND deadline_at>t.at "
            "RETURNING attempt,generation,updated_at,event_count",
            (run_id,),
        )
        if changed:
            attempt, generation, at, seq = changed[0]
            exhausted = attempt == 3
            event = {
                "seq": seq,
                "at": timestamp(at),
                "type": "FAILED" if exhausted else "REQUEUED",
                "state": "FAILED" if exhausted else "QUEUED",
                "attempt": attempt,
                "generation": generation,
                "reason": "RETRY_EXHAUSTED" if exhausted else "LEASE_EXPIRED",
            }
            await op.execute(
                "INSERT INTO aiddos_runs_v1.events VALUES(%s,%s,%s)",
                (run_id, seq, canonical(event)),
            )
            await op.execute(
                "UPDATE aiddos_runs_v1.quota SET leased_count=leased_count-1,"
                "unfinished_count=unfinished_count-%s",
                (int(exhausted),),
            )
        await commit(op, mutation=bool(changed))


async def claim(op, *, run_id=None):
    if run_id is not None:
        identifier(run_id)
    await begin(op)
    counts = await quota(op, lock=True)
    if counts[2] >= (2 if run_id is None else 1):
        await commit(op)
        return None
    selection = "" if run_id is None else "AND j.run_id=%s AND j.attempt=0 "
    rows = await op.execute(
        "SELECT j.run_id,i.snapshot,i.request,i.request_digest,i.snapshot_digest,i.request_id "
        "FROM aiddos_runs_v1.jobs j JOIN aiddos_runs_v1.inputs i "
        "ON i.run_id=j.run_id WHERE j.state='QUEUED' AND j.attempt<3 "
        + selection
        + "AND j.deadline_at>clock_timestamp() ORDER BY i.ordinal LIMIT 1 "
        "FOR UPDATE OF j SKIP LOCKED",
        None if run_id is None else (run_id,),
    )
    if not rows:
        await commit(op)
        return None
    run_id = rows[0][0]
    op.affected = run_id
    token = uuid4()
    changed = await op.execute(
        "WITH t AS (SELECT clock_timestamp() AS at) UPDATE aiddos_runs_v1.jobs j "
        "SET state='RUNNING',attempt=attempt+1,generation=generation+1,"
        "owner_token=%s,lease_until=t.at+interval '10 seconds',step=0,"
        "started_at=coalesce(started_at,t.at),updated_at=t.at,event_count=event_count+1 "
        "FROM t WHERE j.run_id=%s AND state='QUEUED' AND deadline_at>t.at "
        "AND attempt<3 RETURNING attempt,generation,updated_at,event_count",
        (token, run_id),
    )
    if not changed:
        raise StaleClaim()
    attempt, generation, at, seq = changed[0]
    event = {
        "seq": seq,
        "at": timestamp(at),
        "type": "CLAIMED",
        "state": "RUNNING",
        "attempt": attempt,
        "generation": generation,
        "reason": None,
    }
    await op.execute(
        "INSERT INTO aiddos_runs_v1.events VALUES(%s,%s,%s)", (run_id, seq, canonical(event))
    )
    await op.execute("UPDATE aiddos_runs_v1.quota SET leased_count=leased_count+1")
    await commit(op, mutation=True)
    return {
        "run_id": run_id,
        "attempt": attempt,
        "generation": generation,
        "owner_token": token,
        "snapshot": rows[0][1],
        "request": rows[0][2],
        "request_digest": rows[0][3],
        "snapshot_digest": rows[0][4],
        "request_id": str(rows[0][5]),
    }


async def heartbeat(op, owned):
    await begin(op)
    await quota(op, lock=True)
    rows = await op.execute(
        "SELECT state,attempt,generation,owner_token,lease_until,deadline_at "
        "FROM aiddos_runs_v1.jobs WHERE run_id=%s FOR UPDATE",
        (owned["run_id"],),
    )
    now = (await op.execute("SELECT clock_timestamp()"))[0][0]
    if (
        not rows
        or rows[0][0] not in {"RUNNING", "CANCEL_REQUESTED"}
        or rows[0][1:4] != (owned["attempt"], owned["generation"], owned["owner_token"])
        or rows[0][4] <= now
    ):
        raise StaleClaim()
    if rows[0][0] == "CANCEL_REQUESTED" or rows[0][5] <= now:
        await commit(op)
        return False
    changed = await op.execute(
        "WITH t AS (SELECT clock_timestamp() AS at) UPDATE aiddos_runs_v1.jobs j "
        "SET lease_until=t.at+interval '10 seconds' FROM t "
        "WHERE run_id=%s AND state='RUNNING' AND attempt=%s AND generation=%s "
        "AND owner_token=%s AND lease_until>t.at AND deadline_at>t.at RETURNING run_id",
        (owned["run_id"], owned["attempt"], owned["generation"], owned["owner_token"]),
    )
    if not changed:
        raise StaleClaim()
    await commit(op, mutation=True)


async def publish(op, owned, step, result=None, *, failure=None):
    if failure is not None and failure not in {
        "SNAPSHOT_INVALID",
        "OFFLINE_PREPARATION_FAILED",
        "RESULT_LIMIT_EXCEEDED",
    }:
        raise ValueError("WORKER_FAILURE_CODE")
    if step == 3:
        from .offline import compile_manifest, verify

        def validate_result():
            if result != compile_manifest(verify(owned["snapshot"])):
                raise DraftError("RUN_STATE_CORRUPT")

        await op.compute(validate_result)
    await begin(op)
    await quota(op, lock=True)
    rows = await op.execute(
        "SELECT state,attempt,generation,owner_token,lease_until,deadline_at,step "
        "FROM aiddos_runs_v1.jobs WHERE run_id=%s FOR UPDATE",
        (owned["run_id"],),
    )
    if not rows:
        raise StaleClaim()
    row = rows[0]
    now = (await op.execute("SELECT clock_timestamp()"))[0][0]
    if (
        row[0] not in {"RUNNING", "CANCEL_REQUESTED"}
        or row[1:4] != (owned["attempt"], owned["generation"], owned["owner_token"])
        or row[4] <= now
    ):
        raise StaleClaim()
    if row[0] == "CANCEL_REQUESTED" or row[5] <= now or failure is not None:
        cancelled = row[0] == "CANCEL_REQUESTED"
        timed_out = row[5] <= now
        state = "CANCELLED" if cancelled else ("TIMED_OUT" if timed_out else "FAILED")
        reason = "WORKER_ACK" if cancelled else ("DEADLINE_EXCEEDED" if timed_out else failure)
        changed = await op.execute(
            "WITH t AS (SELECT clock_timestamp() AS at) UPDATE aiddos_runs_v1.jobs j "
            "SET state=%s,failure_code=%s,generation=generation+1,"
            "owner_token=NULL,lease_until=NULL,"
            "finished_at=t.at,updated_at=t.at,event_count=event_count+1 FROM t "
            "WHERE run_id=%s AND state=%s AND attempt=%s AND generation=%s "
            "AND owner_token=%s AND lease_until>t.at "
            "AND (%s OR (%s AND deadline_at<=t.at) OR (%s AND deadline_at>t.at)) "
            "RETURNING attempt,generation,updated_at,event_count",
            (
                state,
                None if cancelled else reason,
                owned["run_id"],
                row[0],
                owned["attempt"],
                owned["generation"],
                owned["owner_token"],
                cancelled,
                timed_out,
                not cancelled and not timed_out,
            ),
        )
        if not changed:
            raise StaleClaim()
        attempt, generation, at, seq = changed[0]
        event = {
            "seq": seq,
            "at": timestamp(at),
            "type": state,
            "state": state,
            "attempt": attempt,
            "generation": generation,
            "reason": reason,
        }
        await op.execute(
            "INSERT INTO aiddos_runs_v1.events VALUES(%s,%s,%s)",
            (owned["run_id"], seq, canonical(event)),
        )
        await op.execute(
            "UPDATE aiddos_runs_v1.quota SET unfinished_count=unfinished_count-1,"
            "leased_count=leased_count-1"
        )
        await commit(op, mutation=True)
        return False
    if row[5] <= now:
        raise StaleClaim()
    if row[6] != step - 1:
        raise DraftError("RUN_STATE_CORRUPT")
    terminal = step == 3
    kind = "SUCCEEDED" if terminal else ("SNAPSHOT_VERIFIED" if step == 1 else "MANIFEST_COMPILED")
    changes = (
        "state='SUCCEEDED',generation=generation+1,owner_token=NULL,lease_until=NULL,"
        "finished_at=t.at,"
        if terminal
        else "step=%s,"
    )
    args = (() if terminal else (step,)) + (
        owned["run_id"],
        owned["attempt"],
        owned["generation"],
        owned["owner_token"],
    )
    updated = await op.execute(
        "WITH t AS (SELECT clock_timestamp() AS at) UPDATE aiddos_runs_v1.jobs j SET "
        + changes
        + "updated_at=t.at,event_count=event_count+1 FROM t "
        "WHERE run_id=%s AND state='RUNNING' AND attempt=%s AND generation=%s "
        "AND owner_token=%s AND lease_until>t.at AND deadline_at>t.at "
        "RETURNING attempt,generation,updated_at,event_count",
        args,
    )
    if not updated:
        raise StaleClaim()
    attempt, generation, at, seq = updated[0]
    event = {
        "seq": seq,
        "at": timestamp(at),
        "type": kind,
        "state": "SUCCEEDED" if terminal else "RUNNING",
        "attempt": attempt,
        "generation": generation,
        "reason": None,
    }
    await op.execute(
        "INSERT INTO aiddos_runs_v1.events VALUES(%s,%s,%s)",
        (owned["run_id"], seq, canonical(event)),
    )
    if terminal:
        await op.execute(
            "INSERT INTO aiddos_runs_v1.results VALUES(%s,%s)", (owned["run_id"], result)
        )
        await op.execute(
            "UPDATE aiddos_runs_v1.quota SET unfinished_count=unfinished_count-1,"
            "leased_count=leased_count-1"
        )
    await commit(op, mutation=True)
