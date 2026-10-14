"""Fail closed before hydrating or publishing retained evidence metadata."""

import hashlib
from datetime import UTC

from aiddos.api.errors import DraftError
from aiddos.api.scenarios import canonical
from aiddos.runs.contracts import DIGEST, identifier, raw_json, require
from aiddos.runs.repository import timestamp
from aiddos.runs.validation import moment

from .contracts import MAX_METADATA, MAX_PAIRS, MAX_RESPONSE, MAX_SIDE_BYTES, name_value
from .samples import recognize_pair

SUMMARY_KEYS = {"id", "request_id", "ordinal", "run_id", "run_snapshot_digest", "created_at",
                "provenance", "sample_id", "coverage", "ingress", "egress", "analysis_state"}


def check(condition):
    require(condition, "EVIDENCE_STATE_CORRUPT")


def digest(value):
    check(type(value) is str and DIGEST.fullmatch(value) is not None)
    return value


def descriptor(name, raw):
    return {"name": name_value(name), "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()}


def identity(value):
    return hashlib.sha256(canonical({key: value[key]
                                    for key in ("request_id", "run_id", "ingress", "egress")}
                                   )).hexdigest()


def provenance(ingress, egress):
    pair = recognize_pair(ingress["sha256"], egress["sha256"])
    return {"provenance": "SYNTHETIC" if pair else "UNVERIFIED",
            "sample_id": pair.sample_id if pair else None,
            "coverage": pair.coverage if pair else "UNKNOWN"}


def summary_value(value):
    try:
        check(type(value) is dict and set(value) == SUMMARY_KEYS)
        for key in ("id", "request_id", "run_id"):
            identifier(value[key])
        check(type(value["ordinal"]) is int and 1 <= value["ordinal"] <= MAX_PAIRS)
        digest(value["run_snapshot_digest"])
        check(type(value["created_at"]) is str and len(value["created_at"]) == 27)
        moment(value["created_at"])
        for key in ("ingress", "egress"):
            side = value[key]
            check(type(side) is dict and set(side) == {"name", "size_bytes", "sha256"})
            name_value(side["name"])
            check(type(side["size_bytes"]) is int and 1 <= side["size_bytes"] <= MAX_SIDE_BYTES)
            digest(side["sha256"])
        check(value["analysis_state"] == "REGISTERED")
        check({key: value[key] for key in ("provenance", "sample_id", "coverage")}
              == provenance(value["ingress"], value["egress"]))
        check(len(canonical(value)) <= MAX_METADATA)
        return value
    except (ValueError, TypeError, KeyError, OverflowError, DraftError):
        raise DraftError("EVIDENCE_STATE_CORRUPT") from None


def summary(raw):
    try:
        check(type(raw) is bytes and 1 <= len(raw) <= MAX_METADATA)
        value = summary_value(raw_json(raw))
        check(canonical(value) == raw)
        return value
    except (ValueError, TypeError, KeyError, DraftError):
        raise DraftError("EVIDENCE_STATE_CORRUPT") from None


def metadata(row):
    # Projection: IDs, ordinal, pinned digest, identity, timestamp, metadata, side lengths.
    try:
        value = summary(row[7])
        check((value["id"], value["request_id"], value["ordinal"], value["run_id"],
               value["run_snapshot_digest"], value["created_at"])
              == (str(row[0]), str(row[1]), row[2], str(row[3]), row[4],
                  timestamp(row[6].astimezone(UTC))))
        check(type(row[2]) is int)
        check(digest(row[5]) == identity(value))
        check(all(type(n) is int for n in row[8:10]))
        check((value["ingress"]["size_bytes"], value["egress"]["size_bytes"]) == row[8:10])
        return value
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, DraftError):
        raise DraftError("EVIDENCE_STATE_CORRUPT") from None


def originals(value, ingress, egress):
    for side, raw in (("ingress", ingress), ("egress", egress)):
        check(type(raw) is bytes and 1 <= len(raw) <= MAX_SIDE_BYTES)
        check(descriptor(value[side]["name"], raw) == value[side])


def public_summary(value, report=None):
    checked = summary_value(value)
    if report is None:
        return checked
    from .report import bind
    bind(report, checked)
    return {**checked, "analysis_state": "ANALYZED"}


def detail(value, report=None):
    # Validate typed scalars BEFORE serialization even for server-constructed summaries.
    checked = public_summary(value, report)
    body = canonical({"schema_version": 1, "evidence": checked, "report": report})
    check(len(body) <= MAX_RESPONSE)
    return body
