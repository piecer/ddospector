"""Read-only validation of retained event/state linkage; no transition executor."""

import re
from datetime import datetime

from aiddos.api.scenarios import canonical, record_digest

from .contracts import raw_json

TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT"}
FAILURES = {
    "SNAPSHOT_INVALID",
    "OFFLINE_PREPARATION_FAILED",
    "RESULT_LIMIT_EXCEEDED",
    "RETRY_EXHAUSTED",
}


def check(condition):
    if not condition:
        raise ValueError("retained state")


def moment(text):
    check(type(text) is str and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z", text))
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def validate(summary, rows, owner, lease, step, result_raw, snapshot):
    state, attempt, generation, progress = "QUEUED", 0, 0, 0
    started = cancelled = finished = failure = None
    previous_at = moment(summary["created_at"])
    check(1 <= len(rows) <= 16)
    for index, (seq, raw) in enumerate(rows, 1):
        event = raw_json(raw)
        check(len(raw) <= 512 and canonical(event) == raw)
        check(set(event) == {"seq", "at", "type", "state", "attempt", "generation", "reason"})
        check(type(seq) is int and type(event["seq"]) is int and seq == event["seq"] == index)
        check(type(event["attempt"]) is int and type(event["generation"]) is int)
        at = moment(event["at"])
        check(at >= previous_at and state not in TERMINAL)
        kind, reason = event["type"], event["reason"]
        if index == 1:
            check(
                event
                == {
                    "seq": 1,
                    "at": summary["created_at"],
                    "type": "QUEUED",
                    "state": "QUEUED",
                    "attempt": 0,
                    "generation": 0,
                    "reason": None,
                }
            )
        elif kind == "CLAIMED":
            check(state == "QUEUED" and attempt < 3 and reason is None)
            state, attempt, generation, progress = "RUNNING", attempt + 1, generation + 1, 0
            started = started or event["at"]
        elif kind in {"SNAPSHOT_VERIFIED", "MANIFEST_COMPILED"}:
            check(
                state == "RUNNING"
                and progress == (0 if kind == "SNAPSHOT_VERIFIED" else 1)
                and reason is None
            )
            progress += 1
        elif kind == "REQUEUED":
            check(state == "RUNNING" and attempt < 3 and reason == "LEASE_EXPIRED")
            state, generation, progress = "QUEUED", generation + 1, 0
        elif kind == "CANCEL_REQUESTED":
            check(state == "RUNNING" and reason is None)
            state, cancelled = kind, event["at"]
        elif kind in TERMINAL:
            if kind == "CANCELLED":
                check(
                    (state == "QUEUED" and reason == "BEFORE_CLAIM")
                    or (state == "RUNNING" and reason == "LEASE_REVOKED")
                    or (state == "CANCEL_REQUESTED" and reason in {"LEASE_REVOKED", "WORKER_ACK"})
                )
                cancelled = cancelled or event["at"]
            elif kind == "TIMED_OUT":
                check(
                    state in {"QUEUED", "RUNNING"}
                    and reason == "DEADLINE_EXCEEDED"
                    and at >= moment(summary["deadline_at"])
                )
                failure = reason
            elif kind == "SUCCEEDED":
                check(state == "RUNNING" and progress == 2 and reason is None)
            else:
                check(state == "RUNNING" and reason in FAILURES)
                check(reason != "RETRY_EXHAUSTED" or attempt == 3)
                failure = reason
            if state in {"RUNNING", "CANCEL_REQUESTED"}:
                generation += 1
            state, finished = kind, event["at"]
        else:
            raise ValueError("retained event")
        check(
            event["state"] == state
            and event["attempt"] == attempt
            and event["generation"] == generation
            and generation <= 6
        )
        previous_at = at
    check(
        summary["state"] == state
        and summary["attempt"] == attempt
        and summary["generation"] == generation
        and summary["event_count"] == len(rows)
    )
    check(
        summary["started_at"] == started
        and summary["cancel_requested_at"] == cancelled
        and summary["finished_at"] == finished
        and summary["failure_code"] == failure
    )
    check(moment(summary["updated_at"]) == previous_at and step == progress)
    owned = state in {"RUNNING", "CANCEL_REQUESTED"}
    check(owned == (owner is not None) and owned == (lease is not None))
    if state != "SUCCEEDED":
        check(result_raw is None)
        return None
    # Integrity-only projection, not a worker or a publication path.
    result = raw_json(result_raw)
    definition = snapshot["scenario"]["definition"]
    expected = {
        "schema_version": 1,
        "kind": "offline_preparation",
        "snapshot_digest": snapshot["digest"],
        "checks": ["SNAPSHOT_INTEGRITY", "POLICY_CONSISTENCY", "REQUIREMENTS_COMPILED"],
        "expected_policy": {
            k: definition[k]
            for k in ("expected_action", "delivery_expectation", "detection_required")
        },
        "success_criteria": definition["success_criteria"],
        "declared_limits": {k: definition[k] for k in ("traffic_budget", "stop_conditions")},
        "evidence_requirements": [
            {"role": r, "availability": "NOT_INGESTED"} for r in definition["evidence_requirements"]
        ],
        "asset_status": "NOT_APPLICABLE"
        if definition["profile_id"] == "k6-http"
        else ("NOT_DECLARED" if definition["pcap_asset"] is None else "DECLARED_UNVERIFIED"),
        "evaluation": "NOT_EVALUATED",
        "defense_verdict": None,
        "measurements": None,
    }
    expected["digest"] = record_digest(expected)
    check(len(result_raw) <= 8192 and result_raw == canonical(expected) == canonical(result))
    return result
