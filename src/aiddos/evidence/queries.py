"""Bounded metadata-only listing and selected original verification."""

from aiddos.api.errors import DraftError
from aiddos.api.scenarios import canonical
from aiddos.runs.repository import begin, commit

from .contracts import MAX_PAIRS, MAX_RESPONSE
from .repository import PROJECTION, check_storage, quota, selected
from .validation import check, detail, metadata


async def list_evidence(op, socket):
    await check_storage(op, socket)
    await begin(op, read=True)
    count, _ = await quota(op)
    rows = await op.execute("SELECT " + PROJECTION + " FROM ddospector_evidence_v1.bundles "
                            "ORDER BY ordinal LIMIT 17")
    check(len(rows) == count and len(rows) <= MAX_PAIRS)
    items = [metadata(row) for row in rows]
    check([item["ordinal"] for item in items] == list(range(1, count + 1)))
    body = canonical({"schema_version": 1, "items": items, "total": count})
    check(len(body) <= MAX_RESPONSE)
    await commit(op)
    return 200, body


async def get(op, socket, value, *, by_request=False, side=None):
    await check_storage(op, socket)
    await begin(op, read=True)
    await quota(op)
    found = await selected(op, value, by_request=by_request)
    if found is None:
        raise DraftError("EVIDENCE_NOT_FOUND")
    body = detail(found[0]) if side is None else found[1 if side == "ingress" else 2]
    await commit(op)
    return 200, body
