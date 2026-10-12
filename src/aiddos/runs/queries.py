"""Bounded raw query grammar and stable-through HTTP read operations."""

import re

from aiddos.api.scenarios import canonical

from .contracts import raw_json, require
from .http_detail import retained_detail
from .http_summary import summary
from .repository import begin, check_storage, commit, quota


def page_query(raw, *, events=False):
    require(len(raw) <= 256)
    limits = {b"after": 16 if events else 128, b"limit": 16 if events else 20}
    if not events:
        limits[b"through"] = 128
    values = {"after": 0, "limit": 16 if events else 20}
    seen = set()
    for part in raw.split(b"&") if raw else ():
        key, separator, value = part.partition(b"=")
        require(separator and key in limits and key not in seen)
        require(re.fullmatch(rb"0|[1-9][0-9]*", value) is not None)
        require(len(value) <= 3)
        number = int(value)
        require(number <= limits[key] and (key != b"limit" or number >= 1))
        seen.add(key)
        values[key.decode("ascii")] = number
    return values


async def list_runs(op, socket, query):
    await check_storage(op, socket)
    await begin(op, read=True)
    counts = await quota(op)
    through = query.get("through", counts[0])
    require(through <= counts[0])
    after, limit = query["after"], query["limit"]
    rows = await op.execute(
        "SELECT run_id FROM aiddos_runs_v1.inputs WHERE ordinal>%s AND ordinal<=%s "
        "ORDER BY ordinal LIMIT %s",
        (after, through, limit),
    )
    items = []
    for (run_id,) in rows:
        items.append(await summary(op, str(run_id)))
    next_after = items[-1]["ordinal"] if items and items[-1]["ordinal"] < through else None
    body = canonical(
        {
            "schema_version": 1,
            "after": after,
            "through": through,
            "limit": limit,
            "total": through,
            "items": items,
            "next_after": next_after,
        }
    )
    require(len(body) <= 131072, "RUN_STATE_CORRUPT")
    await commit(op)
    return 200, body


async def events(op, socket, run_id, query):
    await check_storage(op, socket)
    await begin(op, read=True)
    found = await retained_detail(op, run_id)
    await quota(op)
    summary = raw_json(found[1])["run"]
    total = summary["event_count"]
    after, limit = query["after"], query["limit"]
    rows = await op.execute(
        "SELECT event FROM aiddos_runs_v1.events WHERE run_id=%s AND seq>%s ORDER BY seq LIMIT %s",
        (run_id, after, limit),
    )
    items = [raw_json(row[0]) for row in rows]
    next_after = items[-1]["seq"] if items and items[-1]["seq"] < total else None
    body = canonical(
        {
            "schema_version": 1,
            "run_id": run_id,
            "after": after,
            "limit": limit,
            "total": total,
            "items": items,
            "next_after": next_after,
        }
    )
    require(len(body) <= 16384, "RUN_STATE_CORRUPT")
    await commit(op)
    return 200, body
