"""Native HTTP bytes, real S01 creation and isolated PG; no worker witness."""

import hashlib
import http.client
import json
import os
import socket
import subprocess
import sys
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import s02_harness as h  # noqa: E402

ENV = json.loads((ROOT / "cohort-evidence/environment.json").read_text())


def source_check(data):
    assert data["root"] == str(ROOT) and sys.prefix == data["prefix"]
    assert h.identity_of(data["owner"]["pid"]) == data["owner"]
    assert all(
        hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == sha
        for p, sha in data["source"].items()
    )


@contextmanager
def child(data, label, argv, *, extra=None, pass_fds=()):
    output = Path(data["output"])
    env = {**ENV, **(extra or {})}
    with (
        (output / (label + "-stdout.log")).open("wb") as stdout,
        (output / (label + "-stderr.log")).open("wb") as stderr,
    ):
        p = subprocess.Popen(
            argv,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            pass_fds=pass_fds,
            start_new_session=True,
        )
        ident = h.identity_of(p.pid)
        (output / (label + "-started.json")).write_text(
            json.dumps(
                {
                    "identity": ident,
                    "argv": argv,
                    "environment": env,
                },
                indent=2,
            )
            + "\n"
        )
        try:
            yield p
        finally:
            rescued = False
            if p.poll() is None:
                assert h.identity_of(p.pid) == ident
                p.terminate()
            try:
                code = p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                rescued = True
                assert h.identity_of(p.pid) == ident
                p.kill()
                code = p.wait(timeout=2)
            stdout.close()
            stderr.close()
            receipt = {
                "identity": ident,
                "actual_exit": code,
                "reaped": True,
                "stdout_closed": stdout.closed,
                "stderr_closed": stderr.closed,
                "pipes": "not allocated; continuous native file sinks",
                "absent": not Path(f"/proc/{p.pid}").exists(),
                "rescued": rescued,
            }
            (output / (label + "-exit.json")).write_text(json.dumps(receipt, indent=2) + "\n")
            assert receipt["absent"] and not rescued


def serve(data, fd):
    source_check(data)
    if data.get("no_socket"):
        os.environ.pop("AIDDOS_RUN_DB_SOCKET", None)
        import psycopg

        def forbidden(*args, **kwargs):
            raise AssertionError("raw transport/configuration unexpectedly acquired a connection")

        psycopg.AsyncConnection.connect = forbidden
    else:
        os.environ["AIDDOS_RUN_DB_SOCKET"] = data["socket"]
    os.environ["AIDDOS_UI_STATE_PATH"] = data["state"]
    import uvicorn

    if data["case"] == "atomic":
        from http_atomic_probe import install

        install(data)
    if data["case"] == "uncertain":
        from http_atomic_probe import install_uncertain

        install_uncertain(data)
    from aiddos.api.app import app

    listener = socket.socket(fileno=fd)
    assert list(listener.getsockname()) == data["bind"]
    uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False)).run(
        sockets=[listener]
    )


@contextmanager
def server(data, label="api"):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    bind = listener.getsockname()
    data = {**data, "bind": list(bind)}
    output = Path(data["output"])
    handoff = output / (label + "-handoff.json")
    handoff.write_text(json.dumps(data, indent=2) + "\n")
    sequence = 0
    corpus = (
        ROOT / "cohort-evidence/producer-corpus" / output.parent.name / (data["case"] + "-" + label)
    )
    corpus.mkdir(parents=True)

    def request(method, path, body=None, *, provenance="NATURAL_HTTP_S01_PG"):
        nonlocal sequence
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(7)
        sock.connect(bind)
        conn = http.client.HTTPConnection(bind[0], bind[1], timeout=7)
        conn.sock = sock
        raw = (
            None
            if body is None
            else (body if isinstance(body, bytes) else json.dumps(body).encode())
        )
        try:
            conn.request(
                method, path, raw, {} if raw is None else {"Content-Type": "application/json"}
            )
            response = conn.getresponse()
            content, status, headers = response.read(), response.status, dict(response.getheaders())
        finally:
            conn.close()
        sequence += 1
        name = f"{sequence:04d}"
        (corpus / (name + ".body")).write_bytes(content)
        (corpus / (name + ".json")).write_text(
            json.dumps(
                {
                    "method": method,
                    "path": path,
                    "status": status,
                    "headers": headers,
                    "request_hex": None if raw is None else raw.hex(),
                    "body_sha256": hashlib.sha256(content).hexdigest(),
                    "source": data["source"],
                    "kind": "ACTUAL_REAL_ROUTER_HTTP_BYTES",
                    "provenance": provenance,
                    "worker_witness": False,
                },
                indent=2,
            )
            + "\n"
        )
        assert headers.get("cache-control") == "no-store"
        bound = (
            1024
            if status >= 400
            else (
                131072
                if path.split("?")[0] == "/api/v1/offline-runs" and method == "GET"
                else 32768
            )
        )
        if "/events" in path and status == 200:
            bound = 16384
        assert len(content) <= bound
        return status, json.loads(content)

    try:
        with child(
            data,
            label,
            [data["python"], str(Path(__file__)), "--serve", str(handoff), str(listener.fileno())],
            pass_fds=(listener.fileno(),),
        ) as process:
            listener.close()
            until = time.monotonic() + 5
            while True:
                try:
                    if request("GET", "/api/v1/health")[0] == 200:
                        break
                except (OSError, http.client.HTTPException):
                    pass
                assert process.poll() is None and time.monotonic() < until
                time.sleep(0.03)
            yield request
    finally:
        listener.close()


def create_source(request):
    sys.path.insert(0, str(ROOT / "tests/api"))
    from scenario_producer import definition

    targets = []
    for kind in ("DUT", "SINK"):
        status, target = request(
            "POST",
            "/api/v1/targets",
            {"name": kind, "kind": kind, "address": "never-resolve.invalid"},
        )
        assert status == 201
        targets.append(target)
    status, scenario = request(
        "POST", "/api/v1/scenarios", {"revision": 0, "definition": definition(targets)}
    )
    assert status == 201
    record = scenario["scenario"]
    return {
        "request_id": str(uuid4()),
        "mode": "OFFLINE",
        "scenario_id": record["id"],
        "scenario_version": record["version"],
        "scenario_digest": record["digest"],
    }


def list_case(request, value, queued, data):
    base = "/api/v1/offline-runs"
    status, page = request("GET", base + "?after=0&limit=1")
    assert status == 200, (status, page)
    assert page == {
        "schema_version": 1,
        "after": 0,
        "through": 1,
        "limit": 1,
        "total": 1,
        "items": [queued["run"]],
        "next_after": None,
    }
    for query in (
        "after=00",
        "after=-0",
        "after=+1",
        "after=1.0",
        "after=1e0",
        "after=",
        "after=129",
        "through=129",
        "limit=0",
        "limit=21",
        "after=0&after=0",
        "unknown=1",
        "%61fter=0",
        "after=%30",
        "after=%FF",
        "after=%D9%A0",
        "after=0&",
        "&",
        "after=0;limit=1",
        "after=0&&limit=1",
        "after=0=0",
        "after=" + "1" * 251,
    ):
        failed = request("GET", base + "?" + query)
        assert failed[0] == 422 and failed[1]["code"] == "VALIDATION_ERROR", (query, failed)
    ids = [queued["run"]["id"]]
    for _ in range(4):
        code, detail = request("POST", base, {**value, "request_id": str(uuid4())})
        assert code == 202
        ids.append(detail["run"]["id"])
    status, first = request("GET", base + "?limit=2")
    assert status == 200 and first["through"] == first["total"] == 5 and first["next_after"] == 2
    code, appended = request("POST", base, {**value, "request_id": str(uuid4())})
    assert code == 202 and appended["run"]["ordinal"] == 6
    observed = [r["id"] for r in first["items"]]
    after = first["next_after"]
    while after is not None:
        status, page = request("GET", base + f"?after={after}&through=5&limit=2")
        assert status == 200 and page["through"] == page["total"] == 5
        assert all(
            set(row) == set(queued["run"]) and "snapshot" not in row for row in page["items"]
        )
        observed.extend(r["id"] for r in page["items"])
        after = page["next_after"]
    assert observed == ids and len(set(observed)) == 5
    for after in (5, 6, 128):
        code, page = request("GET", base + f"?after={after}&through=5")
        assert code == 200 and page["items"] == [] and page["next_after"] is None
    assert request("GET", base + "?through=7")[0] == 422
    assert request("GET", base + "?through=0")[1]["items"] == []
    assert request("GET", base)[1]["total"] == 6


def events_case(request, value, queued, data):
    from http_state_probe import claim, connect

    base = "/api/v1/offline-runs/" + queued["run"]["id"]
    status, page = request("GET", base + "/events")
    assert status == 200, (status, page)
    assert page == {
        "schema_version": 1,
        "run_id": queued["run"]["id"],
        "after": 0,
        "limit": 16,
        "total": 1,
        "items": [
            {
                "seq": 1,
                "at": queued["run"]["created_at"],
                "type": "QUEUED",
                "state": "QUEUED",
                "attempt": 0,
                "generation": 0,
                "reason": None,
            }
        ],
        "next_after": None,
    }
    for query in (
        "after=17",
        "limit=17",
        "through=1",
        "after=01",
        "after=-1",
        "limit=",
        "after=0&after=1",
        "%61fter=0",
        "after=%31",
        "limit=0",
    ):
        response = request("GET", base + "/events?" + query)
        assert response[0] == 422 and response[1]["code"] == "VALIDATION_ERROR"
    assert request("GET", base + "/events?after=16")[1]["items"] == []
    missing = "/api/v1/offline-runs/" + str(uuid4()) + "/events"
    assert request("GET", missing)[0] == 404
    claim(data, queued["run"]["id"])
    label = "SQL_SEEDED_RUNNING_NOT_WORKER"
    status, first = request("GET", base + "/events?limit=1", provenance=label)
    assert status == 200 and first["next_after"] == 1 and first["total"] == 2
    status, second = request("GET", base + "/events?after=1&limit=1", provenance=label)
    assert (
        status == 200 and second["next_after"] is None and second["items"][0]["type"] == "CLAIMED"
    )
    with connect(data) as db:
        db.execute(
            "UPDATE aiddos_runs_v1.jobs SET lease_until=clock_timestamp()+interval "
            "'10 seconds' WHERE run_id=%s",
            (queued["run"]["id"],),
        )
    assert request("GET", base + "/events?after=1&limit=1", provenance=label) == (status, second)
    with connect(data, owner=True) as db:
        db.execute("UPDATE aiddos_runs_v1.quota SET unfinished_count=0,leased_count=0")
    assert request("GET", missing, provenance="SQL_CORRUPT_QUOTA")[0] == 404
    response = request("GET", base + "/events", provenance="SQL_CORRUPT_QUOTA")
    assert response[0] == 503 and response[1]["code"] == "RUN_STATE_CORRUPT"
    with connect(data, owner=True) as db:
        db.execute("UPDATE aiddos_runs_v1.quota SET unfinished_count=1,leased_count=1")
        with db.transaction():
            db.execute("ALTER TABLE aiddos_runs_v1.events DISABLE TRIGGER events_immutable")
            db.execute("UPDATE aiddos_runs_v1.events SET event=%s WHERE seq=2", (b"{}",))
            db.execute("ALTER TABLE aiddos_runs_v1.events ENABLE TRIGGER events_immutable")
    response = request("GET", base + "/events?after=16", provenance="SQL_CORRUPT_EVENT")
    assert response[0] == 503 and response[1]["code"] == "RUN_STATE_CORRUPT"


def failed_summary_case(request, value, queued, data):
    from http_state_probe import failed_snapshot

    failed_snapshot(data, queued["run"]["id"])
    label = "SQL_SEEDED_FAILED_SNAPSHOT_INVALID_CORRUPT_SNAPSHOT"
    code, page = request("GET", "/api/v1/offline-runs", provenance=label)
    assert code == 200, (code, page)
    assert page["items"][0]["state"] == "FAILED"
    assert page["items"][0]["failure_code"] == "SNAPSHOT_INVALID"
    assert "snapshot" not in page["items"][0]
    code, detail = request("GET", "/api/v1/offline-runs/" + queued["run"]["id"], provenance=label)
    assert code == 503 and detail["code"] == "RUN_STATE_CORRUPT"


def cancel_queued_case(request, value, queued, data):
    from http_state_probe import connect

    base = "/api/v1/offline-runs/" + queued["run"]["id"]
    status, terminal = request("POST", base + "/cancel", {})
    assert status == 200, (status, terminal)
    run = terminal["run"]
    assert run["state"] == "CANCELLED" and run["event_count"] == 2
    assert run["attempt"] == run["generation"] == 0 and run["started_at"] is None
    assert run["finished_at"] == run["updated_at"] == run["cancel_requested_at"]
    assert terminal["snapshot"] == queued["snapshot"] and terminal["result"] is None
    for _ in range(3):
        assert request("POST", base + "/cancel", {}) == (200, terminal)
    assert request("GET", base) == (200, terminal)
    assert request("POST", "/api/v1/offline-runs", value) == (200, terminal)
    with connect(data) as db:
        assert db.execute(
            "SELECT retained_count,unfinished_count,leased_count,reserved_bytes FROM "
            "aiddos_runs_v1.quota"
        ).fetchone() == (1, 0, 0, 65536)
        assert db.execute("SELECT count(*) FROM aiddos_runs_v1.events").fetchone() == (2,)
        event = json.loads(
            db.execute("SELECT event FROM aiddos_runs_v1.events WHERE seq=2").fetchone()[0]
        )
        assert event["reason"] == "BEFORE_CLAIM" and event["at"] == run["updated_at"]
    for body in (
        b"",
        b"[]",
        b"null",
        b'{"x":1}',
        b'{"x":1,"x":1}',
        b'{"x":-0}',
        b"\xef\xbb\xbf{}",
        b"\xff",
    ):
        failed = request("POST", base + "/cancel", body)
        assert failed[0] == 422 and failed[1]["code"] == "VALIDATION_ERROR"
    assert request("POST", base + "/cancel?x=1", {})[0] == 422
    assert request("POST", base + "/cancel", b" " * 1025)[0] == 413
    assert request("POST", "/api/v1/offline-runs/not-id/cancel", {})[0] == 422
    missing = "/api/v1/offline-runs/" + str(uuid4()) + "/cancel"
    assert request("POST", missing, {})[0] == 404
    with connect(data, owner=True) as db:
        db.execute("UPDATE aiddos_runs_v1.quota SET unfinished_count=1")
    assert request("POST", missing, {}, provenance="SQL_CORRUPT_QUOTA")[0] == 404
    failed = request("POST", base + "/cancel", {}, provenance="SQL_CORRUPT_QUOTA")
    assert failed[0] == 503 and failed[1]["code"] == "RUN_STATE_CORRUPT"


def cancel_running_case(request, value, queued, data):
    from http_state_probe import claim, connect

    run_id = queued["run"]["id"]
    claim(data, run_id)
    base = "/api/v1/offline-runs/" + run_id
    label = "SQL_SEEDED_RUNNING_NOT_WORKER"
    before = request("GET", base, provenance=label)[1]
    status, pending = request("POST", base + "/cancel", {}, provenance=label)
    assert status == 202, (status, pending)
    assert pending["run"]["state"] == "CANCEL_REQUESTED"
    assert pending["run"]["event_count"] == 3
    assert pending["run"]["generation"] == pending["run"]["attempt"] == 1
    assert pending["run"]["finished_at"] is None
    assert pending["run"]["started_at"] == before["run"]["started_at"]
    for _ in range(3):
        assert request("POST", base + "/cancel", {}, provenance=label) == (202, pending)
    with connect(data) as db:
        assert db.execute(
            "SELECT unfinished_count,leased_count FROM aiddos_runs_v1.quota"
        ).fetchone() == (1, 1)
        assert db.execute("SELECT count(*) FROM aiddos_runs_v1.events").fetchone() == (3,)
        db.execute(
            "UPDATE aiddos_runs_v1.jobs SET lease_until=clock_timestamp()-interval '1 "
            "second' WHERE run_id=%s",
            (run_id,),
        )
    # Repeated API cancel never acts as a reaper, even when the committed intent's lease expires.
    assert request("POST", base + "/cancel", {}, provenance=label) == (202, pending)
    assert request("GET", base, provenance=label) == (200, pending)


def cancel_expired_case(request, value, queued, data):
    from http_state_probe import claim, connect

    run_id = queued["run"]["id"]
    claim(data, run_id, expired=True)
    base = "/api/v1/offline-runs/" + run_id
    label = "SQL_SEEDED_EXPIRED_RUNNING_NOT_WORKER"
    status, terminal = request("POST", base + "/cancel", {}, provenance=label)
    assert status == 200, (status, terminal)
    assert terminal["run"]["state"] == "CANCELLED"
    assert terminal["run"]["attempt"] == 1 and terminal["run"]["generation"] == 2
    assert terminal["run"]["event_count"] == 3
    assert request("POST", base + "/cancel", {}, provenance=label) == (200, terminal)
    with connect(data) as db:
        assert db.execute(
            "SELECT unfinished_count,leased_count FROM aiddos_runs_v1.quota"
        ).fetchone() == (0, 0)
        assert db.execute("SELECT owner_token,lease_until FROM aiddos_runs_v1.jobs").fetchone() == (
            None,
            None,
        )
        event = json.loads(
            db.execute("SELECT event FROM aiddos_runs_v1.events WHERE seq=3").fetchone()[0]
        )
        assert event["reason"] == "LEASE_REVOKED"


def cancel_deadline_case(request, value, queued, data):
    from datetime import timedelta

    from http_state_probe import claim, connect

    from aiddos.api.scenarios import canonical
    from aiddos.runs.repository import timestamp

    for running in (False, True):
        if running:
            code, queued = request(
                "POST", "/api/v1/offline-runs", {**value, "request_id": str(uuid4())}
            )
            assert code == 202
            claim(data, queued["run"]["id"])
        run_id = queued["run"]["id"]
        with connect(data, owner=True) as db, db.transaction():
            db.execute("ALTER TABLE aiddos_runs_v1.jobs DISABLE TRIGGER jobs_identity")
            db.execute(
                "UPDATE aiddos_runs_v1.jobs SET created_at=created_at-interval '301 "
                "seconds',updated_at=updated_at-interval '301 "
                "seconds',started_at=started_at-interval '301 "
                "seconds',deadline_at=deadline_at-interval '301 seconds' WHERE run_id=%s",
                (run_id,),
            )
            db.execute("ALTER TABLE aiddos_runs_v1.jobs ENABLE TRIGGER jobs_identity")
            db.execute("ALTER TABLE aiddos_runs_v1.events DISABLE TRIGGER events_immutable")
            rows = db.execute(
                "SELECT seq,event FROM aiddos_runs_v1.events WHERE run_id=%s", (run_id,)
            ).fetchall()
            from datetime import datetime

            for seq, raw in rows:
                event = json.loads(raw)
                event["at"] = timestamp(
                    datetime.fromisoformat(event["at"].replace("Z", "+00:00"))
                    - timedelta(seconds=301)
                )
                db.execute(
                    "UPDATE aiddos_runs_v1.events SET event=%s WHERE run_id=%s AND seq=%s",
                    (canonical(event), run_id, seq),
                )
            db.execute("ALTER TABLE aiddos_runs_v1.events ENABLE TRIGGER events_immutable")
        label = "SQL_SEEDED_ELAPSED_DEADLINE_NOT_REAL_300S"
        base = "/api/v1/offline-runs/" + run_id
        status, terminal = request("POST", base + "/cancel", {}, provenance=label)
        assert status == 200, (status, terminal)
        assert terminal["run"]["state"] == "TIMED_OUT"
        assert terminal["run"]["failure_code"] == "DEADLINE_EXCEEDED"
        assert terminal["run"]["cancel_requested_at"] is None
        assert terminal["run"]["generation"] == (2 if running else 0)
        assert request("POST", base + "/cancel", {}, provenance=label) == (200, terminal)
        assert request("GET", base, provenance=label) == (200, terminal)
    with connect(data) as db:
        assert db.execute(
            "SELECT unfinished_count,leased_count FROM aiddos_runs_v1.quota"
        ).fetchone() == (0, 0)


def outage_case(request, value, queued, data):
    from http_state_probe import connect

    base = "/api/v1/offline-runs"
    run = base + "/" + queued["run"]["id"]
    paths = (base, run, base + "/by-request/" + value["request_id"], run + "/events")
    for path in paths:
        assert request("GET", path)[0] == 200
    assert request("POST", run + "/cancel", {})[0] == 200
    saved = {path: request("GET", path) for path in paths}
    output = Path(data["output"])

    def action(name):
        (output / ("request-" + name)).write_text("request owned action\n")
        until = time.monotonic() + 10
        while not (output / ("done-" + name)).exists():
            assert time.monotonic() < until
            time.sleep(0.02)

    action("stop")

    def check_outage(send):
        for path in (*paths, base + "/" + str(uuid4()), base + "/" + str(uuid4()) + "/events"):
            code, error = send("GET", path, provenance="REAL_OWNED_PG_STOPPED")
            assert code == 503 and error["code"] == "RUN_DB_UNAVAILABLE", (path, code, error)
        code, error = send("POST", run + "/cancel", {}, provenance="REAL_OWNED_PG_STOPPED")
        assert code == 503 and error["code"] == "RUN_DB_UNAVAILABLE"
        assert send("GET", base + "?after=00")[0] == 422
        assert send("POST", "/api/v1/runs", b"{")[0] == 409

    check_outage(request)
    with server(data, "api-fresh-outage") as fresh:
        check_outage(fresh)
    action("start")
    until = time.monotonic() + 5
    while True:
        try:
            with connect(data) as db:
                assert db.execute("SELECT 1").fetchone() == (1,)
            break
        except Exception as exc:
            import psycopg

            assert isinstance(exc, psycopg.OperationalError) and time.monotonic() < until
            time.sleep(0.03)
    for path, expected in saved.items():
        assert request("GET", path) == expected
    with server(data, "api-fresh-recovered") as fresh:
        for path, expected in saved.items():
            assert fresh("GET", path) == expected
        assert fresh("POST", run + "/cancel", {}) == saved[run]


def priority_case(request, value, queued, data):
    from http_state_probe import connect

    base = "/api/v1/offline-runs"
    missing = base + "/" + str(uuid4())
    with connect(data) as db, db.transaction():
        db.execute("SELECT * FROM aiddos_runs_v1.quota FOR UPDATE")
        code, error = request("POST", missing + "/cancel", {})
        assert code == 404 and error["code"] == "RUN_NOT_FOUND", (code, error)
    with connect(data, owner=True) as db, db.transaction():
        db.execute("ALTER TABLE aiddos_runs_v1.inputs DISABLE TRIGGER inputs_immutable")
        db.execute("UPDATE aiddos_runs_v1.inputs SET snapshot=%s", (b"{}",))
        db.execute("ALTER TABLE aiddos_runs_v1.inputs ENABLE TRIGGER inputs_immutable")
    with connect(data) as db, db.transaction():
        db.execute("SELECT * FROM aiddos_runs_v1.quota FOR UPDATE")
        code, error = request(
            "POST",
            base + "/" + queued["run"]["id"] + "/cancel",
            {},
            provenance="SQL_CORRUPT_SNAPSHOT_WITH_QUOTA_HELD",
        )
        assert code == 503 and error["code"] == "RUN_STATE_CORRUPT", (code, error)
    with connect(data, owner=True) as db:
        db.execute("UPDATE aiddos_runs_v1.schema_version SET checksum=repeat('a',64)")
    for method, path, body in (
        ("GET", base, None),
        ("GET", missing + "/events", None),
        ("POST", missing + "/cancel", {}),
    ):
        code, error = request(method, path, body, provenance="SQL_UNSUPPORTED_SCHEMA_MARKER")
        assert code == 503 and error["code"] == "RUN_DB_NOT_READY"
        assert request(method, path + "?unknown=1", body)[0] == 422


def orphan_case(request, value, queued, data):
    from http_state_probe import connect

    with connect(data, owner=True) as db, db.transaction():
        db.execute("ALTER TABLE aiddos_runs_v1.events DISABLE TRIGGER events_immutable")
        db.execute("DELETE FROM aiddos_runs_v1.events")
        db.execute("ALTER TABLE aiddos_runs_v1.events ENABLE TRIGGER events_immutable")
        db.execute("ALTER TABLE aiddos_runs_v1.jobs DISABLE TRIGGER jobs_identity")
        db.execute("DELETE FROM aiddos_runs_v1.jobs")
        db.execute("ALTER TABLE aiddos_runs_v1.jobs ENABLE TRIGGER jobs_identity")
    path = "/api/v1/offline-runs/" + queued["run"]["id"]
    for method, suffix, body in (("GET", "/events", None), ("POST", "/cancel", {})):
        code, error = request(
            method, path + suffix, body, provenance="SQL_CORRUPT_MISSING_JOB_WITH_RETAINED_INPUT"
        )
        assert code == 503 and error["code"] == "RUN_STATE_CORRUPT", (code, error)
        missing = "/api/v1/offline-runs/" + str(uuid4()) + suffix
        assert (
            request(
                method, missing, body, provenance="SQL_CORRUPT_MISSING_JOB_WITH_RETAINED_INPUT"
            )[0]
            == 404
        )


def configuration_case(request, value, queued, data):
    family = data["case"].removeprefix("configuration-")
    path = "/api/v1/offline-runs"
    if family != "list":
        path += "/" + str(uuid4()) + "/" + family
    method = "POST" if family == "cancel" else "GET"
    body = {} if family == "cancel" else None
    with server({**data, "no_socket": True}, "api-no-configuration") as client:
        code, reply = client(method, path, body, provenance="MISSING_CONFIGURATION_NO_DRIVER")
        assert code == 503 and reply["code"] == "RUN_DB_NOT_CONFIGURED"
        code, invalid = client(method, path + "?extra=1", body)
        assert code == 422 and invalid["code"] == "VALIDATION_ERROR"
        if family != "cancel":
            code, invalid = client("GET", path, b"x")
            assert code == 400 and invalid["code"] == "INVALID_FRAMING"


def execute(data):
    source_check(data)
    import psycopg

    assert Path(psycopg.__file__).is_relative_to(ROOT / ".venv")
    output = Path(data["output"])
    assert Path(data["socket"]).is_relative_to("/home/piecer/.hermes/cache/scratch/i3w-lecrmpg5")
    data = {**data, "state": str(output / "draft.json")}
    with child(
        data,
        "migration",
        [data["python"], "-m", "aiddos.runs.migrate"],
        extra={"AIDDOS_RUN_DB_SOCKET": data["socket"]},
    ) as process:
        assert process.wait(timeout=8) == 0
    with server(data) as request:
        value = create_source(request)
        code, queued = request("POST", "/api/v1/offline-runs", value)
        assert code == 202 and queued["run"]["state"] == "QUEUED"
        from http_atomic_probe import execute as atomic_case
        from http_atomic_probe import uncertain
        from http_caps_probe import execute as caps_case
        from http_lock_probe import execute as lock_case
        from http_terminal_probe import execute as terminal_case

        {
            "configuration-list": configuration_case,
            "configuration-events": configuration_case,
            "configuration-cancel": configuration_case,
            "orphan": orphan_case,
            "uncertain": uncertain,
            "terminal": terminal_case,
            "priority": priority_case,
            "atomic": atomic_case,
            "caps": caps_case,
            "locks": lock_case,
            "list": list_case,
            "events": events_case,
            "failed-summary": failed_summary_case,
            "cancel-queued": cancel_queued_case,
            "cancel-running": cancel_running_case,
            "cancel-expired": cancel_expired_case,
            "cancel-deadline": cancel_deadline_case,
            "outage": outage_case,
        }[data["case"]](request, value, queued, data)
    (output / "result.json").write_text(json.dumps({"verified": True, "case": data["case"]}) + "\n")


if __name__ == "__main__":
    if sys.argv[1] == "--serve":
        serve(json.loads(Path(sys.argv[2]).read_text()), int(sys.argv[3]))
    else:
        data = json.loads(Path(sys.argv[1]).read_text())
        try:
            execute(data)
        except BaseException as exc:
            (Path(data["output"]) / "failure.json").write_text(
                json.dumps(
                    {
                        "type": type(exc).__name__,
                        "traceback": traceback.format_exc(),
                    },
                    indent=2,
                )
                + "\n"
            )
            raise SystemExit(1) from None
