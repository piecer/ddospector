"""Required readiness-marker faults after real migration and genuine admission."""

import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from aiddos.api import scenario_store
from aiddos.api.app import create_app
from aiddos.runs import repository, schema
from aiddos.runs.lifetime import Operation, manager

ROOT = Path(__file__).resolve().parents[2]
NOT_READY = {
    "code": "RUN_DB_NOT_READY",
    "message": "Offline run storage requires the supported schema and durability settings.",
}


def configuration(handoff, output, endpoint, result):
    import os

    import psycopg

    kind, route = handoff["case"].removeprefix("schema-configuration-").rsplit("-", 1)
    assert kind in {"invalid", "unconfigured"} and route in {"run", "request", "post"}
    calls = []

    async def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("INVALID_CONFIGURATION_DIALED")

    native = psycopg.AsyncConnection.connect
    psycopg.AsyncConnection.connect = forbidden
    if kind == "invalid":
        os.environ["AIDDOS_RUN_DB_SOCKET"] = str(endpoint) + "/absent-owned-socket"
    else:
        os.environ.pop("AIDDOS_RUN_DB_SOCKET")
    request = {
        "request_id": str(uuid4()),
        "mode": "OFFLINE",
        "scenario_id": str(uuid4()),
        "scenario_version": 1,
        "scenario_digest": "a" * 64,
    }
    assert not manager().closed
    try:
        with TestClient(
            create_app(state_path=output / "draft.json"), base_url="http://localhost"
        ) as client:
            response = (
                client.post("/api/v1/offline-runs", json=request)
                if route == "post"
                else client.get(
                    "/api/v1/offline-runs/"
                    + ("by-request/" if route == "request" else "")
                    + str(uuid4())
                )
            )
            result["configuration"] = {
                "status": response.status_code,
                "body": response.json(),
                "driver_calls": len(calls),
                "fresh_manager": True,
            }
            (output / "configuration.json").write_text(json.dumps(result, indent=2) + "\n")
            assert response.status_code == 503
            assert response.json() == (
                {"code": "RUN_DB_UNAVAILABLE", "message": "Offline run storage is unavailable."}
                if kind == "invalid"
                else {
                    "code": "RUN_DB_NOT_CONFIGURED",
                    "message": "Offline run storage is not configured.",
                }
            )
            assert response.headers["cache-control"] == "no-store" and len(response.content) <= 1024
            assert not calls
        result["configuration"]["drain_before_rescue"] = manager().drain_result
        assert manager().drain_result["outcome"] == "CLEAN"
    finally:
        psycopg.AsyncConnection.connect = native
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")


def readiness(handoff, output, endpoint, connect, h, result):
    column, route = handoff["case"].removeprefix("schema-readiness-").rsplit("-", 1)
    assert column in {"checksum", "version", "shape", "checksum-value", "shape-value", "empty"}
    assert route in {"run", "request", "post"}
    assert Path(repository.__file__) == ROOT / "src/aiddos/runs/repository.py"
    assert Path(schema.__file__) == ROOT / "src/aiddos/runs/schema.py"
    evidence = {
        "transport": "actual in-process ASGI TestClient; real invocation-owned PostgreSQL",
        "column": column,
        "route": route,
        "fault_fired": False,
        "source_calls": 0,
        "dml_calls": 0,
        "denied": [],
        "migrations": [],
        "repository_sha256": hashlib.sha256(Path(repository.__file__).read_bytes()).hexdigest(),
    }
    result["schema_readiness"] = evidence

    def save():
        (output / "schema-readiness.json").write_text(json.dumps(evidence, indent=2) + "\n")

    def snapshot():
        with connect(**h.connection_parameters(endpoint), autocommit=True) as db:
            data = {
                table: db.execute(
                    "SELECT row_to_json(t)::text FROM aiddos_runs_v1."
                    + table
                    + " t ORDER BY row_to_json(t)::text"
                ).fetchall()
                for table in ("schema_version", "quota", "inputs", "jobs", "events", "results")
            }
            data["catalog"] = db.execute(schema.SHAPE).fetchall()
            return data

    def migrate(expected, code):
        env = h.child_environment(output)
        env["AIDDOS_RUN_DB_SOCKET"] = str(endpoint)
        process = subprocess.Popen(
            [handoff["python"], "-m", "aiddos.runs.migrate"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        ident = h.identity_of(process.pid)
        stdout, stderr = process.communicate(timeout=15)
        observed = {
            "identity": ident,
            "exit": process.returncode,
            "absent": not Path(f"/proc/{process.pid}").exists(),
            "stdout": stdout.decode(),
            "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
            "stderr_bytes": len(stderr),
        }
        evidence["migrations"].append(observed)
        save()
        assert process.returncode == code and observed["absent"]
        assert json.loads(stdout) == {"schema_version": 1, "status": expected}

    migrate("INSTALLED", 0)
    before_repeat = snapshot()
    migrate("MATCHING", 0)
    evidence["repeat_unchanged"] = snapshot() == before_repeat
    assert evidence["repeat_unchanged"]
    sys.path.insert(0, str(ROOT / "tests/api"))
    from scenario_producer import definition, register_targets

    with TestClient(
        create_app(state_path=output / "draft.json"), base_url="http://localhost"
    ) as client:
        targets = register_targets(client)
        source = client.post(
            "/api/v1/scenarios", json={"revision": 0, "definition": definition(targets)}
        )
        assert source.status_code == 201
        record = source.json()["scenario"]
        request = {
            "request_id": str(uuid4()),
            "mode": "OFFLINE",
            "scenario_id": record["id"],
            "scenario_version": record["version"],
            "scenario_digest": record["digest"],
        }
        created = client.post("/api/v1/offline-runs", json=request)
        assert created.status_code == 202 and created.json()["run"]["state"] == "QUEUED"
        prefix = "/api/v1/offline-runs/" + ("by-request/" if route == "request" else "")
        existing = request["request_id"] if route == "request" else created.json()["run"]["id"]
        missing = str(uuid4())
        read = client.get(prefix + existing)
        assert read.status_code == 200 and read.content == created.content
        replay = client.post("/api/v1/offline-runs", json=request)
        assert replay.status_code == 200 and replay.content == created.content
        absent = client.get(prefix + missing)
        assert absent.status_code == 404 and absent.json() == {
            "code": "RUN_NOT_FOUND",
            "message": "No such offline run or request.",
        }
        evidence["healthy"] = {
            "create": 202,
            "read": read.status_code,
            "replay": replay.status_code,
            "missing": 404,
        }
        for control in (created, read, replay, absent):
            assert control.headers["cache-control"] == "no-store"
        with connect(
            **h.connection_parameters(endpoint, user="aiddos_s02_owner"), autocommit=True
        ) as db:
            if column in {"checksum", "version", "shape"}:
                db.execute(
                    "ALTER TABLE aiddos_runs_v1.schema_version RENAME COLUMN "
                    + column
                    + " TO incompatible_"
                    + column
                )
                columns = [
                    r[0]
                    for r in db.execute(
                        "SELECT column_name FROM information_schema.columns WHERE "
                        "table_schema='aiddos_runs_v1' AND table_name='schema_version'"
                    ).fetchall()
                ]
                evidence["fault_fired"] = (
                    column not in columns and "incompatible_" + column in columns
                )
                evidence["columns"] = columns
            elif column.endswith("-value"):
                field = column.removesuffix("-value")
                db.execute("UPDATE aiddos_runs_v1.schema_version SET " + field + "=%s", ("0" * 64,))
                evidence["fault_fired"] = db.execute(
                    "SELECT " + field + " FROM aiddos_runs_v1.schema_version"
                ).fetchall() == [("0" * 64,)]
            else:
                db.execute("DELETE FROM aiddos_runs_v1.schema_version")
                evidence["fault_fired"] = db.execute(
                    "SELECT count(*) FROM aiddos_runs_v1.schema_version"
                ).fetchone() == (0,)
        save()
        assert evidence["fault_fired"]
        native_history, native_execute = scenario_store.ScenarioStore.history, Operation.execute

        def no_source(*args, **kwargs):
            evidence["source_calls"] += 1
            raise AssertionError("READINESS_DENIAL_REOPENED_SOURCE")

        async def track_execute(op, sql, *args, **kwargs):
            if sql.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE", "ALTER", "CREATE"}:
                evidence["dml_calls"] += 1
            return await native_execute(op, sql, *args, **kwargs)

        scenario_store.ScenarioStore.history = no_source
        Operation.execute = track_execute
        try:
            try:
                no_source()
            except AssertionError:
                evidence["source_guard_fired"] = True
            assert evidence["source_calls"] == 1
            evidence["source_calls"] = 0
            evidence["preservation"] = []
            for corrupt_quota in (False, True):
                if corrupt_quota:
                    with connect(
                        **h.connection_parameters(endpoint, user="aiddos_s02_owner"),
                        autocommit=True,
                    ) as db:
                        db.execute("UPDATE aiddos_runs_v1.quota SET unfinished_count=0")
                        evidence["quota_fault_fired"] = db.execute(
                            "SELECT unfinished_count FROM aiddos_runs_v1.quota"
                        ).fetchall() == [(0,)] and db.execute(
                            "SELECT state,event_count FROM aiddos_runs_v1.jobs"
                        ).fetchall() == [("QUEUED", 1)]
                    assert evidence["quota_fault_fired"]
                before = snapshot()
                for target in (missing, existing):
                    denied = (
                        client.post(
                            "/api/v1/offline-runs",
                            json={**request, "request_id": missing}
                            if target == missing
                            else request,
                        )
                        if route == "post"
                        else client.get(prefix + target)
                    )
                    evidence["denied"].append(
                        {
                            "status": denied.status_code,
                            "body": denied.json(),
                            "no_store": denied.headers["cache-control"],
                            "target": "missing/new" if target == missing else "existing/replay",
                            "corrupt_quota": corrupt_quota,
                        }
                    )
                    after = snapshot()
                    evidence["unchanged"] = after == before
                    evidence["preservation"].append(
                        {
                            "before_sha256": hashlib.sha256(
                                json.dumps(before).encode()
                            ).hexdigest(),
                            "after_sha256": hashlib.sha256(json.dumps(after).encode()).hexdigest(),
                            "catalog_and_all_retained_tables": True,
                        }
                    )
                    save()
                    assert evidence["unchanged"]
                    assert evidence["source_calls"] == evidence["dml_calls"] == 0
                    assert denied.status_code == 503 and denied.json() == NOT_READY
                    assert denied.headers["cache-control"] == "no-store"
                    assert len(denied.content) <= 1024
        finally:
            scenario_store.ScenarioStore.history = native_history
            Operation.execute = native_execute
            save()

        async def retired():
            tasks = {op.coordinator for op in manager().operations}
            if tasks:
                await asyncio.wait(tasks, timeout=1)
            return len(manager().operations)

        evidence["retained_before_rescue"] = client.portal.call(retired)
        assert evidence["retained_before_rescue"] == 0
    evidence["drain_before_rescue"] = manager().drain_result
    assert evidence["drain_before_rescue"]["outcome"] == "CLEAN"
    before_refused = snapshot()
    migrate("REFUSED", 78)
    evidence["refused_unchanged"] = snapshot() == before_refused
    assert evidence["refused_unchanged"]
    save()
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
