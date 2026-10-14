"""Owned normal one-shot proof; no outage, restart, failover or traffic."""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/api"))

from tools import s02_harness as h  # noqa: E402


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def invoke(data, run_id, label):
    output = Path(data["output"])
    env = h.child_environment(output)
    env["DDOSPECTOR_RUN_DB_SOCKET"] = data["socket"]
    argv = [sys.executable, "-m", "ddospector.runs.worker", "--run-id", run_id]
    with (
        (output / f"{label}.stdout").open("wb") as stdout,
        (output / f"{label}.stderr").open("wb") as stderr,
    ):
        process = subprocess.Popen(
            argv, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
            stdout=stdout, stderr=stderr, start_new_session=True,
        )
        identity = None
        timed_out = False
        try:
            identity = h.identity_of(process.pid)
            save(output / f"{label}-started.json", {"identity": identity, "argv": argv})
            code = process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            timed_out = True
            raise
        finally:
            if process.poll() is None:
                assert identity is None or h.identity_of(process.pid) == identity
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    assert h.identity_of(process.pid) == identity
                    process.kill()
                    process.wait(timeout=2)
            save(output / f"{label}-exit.json", {
                "code": process.returncode, "identity": identity, "timed_out": timed_out,
                "absent": not Path(f"/proc/{process.pid}").exists(),
            })
    assert not Path(f"/proc/{process.pid}").exists()
    return code


def main(data):
    assert data["root"] == str(ROOT)
    assert h.identity_of(data["owner"]["pid"]) == data["owner"]
    assert all(
        hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
        for name, digest in data["source"].items()
    )
    os.environ["DDOSPECTOR_RUN_DB_SOCKET"] = data["socket"]
    os.environ["DDOSPECTOR_UI_STATE_PATH"] = str(Path(data["output"]) / "draft.json")
    import psycopg
    from fastapi.testclient import TestClient
    from scenario_producer import definition, register_targets

    from aiddos.api.app import create_app
    from aiddos.api.scenarios import canonical
    from aiddos.runs import schema, transitions
    from aiddos.runs.migrate import migrate
    from aiddos.runs.repository import timestamp
    from aiddos.runs.worker_connection import ConnectionOwner

    assert asyncio.run(migrate(data["socket"])) == "INSTALLED"
    with TestClient(create_app(), base_url="http://localhost") as client:
        captured = []

        def capture(label, response, kind, method="GET", **context):
            assert response.status_code in {200, 202}, response.text
            captured.append({
                "label": label, "raw": response.content.decode("utf-8"),
                "sha256": hashlib.sha256(response.content).hexdigest(),
                "context": {"method": method, "status": response.status_code,
                            "kind": kind, **context},
                "expected": "ACCEPT", "provenance": "RECORDED_ASGI_HTTP",
            })

        response = client.post("/api/v1/scenarios", json={
            "revision": 0, "definition": definition(register_targets(client)),
        })
        assert response.status_code == 201, response.text
        scenario = response.json()["scenario"]
        capture("list-0", client.get("/api/v1/offline-runs"), "list", after=0, limit=20)
        response = client.post("/api/v1/offline-runs", json={
            "request_id": str(uuid4()), "mode": "OFFLINE", "scenario_id": scenario["id"],
            "scenario_version": scenario["version"], "scenario_digest": scenario["digest"],
        })
        capture("create-1", response, "create", "POST")
        cancelled_id = response.json()["run"]["id"]
        path = f"/api/v1/offline-runs/{cancelled_id}"
        capture("detail-2", client.get(path), "detail", id=cancelled_id)
        capture("events-3", client.get(path + "/events"), "events",
                id=cancelled_id, after=0, limit=16)
        capture("cancel-4", client.post(path + "/cancel", json={}), "cancel", "POST",
                id=cancelled_id)
        capture("events-5", client.get(path + "/events"), "events",
                id=cancelled_id, after=0, limit=16)
        created = []
        for _ in range(2):
            response = client.post("/api/v1/offline-runs", json={
                "request_id": str(uuid4()), "mode": "OFFLINE", "scenario_id": scenario["id"],
                "scenario_version": scenario["version"], "scenario_digest": scenario["digest"],
            })
            assert response.status_code == 202, response.text
            created.append(response.json())
        selected = created[1]["run"]["id"]
        request_id = created[1]["run"]["request_id"]
        capture("request-6", client.get(f"/api/v1/offline-runs/by-request/{request_id}"),
                "request", id=request_id)
        capture("list-7", client.get("/api/v1/offline-runs"), "list", after=0, limit=20)
        path = f"/api/v1/offline-runs/{selected}"
        capture("detail-8", client.get(path), "detail", id=selected)
        capture("events-9", client.get(path + "/events"), "events",
                id=selected, after=0, limit=16)
        save(Path(data["output"]) / "created.json", created)
        code = invoke(data, selected, "selected")
        assert code == 0, f"one-shot exit {code}; inspect retained worker logs"
        response = client.get(f"/api/v1/offline-runs/{selected}")
        detail = response.json()
        capture("detail-10", response, "detail", id=selected)
        capture("events-11", client.get(path + "/events"), "events",
                id=selected, after=0, limit=16)
        save(Path(data["output"]) / "captured-wire.json", captured)
        assert detail["run"]["state"] == "SUCCEEDED"
        assert detail["run"]["attempt"] == 1
        other = client.get(f"/api/v1/offline-runs/{created[0]['run']['id']}").json()
        assert other["run"]["state"] == "QUEUED" and other["run"]["attempt"] == 0
        assert invoke(data, selected, "repeat") == 69
        assert client.get(f"/api/v1/offline-runs/{selected}").json() == detail
        with psycopg.connect(**h.connection_parameters(Path(data["socket"]))) as db:
            raw = bytes(db.execute(
                "SELECT result FROM aiddos_runs_v1.results WHERE run_id=%s", (selected,),
            ).fetchone()[0])
        assert json.loads(raw) == detail["result"]

        # A disclosed valid requeued fixture, NOT an executed crash/recovery test.
        previous = created[0]["run"]["id"]
        with psycopg.connect(**h.connection_parameters(Path(data["socket"]))) as db:
            at = db.execute(
                "WITH t AS (SELECT clock_timestamp() AS at) "
                "UPDATE aiddos_runs_v1.jobs SET attempt=1,generation=2,"
                "started_at=t.at,updated_at=t.at,event_count=3 FROM t "
                "WHERE run_id=%s RETURNING updated_at", (previous,),
            ).fetchone()[0]
            for seq, kind, state, generation, reason in (
                (2, "CLAIMED", "RUNNING", 1, None),
                (3, "REQUEUED", "QUEUED", 2, "LEASE_EXPIRED"),
            ):
                event = {"seq": seq, "at": timestamp(at), "type": kind, "state": state,
                         "attempt": 1, "generation": generation, "reason": reason}
                db.execute("INSERT INTO aiddos_runs_v1.events VALUES(%s,%s,%s)",
                           (previous, seq, canonical(event)))
        before = client.get(f"/api/v1/offline-runs/{previous}")
        assert before.status_code == 200, before.text
        assert invoke(data, previous, "previous-attempt") == 69
        assert client.get(f"/api/v1/offline-runs/{previous}").content == before.content

        pending = []
        for _ in range(2):
            response = client.post("/api/v1/offline-runs", json={
                "request_id": str(uuid4()), "mode": "OFFLINE", "scenario_id": scenario["id"],
                "scenario_version": scenario["version"], "scenario_digest": scenario["digest"],
            })
            assert response.status_code == 202, response.text
            pending.append(response.json()["run"]["id"])

        async def leave_unexecuted_claim():
            owner = ConnectionOwner()
            try:
                await owner.acquire(psycopg, h.connection_parameters(Path(data["socket"])))
                await schema.settings(owner.execute)
                assert await transitions.claim(owner, run_id=pending[0]) is not None
            finally:
                assert await owner.dispose()

        asyncio.run(leave_unexecuted_claim())
        # A real claim without computation, not a second competing worker.
        before = client.get(f"/api/v1/offline-runs/{pending[1]}")
        assert before.status_code == 200, before.text
        assert invoke(data, pending[1], "unresolved-lease") == 69
        assert client.get(f"/api/v1/offline-runs/{pending[1]}").content == before.content
        save(Path(data["output"]) / "result.json", {
            "kind": "REAL_PRIVATE_PG_ASGI_HTTP_SEPARATE_ONESHOT_WORKER",
            "run_id": selected, "state": detail["run"]["state"], "attempt": 1,
            "other_run_untouched": True, "repeat_refused": True,
            "stored_result_matches_http": True, "detail": detail,
            "previous_attempt_refused": "VALID_SQL_SEEDED_REQUEUED_FIXTURE",
            "unresolved_lease_refused": "REAL_CLAIM_WITHOUT_COMPUTATION",
            "source": data["source"],
        })


if __name__ == "__main__":
    main(json.loads(Path(sys.argv[1]).read_text()))
