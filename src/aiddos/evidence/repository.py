"""Atomic immutable paired original retention using the existing operation owner."""

from datetime import UTC
from uuid import uuid4

from aiddos.api.errors import DraftError
from aiddos.api.scenarios import canonical
from aiddos.runs.contracts import raw_json
from aiddos.runs.repository import begin, commit, lookup, timestamp
from aiddos.runs.repository import check_storage as core_storage

from . import schema
from .contracts import MAX_PAIRS, MAX_SIDE_BYTES
from .validation import check, descriptor, detail, identity, metadata, originals, provenance

# Avoid driver hydration before metadata() can classify an unrepresentable scalar.
# Both the session-local timestamp and its UTC conversion must fit Python datetime.
# NULL is only a read-side invalid sentinel; metadata() rejects it without repair.
PROJECTION = ("id,request_id,ordinal,run_id,run_snapshot_digest,request_digest,"
              "CASE WHEN extract(year FROM created_at) BETWEEN 1 AND 9999 "
              "AND extract(year FROM created_at AT TIME ZONE 'UTC') BETWEEN 1 AND 9999 "
              "THEN created_at END,"
              "metadata,octet_length(ingress),octet_length(egress)")


async def check_storage(op, socket):
    await core_storage(op, socket)
    await schema.ready(op.execute)


async def quota(op, *, lock=False):
    rows = await op.execute("SELECT singleton,retained_count,raw_bytes "
                            "FROM ddospector_evidence_v1.quota" + (" FOR UPDATE" if lock else ""))
    count, first, last, total = (await op.execute(
        "SELECT count(*),coalesce(min(ordinal),0),coalesce(max(ordinal),0),"
        "coalesce(sum(octet_length(ingress)+octet_length(egress)),0) "
        "FROM ddospector_evidence_v1.bundles"
    ))[0]
    reports = (await op.execute("SELECT count(*) FROM ddospector_evidence_v1.reports"))[0][0]
    check(all(type(n) is int for n in (count, first, last, total, reports)))
    check(0 <= count <= MAX_PAIRS and first == (1 if count else 0) and last == count)
    check(count * 2 <= total <= count * 2 * MAX_SIDE_BYTES and reports == 0)
    check(len(rows) == 1 and rows[0] == (True, count, total))
    check(type(rows[0][0]) is bool and all(type(n) is int for n in rows[0][1:]))
    return count, total


async def selected(op, value, *, by_request=False):
    rows = await op.execute(
        "SELECT " + PROJECTION + ",ingress,egress FROM ddospector_evidence_v1.bundles WHERE "
        + ("request_id" if by_request else "id") + "=%s", (value,),
    )
    if not rows:
        return None
    check(len(rows) == 1)
    row = rows[0]
    value = metadata(row[:10])
    originals(value, row[10], row[11])
    return value, row[10], row[11]


async def create(op, socket, request):
    await check_storage(op, socket)
    await begin(op)
    count, _ = await quota(op, lock=True)
    found = await selected(op, request["request_id"], by_request=True)
    if found is not None:
        value, ingress, egress = found
        if (value["run_id"] != request["run_id"]
                or any(value[side]["name"] != request[side]["name"]
                       for side in ("ingress", "egress"))
                or (ingress, egress) != (request["ingress"]["raw"], request["egress"]["raw"])):
            raise DraftError("EVIDENCE_IDEMPOTENCY_CONFLICT")
        body = detail(value)
        await commit(op)
        return 200, body
    if count >= MAX_PAIRS:
        raise DraftError("EVIDENCE_RETENTION_FULL")
    run = await lookup(op, request["run_id"])
    if run is None:
        raise DraftError("EVIDENCE_RUN_NOT_READY")
    saved = raw_json(run[1])
    if saved["run"]["state"] != "SUCCEEDED" or saved["run"]["mode"] != "OFFLINE":
        raise DraftError("EVIDENCE_RUN_NOT_READY")
    now = (await op.execute("SELECT clock_timestamp()"))[0][0].astimezone(UTC)
    sides = {side: descriptor(request[side]["name"], request[side]["raw"])
             for side in ("ingress", "egress")}
    value = {"id": str(uuid4()), "request_id": request["request_id"], "ordinal": count + 1,
             "run_id": request["run_id"], "run_snapshot_digest": saved["snapshot"]["digest"],
             "created_at": timestamp(now), "analysis_state": "REGISTERED", **sides,
             **provenance(sides["ingress"], sides["egress"])}
    body = detail(value)
    ingress, egress = request["ingress"]["raw"], request["egress"]["raw"]
    originals(value, ingress, egress)
    await op.execute(
        "INSERT INTO ddospector_evidence_v1.bundles "
        "(id,request_id,ordinal,run_id,run_snapshot_digest,request_digest,created_at,metadata,"
        "ingress,egress) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (value["id"], value["request_id"], value["ordinal"], value["run_id"],
         value["run_snapshot_digest"], identity(value), now, canonical(value), ingress, egress),
    )
    await op.execute("UPDATE ddospector_evidence_v1.quota SET retained_count=retained_count+1,"
                     "raw_bytes=raw_bytes+%s", (len(ingress) + len(egress),))
    await commit(op, mutation=True)
    return 201, body
