"""Read-only S01 peer capture, exclusively unwound by its source thread."""

from copy import deepcopy

from aiddos.api.errors import DraftError
from aiddos.api.scenarios import ScenarioVersion, canonical, record_digest


def capture(peer, request):
    if not peer.lock.acquire(timeout=1.0):
        raise DraftError("RUN_BUSY")
    try:
        try:
            history = peer.history(request["scenario_id"])
        except DraftError as exc:
            if exc.code == "SCENARIO_NOT_FOUND":
                raise DraftError("RUN_SOURCE_NOT_FOUND") from None
            raise
        records = [v for v in history["versions"] if v["version"] == request["scenario_version"]]
        if not records:
            raise DraftError("RUN_SOURCE_NOT_FOUND")
        if records[0]["digest"] != request["scenario_digest"]:
            raise DraftError("RUN_SOURCE_CONFLICT")
        scenario = deepcopy(records[0])
        revision = history["revision"]
    finally:
        peer.lock.release()
    ScenarioVersion.model_validate(scenario)
    snapshot = {
        "schema_version": 1,
        "task": "offline_manifest_v1",
        "source_revision": revision,
        "scenario": scenario,
    }
    snapshot["digest"] = record_digest(snapshot)
    if len(canonical(snapshot)) > 12288:
        raise DraftError("RUN_STATE_CORRUPT")
    return snapshot
