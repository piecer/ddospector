"""Owned application probes. No archived runtime or I0 borrower protocol."""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
APPLICATION_CASES = {
    "get-precedence-run",
    "get-precedence-request",
    "create",
    "idempotency",
    "lock",
    "terminal-fixture",
    "quota",
    "retention",
    "atomic",
    "uncertain",
    "corrupt",
    "snapshot",
    "source-timeout",
    "source-shutdown",
    "same-key-race",
    "close-delay",
    "close-unconfirmed",
    "close-after-error",
    "ddl-bounds",
    "corrupt-input",
    "source-lock",
}


def serve(receipt, descriptor):
    import socket

    import uvicorn

    data = json.loads(Path(receipt).read_text())
    assert data["root"] == str(ROOT) and sys.prefix == data["prefix"]
    assert all(
        hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == sha
        for p, sha in data["source"].items()
    )
    os.environ["AIDDOS_RUN_DB_SOCKET"] = data["socket"]
    os.environ["AIDDOS_UI_STATE_PATH"] = data["state_path"]
    from aiddos.api.app import app

    listener = socket.socket(fileno=descriptor)
    assert list(listener.getsockname()) == data["bind"] and data["bind"][0] == "127.0.0.1"
    config = uvicorn.Config(app, log_level="critical", access_log=False, lifespan="on")
    uvicorn.Server(config).run(sockets=[listener])


def durable_http(handoff, output, endpoint, result, h):
    import http.client
    import socket
    import time
    from contextlib import contextmanager

    sys.path.insert(0, str(ROOT / "tests/api"))
    from scenario_producer import definition

    state = output.parent / "durable-draft.json"

    @contextmanager
    def server(number):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        bind = listener.getsockname()
        payload = {**handoff, "state_path": str(state), "bind": list(bind)}
        receipt = output / f"server-{number}.json"
        receipt.write_text(json.dumps(payload, indent=2) + "\n")
        with (output / f"server-{number}.log").open("wb") as log:
            process = subprocess.Popen(
                [
                    handoff["python"],
                    str(Path(__file__).resolve()),
                    "--serve",
                    str(receipt),
                    str(listener.fileno()),
                ],
                cwd=ROOT,
                env=h.child_environment(output),
                pass_fds=(listener.fileno(),),
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
            ident = h.identity_of(process.pid)
            listener.close()

            def request(method, path, body=None):
                connection = http.client.HTTPConnection(bind[0], bind[1], timeout=8)
                # Exact owned numeric endpoint; no proxy/ambient DNS configuration.
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(8)
                sock.connect(bind)
                connection.sock = sock
                try:
                    raw = None if body is None else json.dumps(body).encode()
                    connection.request(
                        method,
                        path,
                        raw,
                        {} if body is None else {"Content-Type": "application/json"},
                    )
                    response = connection.getresponse()
                    return response.status, json.loads(response.read())
                finally:
                    connection.close()

            try:
                until = time.monotonic() + 5
                while True:
                    try:
                        if request("GET", "/api/v1/health")[0] == 200:
                            break
                    except (OSError, http.client.HTTPException):
                        pass
                    assert process.poll() is None and time.monotonic() < until
                    time.sleep(0.05)
                yield request
            finally:
                if process.poll() is None:
                    assert h.identity_of(process.pid) == ident
                    process.terminate()
                code = process.wait(timeout=5)
                absent = not Path(f"/proc/{process.pid}").exists()
                (output / f"server-{number}-exit.json").write_text(
                    json.dumps(
                        {"identity": ident, "bind": list(bind), "code": code, "absent": absent},
                        indent=2,
                    )
                    + "\n"
                )
                assert code == -15 and absent  # Uvicorn re-raises captured SIGTERM after drain.
                text = (output / f"server-{number}.log").read_text()
                if "s02_api_drain" in text:
                    drain = json.loads(
                        next(line for line in text.splitlines() if '"s02_api_drain"' in line)
                    )
                    assert drain["outcome"] == "CLEAN"

    if handoff["case"] == "durability-create":
        env = h.child_environment(output)
        env["AIDDOS_RUN_DB_SOCKET"] = str(endpoint)
        cli = subprocess.run(
            [handoff["python"], "-m", "aiddos.runs.migrate"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            timeout=15,
        )
        assert cli.returncode == 0
        with server(1) as request:
            targets = []
            for kind in ("DUT", "SINK"):
                status, target = request(
                    "POST",
                    "/api/v1/targets",
                    {"name": kind, "kind": kind, "address": "unresolved.example"},
                )
                assert status == 201
                targets.append(target)
            status, scenario = request(
                "POST", "/api/v1/scenarios", {"revision": 0, "definition": definition(targets)}
            )
            assert status == 201
            record = scenario["scenario"]
            value = {
                "request_id": str(uuid4()),
                "mode": "OFFLINE",
                "scenario_id": record["id"],
                "scenario_version": record["version"],
                "scenario_digest": record["digest"],
            }
            status, detail = request("POST", "/api/v1/offline-runs", value)
            assert status == 202
        with server(2) as request:
            assert request("GET", "/api/v1/offline-runs/" + detail["run"]["id"]) == (200, detail)
            assert request("POST", "/api/v1/offline-runs", value) == (200, detail)
        result.update(request=value, detail=detail)
    else:
        saved = json.loads(
            (output.parent / "application-durability-create/result.json").read_text()
        )
        with server(3) as request:
            status, detail = request(
                "GET", "/api/v1/offline-runs/by-request/" + saved["request"]["request_id"]
            )
            if handoff["case"] == "durability-outage":
                assert status == 503 and detail["code"] == "RUN_DB_UNAVAILABLE"
            else:
                assert status == 200 and detail == saved["detail"]
                assert request("POST", "/api/v1/offline-runs", saved["request"]) == (200, detail)
        result["readback"] = True
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")


def execute(handoff):
    import psycopg
    from fastapi.testclient import TestClient

    sys.path.insert(0, str(ROOT))
    from tools import s02_harness as h

    assert str(ROOT) == handoff["root"]
    assert sys.prefix == handoff["prefix"] and sys.executable == handoff["python"]
    assert Path(psycopg.__file__).is_relative_to(ROOT / ".venv")
    assert h.identity_of(handoff["owner"]["pid"]) == handoff["owner"]
    assert all(
        hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == sha
        for p, sha in handoff["source"].items()
    )
    output = Path(handoff["output"])
    endpoint = Path(handoff["socket"])
    assert output.is_relative_to(ROOT / "implementation-evidence")
    assert endpoint.is_relative_to(Path("/home/piecer/.hermes/cache/scratch/i3w-lecrmpg5"))
    os.environ["AIDDOS_RUN_DB_SOCKET"] = str(endpoint)
    os.environ["AIDDOS_UI_STATE_PATH"] = str(output / "draft.json")
    native_async = psycopg.AsyncConnection.connect
    native_sync = psycopg.connect

    def validate(conninfo, kwargs):
        assert not conninfo
        assert kwargs.get("host") == str(endpoint)
        assert h.identity_of(handoff["owner"]["pid"]) == handoff["owner"]
        expected = h.connection_parameters(
            endpoint, user=kwargs.get("user"), database=kwargs.get("dbname")
        )
        assert {k: v for k, v in kwargs.items() if k != "autocommit"} == expected

    async def connect_async(conninfo="", **kwargs):
        validate(conninfo, kwargs)
        return await native_async(conninfo, **kwargs)

    def connect_sync(conninfo="", **kwargs):
        validate(conninfo, kwargs)
        return native_sync(conninfo, **kwargs)

    psycopg.AsyncConnection.connect = connect_async
    psycopg.connect = connect_sync
    try:
        connect_sync(host="/unowned")
    except AssertionError:
        negative = True
    else:
        raise AssertionError("unowned driver boundary admitted")

    import aiddos.api.app as app_module
    from aiddos.api.app import create_app

    assert Path(app_module.__file__) == ROOT / "src/aiddos/api/app.py"
    result = {
        "case": handoff["case"],
        "unowned_denied": negative,
        "prefix": sys.prefix,
        "module": app_module.__file__,
        "pid": h.process_identity(),
    }
    if handoff["case"].startswith("durability-"):
        durable_http(handoff, output, endpoint, result, h)
        return
    if handoff["case"].startswith("schema-configuration-"):
        from offline_schema_readiness_probe import configuration

        configuration(handoff, output, endpoint, result)
        return
    if handoff["case"].startswith("schema-readiness-"):
        from offline_schema_readiness_probe import readiness

        readiness(handoff, output, endpoint, connect_sync, h, result)
        return
    if handoff["case"].startswith("get-readiness-"):
        from offline_get_precedence_probe import readiness

        readiness(handoff, output, endpoint, connect_sync, h, result)
        return
    value = {
        "request_id": str(uuid4()),
        "mode": "OFFLINE",
        "scenario_id": str(uuid4()),
        "scenario_version": 1,
        "scenario_digest": "a" * 64,
    }
    if handoff["case"] == "driver-missing":
        import builtins

        native_import = builtins.__import__

        def unavailable_import(name, *args, **kwargs):
            if name == "psycopg":
                raise ImportError("injected")
            return native_import(name, *args, **kwargs)

        builtins.__import__ = unavailable_import
        try:
            with TestClient(
                create_app(state_path=output / "draft.json"), base_url="http://localhost"
            ) as client:
                response = client.post("/api/v1/offline-runs", json=value)
                result["response"] = {"status": response.status_code, "body": response.json()}
                (output / "observed.json").write_text(json.dumps(result, indent=2) + "\n")
                assert response.status_code == 503 and response.json()["code"] == "RUN_DB_NOT_READY"
                assert client.get("/api/v1/health").status_code == 200
        finally:
            builtins.__import__ = native_import
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        return
    if handoff["case"] == "disconnect":
        from aiddos.runs.lifetime import manager

        async def disconnect_case():
            entered, release = asyncio.Event(), asyncio.Event()

            async def held_connect(*args, **kwargs):
                entered.set()
                await release.wait()
                return await connect_async(*args, **kwargs)

            psycopg.AsyncConnection.connect = held_connect
            app = create_app(state_path=output / "draft.json")
            messages = []
            first = True

            async def receive():
                nonlocal first
                if first:
                    first = False
                    return {
                        "type": "http.request",
                        "body": json.dumps(value).encode(),
                        "more_body": False,
                    }
                await entered.wait()
                return {"type": "http.disconnect"}

            async def send(message):
                messages.append(message)

            scope = {
                "type": "http",
                "asgi": {"version": "3.0"},
                "method": "POST",
                "path": "/api/v1/offline-runs",
                "raw_path": b"/api/v1/offline-runs",
                "query_string": b"",
                "headers": [(b"host", b"localhost"), (b"content-type", b"application/json")],
                "scheme": "http",
                "http_version": "1.1",
            }
            task = asyncio.create_task(app(scope, receive, send))
            try:
                await asyncio.wait_for(entered.wait(), 1)
                await asyncio.sleep(0.05)
                assert len(manager().operations) == 1
                result["tasks"] = [
                    {
                        "name": t.get_coro().__qualname__,
                        "done": t.done(),
                        "frames": [f.f_code.co_name for f in t.get_stack()],
                    }
                    for t in asyncio.all_tasks()
                ]
                result["revoked_before_rescue"] = all(op.revoked for op in manager().operations)
                (output / "observed.json").write_text(json.dumps(result, indent=2) + "\n")
                assert result["revoked_before_rescue"]
            finally:
                release.set()
                await task
                await asyncio.sleep(0.1)
                await manager().shutdown()

        asyncio.run(disconnect_case())
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        return
    if handoff["case"] == "lifetime-acquire":
        import httpx2

        async def lifetime():
            entered = 0
            all_entered = asyncio.Event()
            release = asyncio.Event()

            async def delayed_connect(*args, **kwargs):
                nonlocal entered
                entered += 1
                if entered == 4:
                    all_entered.set()
                await release.wait()
                return await connect_async(*args, **kwargs)

            psycopg.AsyncConnection.connect = delayed_connect
            app = create_app(state_path=output / "draft.json")
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url="http://localhost"
            ) as client:
                pending = [
                    asyncio.create_task(client.post("/api/v1/offline-runs", json=value))
                    for _ in range(4)
                ]
                try:
                    await asyncio.wait_for(all_entered.wait(), 1)
                    response = await client.post("/api/v1/offline-runs", json=value)
                    result["fifth"] = response.status_code
                    (output / "observed.json").write_text(json.dumps(result, indent=2) + "\n")
                    assert response.status_code == 429 and response.json()["code"] == "RUN_BUSY"
                    responses = await asyncio.wait_for(asyncio.gather(*pending), 6)
                    assert all(r.status_code == 503 for r in responses)
                    assert entered == 4
                    response = await client.post("/api/v1/offline-runs", json=value)
                    assert response.json()["code"] == "RUN_BUSY"
                    assert (await client.get("/api/v1/health")).status_code == 200
                finally:
                    release.set()
                    await asyncio.gather(*pending, return_exceptions=True)
                    await asyncio.sleep(0.15)
            from aiddos.runs.lifetime import manager

            owner = manager()
            await owner.shutdown()
            result["drain"] = owner.drain_result
            assert owner.drain_result["outcome"] == "CLEAN"

        asyncio.run(lifetime())
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        return
    if (
        handoff["case"] in {"migration", "migration-incompatible"}
        or handoff["case"] in APPLICATION_CASES
    ):
        cli_env = h.child_environment(output)
        cli_env["AIDDOS_RUN_DB_SOCKET"] = str(endpoint)
        commands = []
        for _ in range(2):
            process = subprocess.Popen(
                ["/usr/bin/make", "runs-migrate"],
                cwd=ROOT,
                env=cli_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            ident = h.identity_of(process.pid)
            stdout, stderr = process.communicate(timeout=15)
            commands.append(
                {
                    "identity": ident,
                    "code": process.returncode,
                    "absent": not Path(f"/proc/{process.pid}").exists(),
                    "stdout": stdout,
                    "stderr_bytes": len(stderr.encode()),
                }
            )
            (output / "cli.json").write_text(json.dumps(commands, indent=2) + "\n")
            assert process.returncode == 0
        with connect_sync(**h.connection_parameters(endpoint), autocommit=True) as connection:
            result["quota"] = list(
                connection.execute(
                    "SELECT retained_count,unfinished_count,leased_count,reserved_bytes "
                    "FROM aiddos_runs_v1.quota"
                ).fetchone()
            )
            assert result["quota"] == [0, 0, 0, 0]
            assert connection.execute(
                "SELECT version FROM aiddos_runs_v1.schema_version"
            ).fetchall() == [(1,)]
            for sql in (
                "CREATE TABLE aiddos_runs_v1.forbidden(n int)",
                "TRUNCATE aiddos_runs_v1.jobs",
                "DELETE FROM aiddos_runs_v1.inputs",
            ):
                try:
                    connection.execute(sql)
                except psycopg.errors.InsufficientPrivilege:
                    pass
                else:
                    raise AssertionError("runtime privilege allowed")
        if handoff["case"] == "migration-incompatible":
            with connect_sync(
                **h.connection_parameters(endpoint, user="aiddos_s02_owner"), autocommit=True
            ) as db:
                db.execute("ALTER TABLE aiddos_runs_v1.quota ADD COLUMN foreign_column integer")
            failed = subprocess.run(
                [handoff["python"], "-m", "aiddos.runs.migrate"],
                cwd=ROOT,
                env=cli_env,
                capture_output=True,
                timeout=15,
            )
            assert failed.returncode == 78 and b'"REFUSED"' in failed.stdout
            with TestClient(
                create_app(state_path=output / "draft.json"), base_url="http://localhost"
            ) as client:
                response = client.post("/api/v1/offline-runs", json=value)
                assert response.status_code == 503 and response.json()["code"] == "RUN_DB_NOT_READY"
            with connect_sync(
                **h.connection_parameters(endpoint, user="aiddos_s02_owner"), autocommit=True
            ) as db:
                assert (
                    db.execute(
                        "SELECT count(*) FROM information_schema.columns WHERE table_"
                        "schema='aiddos_runs_v1' AND column_name='foreign_column'"
                    ).fetchone()[0]
                    == 1
                )
            result["foreign_shape_preserved"] = True
            (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
            return
        if handoff["case"] == "migration":
            (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
            return
    from contextlib import contextmanager

    @contextmanager
    def client_context():
        try:
            with TestClient(
                create_app(state_path=output / "draft.json"), base_url="http://localhost"
            ) as client:
                yield client
        except RuntimeError as exc:
            if (
                handoff["case"] not in {"source-shutdown", "close-delay", "close-unconfirmed"}
                or str(exc) != "S02_DRAIN_INCOMPLETE"
            ):
                raise
            assert (output / "result.json").exists()
            (output / "lifespan-incomplete.json").write_text('{"fixed_failure":true}\n')

    with client_context() as client:
        if handoff["case"] in APPLICATION_CASES:
            sys.path.insert(0, str(ROOT / "tests/api"))
            from scenario_producer import canonical, definition, digest, register_targets

            targets = register_targets(client)
            scenario_response = client.post(
                "/api/v1/scenarios", json={"revision": 0, "definition": definition(targets)}
            )
            assert scenario_response.status_code == 201
            scenario = scenario_response.json()["scenario"]
            value.update(
                scenario_id=scenario["id"],
                scenario_version=scenario["version"],
                scenario_digest=scenario["digest"],
            )
        response = client.post("/api/v1/offline-runs", json=value)
        result["response"] = {"status": response.status_code, "body": response.json()}
        (output / "observed.json").write_text(json.dumps(result, indent=2) + "\n")
        if handoff["case"] in APPLICATION_CASES:
            assert response.status_code == 202
            detail = response.json()
            assert set(detail) == {"schema_version", "run", "snapshot", "result"}
            assert detail["snapshot"]["scenario"] == scenario
            assert detail["snapshot"]["digest"] == digest(detail["snapshot"])
            assert detail["snapshot"]["source_revision"] == 1
            assert detail["run"]["state"] == "QUEUED" and detail["result"] is None
            assert detail["run"]["event_count"] == 1
            case = handoff["case"]
            if case in {"get-precedence-run", "get-precedence-request"}:
                from offline_get_precedence_probe import precedence

                precedence(client, response, value, case, output, endpoint, connect_sync, h, result)
                return
            if case in {"close-delay", "close-unconfirmed", "close-after-error"}:
                import time

                from aiddos.runs.lifetime import manager

                original_close = psycopg.AsyncConnection.close
                release = asyncio.Event()
                calls = []

                async def close(connection):
                    calls.append(id(connection))
                    if case == "close-delay":
                        await release.wait()
                    if case == "close-unconfirmed":
                        raise OSError("injected")
                    await original_close(connection)
                    if case == "close-after-error":
                        raise OSError("injected")

                psycopg.AsyncConnection.close = close
                try:
                    count = 4 if case == "close-delay" else 1
                    for _ in range(count):
                        observed = client.get("/api/v1/offline-runs/" + detail["run"]["id"])
                        assert observed.status_code == 200 and observed.json() == detail
                    if case == "close-after-error":
                        until = time.monotonic() + 1
                        while manager().operations and time.monotonic() < until:
                            time.sleep(0.01)
                        assert not manager().operations
                    else:
                        assert len(manager().operations) == count
                        if count == 4:
                            assert (
                                client.get("/api/v1/offline-runs/" + detail["run"]["id"]).json()[
                                    "code"
                                ]
                                == "RUN_BUSY"
                            )
                        before = time.monotonic()
                        try:
                            client.portal.call(manager().shutdown)
                        except RuntimeError as error:
                            assert str(error) == "S02_DRAIN_INCOMPLETE"
                        else:
                            raise AssertionError("false clean drain")
                        assert time.monotonic() - before < 1.5
                        result["custody_before_release"] = dict(manager().drain_result)
                        assert manager().drain_result["retained_operations"] == count
                        if case == "close-unconfirmed":
                            assert manager().drain_result["disposal_unconfirmed"] == 1
                        assert (
                            client.get("/api/v1/offline-runs/" + detail["run"]["id"]).json()["code"]
                            == "RUN_DB_UNAVAILABLE"
                        )
                    assert len(calls) == len(set(calls)) == count
                    result["single_close_attempts"] = len(calls)
                finally:
                    client.portal.call(release.set)
                    psycopg.AsyncConnection.close = original_close
                    if case == "close-delay":
                        until = time.monotonic() + 1
                        while manager().operations and time.monotonic() < until:
                            time.sleep(0.01)
                        assert not manager().operations
                (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
                return
            if case in {"source-timeout", "source-shutdown", "same-key-race"}:
                import threading
                import time
                from concurrent.futures import ThreadPoolExecutor
                from contextlib import contextmanager

                from aiddos.api import scenario_persistence as persistence
                from aiddos.runs.lifetime import manager

                original_stream = persistence.stream_for
                entered, release = threading.Event(), threading.Event()
                observations = []
                registry = output / "draft.json.scenarios.json"
                inode = registry.stat().st_ino
                source_before = registry.read_bytes()

                @contextmanager
                def held_stream(fd, mode):
                    with original_stream(fd, mode) as stream:
                        if mode == "rb" and os.fstat(fd).st_ino == inode:

                            class Reader:
                                def read(self, size):
                                    observations.append(
                                        {
                                            "thread": threading.get_ident(),
                                            "fd": fd,
                                            "inode": os.fstat(fd).st_ino,
                                        }
                                    )
                                    entered.set()
                                    assert release.wait(8)
                                    return stream.read(size)

                            yield Reader()
                        else:
                            yield stream

                persistence.stream_for = held_stream
                try:
                    with ThreadPoolExecutor(max_workers=4) as requests:
                        extra = {**value, "request_id": str(uuid4())}
                        count = 4 if case == "same-key-race" else 1
                        pending = [
                            requests.submit(client.post, "/api/v1/offline-runs", json=extra)
                            for _ in range(count)
                        ]
                        assert entered.wait(1)
                        start = time.monotonic()
                        assert client.get("/api/v1/health").status_code == 200
                        assert time.monotonic() - start < 1
                        if case == "same-key-race":
                            release.set()
                            statuses = [p.result(timeout=5).status_code for p in pending]
                            assert sorted(statuses) == [200, 200, 200, 202]
                        else:
                            response = pending[0].result(timeout=6)
                            assert (
                                response.status_code == 503
                                and response.json()["code"] == "RUN_DB_UNAVAILABLE"
                            )
                            assert len(manager().operations) == 1
                            assert not manager().operations.copy().pop().source_future.done()
                            assert os.fstat(observations[0]["fd"]).st_ino == inode
                            if case == "source-shutdown":
                                start = time.monotonic()
                                try:
                                    client.portal.call(manager().shutdown)
                                except RuntimeError as error:
                                    assert str(error) == "S02_DRAIN_INCOMPLETE"
                                else:
                                    raise AssertionError("false clean drain")
                                assert time.monotonic() - start < 1.5
                                assert manager().drain_result["outcome"] == "INCOMPLETE"
                                result["incomplete_before_release"] = dict(manager().drain_result)
                                (output / "observed-drain.json").write_text(
                                    json.dumps(manager().drain_result) + "\n"
                                )
                                assert manager().drain_result["source_pending"] == 1
                                assert manager().drain_result["db_pending"] == 0
                                assert manager().drain_result["disposal_unconfirmed"] == 0
                                denied = client.post("/api/v1/offline-runs", json=extra)
                                assert denied.json()["code"] == "RUN_DB_UNAVAILABLE"
                            release.set()
                        until = time.monotonic() + 1
                        while manager().operations and time.monotonic() < until:
                            time.sleep(0.01)
                        assert not manager().operations
                        assert registry.read_bytes() == source_before
                        result["source_finalizers_returned"] = True
                        result["source_observations"] = observations
                finally:
                    release.set()
                    persistence.stream_for = original_stream
                with connect_sync(**h.connection_parameters(endpoint), autocommit=True) as db:
                    assert db.execute("SELECT count(*) FROM aiddos_runs_v1.inputs").fetchone()[
                        0
                    ] == (2 if case == "same-key-race" else 1)
                (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
                return
            if case == "source-lock":
                import threading
                import time
                from concurrent.futures import ThreadPoolExecutor

                from aiddos.api.scenario_store import ScenarioStore
                from aiddos.api.store import DraftStore

                peer = ScenarioStore(DraftStore(output / "draft.json"), ticket=None)
                entered, release = threading.Event(), threading.Event()

                def hold():
                    with peer.lock:
                        entered.set()
                        assert release.wait(3)

                with ThreadPoolExecutor(max_workers=1) as pool:
                    holding = pool.submit(hold)
                    assert entered.wait(1)
                    before = time.monotonic()
                    try:
                        failed = client.post(
                            "/api/v1/offline-runs", json={**value, "request_id": str(uuid4())}
                        )
                        assert failed.status_code == 429 and failed.json()["code"] == "RUN_BUSY"
                        assert time.monotonic() - before < 2
                        assert client.get("/api/v1/health").status_code == 200
                    finally:
                        release.set()
                        holding.result(timeout=1)
                result["lock_wait_refused"] = True
            if case == "corrupt-input":
                with (
                    connect_sync(
                        **h.connection_parameters(endpoint, user="aiddos_s02_owner"),
                        autocommit=True,
                    ) as db,
                    db.transaction(),
                ):
                    db.execute("ALTER TABLE aiddos_runs_v1.inputs DISABLE TRIGGER inputs_immutable")
                    db.execute("UPDATE aiddos_runs_v1.inputs SET request_digest=%s", ("b" * 64,))
                    db.execute("ALTER TABLE aiddos_runs_v1.inputs ENABLE TRIGGER inputs_immutable")
                failed = client.get("/api/v1/offline-runs/" + detail["run"]["id"])
                assert failed.status_code == 503 and failed.json()["code"] == "RUN_STATE_CORRUPT"
                with connect_sync(**h.connection_parameters(endpoint), autocommit=True) as db:
                    assert (
                        db.execute("SELECT request_digest FROM aiddos_runs_v1.inputs").fetchone()[0]
                        == "b" * 64
                    )
                result["corrupt_preserved"] = True
                (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
                return
            if case == "ddl-bounds":
                result["bounds"] = []
                with connect_sync(**h.connection_parameters(endpoint), autocommit=True) as db:
                    for field, cap in (("request", 1024), ("snapshot", 12288)):
                        for size in (cap, cap + 1):
                            try:
                                with db.transaction():
                                    db.execute(
                                        "INSERT INTO aiddos_runs_v1.inputs "
                                        "VALUES(%s,%s,2,%s,%s,%s,%s)",
                                        (
                                            str(uuid4()),
                                            str(uuid4()),
                                            b"x" * size if field == "request" else b"{}",
                                            "a" * 64,
                                            b"x" * size if field == "snapshot" else b"{}",
                                            "a" * 64,
                                        ),
                                    )
                                    assert size == cap
                                    raise psycopg.Rollback()
                            except psycopg.errors.CheckViolation:
                                assert size == cap + 1
                            result["bounds"].append([field, size, size == cap])
                    for table, field, cap in (
                        ("results", "result", 8192),
                        ("events", "event", 512),
                    ):
                        for size in (cap, cap + 1):
                            try:
                                with db.transaction():
                                    query = (
                                        "INSERT INTO aiddos_runs_v1."
                                        + table
                                        + " VALUES(%s,"
                                        + ("2," if table == "events" else "")
                                        + "%s)"
                                    )
                                    db.execute(query, (detail["run"]["id"], b"x" * size))
                                    assert size == cap
                                    raise psycopg.Rollback()
                            except psycopg.errors.CheckViolation:
                                assert size == cap + 1
                            result["bounds"].append([field, size, size == cap])
                    for query in (
                        "UPDATE aiddos_runs_v1.inputs SET snapshot=snapshot",
                        "UPDATE aiddos_runs_v1.events SET event=event",
                        "ALTER TABLE aiddos_runs_v1.inputs DISABLE TRIGGER inputs_immutable",
                        "UPDATE aiddos_runs_v1.jobs SET created_at=created_at+interval '1 second'",
                    ):
                        try:
                            db.execute(query)
                        except (
                            psycopg.errors.InsufficientPrivilege,
                            psycopg.errors.CheckViolation,
                        ):
                            pass
                        else:
                            raise AssertionError("immutable runtime mutation allowed")
                result["fixture_kind"] = "DB_PRIMITIVE_LIMITS_NOT_WORKER_REACHABLE"
            if case == "snapshot":
                appended = client.put(
                    "/api/v1/scenarios/" + scenario["id"],
                    json={
                        "revision": 1,
                        "definition": {**definition(targets), "objective": "changed"},
                    },
                )
                assert appended.status_code == 200
                assert client.get("/api/v1/offline-runs/" + detail["run"]["id"]).json() == detail
                assert client.post("/api/v1/offline-runs", json=value).json() == detail
            if case in {"atomic", "uncertain"}:
                from psycopg.transaction import AsyncTransaction

                original_execute = psycopg.AsyncConnection.execute
                original_exit = AsyncTransaction.__aexit__
                fired = []
                dirty = set()

                async def fault_execute(connection, query, *args, **kwargs):
                    if isinstance(query, str) and query.startswith(
                        "INSERT INTO aiddos_runs_v1.inputs"
                    ):
                        dirty.add(id(connection))
                    if (
                        case == "atomic"
                        and isinstance(query, str)
                        and query.startswith("INSERT INTO aiddos_runs_v1.events")
                    ):
                        fired.append("after-input-and-job")
                        raise psycopg.OperationalError("injected")
                    return await original_execute(connection, query, *args, **kwargs)

                async def fault_exit(transaction, typ, exc, tb):
                    result_exit = await original_exit(transaction, typ, exc, tb)
                    if case == "uncertain" and typ is None and id(transaction.connection) in dirty:
                        fired.append("after-real-commit")
                        raise psycopg.OperationalError("injected")
                    return result_exit

                psycopg.AsyncConnection.execute = fault_execute
                AsyncTransaction.__aexit__ = fault_exit
                extra = {**value, "request_id": str(uuid4())}
                try:
                    failed = client.post("/api/v1/offline-runs", json=extra)
                    assert failed.status_code == 503
                    assert failed.json()["code"] == (
                        "RUN_COMMIT_UNCERTAIN" if case == "uncertain" else "RUN_DB_UNAVAILABLE"
                    )
                    assert len(fired) == 1
                finally:
                    psycopg.AsyncConnection.execute = original_execute
                    AsyncTransaction.__aexit__ = original_exit
                recovered = client.get("/api/v1/offline-runs/by-request/" + extra["request_id"])
                assert recovered.status_code == (200 if case == "uncertain" else 404)
                result["fault_fired"] = fired
                if case == "uncertain":
                    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
                    return
            if case == "quota":
                for _ in range(15):
                    accepted = client.post(
                        "/api/v1/offline-runs", json={**value, "request_id": str(uuid4())}
                    )
                    assert accepted.status_code == 202
                denied = client.post(
                    "/api/v1/offline-runs", json={**value, "request_id": str(uuid4())}
                )
                assert denied.status_code == 429 and denied.json()["code"] == "RUN_QUEUE_FULL"
                assert client.post("/api/v1/offline-runs", json=value).status_code == 200
                with connect_sync(**h.connection_parameters(endpoint), autocommit=True) as db:
                    assert db.execute(
                        "SELECT retained_count,unfinished_count,reserved_bytes FROM a"
                        "iddos_runs_v1.quota"
                    ).fetchone() == (16, 16, 1048576)
                    assert (
                        db.execute("SELECT count(*) FROM aiddos_runs_v1.events").fetchone()[0] == 16
                    )
                result["quota_bound"] = 16
                (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
                return
            if case == "retention":
                with (
                    connect_sync(
                        **h.connection_parameters(endpoint, user="aiddos_s02_owner"),
                        autocommit=True,
                    ) as db,
                    db.transaction(),
                ):
                    source_input = db.execute(
                        "SELECT snapshot,snapshot_digest FROM aiddos_runs_v1.inputs"
                    ).fetchone()
                    first_event = db.execute("SELECT event FROM aiddos_runs_v1.events").fetchone()[
                        0
                    ]
                    cancelled_event = canonical(
                        {
                            **json.loads(first_event),
                            "seq": 2,
                            "state": "CANCELLED",
                            "type": "CANCELLED",
                            "reason": "BEFORE_CLAIM",
                        }
                    )
                    for ordinal in range(2, 128):
                        fixture_id, key = str(uuid4()), str(uuid4())
                        raw_request = canonical({**value, "request_id": key})
                        db.execute(
                            "INSERT INTO aiddos_runs_v1.inputs VALUES(%s,%s,%s,%s,%s,%s,%s)",
                            (
                                fixture_id,
                                key,
                                ordinal,
                                raw_request,
                                hashlib.sha256(raw_request).hexdigest(),
                                *source_input,
                            ),
                        )
                        db.execute(
                            (
                                "INSERT INTO aiddos_runs_v1.jobs SELECT %s,'CANCELLED',0,0,cr"
                                "eated_at,NULL,created_at,created_at,deadline_at,created_at,2"
                                ",NULL,NULL,NULL,0 FROM aiddos_runs_v1.jobs WHERE run_id=%s"
                            ),
                            (fixture_id, detail["run"]["id"]),
                        )
                        db.execute(
                            "INSERT INTO aiddos_runs_v1.events VALUES(%s,1,%s),(%s,2,%s)",
                            (fixture_id, first_event, fixture_id, cancelled_event),
                        )
                    db.execute(
                        "UPDATE aiddos_runs_v1.quota SET retained_count=127,reserved_"
                        "bytes=127*65536"
                    )
                last = client.post(
                    "/api/v1/offline-runs", json={**value, "request_id": str(uuid4())}
                )
                assert last.status_code == 202 and last.json()["run"]["ordinal"] == 128
                denied = client.post(
                    "/api/v1/offline-runs", json={**value, "request_id": str(uuid4())}
                )
                assert denied.status_code == 409 and denied.json()["code"] == "RUN_RETENTION_FULL"
                assert client.post("/api/v1/offline-runs", json=value).status_code == 200
                with connect_sync(**h.connection_parameters(endpoint), autocommit=True) as db:
                    assert db.execute(
                        "SELECT retained_count,unfinished_count,reserved_bytes FROM a"
                        "iddos_runs_v1.quota"
                    ).fetchone() == (128, 2, 8388608)
                result["retained_fixture_bound"] = 128
                (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
                return
            if case == "corrupt":
                with connect_sync(
                    **h.connection_parameters(endpoint, user="aiddos_s02_owner"), autocommit=True
                ) as db:
                    db.execute("UPDATE aiddos_runs_v1.quota SET unfinished_count=0")
                corrupt = client.get("/api/v1/offline-runs/" + detail["run"]["id"])
                assert corrupt.status_code == 503 and corrupt.json()["code"] == "RUN_STATE_CORRUPT"
                denied = client.post(
                    "/api/v1/offline-runs", json={**value, "request_id": str(uuid4())}
                )
                assert denied.json()["code"] == "RUN_STATE_CORRUPT"
                result["corruption_refused"] = True
                (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
                return
            if handoff["case"] == "terminal-fixture":
                # Explicit DB-only quota fixture, NOT a worker completion witness.
                with (
                    connect_sync(
                        **h.connection_parameters(endpoint, user="aiddos_s02_owner"),
                        autocommit=True,
                    ) as fixture,
                    fixture.transaction(),
                ):
                    event = {
                        "seq": 2,
                        "at": detail["run"]["created_at"],
                        "type": "CANCELLED",
                        "state": "CANCELLED",
                        "attempt": 0,
                        "generation": 0,
                        "reason": "BEFORE_CLAIM",
                    }
                    fixture.execute("SELECT * FROM aiddos_runs_v1.quota FOR UPDATE")
                    fixture.execute(
                        "UPDATE aiddos_runs_v1.jobs SET state='CANCELLED',finished_at=created_at,"
                        "cancel_requested_at=created_at,event_count=2 WHERE run_id=%s",
                        (detail["run"]["id"],),
                    )
                    fixture.execute(
                        "INSERT INTO aiddos_runs_v1.events VALUES(%s,2,%s)",
                        (detail["run"]["id"], canonical(event)),
                    )
                    fixture.execute("UPDATE aiddos_runs_v1.quota SET unfinished_count=0")
                response = client.post("/api/v1/offline-runs", json=value)
                result["fixture_response"] = {
                    "status": response.status_code,
                    "body": response.json(),
                }
                (output / "observed.json").write_text(json.dumps(result, indent=2) + "\n")
                assert (
                    response.status_code == 200 and response.json()["run"]["state"] == "CANCELLED"
                )
                result["fixture_kind"] = "DB_ONLY_NOT_WORKER_REACHABLE"
                (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
                return
            if handoff["case"] == "lock":
                with (
                    connect_sync(
                        **h.connection_parameters(endpoint, user="aiddos_s02_owner"),
                        autocommit=True,
                    ) as locker,
                    locker.transaction(),
                ):
                    locker.execute("SELECT * FROM aiddos_runs_v1.quota FOR UPDATE")
                    response = client.post(
                        "/api/v1/offline-runs", json={**value, "request_id": str(uuid4())}
                    )
                    assert response.status_code == 429 and response.json()["code"] == "RUN_BUSY"
                    assert client.get("/api/v1/health").status_code == 200
            if handoff["case"] == "idempotency":
                # The existing snapshot and replay must survive unavailable S01.
                from aiddos.api import scenario_store

                original = scenario_store.ScenarioStore.history

                def unavailable(*args, **kwargs):
                    raise AssertionError("DB-only path reopened source")

                scenario_store.ScenarioStore.history = unavailable
                try:
                    assert (
                        client.get("/api/v1/offline-runs/" + detail["run"]["id"]).json() == detail
                    )
                    assert (
                        client.get("/api/v1/offline-runs/by-request/" + value["request_id"]).json()
                        == detail
                    )
                    from concurrent.futures import ThreadPoolExecutor

                    with ThreadPoolExecutor(max_workers=4) as pool:
                        duplicates = list(
                            pool.map(
                                lambda _: client.post("/api/v1/offline-runs", json=value), range(4)
                            )
                        )
                    assert all(r.status_code == 200 and r.json() == detail for r in duplicates)
                    conflict = client.post(
                        "/api/v1/offline-runs", json={**value, "scenario_digest": "b" * 64}
                    )
                    assert (
                        conflict.status_code == 409
                        and conflict.json()["code"] == "RUN_IDEMPOTENCY_CONFLICT"
                    )
                finally:
                    scenario_store.ScenarioStore.history = original
            with connect_sync(**h.connection_parameters(endpoint), autocommit=True) as connection:
                rows = connection.execute(
                    "SELECT request,snapshot FROM aiddos_runs_v1.inputs"
                ).fetchall()
                assert rows == [(canonical(value), canonical(detail["snapshot"]))]
                assert connection.execute(
                    "SELECT state,event_count FROM aiddos_runs_v1.jobs"
                ).fetchall() == [("QUEUED", 1)]
                result["quota"] = list(
                    connection.execute(
                        "SELECT retained_count,unfinished_count,leased_count,reserved"
                        "_bytes FROM aiddos_runs_v1.quota"
                    ).fetchone()
                )
                assert result["quota"] == [1, 1, 0, 65536]
                events = connection.execute(
                    "SELECT seq,event FROM aiddos_runs_v1.events"
                ).fetchall()
                assert len(events) == 1 and events[0][0] == 1
                assert json.loads(events[0][1])["type"] == "QUEUED"
            (output / "producer-detail.json").write_bytes(response.content)
            (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
            return
        assert response.status_code == 503
        assert response.json()["code"] == "RUN_DB_NOT_READY"
        assert client.get("/api/v1/health").status_code == 200
    with connect_sync(
        **h.connection_parameters(endpoint, user="aiddos_s02_owner"), autocommit=True
    ) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM pg_namespace WHERE nspname='aiddos_runs_v1'"
            ).fetchone()[0]
            == 0
        )
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--serve"]:
        serve(sys.argv[2], int(sys.argv[3]))
        sys.exit(0)
    if sys.argv[1:] == ["--collect-only"]:
        assert Path(sys.prefix) == ROOT / ".venv"
        print(
            json.dumps(
                {
                    "effects": 0,
                    "callable": callable(execute),
                    "prefix": sys.prefix,
                    "origin": str(Path(__file__).resolve()),
                }
            )
        )
        sys.exit(0)
    receipt = Path(sys.argv[1])
    data = json.loads(receipt.read_text())
    try:
        execute(data)
    except BaseException as exc:
        frames = [
            {"file": f.filename, "line": f.lineno, "function": f.name}
            for f in traceback.extract_tb(exc.__traceback__)
        ]
        (Path(data["output"]) / "failure.json").write_text(
            json.dumps(
                {
                    "type": type(exc).__name__,
                    "frames": frames,
                },
                indent=2,
            )
            + "\n"
        )
        sys.exit(1)
