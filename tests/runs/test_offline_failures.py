"""Pure captured-byte regressions; no PostgreSQL or worker processes."""

import hashlib
import json
import threading
from pathlib import Path

import pytest

from aiddos.api.errors import DraftError
from aiddos.api.scenarios import canonical
from aiddos.runs import offline

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def captured():
    corpus = ROOT / "tests/fixtures/runs/h1"
    index = json.loads((corpus / "selected-index.json").read_text())
    entry = next(item for item in index if item["state"] == "QUEUED")
    body = (corpus / entry["body"]).read_bytes()
    assert hashlib.sha256(body).hexdigest() == entry["sha256"]
    detail = json.loads(body)
    run = detail["run"]
    request = canonical({
        "request_id": run["request_id"],
        "mode": run["mode"],
        "scenario_id": run["scenario_id"],
        "scenario_version": run["scenario_version"],
        "scenario_digest": run["scenario_digest"],
    })
    return detail["snapshot"], {
        "snapshot": canonical(detail["snapshot"]),
        "request": request,
        "request_id": run["request_id"],
        "request_digest": hashlib.sha256(request).hexdigest(),
        "snapshot_digest": run["snapshot_digest"],
    }


@pytest.mark.parametrize("raw", [b"{", b"null", b"[]", b"1", b"{}", b"\xff"])
def test_snapshot_decode_and_shape_failures_are_value_errors(raw):
    with pytest.raises(ValueError):
        offline.verify(raw)


@pytest.mark.parametrize("raw", [b"{", b"null", b"[]", b"1", b"{}", b"\xff"])
def test_request_decode_and_shape_failures_are_value_errors(captured, raw):
    _, owned = captured
    owned["request"] = raw
    with pytest.raises(ValueError):
        offline.verify_claim(owned)


def test_missing_claim_field_is_normalized(captured):
    _, owned = captured
    del owned["request"]
    with pytest.raises(ValueError):
        offline.verify_claim(owned)


def test_valid_captured_bytes_compile_deterministically_without_measurements(captured):
    snapshot, owned = captured
    assert offline.verify(owned["snapshot"]) == snapshot
    assert offline.verify_claim(owned) == snapshot
    first = offline.compile_manifest(snapshot)
    assert offline.compile_manifest(snapshot) == first
    result = json.loads(first)
    assert result["snapshot_digest"] == snapshot["digest"]
    assert result["evaluation"] == "NOT_EVALUATED"
    assert result["measurements"] is None
    assert result["defense_verdict"] is None
    assert all(item["availability"] == "NOT_INGESTED" for item in result["evidence_requirements"])


@pytest.mark.parametrize("method", ["verify", "verify_claim", "compile_manifest"])
def test_cooperative_stop_is_not_reclassified_as_bad_input(captured, method):
    snapshot, owned = captured
    stop = threading.Event()
    stop.set()
    argument = {"verify": owned["snapshot"], "verify_claim": owned,
                "compile_manifest": snapshot}[method]
    with pytest.raises(offline.WorkStopped):
        getattr(offline, method)(argument, stop=stop)


def test_unrelated_draft_error_keeps_original_identity(monkeypatch):
    error = DraftError("RUN_DB_UNAVAILABLE")

    def fail(_):
        raise error

    monkeypatch.setattr(offline, "raw_json", fail)
    with pytest.raises(DraftError) as captured_error:
        offline.verify(b"{}")
    assert captured_error.value is error


def test_actual_compiler_encoder_limit_has_distinct_failure(captured, monkeypatch):
    snapshot, _ = captured
    # An explicit encoder seam, not a naturally oversized valid scenario.
    monkeypatch.setattr(offline, "canonical", lambda _: b"x" * 8193)
    with pytest.raises(ValueError) as error:
        offline.compile_manifest(snapshot)
    assert type(error.value).__name__ == "ResultLimitExceeded"
