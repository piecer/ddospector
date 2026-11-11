"""Opt-in normal-only ASGI/PG/worker capture; never updates repository fixtures.

Run from the checkout's Python environment with --output pointing to a NEW private
artifact directory. Requires the already-cached PostgreSQL image. No model/DUT,
network image pull, full W2 campaign, or automatic retry is admitted.
"""

import argparse
import hashlib
import json
import os
import signal
import sys
import time
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LEGACY = "tests/fixtures/runs/normal-wire.json"
LEGACY_SHA256 = "e3ee5b76d6a180d3a6d61462174c695989c444adc2f4bdb9c11a94d0aca47922"
SUPPORT = (
    "pyproject.toml", "uv.lock", "tests/api/scenario_producer.py",
    "tests/runs/phase1_probe.py", "tools/s02_harness.py", "tools/s02_web_probe.py",
    "tools/normal_wire.py", "tools/normal_wire_observer/sitecustomize.py",
)
LABELS = ("list-0", "create-1", "detail-2", "events-3", "cancel-4", "events-5",
          "request-6", "list-7", "detail-8", "events-9", "detail-10", "events-11")
WORKERS = {"selected": 0, "repeat": 69, "previous-attempt": 69, "unresolved-lease": 69}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition):
    if not condition:
        raise ValueError("NORMAL_WIRE_EVIDENCE_INVALID")


def source_manifest(root):
    paths = {str(p.relative_to(root)) for p in (root / "src").rglob("*")
             if p.is_file() and p.suffix in {".py", ".sql"}}
    paths.update(SUPPORT)
    return {name: sha((root / name).read_bytes()) for name in sorted(paths)}


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def assemble(root, captured, proof, source):
    """Validate complete same-invocation observations before publishing a corpus.

    Hashes bind retained observations, not authentication against malicious local
    writers. Synthetic unit controls cannot substitute for capture() execution.
    """
    require(source == source_manifest(root))
    legacy_bytes = (root / LEGACY).read_bytes()
    require(sha(legacy_bytes) == LEGACY_SHA256)
    legacy = json.loads(legacy_bytes)
    require(len(captured) == 12 and tuple(row["label"] for row in captured) == LABELS)
    for row in captured:
        require(set(row) == {"label", "raw", "sha256", "context", "expected", "provenance"})
        require(row["expected"] == "ACCEPT" and row["provenance"] == "RECORDED_ASGI_HTTP")
        require(row["sha256"] == sha(row["raw"].encode("utf-8")))
    require(set(proof) == {"probe_exit", "probe_process", "report", "workers", "worker_starts",
                           "origins", "native", "pg", "artifacts"})
    require(type(proof["probe_exit"]) is int and proof["probe_exit"] == 0)
    report = proof["report"]
    require(set(proof["artifacts"]) == {"captured-wire.json", "result.json"})
    for name, parsed in (("captured-wire.json", captured), ("result.json", report)):
        artifact = proof["artifacts"][name]
        require(set(artifact) == {"raw", "sha256"})
        require(type(artifact["raw"]) is str
                and sha(artifact["raw"].encode("utf-8")) == artifact["sha256"])
        require(json.loads(artifact["raw"]) == parsed)
    terminal = json.loads(captured[10]["raw"])
    require(report["kind"] == "REAL_PRIVATE_PG_ASGI_HTTP_SEPARATE_ONESHOT_WORKER")
    require(report["state"] == "SUCCEEDED" and type(report["attempt"]) is int
            and report["attempt"] == 1)
    require(report["run_id"] == terminal["run"]["id"] and report["detail"] == terminal)
    for key in ("other_run_untouched", "repeat_refused", "stored_result_matches_http"):
        require(report[key] is True)
    require(report["previous_attempt_refused"] == "VALID_SQL_SEEDED_REQUEUED_FIXTURE")
    require(report["unresolved_lease_refused"] == "REAL_CLAIM_WITHOUT_COMPUTATION")
    require(report["source"] == {p: h for p, h in source.items()
                                 if p.startswith("src/") and p.endswith(".py")})
    require(set(proof["workers"]) == set(WORKERS))
    require(set(proof["worker_starts"]) == set(WORKERS))
    require(set(proof["origins"]) == {"probe", *WORKERS})
    native = proof["native"]
    require(set(native) == {"clean", "remaining", "identities", "origins", "signals",
                            "reaped_descendants", "remaining_direct_children", "errors",
                            "pidfds_closed"})
    require(native["errors"] == native["remaining_direct_children"] == native["signals"] == [])
    require(native["pidfds_closed"] is True)
    process = proof["probe_process"]
    require(process["actual_exit"] == proof["probe_exit"] and process["forced"] is False)
    for key in ("log_pipes_closed", "reaped", "absent", "stdout_closed", "stderr_closed"):
        require(process[key] is True)
    probe_identity = proof["origins"]["probe"]["identity"]
    require(all(process[key] == probe_identity[key] for key in ("pid", "start_ticks", "boot_id")))
    require(process["cwd"] == str(root) and len(process["argv"]) == 3
            and process["argv"][1] == str(root / "tests/runs/phase1_probe.py"))
    for role, expected in WORKERS.items():
        record = proof["workers"][role]
        require(type(record["code"]) is int and record["code"] == expected)
        require(record["absent"] is True and record["timed_out"] is False)
        require(record["identity"]["pid"] == proof["origins"][role]["pid"])
        require(record["identity"] == proof["origins"][role]["identity"])
        start = proof["worker_starts"][role]
        require(set(start) == {"identity", "argv"} and start["identity"] == record["identity"])
        argv = start["argv"]
        require(len(argv) == 5 and argv[:4] == [process["argv"][0], "-m",
                                                "ddospector.runs.worker", "--run-id"])
        run_id = UUID(argv[4])
        require(run_id.version == 4 and str(run_id) == argv[4])
        require((argv[4] == report["run_id"]) == (role in {"selected", "repeat"}))
    for role, observation in proof["origins"].items():
        require(observation["root"] == str(root))
        require(observation["identity"]["pid"] == observation["pid"])
        require(observation["identity"] in proof["native"]["identities"])
        execution = native["origins"][str(observation["pid"])]
        expected_argv = (process["argv"] if role == "probe"
                         else proof["worker_starts"][role]["argv"])
        require(execution["cwd"] == str(root) and execution["argv"] == expected_argv)
        modules = observation["modules"]
        required = {"aiddos.api.app", "scenario_producer"} if role == "probe" else {
            "aiddos.runs.worker", "aiddos.runs.offline"}
        require(required <= set(modules))
        for name, module in modules.items():
            require(module["path"] in source and module["sha256"] == source[module["path"]])
            stem = "src/" + name.replace(".", "/")
            expected = {"tests/api/scenario_producer.py"} if name == "scenario_producer" else {
                stem + ".py", stem + "/__init__.py"}
            require(module["path"] in expected)
    require(proof["native"]["clean"] is True and proof["native"]["remaining"] == [])
    require(len({o["pid"] for o in proof["origins"].values()}) == 5)
    require(proof["pg"]["state"] == "CLEAN")
    events = proof["pg"]["journal"]
    require(events[0]["backend_kind"] == "docker")
    require(sum(e["event"] == "registered" for e in events) == 1)
    registered = next(e for e in events if e["event"] == "registered")
    clean = events[-1]
    require(clean["event"] == "clean" and clean["cid"] == registered["cid"]
            and clean["volume"] == registered["volume"])
    require(registered["metadata"]["NetworkMode"] == "none"
            and registered["metadata"]["PortBindings"] == {})
    require(any(e["event"] == "container_absent" and e["cid"] == clean["cid"]
                for e in events))
    absence = [e for e in events if e["event"] == "volume_absence_readback"]
    require(len(absence) == 1)
    absence = absence[0]
    require(absence["code"] == 1 and absence["timed_out"] is False
            and absence["volume"] == clean["volume"] and absence["stdout"].strip() == "")
    require(absence["stderr"].strip() == "Error response from daemon: get "
            + clean["volume"]["Name"] + ": no such volume")
    negatives = [row for row in legacy["cases"]
                 if row["provenance"] == "SYNTHETIC_CONSUMER_NEGATIVE"]
    require(len(negatives) == 39)
    return {"schema_version": 2,
            "scope": "Current real private PostgreSQL/separate-worker ASGI HTTP capture; "
                     "39 unchanged historical synthetic negatives. Not TCP/DUT/W2 acceptance.",
            "producer_source_sha256": source,
            "origin": {"transport": "IN_PROCESS_ASGI_HTTP", "legacy_sha256": LEGACY_SHA256,
                       "probe": "tests/runs/phase1_probe.py"},
            "proof": proof, "cases": captured + negatives}


def capture(output):
    from tools import s02_harness as h
    from tools.s02_web_probe import NativeChildren

    # mkdir is deliberately exclusive: no adoption, overwrite, retry or resume.
    require(output.is_absolute())
    output.mkdir(mode=0o700)
    source = source_manifest(ROOT)
    write_json(output / "source.json", source)
    env = h.child_environment(output)
    observer = ROOT / "tools/normal_wire_observer"
    env.update(PYTHONPATH=f"{observer}{os.pathsep}{ROOT / 'src'}",
               NORMAL_WIRE_ROOT=str(ROOT), NORMAL_WIRE_ORIGIN=str(output / "probe-origins.json"))
    received = []
    old = {sig: signal.signal(sig, lambda sig, frame: received.append(sig))
           for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    native = None
    owner = None
    probe_exit = None
    try:
        native = NativeChildren(output, env)
        with h.Harness(output) as owner:
            try:
                require(not received)
                owner.bootstrap()
                require(not received and source_manifest(ROOT) == source)
                work = owner.directory / "phase1-normal"
                work.mkdir()
                handoff = {"root": str(ROOT), "socket": str(owner.socket), "output": str(work),
                           "owner": owner.owner_process, "observe_origins": True,
                           "source": {p: digest for p, digest in source.items()
                                      if p.startswith("src/") and p.endswith(".py")}}
                config = work / "handoff.json"
                write_json(config, handoff)
                deadline = time.monotonic() + 60
                probe = native.launch("probe", [sys.executable,
                    str(ROOT / "tests/runs/phase1_probe.py"), str(config)])
                while probe.poll() is None:
                    native.discover()
                    if received or time.monotonic() >= deadline:
                        raise RuntimeError("NORMAL_WIRE_CAPTURE_INTERRUPTED_OR_EXPIRED")
                    time.sleep(0.02)
                if received or time.monotonic() >= deadline:
                    raise RuntimeError("NORMAL_WIRE_CAPTURE_INTERRUPTED_OR_EXPIRED")
                probe_exit = probe.returncode
                require(probe_exit == 0 and not received)
            finally:
                # Includes probe workers in independent sessions, before PG retirement.
                native.retire_all()
                require(native.clean)
        require(owner.state == "CLEAN" and not received and source_manifest(ROOT) == source)
        def load(path):
            return json.loads(path.read_text())

        proof = {"probe_exit": probe_exit, "probe_process": load(output / "probe.native-end.json"),
                 "report": load(work / "result.json"),
                 "workers": {role: load(work / f"{role}-exit.json") for role in WORKERS},
                 "worker_starts": {role: load(work / f"{role}-started.json") for role in WORKERS},
                 "origins": {"probe": load(output / "probe-origins.json"),
                             **{role: load(work / f"{role}-origins.json") for role in WORKERS}},
                 "native": load(output / "native-retirement.json"),
                 "pg": {"state": owner.state, "journal": [json.loads(line) for line in
                         owner.journal.read_text().splitlines()]},
                 "artifacts": {name: {"raw": (work / name).read_bytes().decode("utf-8"),
                                      "sha256": sha((work / name).read_bytes())}
                               for name in ("captured-wire.json", "result.json")}}
        value = assemble(ROOT, load(work / "captured-wire.json"), proof, source)
        # Only this final, validated artifact is promotable; partial raw files remain evidence.
        write_json(output / "normal-wire-current.json", value)
        print(json.dumps({"status": "CAPTURED", "output": str(output), "cases": 51}))
    finally:
        try:
            if native is not None and not native.closed:
                native.retire_all()
        finally:
            for sig, handler in old.items():
                signal.signal(sig, handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--output", type=Path, required=True,
                        help="NEW absolute evidence directory")
    args = parser.parse_args(argv)
    capture(args.output)


if __name__ == "__main__":
    main()
