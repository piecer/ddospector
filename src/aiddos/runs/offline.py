"""Two bounded, deterministic pure steps over captured PostgreSQL bytes."""

from functools import wraps

from aiddos.api.errors import DraftError
from aiddos.api.scenarios import ScenarioVersion, canonical, record_digest

from .contracts import raw_json, request_value
from .validation import check


class WorkStopped(Exception):
    """Cooperative pure-step interruption; not a task verdict."""


def check_stop(stop):
    if stop is not None and stop.is_set():
        raise WorkStopped()


class SnapshotInvalid(ValueError):
    """Expected captured-byte decoding, shape or integrity refusal."""


def snapshot_integrity(function):
    @wraps(function)
    def checked(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except DraftError as error:
            if error.code != "VALIDATION_ERROR":
                raise
            raise SnapshotInvalid() from None
        except (ValueError, TypeError, KeyError):
            raise SnapshotInvalid() from None

    return checked


@snapshot_integrity
def verify(raw, *, stop=None):
    check_stop(stop)
    snapshot = raw_json(raw)
    check(len(raw) <= 12288 and canonical(snapshot) == raw)
    check(set(snapshot) == {"schema_version", "task", "source_revision", "scenario", "digest"})
    check(type(snapshot["schema_version"]) is int and snapshot["schema_version"] == 1)
    check(snapshot["task"] == "offline_manifest_v1")
    check(type(snapshot["source_revision"]) is int)
    ScenarioVersion.model_validate(snapshot["scenario"])
    check(len(canonical(snapshot["scenario"])) <= 8192)
    check(snapshot["scenario"]["version"] <= snapshot["source_revision"] <= 1000)
    check(snapshot["digest"] == record_digest(snapshot))
    check_stop(stop)
    return snapshot


@snapshot_integrity
def verify_claim(owned, *, stop=None):
    import hashlib

    snapshot = verify(owned["snapshot"], stop=stop)
    request = request_value(owned["request"])
    check(canonical(request) == owned["request"])
    check(hashlib.sha256(owned["request"]).hexdigest() == owned["request_digest"])
    check(request["request_id"] == owned["request_id"] and request["mode"] == "OFFLINE")
    scenario = snapshot["scenario"]
    check(
        (scenario["id"], scenario["version"], scenario["digest"])
        == (request["scenario_id"], request["scenario_version"], request["scenario_digest"])
    )
    check(snapshot["digest"] == owned["snapshot_digest"])
    check_stop(stop)
    return snapshot


class ResultLimitExceeded(ValueError):
    """The actual compiler encoder exceeded the retained-result boundary."""


def compile_manifest(snapshot, *, stop=None):
    check_stop(stop)
    definition = snapshot["scenario"]["definition"]
    result = {
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
            {"role": role, "availability": "NOT_INGESTED"}
            for role in definition["evidence_requirements"]
        ],
        "asset_status": "NOT_APPLICABLE"
        if definition["profile_id"] == "k6-http"
        else ("NOT_DECLARED" if definition["pcap_asset"] is None else "DECLARED_UNVERIFIED"),
        "evaluation": "NOT_EVALUATED",
        "defense_verdict": None,
        "measurements": None,
    }
    result["digest"] = record_digest(result)
    raw = canonical(result)
    if len(raw) > 8192:
        raise ResultLimitExceeded()
    check_stop(stop)
    return raw
