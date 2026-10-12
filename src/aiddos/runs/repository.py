"""PostgreSQL storage admission. No migrations on a request path."""

import hashlib
from datetime import timedelta
from uuid import uuid4

from aiddos.api.errors import DraftError
from aiddos.api.scenarios import ScenarioVersion, canonical, record_digest

from . import schema
from .config import driver, parameters
from .contracts import identifier, raw_json, request_value
from .validation import check, validate


async def check_storage(operation, socket):
    kwargs = parameters(socket)
    pg = driver()
    try:
        await operation.call(
            lambda: pg.AsyncConnection.connect(**kwargs, autocommit=True), connect=True
        )
        await schema.settings(operation.execute)
        await schema.ready(operation.execute)
    except (pg.errors.UndefinedTable, pg.errors.UndefinedColumn):
        raise DraftError("RUN_DB_NOT_READY") from None
    except pg.Error:
        raise DraftError("RUN_DB_UNAVAILABLE") from None


def timestamp(value):
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


async def begin(op, *, read=False):
    op.transaction = op.connection.transaction()
    await op.call(op.transaction.__aenter__)
    await op.execute(
        "SET TRANSACTION ISOLATION LEVEL "
        + ("REPEATABLE READ READ ONLY" if read else "READ COMMITTED")
    )


async def commit(op, *, mutation=False):
    op.checkpoint()
    tx = op.transaction
    op.transaction = None
    await op.call(lambda: tx.__aexit__(None, None, None), commit=mutation)


async def quota(op, *, lock=False):
    rows = await op.execute(
        "SELECT retained_count,unfinished_count,leased_count,reserved_bytes "
        "FROM aiddos_runs_v1.quota" + (" FOR UPDATE" if lock else "")
    )
    counts = (
        await op.execute(
            "SELECT count(*),count(*) FILTER (WHERE state IN "
            "('QUEUED','RUNNING','CANCEL_REQUESTED')),count(*) FILTER "
            "(WHERE state IN ('RUNNING','CANCEL_REQUESTED')) "
            "FROM aiddos_runs_v1.jobs"
        )
    )[0]
    inputs = (
        await op.execute("SELECT count(*),coalesce(max(ordinal),0) FROM aiddos_runs_v1.inputs")
    )[0]
    events = (await op.execute("SELECT count(*) FROM aiddos_runs_v1.events"))[0][0]
    event_count = (
        await op.execute("SELECT coalesce(sum(event_count),0) FROM aiddos_runs_v1.jobs")
    )[0][0]
    if (
        len(rows) != 1
        or rows[0] != (*counts, counts[0] * 65536)
        or inputs != (counts[0], counts[0])
        or events != event_count
        or events > 2048
    ):
        raise DraftError("RUN_STATE_CORRUPT")
    return rows[0]


async def lookup(op, value, *, by_request=False):
    rows = await op.execute(
        "SELECT i.run_id,i.request_id,i.ordinal,i.request,i.request_digest,i.snapshot,"
        "i.snapshot_digest,j.state,j.attempt,j.generation,j.created_at,j.started_at,"
        "j.updated_at,j.finished_at,j.deadline_at,j.cancel_requested_at,j.event_count,"
        "j.failure_code,j.owner_token,j.lease_until,j.step,r.result "
        "FROM aiddos_runs_v1.inputs i JOIN aiddos_runs_v1.jobs j ON j.run_id=i.run_id "
        "LEFT JOIN aiddos_runs_v1.results r ON r.run_id=i.run_id WHERE i."
        + ("request_id" if by_request else "run_id")
        + "=%s",
        (value,),
    )
    if not rows:
        return None
    row = rows[0]
    try:
        request = request_value(row[3])
        snapshot = raw_json(row[5])
        check(canonical(request) == row[3] and request["mode"] == "OFFLINE")
        check(hashlib.sha256(row[3]).hexdigest() == row[4])
        check(canonical(snapshot) == row[5] and len(row[5]) <= 12288)
        check(set(snapshot) == {"schema_version", "task", "source_revision", "scenario", "digest"})
        check(type(snapshot["schema_version"]) is int and snapshot["schema_version"] == 1)
        check(snapshot["task"] == "offline_manifest_v1")
        scenario = snapshot["scenario"]
        ScenarioVersion.model_validate(scenario)
        check(snapshot["digest"] == record_digest(snapshot) == row[6])
        check(type(snapshot["source_revision"]) is int)
        check(scenario["version"] <= snapshot["source_revision"] <= 1000)
        check(
            (scenario["id"], scenario["version"], scenario["digest"])
            == (request["scenario_id"], request["scenario_version"], request["scenario_digest"])
        )
        check(str(row[1]) == request["request_id"])
        identifier(str(row[0]))
        keys = (
            "state",
            "attempt",
            "generation",
            "created_at",
            "started_at",
            "updated_at",
            "finished_at",
            "deadline_at",
            "cancel_requested_at",
            "event_count",
            "failure_code",
        )
        summary = dict(zip(keys, row[7:18], strict=True))
        for key in keys:
            if key.endswith("_at") and summary[key] is not None:
                summary[key] = timestamp(summary[key])
        summary.update(
            id=str(row[0]),
            request_id=str(row[1]),
            ordinal=row[2],
            mode="OFFLINE",
            task="offline_manifest_v1",
            scenario_id=scenario["id"],
            scenario_version=scenario["version"],
            scenario_digest=scenario["digest"],
            snapshot_digest=snapshot["digest"],
        )
        check(row[14] == row[10] + timedelta(seconds=300))
        check(row[12] >= row[10] and 1 <= row[2] <= 128)
        events = await op.execute(
            "SELECT seq,event FROM aiddos_runs_v1.events WHERE run_id=%s ORDER BY seq", (row[0],)
        )
        result = validate(summary, events, row[18], row[19], row[20], row[21], snapshot)
        detail = {"schema_version": 1, "run": summary, "snapshot": snapshot, "result": result}
        body = canonical(detail)
        check(len(canonical(summary)) <= 4096 and len(body) <= 32768)
        return row[3], body
    except (ValueError, TypeError, KeyError, AssertionError, DraftError):
        raise DraftError("RUN_STATE_CORRUPT") from None


async def get(op, socket, value, *, by_request=False):
    await check_storage(op, socket)
    await begin(op, read=True)
    found = await lookup(op, value, by_request=by_request)
    if found is None:
        raise DraftError("RUN_NOT_FOUND")
    await quota(op)
    await commit(op)
    return 200, found[1]


async def replay(op, request):
    found = await lookup(op, request["request_id"], by_request=True)
    if found is not None:
        if found[0] != canonical(request):
            raise DraftError("RUN_IDEMPOTENCY_CONFLICT")
        return 200, found[1]
    return None


async def create(op, socket, peer, request):
    await check_storage(op, socket)
    await begin(op, read=True)
    found = await replay(op, request)
    await commit(op)
    if found is not None:
        return found
    snapshot = await op.capture(peer, request)
    raw_request, raw_snapshot = canonical(request), canonical(snapshot)
    await begin(op)
    counts = await quota(op, lock=True)
    found = await replay(op, request)
    if found is not None:
        await commit(op)
        return found
    if counts[0] >= 128:
        raise DraftError("RUN_RETENTION_FULL")
    if counts[1] >= 16:
        raise DraftError("RUN_QUEUE_FULL")
    now = (await op.execute("SELECT clock_timestamp()"))[0][0]
    run_id = str(uuid4())
    summary = {
        "id": run_id,
        "request_id": request["request_id"],
        "ordinal": counts[0] + 1,
        "mode": "OFFLINE",
        "task": "offline_manifest_v1",
        "state": "QUEUED",
        "attempt": 0,
        "generation": 0,
        "scenario_id": request["scenario_id"],
        "scenario_version": request["scenario_version"],
        "scenario_digest": request["scenario_digest"],
        "snapshot_digest": snapshot["digest"],
        "created_at": timestamp(now),
        "started_at": None,
        "updated_at": timestamp(now),
        "finished_at": None,
        "deadline_at": timestamp(now + timedelta(seconds=300)),
        "cancel_requested_at": None,
        "event_count": 1,
        "failure_code": None,
    }
    detail = {"schema_version": 1, "run": summary, "snapshot": snapshot, "result": None}
    event = {
        "seq": 1,
        "at": timestamp(now),
        "type": "QUEUED",
        "state": "QUEUED",
        "attempt": 0,
        "generation": 0,
        "reason": None,
    }
    body = canonical(detail)
    if len(canonical(summary)) > 4096 or len(body) > 32768 or len(canonical(event)) > 512:
        raise DraftError("RUN_STATE_CORRUPT")
    identifier(run_id)
    validate(summary, [(1, canonical(event))], None, None, 0, None, snapshot)
    op.checkpoint()
    await op.execute(
        "INSERT INTO aiddos_runs_v1.inputs VALUES(%s,%s,%s,%s,%s,%s,%s)",
        (
            run_id,
            request["request_id"],
            summary["ordinal"],
            raw_request,
            hashlib.sha256(raw_request).hexdigest(),
            raw_snapshot,
            snapshot["digest"],
        ),
    )
    await op.execute(
        "INSERT INTO aiddos_runs_v1.jobs VALUES(%s,'QUEUED',0,0,%s,NULL,%s,NULL,"
        "%s,NULL,1,NULL,NULL,NULL,0)",
        (run_id, now, now, now + timedelta(seconds=300)),
    )
    await op.execute(
        "INSERT INTO aiddos_runs_v1.events VALUES(%s,1,%s)", (run_id, canonical(event))
    )
    await op.execute(
        "UPDATE aiddos_runs_v1.quota SET retained_count=retained_count+1,"
        "unfinished_count=unfinished_count+1,reserved_bytes=reserved_bytes+65536"
    )
    await commit(op, mutation=True)
    return 202, body
