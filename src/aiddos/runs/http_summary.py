"""Summary-only exception for recorded snapshot-integrity failure."""

import hashlib
from datetime import timedelta

from aiddos.api.errors import DraftError
from aiddos.api.scenarios import canonical

from .contracts import DIGEST, identifier, raw_json, request_value
from .repository import lookup, timestamp
from .validation import check, validate


async def summary(op, run_id):
    rows = await op.execute(
        "SELECT i.request,i.request_digest,i.request_id,i.ordinal,i.snapshot_digest,"
        "j.state,j.attempt,j.generation,j.created_at,j.started_at,j.updated_at,j.finished_at,"
        "j.deadline_at,j.cancel_requested_at,j.event_count,j.failure_code,j.owner_token,"
        "j.lease_until,j.step,r.result FROM aiddos_runs_v1.inputs i "
        "JOIN aiddos_runs_v1.jobs j ON j.run_id=i.run_id "
        "LEFT JOIN aiddos_runs_v1.results r ON r.run_id=i.run_id WHERE i.run_id=%s",
        (run_id,),
    )
    if not rows:
        raise DraftError("RUN_STATE_CORRUPT")
    row = rows[0]
    if (row[5], row[15]) != ("FAILED", "SNAPSHOT_INVALID"):
        found = await lookup(op, run_id)
        check(found is not None)
        return raw_json(found[1])["run"]
    try:
        request = request_value(row[0])
        check(canonical(request) == row[0] and request["mode"] == "OFFLINE")
        check(hashlib.sha256(row[0]).hexdigest() == row[1])
        check(str(row[2]) == request["request_id"])
        identifier(str(run_id))
        check(DIGEST.fullmatch(row[4]) is not None)
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
        value = dict(zip(keys, row[5:16], strict=True))
        for key in keys:
            if key.endswith("_at") and value[key] is not None:
                value[key] = timestamp(value[key])
        value.update(
            id=str(run_id),
            request_id=str(row[2]),
            ordinal=row[3],
            mode="OFFLINE",
            task="offline_manifest_v1",
            scenario_id=request["scenario_id"],
            scenario_version=request["scenario_version"],
            scenario_digest=request["scenario_digest"],
            snapshot_digest=row[4],
        )
        check(row[12] == row[8] + timedelta(seconds=300))
        check(row[10] >= row[8] and 1 <= row[3] <= 128)
        events = await op.execute(
            "SELECT seq,event FROM aiddos_runs_v1.events WHERE run_id=%s ORDER BY seq",
            (run_id,),
        )
        validate(value, events, row[16], row[17], row[18], row[19], None)
        check(len(canonical(value)) <= 4096)
        return value
    except (ValueError, TypeError, KeyError, AssertionError, DraftError):
        raise DraftError("RUN_STATE_CORRUPT") from None
