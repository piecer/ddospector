"""HTTP cancellation uses the existing API custodian and one PG transaction."""

from aiddos.api.scenarios import canonical

from .contracts import raw_json, require
from .http_detail import retained_detail
from .repository import begin, check_storage, commit, lookup, quota, timestamp
from .validation import TERMINAL


async def cancel(op, socket, run_id):
    await check_storage(op, socket)
    # A consistent preflight keeps missing/corrupt records ahead of arbitration
    # contention. Never publish it: reread under quota/job locks before deciding.
    await begin(op, read=True)
    found = await retained_detail(op, run_id)
    await quota(op)
    await commit(op)
    await begin(op)
    # Lock order is quota, then job. Integrity follows existence, not vice versa.
    await op.execute("SELECT singleton FROM aiddos_runs_v1.quota FOR UPDATE")
    await op.execute("SELECT run_id FROM aiddos_runs_v1.jobs WHERE run_id=%s FOR UPDATE", (run_id,))
    found = await retained_detail(op, run_id)
    await quota(op)
    run = raw_json(found[1])["run"]
    if run["state"] in TERMINAL or run["state"] == "CANCEL_REQUESTED":
        await commit(op)
        return (202 if run["state"] == "CANCEL_REQUESTED" else 200), found[1]
    # The clock is sampled inside the guarded DML after both locks and integrity.
    # No Python decision can carry a pre-wait deadline/lease sample across a wait.
    rows = await op.execute(
        "WITH clock AS MATERIALIZED (SELECT clock_timestamp() AS t), "
        "decision AS MATERIALIZED (SELECT t, CASE WHEN j.deadline_at<=t THEN 'TIMED_OUT' "
        "WHEN j.state='QUEUED' OR j.lease_until<=t THEN 'CANCELLED' "
        "ELSE 'CANCEL_REQUESTED' END AS next FROM aiddos_runs_v1.jobs j,clock "
        "WHERE j.run_id=%s) UPDATE aiddos_runs_v1.jobs j SET state=d.next,updated_at=d.t,"
        "event_count=j.event_count+1,"
        "finished_at=CASE WHEN d.next<>'CANCEL_REQUESTED' THEN d.t END,"
        "cancel_requested_at=CASE WHEN d.next<>'TIMED_OUT' THEN d.t END,"
        "failure_code=CASE WHEN d.next='TIMED_OUT' THEN 'DEADLINE_EXCEEDED' END,"
        "generation=j.generation+CASE WHEN j.state='RUNNING' AND d.next<>'CANCEL_REQUESTED' "
        "THEN 1 ELSE 0 END,"
        "owner_token=CASE WHEN d.next='CANCEL_REQUESTED' THEN j.owner_token END,"
        "lease_until=CASE WHEN d.next='CANCEL_REQUESTED' THEN j.lease_until END "
        "FROM decision d WHERE j.run_id=%s AND j.state=%s AND j.attempt=%s "
        "AND j.generation=%s AND j.event_count=%s "
        "RETURNING j.updated_at,j.event_count,j.attempt,j.generation,j.state",
        (run_id, run_id, run["state"], run["attempt"], run["generation"], run["event_count"]),
    )
    require(len(rows) == 1, "RUN_STATE_CORRUPT")
    at, seq, attempt, generation, state = rows[0]
    reason = None
    if state == "TIMED_OUT":
        reason = "DEADLINE_EXCEEDED"
    elif state == "CANCELLED":
        reason = "BEFORE_CLAIM" if run["state"] == "QUEUED" else "LEASE_REVOKED"
    event = {
        "seq": seq,
        "at": timestamp(at),
        "type": state,
        "state": state,
        "attempt": attempt,
        "generation": generation,
        "reason": reason,
    }
    require(len(canonical(event)) <= 512, "RUN_STATE_CORRUPT")
    await op.execute(
        "INSERT INTO aiddos_runs_v1.events VALUES(%s,%s,%s)", (run_id, seq, canonical(event))
    )
    if state != "CANCEL_REQUESTED":
        await op.execute(
            "UPDATE aiddos_runs_v1.quota SET unfinished_count=unfinished_count-1,"
            "leased_count=leased_count-%s",
            (int(run["state"] == "RUNNING"),),
        )
    result = await lookup(op, run_id)
    await quota(op)
    await commit(op, mutation=True)
    return (202 if state == "CANCEL_REQUESTED" else 200), result[1]
