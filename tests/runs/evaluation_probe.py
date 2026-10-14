"""Real retained PCAP -> separate evaluator -> immutable API readback, no traffic."""
import asyncio
import base64
import fcntl
import hashlib
import json
import os
import struct
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from evidence_checks import connect, core_bytes
from evidence_probe import migrate_public
from phase1_probe import ROOT, h, invoke, save


def evaluate(data, evidence_id, label, expected=0):
    output = Path(data["output"])
    env = h.child_environment(output) | {"DDOSPECTOR_RUN_DB_SOCKET": data["socket"]}
    argv = [sys.executable, "-m", "ddospector.evidence.evaluate", "--evidence-id", evidence_id]
    with (output / (label + ".stdout")).open("wb") as stdout, (
        output / (label + ".stderr")
    ).open("wb") as stderr:
        child = subprocess.Popen(argv, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                 stdout=stdout, stderr=stderr, start_new_session=True)
        identity = h.identity_of(child.pid)
        timed_out = False
        try:
            code = child.wait(timeout=12)
        except subprocess.TimeoutExpired:
            timed_out = True
            raise
        finally:
            if child.poll() is None:
                assert h.identity_of(child.pid) == identity
                child.terminate()
                child.wait(timeout=3)
            save(output / (label + "-exit.json"), {"argv": argv, "identity": identity,
                 "code": child.returncode, "absent": not Path(f"/proc/{child.pid}").exists(),
                 "timed_out": timed_out})
        assert not Path(f"/proc/{child.pid}").exists()
    assert code == expected, (label, code, (output / (label + ".stderr")).read_text())
    return json.loads((output / (label + ".stdout")).read_bytes()) if code == 0 else None


def cancellation_before_publication(data, evidence_id):
    from aiddos.api.errors import DraftError
    from aiddos.evidence import report, worker
    from aiddos.runs.lifetime import Operation

    original_build, original_check = report.build, Operation.checkpoint
    completed = []
    def built(*args, **kwargs):
        value = original_build(*args, **kwargs)
        completed.append(True)
        return value
    def revoked(self):
        if completed:
            self.revoke()
        original_check(self)
    report.build, Operation.checkpoint = built, revoked
    try:
        with worker.ownership(data["socket"]) as identity:
            try:
                asyncio.run(worker.run(evidence_id, data["socket"], identity))
            except DraftError as error:
                assert error.code == "RUN_DB_UNAVAILABLE"
            else:
                raise AssertionError("cancelled evaluation published")
    finally:
        report.build, Operation.checkpoint = original_build, original_check
    assert completed == [True]
    with connect(data) as db:
        assert db.execute("SELECT count(*) FROM ddospector_evidence_v1.reports"
                          ).fetchone() == (0,)
    save(Path(data["output"]) / "cancellation.json", {
        "actual_build_completed": True, "revoked_before_insert": True,
        "stored_reports": 0, "source": data["source"]})


def no_reparse(data, evidence_id, expected):
    from aiddos.evidence import report, worker
    original = report.build
    def forbidden(*args, **kwargs):
        raise AssertionError("existing report was recomputed")
    report.build = forbidden
    try:
        with worker.ownership(data["socket"]) as identity:
            assert asyncio.run(worker.run(evidence_id, data["socket"], identity)) == (
                "ALREADY_ANALYZED", expected)
    finally:
        report.build = original


def main(data):
    assert data["root"] == str(ROOT)
    assert h.identity_of(data["owner"]["pid"]) == data["owner"]
    assert all(hashlib.sha256((ROOT / n).read_bytes()).hexdigest() == d
               for n, d in data["source"].items())
    output = Path(data["output"])
    os.environ["DDOSPECTOR_RUN_DB_SOCKET"] = data["socket"]
    os.environ["DDOSPECTOR_UI_STATE_PATH"] = str(output / "draft.json")
    from fastapi.testclient import TestClient
    from scenario_producer import definition, register_targets

    from aiddos.api.app import create_app
    from aiddos.api.scenarios import canonical, record_digest
    from aiddos.evidence.samples import make_sample
    from aiddos.runs.migrate import migrate

    assert asyncio.run(migrate(data["socket"])) == "INSTALLED"
    assert migrate_public(data, "evidence-migration")["status"] == "INSTALLED"
    captures = []

    def capture(label, response, status=200):
        (output / (label + ".body")).write_bytes(response.content)
        captures.append({"label": label, "status": response.status_code,
                         "sha256": hashlib.sha256(response.content).hexdigest(),
                         "source": data["source"], "origin": "REAL_OWNED_PG_ASGI_HTTP"})
        save(output / "wire-manifest.json", captures)
        assert response.status_code == status, (label, response.text)
        return response

    with TestClient(create_app(), base_url="http://localhost") as client:
        policy = definition(register_targets(client))
        policy["success_criteria"]["minimum_delivery_pct"] = 95
        scenario = capture("scenario", client.post("/api/v1/scenarios", json={
            "revision": 0, "definition": policy}), 201).json()["scenario"]
        run_id = capture("run-created", client.post("/api/v1/offline-runs", json={
            "request_id": str(uuid4()), "mode": "OFFLINE", "scenario_id": scenario["id"],
            "scenario_version": scenario["version"], "scenario_digest": scenario["digest"]}),
            202).json()["run"]["id"]
        assert invoke(data, run_id, "run-worker") == 0
        run_path = "/api/v1/offline-runs/" + run_id
        before = capture("run-before", client.get(run_path)).content
        events = capture("events-before", client.get(run_path + "/events")).content
        original_core = core_bytes(data, run_id)
        for key, raw in original_core.items():
            (output / ("original-core-" + key + ".body")).write_bytes(raw)
        root = "/api/v1/evidence"
        retained = []
        for sample, outcome in (("complete", "SATISFIED"), ("violation", "VIOLATED"),
                                ("unknown", "UNKNOWN")):
            pair = make_sample(sample)
            payload = {"request_id": str(uuid4()), "run_id": run_id,
                       **{side: {"name": " original " + side + ".pcap",
                                 "base64": base64.b64encode(getattr(pair, side)).decode("ascii")}
                          for side in ("ingress", "egress")}}
            old = capture(sample + "-registered", client.post(root, json=payload), 201).json()
            evidence_id = old["evidence"]["id"]
            with connect(data) as db:
                saved = db.execute("SELECT metadata,ingress,egress FROM "
                                   "ddospector_evidence_v1.bundles WHERE id=%s",
                                   (evidence_id,)).fetchone()
            assert old["report"] is None
            if sample == "complete":
                fd = os.open(data["socket"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    evaluate(data, evidence_id, "contention", 78)
                    with connect(data) as db:
                        assert db.execute("SELECT count(*) FROM ddospector_evidence_v1.reports"
                                          ).fetchone() == (0,)
                finally:
                    os.close(fd)
            if sample == "complete":
                cancellation_before_publication(data, evidence_id)
            with connect(data) as db:
                producer_before = db.execute("SELECT clock_timestamp()").fetchone()[0]
            response = evaluate(data, evidence_id, sample + "-evaluate")
            with connect(data) as db:
                producer_after = db.execute("SELECT clock_timestamp()").fetchone()[0]
            assert response["status"] == "ANALYZED"
            report = response["report"]
            assert report == expected_report(old["evidence"], policy, pair, report["created_at"])
            assert report["outcome"] == outcome and report["sample_id"] == sample
            assert report["policy"]["minimum_delivery_pct"] == 95
            assert report["scenario_evaluation"] == "NOT_EVALUATED"
            assert report["defense_verdict"] is None
            assert report["unassessed_requirements"] == ["service_probe"]
            assert report["digest"] == record_digest(report)
            assert report["run_snapshot_digest"] == json.loads(before)["snapshot"]["digest"]
            from aiddos.runs.validation import moment
            assert producer_before <= moment(report["created_at"]) <= producer_after
            assert report["created_at"] >= old["evidence"]["created_at"]
            selected = root + "/" + evidence_id
            detail = capture(sample + "-detail", client.get(selected)).json()
            assert detail == {"schema_version": 1, "evidence": {
                **old["evidence"], "analysis_state": "ANALYZED"}, "report": report}
            for label, response in (("replay", client.post(root, json=payload)),
                                    ("by-request", client.get(root + "/by-request/" +
                                                               payload["request_id"]))):
                assert capture(sample + "-" + label, response).json() == detail
            for side in ("ingress", "egress"):
                assert capture(sample + "-" + side, client.get(selected + "/raw/" + side)
                               ).content == getattr(pair, side)
            repeated = evaluate(data, evidence_id, sample + "-repeat")
            assert repeated == {**response_envelope(report), "status": "ALREADY_ANALYZED"}
            with connect(data) as db:
                assert db.execute("SELECT metadata,ingress,egress FROM "
                                  "ddospector_evidence_v1.bundles WHERE id=%s",
                                  (evidence_id,)).fetchone() == saved
                body, sha = db.execute("SELECT body,sha256 FROM ddospector_evidence_v1.reports "
                                       "WHERE bundle_id=%s", (evidence_id,)).fetchone()
                assert body == canonical(report) and sha == hashlib.sha256(body).hexdigest()
            no_reparse(data, evidence_id, report)
            retained.append((evidence_id, report, payload))

        from aiddos.runs.lifetime import Operation
        execute = Operation.execute
        census = []
        async def observe(self, sql, args=None):
            rows = await execute(self, sql, args)
            census.append({"sql": sql, "rows": len(rows), "byte_columns": [
                [len(v) for v in row if type(v) is bytes] for row in rows]})
            return rows
        Operation.execute = observe
        try:
            listing = capture("analyzed-list", client.get(root))
        finally:
            Operation.execute = execute
        assert listing.json()["total"] == 3 and len(listing.content) <= 65536
        assert all(v["analysis_state"] == "ANALYZED" and "report" not in v
                   for v in listing.json()["items"])
        assert not any(",ingress,egress FROM" in row["sql"] for row in census)
        report_reads = [row for row in census if row["sql"].startswith("SELECT body,sha256")]
        assert len(report_reads) == 3
        assert sum(row["rows"] for row in report_reads) == 3
        assert all(size <= 32768 for row in report_reads for columns in row["byte_columns"]
                   for size in columns)
        save(output / "list-query-census.json", census)

        # Owner-only corruption fixtures in this disposable world, no runtime repair.
        evidence_id, report, payload = retained[0]
        selected = root + "/" + evidence_id
        def replace(raw, sha):
            with connect(data, owner=True) as db:
                db.execute("ALTER TABLE ddospector_evidence_v1.reports "
                           "DISABLE TRIGGER reports_immutable")
                db.execute("UPDATE ddospector_evidence_v1.reports SET body=%s,sha256=%s "
                           "WHERE bundle_id=%s", (raw, sha, evidence_id))
                db.execute("ALTER TABLE ddospector_evidence_v1.reports "
                           "ENABLE TRIGGER reports_immutable")
        good = canonical(report)
        foreign = json.loads(good)
        foreign["policy"]["minimum_delivery_pct"] = 90
        foreign["digest"] = record_digest(foreign)
        for label, raw, sha, list_status in (
            ("malformed", b"{}", hashlib.sha256(b"{}").hexdigest(), 503),
            ("stored-sha", good, "0" * 64, 503),
            ("foreign-policy", canonical(foreign), hashlib.sha256(canonical(foreign)).hexdigest(),
             200),
        ):
            replace(raw, sha)
            try:
                capture(label + "-list", client.get(root), list_status)
                for name, path in (("detail", selected), ("raw", selected + "/raw/ingress"),
                                   ("by-request", root + "/by-request/" + payload["request_id"])):
                    assert capture(label + "-" + name, client.get(path), 503).json()["code"] == (
                        "EVIDENCE_STATE_CORRUPT")
                assert capture(label + "-replay", client.post(root, json=payload), 503
                               ).json()["code"] == "EVIDENCE_STATE_CORRUPT"
                evaluate(data, evidence_id, label + "-evaluate", 75)
                with connect(data) as db:
                    assert db.execute("SELECT body,sha256 FROM ddospector_evidence_v1.reports "
                                      "WHERE bundle_id=%s", (evidence_id,)).fetchone() == (raw, sha)
            finally:
                replace(good, hashlib.sha256(good).hexdigest())
        assert core_bytes(data, run_id) == original_core
        assert capture("run-after", client.get(run_path)).content == before
        assert capture("events-after", client.get(run_path + "/events")).content == events
        assert capture("list-restored", client.get(root)).content == listing.content
    from aiddos.runs.lifetime import manager
    drain = manager().drain_result
    assert drain["outcome"] == "CLEAN" and not manager().operations
    with connect(data) as db:
        assert db.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                          "AND pid<>pg_backend_pid() AND usename='aiddos_s02'").fetchone() == (0,)
    origins = {}
    for name, module in tuple(sys.modules.items()):
        if name.startswith(("aiddos.", "ddospector.")) and getattr(module, "__file__", None):
            path = Path(module.__file__).resolve()
            assert path.is_relative_to(ROOT / "src"), (name, path)
            origins[name] = {"path": str(path),
                             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    save(output / "source-origins.json", {"modules": origins, "executable": sys.executable,
                                          "prefix": sys.prefix})
    save(output / "result.json", {"evaluation_readback": True, "run_unchanged": True,
                                 "source": data["source"], "api_drain": drain,
                                 "evaluators_retired": True, "outcomes": [r[1]["outcome"]
                                                                          for r in retained]})


def expected_report(summary, policy, pair, created_at):
    """Independent direct framing of the known generated PCAPs (not product parser)."""
    from aiddos.api.scenarios import record_digest
    captures = {}
    for side in ("ingress", "egress"):
        raw = getattr(pair, side)
        offset, count, wire, payload = 24, 0, 0, 0
        timestamps = []
        while offset < len(raw):
            sec, usec, included, original = struct.unpack("<IIII", raw[offset:offset + 16])
            frame = raw[offset + 16:offset + 16 + included]
            assert included == original and len(frame) == included
            wire += original
            payload += int.from_bytes(frame[16:18], "big") - 40
            count += 1
            timestamps.append(sec * 1000000000 + usec * 1000)
            offset += 16 + included
        assert offset == len(raw)
        captures[side] = {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw),
            "parse_error": None, "packet_count": count, "wire_bytes": wire,
            "payload_bytes": payload, "first_timestamp_ns": str(timestamps[0]),
            "last_timestamp_ns": str(timestamps[-1]), "timestamps_ordered": True}
    matched = 10 if pair.sample_id == "complete" else 9
    expected = {"schema_version": 1, "kind": "offline_capture_criterion",
        "rule_id": "TCP_ALLOW_CAPTURE_V1", "scope": "CAPTURE_RECORDSET_ONLY",
        "evidence_id": summary["id"], "run_id": summary["run_id"],
        "run_snapshot_digest": summary["run_snapshot_digest"], "created_at": created_at,
        "provenance": "SYNTHETIC", "sample_id": pair.sample_id, "coverage": pair.coverage,
        "outcome": {"complete": "SATISFIED", "violation": "VIOLATED", "unknown": "UNKNOWN"}[
            pair.sample_id], "scenario_evaluation": "NOT_EVALUATED", "defense_verdict": None,
        "policy": {**{key: policy[key] for key in ("profile_id", "ip_version", "protocol",
            "expected_action", "delivery_expectation", "detection_required",
            "evidence_requirements")}, **policy["success_criteria"]},
        "captures": captures, "facts": {"matched_packets": matched,
            "unmatched_ingress_packets": 10 - matched, "unmatched_egress_packets": 0,
            "delivery_basis_points_floor": matched * 1000},
        "issues": ["CAPTURE_COVERAGE_UNKNOWN"] if pair.sample_id == "unknown" else [],
        "unassessed_requirements": ["service_probe"]}
    expected["digest"] = record_digest(expected)
    return expected


def response_envelope(report):
    return {"schema_version": 1, "status": "ANALYZED", "report": report}


if __name__ == "__main__":
    main(json.loads(Path(sys.argv[1]).read_text()))
