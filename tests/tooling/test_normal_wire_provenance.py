"""Synthetic provenance-graph controls; none are actual PostgreSQL capture proof."""

import copy
import json
from pathlib import Path

import pytest

from tools import normal_wire as wire

ROOT = Path(__file__).resolve().parents[2]


def synthetic_observations():
    source = wire.source_manifest(ROOT)
    legacy = json.loads((ROOT / wire.LEGACY).read_text())
    rows = [r for r in legacy["cases"] if r["provenance"] == "RECORDED_ASGI_HTTP"]
    detail = json.loads(rows[10]["raw"])
    origins, workers = {}, {}
    for index, role in enumerate(("probe", *wire.WORKERS), 1):
        modules = ({"aiddos.api.app": "src/aiddos/api/app.py",
                    "scenario_producer": "tests/api/scenario_producer.py"}
                   if role == "probe" else {
                       "aiddos.runs.worker": "src/aiddos/runs/worker.py",
                       "aiddos.runs.offline": "src/aiddos/runs/offline.py"})
        identity = {"pid": index, "start_ticks": str(index), "boot_id": "synthetic-boot"}
        origins[role] = {"root": str(ROOT), "pid": index, "identity": identity,
                         "modules": {name: {"path": p, "sha256": source[p]}
                                     for name, p in modules.items()}}
        if role != "probe":
            workers[role] = {"code": wire.WORKERS[role], "timed_out": False,
                             "absent": True, "identity": identity}
    volume = {"Name": "synthetic-volume"}
    proof = {"probe_exit": 0, "report": {
        "kind": "REAL_PRIVATE_PG_ASGI_HTTP_SEPARATE_ONESHOT_WORKER",
        "state": "SUCCEEDED", "attempt": 1, "run_id": detail["run"]["id"],
        "detail": detail, "other_run_untouched": True, "repeat_refused": True,
        "stored_result_matches_http": True,
        "previous_attempt_refused": "VALID_SQL_SEEDED_REQUEUED_FIXTURE",
        "unresolved_lease_refused": "REAL_CLAIM_WITHOUT_COMPUTATION",
        "source": {p: h for p, h in source.items() if p.startswith("src/") and p.endswith(".py")},
    }, "workers": workers, "origins": origins,
        "native": {"clean": True, "remaining": [],
                   "identities": [o["identity"] for o in origins.values()]},
        "pg": {"state": "CLEAN", "journal": [
            {"event": "initialized", "backend_kind": "docker"},
            {"event": "registered", "cid": "synthetic-container", "volume": volume,
             "metadata": {"NetworkMode": "none", "PortBindings": {}}},
            {"event": "container_absent", "cid": "synthetic-container"},
            {"event": "volume_absence_readback", "code": 1, "timed_out": False,
             "volume": volume},
            {"event": "clean", "cid": "synthetic-container", "volume": volume},
        ]}}
    proof["probe_process"] = {
        **origins["probe"]["identity"], "actual_exit": 0, "forced": False,
        "log_pipes_closed": True, "reaped": True, "absent": True,
        "stdout_closed": True, "stderr_closed": True, "cwd": str(ROOT),
        "argv": [str(ROOT / ".venv/bin/python"), str(ROOT / "tests/runs/phase1_probe.py"),
                 "/synthetic/handoff.json"],
    }
    proof["worker_starts"] = {}
    native_origins = {}
    for role, observation in origins.items():
        if role == "probe":
            argv = proof["probe_process"]["argv"]
        else:
            run_id = (detail["run"]["id"] if role in {"selected", "repeat"}
                      else "00000000-0000-4000-8000-000000000001")
            argv = [str(ROOT / ".venv/bin/python"), "-m", "ddospector.runs.worker",
                    "--run-id", run_id]
            proof["worker_starts"][role] = {"identity": observation["identity"], "argv": argv}
        native_origins[str(observation["pid"])] = {"cwd": str(ROOT), "argv": argv}
    proof["native"].update(origins=native_origins, errors=[], remaining_direct_children=[],
                           signals=[], reaped_descendants=[], pidfds_closed=True)
    absence = proof["pg"]["journal"][-2]
    absence.update(stdout="",
                   stderr="Error response from daemon: get synthetic-volume: no such volume")
    proof["artifacts"] = {}
    for name, value in (("captured-wire.json", rows), ("result.json", proof["report"])):
        raw = json.dumps(value, indent=2) + "\n"
        proof["artifacts"][name] = {"raw": raw, "sha256": wire.sha(raw.encode())}
    return rows, proof, source


def test_synthetic_assembly_preserves_all_historical_negative_bytes():
    rows, proof, source = synthetic_observations()
    before = copy.deepcopy((rows, proof, source))
    value = wire.assemble(ROOT, rows, proof, source)
    legacy = json.loads((ROOT / wire.LEGACY).read_text())
    assert value["cases"][:12] == rows
    assert value["cases"][12:] == [r for r in legacy["cases"]
                                    if r["provenance"] == "SYNTHETIC_CONSUMER_NEGATIVE"]
    assert (rows, proof, source) == before


@pytest.mark.parametrize("fault", [
    "probe_failed", "report_incomplete", "foreign_report", "missing_worker",
    "selected_failed", "refusal_succeeded", "worker_live", "worker_timeout", "foreign_pid",
    "foreign_origin", "missing_module", "source_drift", "missing_source", "missing_sql",
    "capture_bytes", "capture_count", "capture_order", "native_dirty", "pg_dirty",
    "missing_cleanup", "foreign_cleanup", "foreign_probe_identity", "foreign_worker_start",
    "missing_native_origins", "foreign_run_argv", "wrong_module_path", "native_errors",
    "false_volume_absence", "missing_raw_hashes", "raw_hash_drift", "raw_report_disagrees",
])
def test_synthetic_incomplete_or_foreign_proof_cannot_promote(fault):
    rows, proof, source = synthetic_observations()
    if fault == "probe_failed":
        proof["probe_exit"] = 1
    elif fault == "report_incomplete":
        proof["report"]["stored_result_matches_http"] = False
    elif fault == "foreign_report":
        proof["report"]["run_id"] = "foreign"
    elif fault == "missing_worker":
        del proof["workers"]["repeat"]
    elif fault == "selected_failed":
        proof["workers"]["selected"]["code"] = 69
    elif fault == "refusal_succeeded":
        proof["workers"]["repeat"]["code"] = 0
    elif fault == "worker_live":
        proof["workers"]["selected"]["absent"] = False
    elif fault == "worker_timeout":
        proof["workers"]["selected"]["timed_out"] = True
    elif fault == "foreign_pid":
        proof["origins"]["selected"]["pid"] = 99
    elif fault == "foreign_origin":
        proof["origins"]["selected"]["root"] = "/foreign"
    elif fault == "missing_module":
        del proof["origins"]["selected"]["modules"]["aiddos.runs.worker"]
    elif fault == "source_drift":
        source["src/aiddos/api/app.py"] = "0" * 64
    elif fault == "missing_source":
        del source["tests/api/scenario_producer.py"]
    elif fault == "missing_sql":
        del source[next(p for p in source if p.endswith(".sql"))]
    elif fault == "capture_bytes":
        rows[0]["raw"] += " "
    elif fault == "capture_count":
        rows.pop()
    elif fault == "capture_order":
        rows.reverse()
    elif fault == "native_dirty":
        proof["native"]["clean"] = False
    elif fault == "pg_dirty":
        proof["pg"]["state"] = "OWNED"
    elif fault == "missing_cleanup":
        proof["pg"]["journal"].pop()
    elif fault == "foreign_cleanup":
        proof["pg"]["journal"][-1]["cid"] = "foreign"
    elif fault == "foreign_probe_identity":
        proof["origins"]["probe"]["identity"] = {"pid": 99, "start_ticks": "99", "boot_id": "x"}
    elif fault == "foreign_worker_start":
        proof["origins"]["selected"]["identity"] = {
            **proof["origins"]["selected"]["identity"], "start_ticks": "foreign"}
    elif fault == "missing_native_origins":
        del proof["native"]["origins"]
    elif fault == "foreign_run_argv":
        pid = str(proof["workers"]["selected"]["identity"]["pid"])
        proof["native"]["origins"][pid]["argv"][-1] = "foreign-run"
    elif fault == "wrong_module_path":
        proof["origins"]["selected"]["modules"]["aiddos.runs.worker"] = {
            "path": "tools/normal_wire.py", "sha256": source["tools/normal_wire.py"]}
    elif fault == "native_errors":
        proof["native"]["errors"].append("retirement unconfirmed")
    elif fault == "false_volume_absence":
        proof["pg"]["journal"][-2]["stderr"] = "Cannot connect to Docker"
    elif fault == "missing_raw_hashes":
        del proof["artifacts"]
    elif fault == "raw_hash_drift":
        proof["artifacts"]["captured-wire.json"]["sha256"] = "0" * 64
    elif fault == "raw_report_disagrees":
        raw = "{}\n"
        proof["artifacts"]["result.json"] = {"raw": raw, "sha256": wire.sha(raw.encode())}
    with pytest.raises((ValueError, KeyError)):
        wire.assemble(ROOT, rows, proof, source)


def replay_archive(monkeypatch, value):
    """Map archived filesystem observations, not the recorded proof or its authority.

    assemble() is a capture-time publisher: its cwd must be the recorded producer
    cwd. A replay checkout must not require that old private directory to exist.
    Compute the complete current inventory and read the immutable legacy bytes
    first, then map ONLY those two observations to the independently recorded root.
    All receipt bytes, origins, argv, semantic checks and mutation assertions stay
    unchanged. No file under the historical capture checkout is opened.
    """
    recorded_root = Path(value["proof"]["origins"]["probe"]["root"])
    sources = wire.source_manifest(ROOT)
    legacy = (ROOT / wire.LEGACY).read_bytes()
    reads = []

    def manifest(path):
        assert path == recorded_root
        return sources

    def read(path):
        assert path == recorded_root / wire.LEGACY
        reads.append(path)
        return legacy

    with monkeypatch.context() as mapping:
        mapping.setattr(wire, "source_manifest", manifest)
        mapping.setattr(Path, "read_bytes", read)
        result = wire.assemble(recorded_root, value["cases"][:12], value["proof"],
                               value["producer_source_sha256"])
    assert reads == [recorded_root / wire.LEGACY]
    return result


def test_archived_actual_receipt_replays_without_reading_old_checkout(monkeypatch):
    value = json.loads((ROOT / "tests/fixtures/runs/normal-wire-current.json").read_text())
    before = copy.deepcopy(value)
    assert replay_archive(monkeypatch, value)["cases"] == value["cases"]
    assert value == before


def test_archive_mapping_never_replaces_current_source_truth(monkeypatch):
    value = json.loads((ROOT / "tests/fixtures/runs/normal-wire-current.json").read_text())
    changed = wire.source_manifest(ROOT)
    changed["src/aiddos/api/app.py"] = "0" * 64
    monkeypatch.setattr(wire, "source_manifest", lambda _: changed)
    with pytest.raises(ValueError, match="NORMAL_WIRE_EVIDENCE_INVALID"):
        replay_archive(monkeypatch, value)


@pytest.mark.parametrize("fault", [
    "missing_native_origins", "foreign_run_argv", "wrong_module_path", "native_errors",
    "false_volume_absence", "missing_raw_hashes",
])
def test_review_mutations_of_actual_receipt_are_refused(fault, monkeypatch):
    value = json.loads((ROOT / "tests/fixtures/runs/normal-wire-current.json").read_text())
    # Every negative starts from an admitted current actual receipt, not stale-source refusal.
    replay_archive(monkeypatch, value)
    proof = value["proof"]
    if fault == "missing_native_origins":
        del proof["native"]["origins"]
    elif fault == "foreign_run_argv":
        pid = str(proof["workers"]["selected"]["identity"]["pid"])
        proof["native"]["origins"][pid]["argv"][-1] = "foreign-run"
    elif fault == "wrong_module_path":
        proof["origins"]["selected"]["modules"]["aiddos.runs.worker"] = {
            "path": "tools/normal_wire.py",
            "sha256": value["producer_source_sha256"]["tools/normal_wire.py"],
        }
    elif fault == "native_errors":
        proof["native"]["errors"].append("retirement unconfirmed")
    elif fault == "false_volume_absence":
        entry = next(e for e in proof["pg"]["journal"]
                     if e["event"] == "volume_absence_readback")
        entry["stderr"] = "Cannot connect to the Docker daemon"
    elif fault == "missing_raw_hashes":
        proof.pop("artifacts", None)
    with pytest.raises((ValueError, KeyError)):
        replay_archive(monkeypatch, value)
