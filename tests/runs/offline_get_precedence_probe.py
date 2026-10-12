"""Additional ASGI/real-owned-PG controls; called after the original guards."""

import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

from aiddos.api import scenario_store

ROOT = Path(__file__).resolve().parents[2]
MESSAGES = {
    "RUN_NOT_FOUND": "No such offline run or request.",
    "RUN_STATE_CORRUPT": "Retained offline run data is invalid; no repair was performed.",
    "RUN_DB_NOT_CONFIGURED": "Offline run storage is not configured.",
    "RUN_DB_NOT_READY": (
        "Offline run storage requires the supported schema and durability settings."
    ),
    "RUN_DB_UNAVAILABLE": "Offline run storage is unavailable.",
}


def precedence(client, response, value, case, output, endpoint, connect, h, result):
    from aiddos.runs import repository

    assert Path(repository.__file__) == ROOT / "src/aiddos/runs/repository.py"
    assert Path(__file__) == ROOT / "tests/runs/offline_get_precedence_probe.py"
    detail = response.json()
    by_request = case.endswith("-request")
    prefix = "/api/v1/offline-runs/" + ("by-request/" if by_request else "")
    existing = value["request_id"] if by_request else detail["run"]["id"]
    missing = str(uuid4())
    assert missing != existing
    evidence = {
        "transport": "in-process ASGI TestClient, not network HTTP",
        "database": "real invocation-owned PostgreSQL",
        "route": "by-request" if by_request else "run-id",
        "repository": repository.__file__,
        "repository_sha256": hashlib.sha256(Path(repository.__file__).read_bytes()).hexdigest(),
        "fault_fired": False,
        "source_calls": 0,
    }
    result["precedence"] = evidence

    def save():
        (output / "precedence.json").write_text(json.dumps(evidence, indent=2) + "\n")

    def snapshot():
        with connect(**h.connection_parameters(endpoint), autocommit=True) as db:
            return {
                table: db.execute(
                    "SELECT row_to_json(t)::text FROM aiddos_runs_v1."
                    + table
                    + " t ORDER BY row_to_json(t)::text"
                ).fetchall()
                for table in ("quota", "inputs", "jobs", "events", "results")
            }

    def observe(name, target):
        reply = client.get(prefix + target)
        evidence[name] = {"status": reply.status_code, "body": reply.json()}
        save()  # Save actual producer result before any contract assertion.
        return reply

    def error(reply, status, code):
        assert reply.status_code == status
        assert reply.json() == {"code": code, "message": MESSAGES[code]}
        assert len(reply.content) <= 1024
        assert reply.headers["cache-control"] == "no-store"

    original = scenario_store.ScenarioStore.history

    def unavailable(*args, **kwargs):
        evidence["source_calls"] += 1
        raise AssertionError("DB-only GET reopened S01")

    scenario_store.ScenarioStore.history = unavailable
    try:
        # Prove the guard is live independently from its required zero GET calls.
        try:
            unavailable()
        except AssertionError:
            evidence["source_guard_fired"] = True
        assert evidence["source_calls"] == 1
        evidence["source_calls"] = 0
        before = snapshot()
        healthy = observe("existing_healthy", existing)
        assert healthy.status_code == 200 and healthy.content == response.content
        error(observe("missing_healthy", missing), 404, "RUN_NOT_FOUND")
        after = snapshot()
        evidence.update(healthy_before=before, healthy_after=after)
        assert before == after
        with connect(
            **h.connection_parameters(endpoint, user="aiddos_s02_owner"), autocommit=True
        ) as db:
            db.execute("UPDATE aiddos_runs_v1.quota SET unfinished_count=0")
            quota = db.execute(
                "SELECT retained_count,unfinished_count,leased_count,reserved_bytes "
                "FROM aiddos_runs_v1.quota"
            ).fetchall()
            jobs = db.execute("SELECT state,event_count FROM aiddos_runs_v1.jobs").fetchall()
        evidence["fault_fired"] = quota == [(1, 0, 0, 65536)] and jobs == [("QUEUED", 1)]
        evidence.update(quota_fault=quota, genuine_jobs=jobs)
        save()
        assert evidence["fault_fired"]
        before = snapshot()
        error(observe("existing_corrupt", existing), 503, "RUN_STATE_CORRUPT")
        missing_reply = observe("missing_corrupt", missing)
        after = snapshot()
        evidence.update(corrupt_before=before, corrupt_after=after, unchanged=before == after)
        save()
        assert before == after and evidence["source_calls"] == 0
        error(missing_reply, 404, "RUN_NOT_FOUND")
        from aiddos.runs.lifetime import manager

        async def retired():
            tasks = {op.coordinator for op in manager().operations}
            if tasks:
                await asyncio.wait(tasks, timeout=1)
            return len(manager().operations)

        evidence["retained_operations_before_rescue"] = client.portal.call(retired)
        assert evidence["retained_operations_before_rescue"] == 0
    finally:
        scenario_store.ScenarioStore.history = original
        save()
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")


def readiness(handoff, output, endpoint, connect, h, result):
    import psycopg
    from fastapi.testclient import TestClient

    from aiddos.api.app import create_app
    from aiddos.runs.lifetime import manager

    case = handoff["case"]
    kind, route = case.removeprefix("get-readiness-").rsplit("-", 1)
    expected = {
        "unconfigured": "RUN_DB_NOT_CONFIGURED",
        "missing-schema": "RUN_DB_NOT_READY",
        "invalid-schema": "RUN_DB_NOT_READY",
        "outage": "RUN_DB_UNAVAILABLE",
    }[kind]
    evidence = {"case": case, "transport": "in-process ASGI TestClient", "control_fired": False}
    result["readiness"] = evidence
    native = psycopg.AsyncConnection.connect
    calls = []

    async def tracked(*args, **kwargs):
        calls.append(True)
        return await native(*args, **kwargs)

    if kind == "invalid-schema":
        env = h.child_environment(output)
        env["AIDDOS_RUN_DB_SOCKET"] = str(endpoint)
        process = subprocess.Popen(
            [handoff["python"], "-m", "aiddos.runs.migrate"],
            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        identity = h.identity_of(process.pid)
        stdout, stderr = process.communicate(timeout=15)
        evidence["migration"] = {
            "identity": identity, "code": process.returncode,
            "absent": not Path(f"/proc/{process.pid}").exists(),
            "stdout": stdout.decode(), "stderr_bytes": len(stderr),
        }
        assert process.returncode == 0
        with connect(
            **h.connection_parameters(endpoint, user="aiddos_s02_owner"), autocommit=True
        ) as db:
            db.execute("ALTER TABLE aiddos_runs_v1.quota ADD COLUMN foreign_column integer")
    if kind == "unconfigured":
        del os.environ["AIDDOS_RUN_DB_SOCKET"]

    def schema_state():
        with connect(**h.connection_parameters(endpoint), autocommit=True) as db:
            return db.execute(
                "SELECT table_name,column_name,data_type FROM information_schema.columns "
                "WHERE table_schema='aiddos_runs_v1' ORDER BY table_name,ordinal_position"
            ).fetchall()

    before = None if kind == "outage" else schema_state()
    psycopg.AsyncConnection.connect = tracked
    try:
        with TestClient(
            create_app(state_path=output / "draft.json"), base_url="http://localhost"
        ) as client:
            prefix = "/api/v1/offline-runs/" + ("by-request/" if route == "request" else "")
            response = client.get(prefix + str(uuid4()))
            evidence.update(status=response.status_code, body=response.json(), connects=len(calls))
            evidence["control_fired"] = (
                len(calls) == 0 and "AIDDOS_RUN_DB_SOCKET" not in os.environ
                if kind == "unconfigured" else len(calls) == 1
            )
            (output / "readiness.json").write_text(json.dumps(evidence, indent=2) + "\n")
            assert evidence["control_fired"]
            assert response.status_code == 503
            assert response.json() == {"code": expected, "message": MESSAGES[expected]}
            assert len(response.content) <= 1024
            assert response.headers["cache-control"] == "no-store"
            assert client.get("/api/v1/health").status_code == 200
        evidence["drain_before_rescue"] = manager().drain_result
        assert manager().drain_result["outcome"] == "CLEAN"
    finally:
        psycopg.AsyncConnection.connect = native
    if kind != "outage":
        after = schema_state()
        evidence.update(schema_before=before, schema_after=after)
        assert before == after
        if kind in {"unconfigured", "missing-schema"}:
            assert before == []
        else:
            assert ("quota", "foreign_column", "integer") in before
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
