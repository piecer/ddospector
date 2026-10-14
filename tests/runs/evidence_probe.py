"""Real owned PostgreSQL + ASGI registration; source-bound original byte receipts."""

import asyncio
import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from phase1_probe import ROOT, h, invoke, save


def migrate_public(data, label):
    output = Path(data["output"])
    env = h.child_environment(output) | {"DDOSPECTOR_RUN_DB_SOCKET": data["socket"]}
    argv = [sys.executable, "-m", "ddospector.evidence.migrate"]
    with (output / (label + ".stdout")).open("wb") as stdout, (
        output / (label + ".stderr")
    ).open("wb") as stderr:
        child = subprocess.Popen(argv, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                 stdout=stdout, stderr=stderr, start_new_session=True)
        identity = h.identity_of(child.pid)
        try:
            assert child.wait(timeout=15) == 0
        finally:
            if child.poll() is None:
                assert h.identity_of(child.pid) == identity
                child.terminate()
                child.wait(timeout=3)
            save(output / (label + "-exit.json"), {"argv": argv, "identity": identity,
                 "code": child.returncode, "absent": not Path(f"/proc/{child.pid}").exists()})
        assert not Path(f"/proc/{child.pid}").exists()
    return json.loads((output / (label + ".stdout")).read_bytes())


def main(data):
    assert data["root"] == str(ROOT)
    assert h.identity_of(data["owner"]["pid"]) == data["owner"]
    assert all(hashlib.sha256((ROOT / n).read_bytes()).hexdigest() == d
               for n, d in data["source"].items())
    output = Path(data["output"])
    os.environ["DDOSPECTOR_RUN_DB_SOCKET"] = data["socket"]
    os.environ["DDOSPECTOR_UI_STATE_PATH"] = str(output / "draft.json")
    from evidence_checks import check_controls, core_bytes
    from fastapi.testclient import TestClient
    from scenario_producer import definition, register_targets

    from aiddos.api.app import create_app
    from aiddos.evidence.samples import make_sample
    from aiddos.runs.migrate import migrate

    assert asyncio.run(migrate(data["socket"])) == "INSTALLED"
    captures = []

    def capture(label, response, status):
        (output / (label + ".body")).write_bytes(response.content)
        captures.append({"label": label, "file": label + ".body", "status": response.status_code,
                         "headers": list(response.headers.multi_items()),
                         "method": response.request.method, "url": str(response.request.url),
                         "size_bytes": len(response.content),
                         "sha256": hashlib.sha256(response.content).hexdigest(),
                         "origin": "REAL_OWNED_PG_ASGI_HTTP"})
        save(output / "wire-manifest.json", captures)
        assert response.status_code == status, (label, response.text)
        return response

    with TestClient(create_app(), base_url="http://localhost") as client:
        unavailable = capture("not-ready", client.get("/api/v1/evidence"), 503)
        assert unavailable.json()["code"] == "EVIDENCE_NOT_READY"
        assert migrate_public(data, "migration-install") == {
            "schema_version": 1, "status": "INSTALLED"}
        assert migrate_public(data, "migration-matching") == {
            "schema_version": 1, "status": "MATCHING"}
        capture("empty", client.get("/api/v1/evidence"), 200)
        response = client.post("/api/v1/scenarios", json={
            "revision": 0, "definition": definition(register_targets(client)),
        })
        assert response.status_code == 201, response.text
        scenario = response.json()["scenario"]
        created = client.post("/api/v1/offline-runs", json={
            "request_id": str(uuid4()), "mode": "OFFLINE", "scenario_id": scenario["id"],
            "scenario_version": scenario["version"], "scenario_digest": scenario["digest"],
        })
        assert created.status_code == 202, created.text
        run_id = created.json()["run"]["id"]
        pair = make_sample("complete")
        payload = {"request_id": str(uuid4()), "run_id": run_id,
                   **{side: {"name": " original " + side + ".pcap",
                             "base64": base64.b64encode(getattr(pair, side)).decode("ascii")}
                      for side in ("ingress", "egress")}}
        capture("run-pending", client.post("/api/v1/evidence", json=payload), 409)
        assert invoke(data, run_id, "worker") == 0
        run_path = "/api/v1/offline-runs/" + run_id
        before = capture("run-before", client.get(run_path), 200).content
        events = capture("events-before", client.get(run_path + "/events"), 200).content
        assert json.loads(before)["run"]["state"] == "SUCCEEDED"
        original_core = core_bytes(data, run_id)
        for key, raw in original_core.items():
            (output / ("original-core-" + key + ".body")).write_bytes(raw)
        response = capture("created", client.post("/api/v1/evidence", json=payload), 201)
        detail = response.json()
        assert detail["report"] is None
        assert detail["evidence"]["provenance"] == "SYNTHETIC"
        assert detail["evidence"]["run_snapshot_digest"] == json.loads(before)["snapshot"]["digest"]
        selected = "/api/v1/evidence/" + detail["evidence"]["id"]
        assert capture("detail", client.get(selected), 200).content == response.content
        assert capture("by-request", client.get("/api/v1/evidence/by-request/" +
                       payload["request_id"]), 200).content == response.content
        assert capture("replayed", client.post("/api/v1/evidence", json=payload),
                       200).content == response.content
        for side in ("ingress", "egress"):
            raw = capture("raw-" + side, client.get(selected + "/raw/" + side), 200)
            assert raw.content == getattr(pair, side)
            assert "content-encoding" not in raw.headers
            assert raw.headers["x-content-type-options"] == "nosniff"
        assert capture("list", client.get("/api/v1/evidence"), 200).json()["total"] == 1
        check_controls(client, data, capture, payload, detail)
        assert core_bytes(data, run_id) == original_core
        assert capture("run-after", client.get(run_path), 200).content == before
        assert capture("events-after", client.get(run_path + "/events"), 200).content == events
    from aiddos.runs.lifetime import manager
    drain = manager().drain_result
    assert drain["outcome"] == "CLEAN" and not manager().operations
    origins = {}
    for name, module in tuple(sys.modules.items()):
        if name.startswith(("aiddos.", "ddospector.")) and getattr(module, "__file__", None):
            path = Path(module.__file__).resolve()
            assert path.is_relative_to(ROOT / "src"), (name, path)
            origins[name] = {"path": str(path),
                             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    save(output / "source-origins.json", {"modules": origins, "executable": sys.executable,
                                          "prefix": sys.prefix})
    save(output / "result.json", {"registration_readback": True, "run_unchanged": True,
                                 "source": data["source"], "kind": "REAL_OWNED_PG_ASGI",
                                 "api_drain": drain})


if __name__ == "__main__":
    main(json.loads(Path(sys.argv[1]).read_text()))
