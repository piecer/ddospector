"""Instrument production worker paths in exclusively owned child processes."""

import asyncio
import json
import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cohort-evidence"))
from supervise import environment, save  # noqa: E402

from tools import s02_harness as h  # noqa: E402


@contextmanager
def child(data, label, argv, *, extra=None):
    output = Path(data["output"])
    env = environment()
    env["AIDDOS_RUN_DB_SOCKET"] = data["socket"]
    if extra:
        env.update(extra)
    process = subprocess.Popen(
        argv,
        cwd=ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    identity = h.identity_of(process.pid)
    save(
        output / (label + "-started.json"), {"identity": identity, "argv": argv, "environment": env}
    )

    def drain(stream, path):
        with path.open("wb") as target:
            while chunk := stream.read(4096):
                target.write(chunk)
                target.flush()
        stream.close()

    threads = [
        threading.Thread(target=drain, args=(s, output / (label + suffix)))
        for s, suffix in ((process.stdout, "-stdout.log"), (process.stderr, "-stderr.log"))
    ]
    for thread in threads:
        thread.start()
    rescued = False
    start = None
    try:
        yield process
    finally:
        if process.poll() is None:
            assert h.identity_of(process.pid) == identity
            start = time.monotonic()
            process.send_signal(signal.SIGCONT)
            process.terminate()
        try:
            code = process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            rescued = True
            save(output / (label + "-before-rescue.json"), {"identity": h.identity_of(process.pid)})
            assert h.identity_of(process.pid) == identity
            process.kill()
            code = process.wait(timeout=2)
        for thread in threads:
            thread.join(timeout=2)
        receipt = {
            "identity": identity,
            "actual_exit": code,
            "reaped": True,
            "absent": not Path(f"/proc/{process.pid}").exists(),
            "rescued": rescued,
            "pipes_closed": process.stdout.closed and process.stderr.closed,
            "term_elapsed": None if start is None else time.monotonic() - start,
        }
        save(output / (label + "-exit.json"), receipt)
        assert receipt["absent"] and receipt["pipes_closed"] and not rescued


def worker_child(data, mode):
    from aiddos.runs import transitions, worker

    output = Path(data["output"])
    trace_events = []

    def trace(frame, event, arg):
        if (
            frame.f_code.co_filename == worker.__file__
            and event == "exception"
            and arg[0] not in {StopIteration, StopAsyncIteration}
        ):
            trace_events.append(
                {
                    "function": frame.f_code.co_name,
                    "line": frame.f_lineno,
                    "kind": arg[0].__name__,
                    "time": time.monotonic(),
                }
            )
            save(output / f"worker-exceptions-{os.getpid()}.json", trace_events)
        return trace

    sys.settrace(trace)
    if mode in {"pure-invalid", "pure-failure", "pure-limit"}:
        from aiddos.runs import offline

        def invalid(*args, **kwargs):
            raise ValueError("VERIFIER_SNAPSHOT_INVALID")

        def failed(*args, **kwargs):
            raise RuntimeError("VERIFIER_PURE_FAILURE")

        def oversized(*args, **kwargs):
            return b"x" * 8193

        if mode == "pure-invalid":
            offline.verify = invalid
        else:
            offline.compile_manifest = failed if mode == "pure-failure" else oversized
    if mode == "outage":
        import psycopg

        original_connect = psycopg.AsyncConnection.connect
        attempts = []

        async def tracked_connect(cls, **kwargs):
            entry = {"start": time.monotonic()}
            attempts.append(entry)
            save(output / "connect-attempts.json", attempts)
            try:
                connection = await original_connect(**kwargs)
                entry["success"] = True
                return connection
            except Exception:
                entry["success"] = False
                raise
            finally:
                entry["end"] = time.monotonic()
                save(output / "connect-attempts.json", attempts)

        psycopg.AsyncConnection.connect = classmethod(tracked_connect)
        original_recover = transitions.recover

        async def recovered(op):
            value = await original_recover(op)
            save(output / "outage-ready.json", {"at": time.monotonic()})
            if sum(x.get("success", False) for x in attempts) > 1:
                save(output / "outage-resumed.json", {"at": time.monotonic()})
            return value

        transitions.recover = recovered
    if mode.startswith("close-"):
        import psycopg

        original_ready = worker.schema.ready
        calls = []

        async def ready(execute):
            await original_ready(execute)
            save(output / "close-ready.json", {"pid": os.getpid()})

        async def unconfirmed(connection):
            calls.append({"closed": connection.closed, "at": time.monotonic()})
            save(output / "close-calls.json", calls)
            if mode == "close-pending":
                await asyncio.Event().wait()
            raise OSError("VERIFIER_CLOSE_WITHOUT_EFFECT")

        worker.schema.ready = ready
        psycopg.AsyncConnection.close = unconfirmed
    if mode == "cooperative":
        import psycopg

        from aiddos.runs import offline

        original_verify = offline.verify
        original_close = psycopg.AsyncConnection.close

        def cooperative(raw, stop=None):
            save(output / "cooperative-entered.json", {"at": time.monotonic()})
            while stop is None or not stop.is_set():
                time.sleep(0.01)
            time.sleep(0.6)
            save(output / "cooperative-done.json", {"at": time.monotonic()})
            return original_verify(raw)

        async def close(connection):
            await asyncio.sleep(0.6)
            await original_close(connection)
            save(
                output / "cooperative-closed.json",
                {"at": time.monotonic(), "closed": connection.closed},
            )

        offline.verify = cooperative
        psycopg.AsyncConnection.close = close
    if mode == "refuse-driver":
        sys.modules["psycopg"] = None
    if mode == "refuse-config":
        os.environ.pop("AIDDOS_RUN_DB_SOCKET", None)
    if mode == "idle":
        original = transitions.claim
        counts = []

        async def claim(op):
            counts.append(
                sum(t.get_coro().__qualname__ == "Event.wait" for t in asyncio.all_tasks())
            )
            if len(counts) == 5:
                save(output / "result.json", {"waiter_counts": counts})
                os.kill(os.getpid(), signal.SIGTERM)
            return await original(op)

        transitions.claim = claim
    if mode == "atomic-complete":
        original_commit = transitions.commit

        async def precommit(op, **kwargs):
            if op.phase == "COMPLETE":
                save(output / "precommit-fired.json", {"at": time.monotonic()})
                raise RuntimeError("VERIFIER_PRECOMMIT_FAILURE")
            return await original_commit(op, **kwargs)

        transitions.commit = precommit
    if mode == "row-lock-deadline":
        original_publish = transitions.publish

        async def paused_publish(op, owned, step, result=None, **kwargs):
            if step == 1:
                save(output / "publish-ready.json", {"backend_pid": op.connection.info.backend_pid})
                while not (output / "publish-go").exists():
                    await asyncio.sleep(0.005)
            return await original_publish(op, owned, step, result, **kwargs)

        transitions.publish = paused_publish
    if mode == "stale":
        original_claim = transitions.claim
        connections = []

        async def tracked(op):
            connections.append(op.connection.info.backend_pid)
            save(output / "stale-connections.json", connections)
            value = await original_claim(op)
            if value is not None:
                save(output / "stale-claimed.json", {"pid": os.getpid()})
                os.kill(os.getpid(), signal.SIGSTOP)
                from aiddos.runs import offline

                result = offline.compile_manifest(offline.verify(value["snapshot"]))
                original_compute = op.compute

                async def check(function):
                    return await asyncio.to_thread(function)

                op.compute = check
                fenced = []
                try:
                    for label, action in (
                        ("heartbeat", lambda: transitions.heartbeat(op, value)),
                        ("progress", lambda: transitions.publish(op, value, 1)),
                        (
                            "failure",
                            lambda: transitions.publish(
                                op, value, 0, failure="OFFLINE_PREPARATION_FAILED"
                            ),
                        ),
                        ("success", lambda: transitions.publish(op, value, 3, result)),
                    ):
                        try:
                            await action()
                        except transitions.StaleClaim:
                            fenced.append(label)
                        else:
                            raise AssertionError("OLD_OWNER_WAS_NOT_FENCED")
                        finally:
                            await op.rollback()
                finally:
                    op.compute = original_compute
                save(output / "stale-fences.json", fenced)
            return value

        transitions.claim = tracked
    if mode == "progress-barrier":
        from aiddos.runs import offline

        original_compile = offline.compile_manifest

        def hold_compilation(snapshot, *, stop=None):
            save(output / f"progress-{os.getpid()}.json", {"pid": os.getpid()})
            until(lambda: (output / "release").exists(), 40)
            return original_compile(snapshot)

        offline.compile_manifest = hold_compilation
    if mode == "barrier":
        from aiddos.runs import offline

        original_verify = offline.verify

        def hold(raw, *, stop=None):
            save(output / f"entered-{os.getpid()}.json", {"pid": os.getpid()})
            until(lambda: (output / "release").exists(), 20)
            return original_verify(raw)

        offline.verify = hold
    if mode == "pure":
        from aiddos.runs import offline

        original_claim = transitions.claim
        connection = []
        calls = []

        async def tracked_claim(op):
            connection[:] = [op]
            return await original_claim(op)

        transitions.claim = tracked_claim

        def instrument(function):
            def pure(*args, **kwargs):
                calls.append(
                    {
                        "thread": threading.get_ident(),
                        "transaction": connection[0].transaction is not None,
                        "driver_status": int(connection[0].connection.info.transaction_status),
                    }
                )
                save(
                    output / "pure-calls.json",
                    {"calls": calls, "main_thread": threading.main_thread().ident},
                )
                return function(*args, **kwargs)

            return pure

        offline.verify = instrument(offline.verify)
        offline.compile_manifest = instrument(offline.compile_manifest)
        original_model = offline.ScenarioVersion.model_validate
        checked_model = instrument(original_model)
        offline.ScenarioVersion.model_validate = classmethod(
            lambda cls, *args, **kwargs: checked_model(*args, **kwargs)
        )
    raise SystemExit(worker.main())


def seed(data, count=1, age=0):
    os.environ["AIDDOS_RUN_DB_SOCKET"] = data["socket"]
    os.environ["AIDDOS_UI_STATE_PATH"] = str(Path(data["output"]) / "draft.json")
    sys.path.insert(0, str(ROOT / "tests/api"))
    from datetime import timedelta
    from uuid import uuid4

    from fastapi.testclient import TestClient
    from scenario_producer import definition

    from aiddos.api import runs as router_module
    from aiddos.api.app import app
    from aiddos.runs import repository

    original_create = repository.create

    async def clock_seed(op, *args):
        original_execute = op.execute

        async def execute(sql, params=None):
            rows = await original_execute(sql, params)
            if sql == "SELECT clock_timestamp()":
                return [(rows[0][0] - timedelta(seconds=age),)]
            return rows

        op.execute = execute
        try:
            return await original_create(op, *args)
        finally:
            op.execute = original_execute

    if age:
        router_module.create = clock_seed
        save(
            Path(data["output"]) / "clock-fixture.json",
            {
                "admission_clock_shift_seconds": age,
                "kind": "DISCLOSED_SQL_CLOCK_SEED_NOT_NATURAL_300S",
            },
        )
    with TestClient(app, base_url="http://127.0.0.1:5180") as client:
        targets = []
        for kind in ("DUT", "SINK"):
            response = client.post(
                "/api/v1/targets",
                json={"name": kind, "kind": kind, "address": "never-resolve.invalid"},
            )
            assert response.status_code == 201, response.text
            targets.append(response.json())
        response = client.post(
            "/api/v1/scenarios", json={"revision": 0, "definition": definition(targets)}
        )
        assert response.status_code == 201, response.text
        record = response.json()["scenario"]
        values = []
        for _ in range(count):
            response = client.post(
                "/api/v1/offline-runs",
                json={
                    "request_id": str(uuid4()),
                    "mode": "OFFLINE",
                    "scenario_id": record["id"],
                    "scenario_version": record["version"],
                    "scenario_digest": record["digest"],
                },
            )
            assert response.status_code == 202, response.text
            values.append(response.json())
        save(Path(data["output"]) / "asgi-producer.json", values)
    router_module.create = original_create
    for path in Path(data["output"]).glob("draft.json*"):
        if path.is_file():
            path.rename(path.with_name("unavailable-" + path.name))
    return values


def cancel_intent(db):
    from aiddos.api.scenarios import canonical
    from aiddos.runs.repository import timestamp

    with db.transaction():
        db.execute("SELECT * FROM aiddos_runs_v1.quota FOR UPDATE")
        db.execute("SELECT * FROM aiddos_runs_v1.jobs FOR UPDATE")
        row = db.execute(
            "WITH t AS (SELECT clock_timestamp() at) UPDATE aiddos_runs_v1.jobs j "
            "SET state='CANCEL_REQUESTED',cancel_requested_at=t.at,updated_at=t.at,"
            "event_count=event_count+1 FROM t WHERE state='RUNNING' "
            "RETURNING run_id,event_count,updated_at,attempt,generation"
        ).fetchone()
        run_id, seq, at, attempt, generation = row
        event = {
            "seq": seq,
            "at": timestamp(at),
            "type": "CANCEL_REQUESTED",
            "state": "CANCEL_REQUESTED",
            "attempt": attempt,
            "generation": generation,
            "reason": None,
        }
        db.execute(
            "INSERT INTO aiddos_runs_v1.events VALUES(%s,%s,%s)", (run_id, seq, canonical(event))
        )


def connect(data):
    import psycopg

    return psycopg.connect(**h.connection_parameters(Path(data["socket"])), autocommit=True)


def until(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while not (value := predicate()):
        assert time.monotonic() < deadline, "OBSERVER_DEADLINE"
        time.sleep(0.02)
    return value


def execute(data):
    assert data["root"] == str(ROOT)
    assert sys.prefix == str(ROOT / ".venv")
    assert h.identity_of(data["owner"]["pid"]) == data["owner"]
    if data["case"].startswith("refuse-"):
        with child(
            data,
            "refused",
            [
                sys.executable,
                str(Path(__file__)),
                "--worker",
                str(Path(data["output"]) / "handoff.json"),
                data["case"],
            ],
        ) as p:
            code = p.wait(timeout=4)
        save(Path(data["output"]) / "result.json", {"exit": code})
        assert code == 78
        return
    with child(data, "migration", [sys.executable, "-m", "aiddos.runs.migrate"]) as p:
        assert p.wait(timeout=8) == 0
    if data["case"] == "atomic-complete":
        seed(data)
        output = Path(data["output"])
        with (
            child(
                data,
                "worker",
                [
                    sys.executable,
                    str(Path(__file__)),
                    "--worker",
                    str(output / "handoff.json"),
                    "atomic-complete",
                ],
            ) as p,
            connect(data) as db,
        ):
            assert p.wait(timeout=5) == 75
            assert (output / "precommit-fired.json").exists()
            row = db.execute(
                "SELECT state,attempt,generation,event_count,step FROM aiddos_runs_v1.jobs"
            ).fetchone()
            assert row == ("RUNNING", 1, 1, 4, 2)
            assert db.execute("SELECT count(*) FROM aiddos_runs_v1.events").fetchone()[0] == 4
            assert db.execute("SELECT count(*) FROM aiddos_runs_v1.results").fetchone()[0] == 0
            assert db.execute(
                "SELECT unfinished_count,leased_count FROM aiddos_runs_v1.quota"
            ).fetchone() == (1, 1)
        save(
            output / "result.json",
            {
                "no_partial_writes": True,
                "row": list(row),
                "kind": "INJECTED_PRECOMMIT_EXCEPTION_NOT_SQLSTATE_OR_ACK_LOSS",
            },
        )
        return
    if data["case"] == "row-lock-deadline":
        seed(data, age=297)
        output = Path(data["output"])
        with (
            child(
                data,
                "worker",
                [
                    sys.executable,
                    str(Path(__file__)),
                    "--worker",
                    str(output / "handoff.json"),
                    "row-lock-deadline",
                ],
            ),
            connect(data) as db,
        ):
            until(lambda: (output / "publish-ready.json").exists())
            backend = json.loads((output / "publish-ready.json").read_text())["backend_pid"]
            with connect(data) as holder:
                until(
                    lambda: db.execute(
                        "SELECT extract(epoch FROM deadline_at-clock_timestamp())<.2 "
                        "FROM aiddos_runs_v1.jobs"
                    ).fetchone()[0]
                )
                with holder.transaction():
                    holder.execute("SELECT * FROM aiddos_runs_v1.jobs FOR UPDATE")
                    (output / "publish-go").touch()
                    until(
                        lambda: db.execute(
                            "SELECT wait_event_type='Lock' FROM pg_stat_activity WHERE pid=%s",
                            (backend,),
                        ).fetchone()[0],
                        0.15,
                    )
                    before = db.execute(
                        "SELECT state,event_count,clock_timestamp(),deadline_at "
                        "FROM aiddos_runs_v1.jobs"
                    ).fetchone()
                    assert before[:2] == ("RUNNING", 2) and before[2] < before[3]
                    until(
                        lambda: db.execute(
                            "SELECT clock_timestamp()>=deadline_at FROM aiddos_runs_v1.jobs"
                        ).fetchone()[0],
                        0.3,
                    )
            until(
                lambda: db.execute("SELECT state='TIMED_OUT' FROM aiddos_runs_v1.jobs").fetchone()[
                    0
                ]
            )
            row = db.execute(
                "SELECT state,event_count,finished_at,deadline_at FROM aiddos_runs_v1.jobs"
            ).fetchone()
            assert row[1] == 3 and row[2] >= row[3]
            assert db.execute(
                "SELECT unfinished_count,leased_count FROM aiddos_runs_v1.quota"
            ).fetchone() == (0, 0)
            assert db.execute("SELECT count(*) FROM aiddos_runs_v1.results").fetchone()[0] == 0
        save(
            output / "result.json",
            {
                "lock_observed": True,
                "state": row[0],
                "before": [str(v) for v in before],
                "after": [str(v) for v in row],
            },
        )
        return
    if data["case"] == "real-deadline":
        started = time.monotonic()
        queued = seed(data)[0]
        output = Path(data["output"])
        with connect(data) as db:
            samples = []
            while True:
                row = db.execute(
                    "SELECT state,attempt,created_at,deadline_at,clock_timestamp() "
                    "FROM aiddos_runs_v1.jobs"
                ).fetchone()
                assert row[:2] == ("QUEUED", 0)
                assert (row[3] - row[2]).total_seconds() == 300
                samples.append(
                    {"at": str(row[4]), "state": row[0], "age": (row[4] - row[2]).total_seconds()}
                )
                save(output / "real-clock-samples.json", samples)
                if row[4] >= row[3]:
                    break
                assert time.monotonic() - started < 310
                time.sleep(0.5)
            assert not (output / "clock-fixture.json").exists()
            with child(data, "expiry-worker", [sys.executable, "-m", "aiddos.runs.worker"]):
                until(
                    lambda: db.execute(
                        "SELECT state='TIMED_OUT' FROM aiddos_runs_v1.jobs"
                    ).fetchone()[0]
                )
                row = db.execute(
                    "SELECT attempt,generation,created_at,deadline_at,finished_at,event_count "
                    "FROM aiddos_runs_v1.jobs"
                ).fetchone()
                from aiddos.runs.repository import timestamp

                assert row[:2] == (0, 0) and row[5] == 2
                assert timestamp(row[3]) == queued["run"]["deadline_at"]
                assert row[4] >= row[3]
                assert db.execute(
                    "SELECT unfinished_count,leased_count FROM aiddos_runs_v1.quota"
                ).fetchone() == (0, 0)
                assert db.execute("SELECT count(*) FROM aiddos_runs_v1.results").fetchone()[0] == 0
                terminal = db.execute("SELECT * FROM aiddos_runs_v1.jobs").fetchall()
                time.sleep(1.1)
                assert db.execute("SELECT * FROM aiddos_runs_v1.jobs").fetchall() == terminal
        save(
            output / "result.json",
            {
                "age_seconds": (row[4] - row[2]).total_seconds(),
                "attempt": row[0],
                "elapsed": time.monotonic() - started,
                "clock_accelerated": False,
            },
        )
        return
    if data["case"] in {"pure-invalid", "pure-failure", "pure-limit"}:
        seed(data)
        output = Path(data["output"])
        with (
            child(
                data,
                "worker",
                [
                    sys.executable,
                    str(Path(__file__)),
                    "--worker",
                    str(output / "handoff.json"),
                    data["case"],
                ],
            ) as p,
            connect(data) as db,
        ):
            try:
                until(
                    lambda: db.execute("SELECT state='FAILED' FROM aiddos_runs_v1.jobs").fetchone()[
                        0
                    ],
                    4,
                )
            finally:
                row = db.execute(
                    "SELECT state,attempt,failure_code FROM aiddos_runs_v1.jobs"
                ).fetchone()
                save(
                    output / "pure-failure-observation.json",
                    {"row": list(row), "worker_exit": p.poll()},
                )
            assert p.poll() is None
            assert row[1] == 1
            assert db.execute(
                "SELECT unfinished_count,leased_count FROM aiddos_runs_v1.quota"
            ).fetchone() == (0, 0)
            assert db.execute("SELECT count(*) FROM aiddos_runs_v1.results").fetchone()[0] == 0
        with connect(data) as db:
            terminal = db.execute("SELECT * FROM aiddos_runs_v1.jobs").fetchall()
            with child(data, "restart", [sys.executable, "-m", "aiddos.runs.worker"]):
                time.sleep(1.2)
                assert db.execute("SELECT * FROM aiddos_runs_v1.jobs").fetchall() == terminal
        save(output / "result.json", {"failure_code": row[2]})
        return
    if data["case"].startswith("outage-"):
        output = Path(data["output"])
        with child(
            data,
            "worker",
            [
                sys.executable,
                str(Path(__file__)),
                "--worker",
                str(output / "handoff.json"),
                "outage",
            ],
        ) as p:
            until(lambda: (output / "db-stopped").exists(), 10)
            if data["case"] == "outage-exhaust":
                assert p.wait(timeout=28) == 75
            else:
                until(lambda: (output / "outage-resumed.json").exists(), 12)
                assert p.poll() is None
        attempts = json.loads((output / "connect-attempts.json").read_text())
        if data["case"] == "outage-exhaust":
            assert len(attempts) == 6, attempts
            for gap, previous, current in zip(
                (1, 2, 4, 8), attempts[1:], attempts[2:], strict=False
            ):
                assert gap <= current["start"] - previous["end"] < gap + 0.5
            assert all(not a["success"] for a in attempts[1:])
        else:
            assert sum(a["success"] for a in attempts) == 2
            resumed = json.loads((output / "outage-resumed.json").read_text())["at"]
            assert resumed - attempts[-1]["end"] >= 1
        assert all(a["end"] - a["start"] < 2.2 for a in attempts)
        save(output / "result.json", {"verified": True, "attempts": attempts})
        return
    if data["case"].startswith("close-"):
        output = Path(data["output"])
        with child(
            data,
            "worker",
            [
                sys.executable,
                str(Path(__file__)),
                "--worker",
                str(output / "handoff.json"),
                data["case"],
            ],
        ) as p:
            until(lambda: (output / "close-ready.json").exists())
            start = time.monotonic()
            p.terminate()
            code = p.wait(timeout=1.5)
            assert code == 75
            assert time.monotonic() - start < 1.3
            assert len(json.loads((output / "close-calls.json").read_text())) == 1
        save(output / "result.json", {"exit": code})
        return
    if data["case"] == "cancel-cooperative":
        seed(data)
        output = Path(data["output"])
        with (
            child(
                data,
                "worker",
                [
                    sys.executable,
                    str(Path(__file__)),
                    "--worker",
                    str(output / "handoff.json"),
                    "cooperative",
                ],
            ),
            connect(data) as db,
        ):
            until(lambda: (output / "cooperative-entered.json").exists())
            cancel_intent(db)
            until(
                lambda: db.execute("SELECT state='CANCELLED' FROM aiddos_runs_v1.jobs").fetchone()[
                    0
                ],
                3.5,
            )
            assert (output / "cooperative-done.json").exists()
            event = json.loads(
                db.execute(
                    "SELECT event FROM aiddos_runs_v1.events ORDER BY seq DESC LIMIT 1"
                ).fetchone()[0]
            )
            assert event["reason"] == "WORKER_ACK"
        save(output / "result.json", {"reason": event["reason"]})
        return
    if data["case"] == "term-cooperative":
        seed(data, 2)
        output = Path(data["output"])
        with (
            child(
                data,
                "worker",
                [
                    sys.executable,
                    str(Path(__file__)),
                    "--worker",
                    str(output / "handoff.json"),
                    "cooperative",
                ],
            ) as p,
            connect(data) as db,
        ):
            until(lambda: (output / "cooperative-entered.json").exists())
            start = time.monotonic()
            save(output / "before-term.json", {"identity": h.identity_of(p.pid), "at": start})
            p.terminate()
            code = p.wait(timeout=1.5)
            assert code == 0, "COOPERATIVE_STOP_NOT_SIGNALED"
            assert time.monotonic() - start < 1.3
            assert (output / "cooperative-done.json").exists()
            assert json.loads((output / "cooperative-closed.json").read_text())["closed"]
            assert db.execute("SELECT sum(attempt) FROM aiddos_runs_v1.jobs").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM aiddos_runs_v1.results").fetchone()[0] == 0
        save(output / "result.json", {"exit": code})
        return
    if data["case"] in {"watchdog", "term-stuck"}:
        seed(data, 2)
        output = Path(data["output"])
        with (
            child(
                data,
                "worker",
                [
                    sys.executable,
                    str(Path(__file__)),
                    "--worker",
                    str(output / "handoff.json"),
                    "barrier",
                ],
            ) as p,
            connect(data) as db,
        ):
            until(lambda: (output / f"entered-{p.pid}.json").exists())
            start = time.monotonic()
            if data["case"] == "term-stuck":
                save(output / "before-term.json", h.identity_of(p.pid))
                p.terminate()
            code = p.wait(timeout=7 if data["case"] == "watchdog" else 1.5)
            elapsed = time.monotonic() - start
            assert code == 75
            assert elapsed <= (6.5 if data["case"] == "watchdog" else 1.3)
            assert db.execute(
                "SELECT sum(attempt),count(*) FILTER (WHERE state='QUEUED') "
                "FROM aiddos_runs_v1.jobs"
            ).fetchone() == (1, 1)
            assert db.execute("SELECT count(*) FROM aiddos_runs_v1.results").fetchone()[0] == 0
        save(output / "result.json", {"exit": code, "elapsed": elapsed})
        return
    if data["case"].startswith("deadline-"):
        seed(data, age=298)
        output = Path(data["output"])
        if data["case"] == "deadline-queued":
            time.sleep(2.1)
            mode = "normal"
        else:
            mode = "barrier"
        with (
            child(
                data,
                "worker",
                [
                    sys.executable,
                    str(Path(__file__)),
                    "--worker",
                    str(output / "handoff.json"),
                    mode,
                ],
            ) as p,
            connect(data) as db,
        ):
            if mode == "barrier":
                until(lambda: (output / f"entered-{p.pid}.json").exists())
                until(
                    lambda: db.execute(
                        "SELECT clock_timestamp()>=deadline_at FROM aiddos_runs_v1.jobs"
                    ).fetchone()[0],
                    3,
                )
                (output / "release").touch()
            try:
                until(
                    lambda: db.execute(
                        "SELECT state='TIMED_OUT' FROM aiddos_runs_v1.jobs"
                    ).fetchone()[0],
                    4,
                )
            finally:
                row = db.execute(
                    "SELECT state,attempt,generation,deadline_at,finished_at "
                    "FROM aiddos_runs_v1.jobs"
                ).fetchone()
                save(output / "deadline-observation.json", {"row": [str(v) for v in row]})
            assert row[4] >= row[3]
            assert db.execute(
                "SELECT unfinished_count,leased_count FROM aiddos_runs_v1.quota"
            ).fetchone() == (0, 0)
            assert db.execute("SELECT count(*) FROM aiddos_runs_v1.results").fetchone()[0] == 0
        save(output / "result.json", {"state": row[0]})
        return
    if data["case"] == "cancel-expired":
        seed(data, age=298)
        output = Path(data["output"])
        with connect(data) as db:
            with child(
                data,
                "interrupted",
                [
                    sys.executable,
                    str(Path(__file__)),
                    "--worker",
                    str(output / "handoff.json"),
                    "barrier",
                ],
            ) as p:
                until(lambda: (output / f"entered-{p.pid}.json").exists())
                cancel_intent(db)
                save(output / "before-kill.json", h.identity_of(p.pid))
                p.kill()
                assert p.wait(timeout=2) == -9
            with child(data, "reaper", [sys.executable, "-m", "aiddos.runs.worker"]):
                time.sleep(2.1)
                assert (
                    db.execute("SELECT state FROM aiddos_runs_v1.jobs").fetchone()[0]
                    == "CANCEL_REQUESTED"
                )
                until(
                    lambda: db.execute(
                        "SELECT state='CANCELLED' FROM aiddos_runs_v1.jobs"
                    ).fetchone()[0],
                    11,
                )
                event = json.loads(
                    db.execute(
                        "SELECT event FROM aiddos_runs_v1.events ORDER BY seq DESC LIMIT 1"
                    ).fetchone()[0]
                )
                assert event["reason"] == "LEASE_REVOKED"
                assert db.execute(
                    "SELECT unfinished_count,leased_count FROM aiddos_runs_v1.quota"
                ).fetchone() == (0, 0)
        save(output / "result.json", {"reason": event["reason"]})
        return
    if data["case"] == "cancel":
        seed(data)
        output = Path(data["output"])
        with (
            child(
                data,
                "worker",
                [
                    sys.executable,
                    str(Path(__file__)),
                    "--worker",
                    str(output / "handoff.json"),
                    "barrier",
                ],
            ) as p,
            connect(data) as db,
        ):
            until(lambda: (output / f"entered-{p.pid}.json").exists())
            cancel_intent(db)
            save(
                output / "fixture-kind.json",
                {"kind": "SQL_SEEDED_VALID_CANCEL_INTENT_NOT_HTTP_RACE"},
            )
            assert (
                db.execute("SELECT state FROM aiddos_runs_v1.jobs").fetchone()[0]
                == "CANCEL_REQUESTED"
            )
            (output / "release").touch()
            until(
                lambda: db.execute("SELECT state='CANCELLED' FROM aiddos_runs_v1.jobs").fetchone()[
                    0
                ],
                4,
            )
            rows = db.execute("SELECT * FROM aiddos_runs_v1.jobs").fetchall()
            event = json.loads(
                db.execute(
                    "SELECT event FROM aiddos_runs_v1.events ORDER BY seq DESC LIMIT 1"
                ).fetchone()[0]
            )
            assert event["reason"] == "WORKER_ACK"
            assert db.execute(
                "SELECT unfinished_count,leased_count FROM aiddos_runs_v1.quota"
            ).fetchone() == (0, 0)
            assert db.execute("SELECT count(*) FROM aiddos_runs_v1.results").fetchone()[0] == 0
        with (
            child(data, "restart", [sys.executable, "-m", "aiddos.runs.worker"]),
            connect(data) as db,
        ):
            time.sleep(1.2)
            assert db.execute("SELECT * FROM aiddos_runs_v1.jobs").fetchall() == rows
        save(output / "result.json", {"state": "CANCELLED", "reason": event["reason"]})
        return
    if data["case"] == "stale":
        seed(data)
        output = Path(data["output"])
        with (
            child(
                data,
                "old-worker",
                [
                    sys.executable,
                    str(Path(__file__)),
                    "--worker",
                    str(output / "handoff.json"),
                    "stale",
                ],
            ) as old,
            connect(data) as db,
        ):
            until(lambda: (output / "stale-claimed.json").exists())
            assert Path(f"/proc/{old.pid}/stat").read_text().rsplit(")", 1)[1].split()[0] == "T"
            with child(data, "successor", [sys.executable, "-m", "aiddos.runs.worker"]):
                until(
                    lambda: db.execute(
                        "SELECT state='SUCCEEDED' FROM aiddos_runs_v1.jobs"
                    ).fetchone()[0],
                    13,
                )
                before = db.execute("SELECT * FROM aiddos_runs_v1.jobs").fetchall()
                save(
                    output / "before-resume.json",
                    {
                        "identity": h.identity_of(old.pid),
                        "rows": [[str(v) for v in row] for row in before],
                    },
                )
                old.send_signal(signal.SIGCONT)
                time.sleep(1.3)
                assert old.poll() is None, "STALE_OWNER_EXITED_INSTEAD_OF_HEALTHY_REUSE"
                connections = json.loads((output / "stale-connections.json").read_text())
                assert len(connections) >= 2 and len(set(connections)) == 1
                assert json.loads((output / "stale-fences.json").read_text()) == [
                    "heartbeat",
                    "progress",
                    "failure",
                    "success",
                ]
                assert db.execute("SELECT * FROM aiddos_runs_v1.jobs").fetchall() == before
                assert db.execute("SELECT count(*) FROM aiddos_runs_v1.results").fetchone()[0] == 1
        save(output / "result.json", {"same_connection": True, "unchanged": True})
        return
    if data["case"] == "exhausted":
        queued = seed(data)[0]
        output = Path(data["output"])
        with connect(data) as db:
            for i in range(3):
                with child(
                    data,
                    f"interrupted-{i}",
                    [
                        sys.executable,
                        str(Path(__file__)),
                        "--worker",
                        str(output / "handoff.json"),
                        "progress-barrier",
                    ],
                ) as p:
                    until(lambda: (output / f"progress-{p.pid}.json").exists(), 13)
                    row = db.execute(
                        "SELECT attempt,generation,deadline_at FROM aiddos_runs_v1.jobs"
                    ).fetchone()
                    assert row[:2] == (i + 1, 2 * i + 1)
                    save(
                        output / f"before-kill-{i}.json",
                        {"identity": h.identity_of(p.pid), "row": [str(v) for v in row]},
                    )
                    p.kill()
                    assert p.wait(timeout=2) == -9
            with child(data, "reaper", [sys.executable, "-m", "aiddos.runs.worker"]):
                until(
                    lambda: db.execute("SELECT state='FAILED' FROM aiddos_runs_v1.jobs").fetchone()[
                        0
                    ],
                    13,
                )
                row = db.execute(
                    "SELECT state,attempt,generation,failure_code,deadline_at "
                    "FROM aiddos_runs_v1.jobs"
                ).fetchone()
                from aiddos.runs.repository import timestamp

                assert row[:4] == ("FAILED", 3, 6, "RETRY_EXHAUSTED")
                assert timestamp(row[4]) == queued["run"]["deadline_at"]
                assert db.execute(
                    "SELECT unfinished_count,leased_count FROM aiddos_runs_v1.quota"
                ).fetchone() == (0, 0)
                assert db.execute("SELECT count(*) FROM aiddos_runs_v1.results").fetchone()[0] == 0
        save(output / "result.json", {"state": row[0], "attempt": row[1]})
        return
    if data["case"] == "restart":
        queued = seed(data)[0]
        output = Path(data["output"])
        with child(
            data,
            "killed-worker",
            [
                sys.executable,
                str(Path(__file__)),
                "--worker",
                str(output / "handoff.json"),
                "progress-barrier",
            ],
        ) as p:
            until(lambda: (output / f"progress-{p.pid}.json").exists())
            save(output / "before-kill.json", h.identity_of(p.pid))
            p.kill()
            assert p.wait(timeout=2) == -9
        with (
            child(data, "successor", [sys.executable, "-m", "aiddos.runs.worker"]),
            connect(data) as db,
        ):
            until(
                lambda: db.execute("SELECT state='SUCCEEDED' FROM aiddos_runs_v1.jobs").fetchone()[
                    0
                ],
                13,
            )
            row = db.execute(
                "SELECT attempt,generation,deadline_at,event_count FROM aiddos_runs_v1.jobs"
            ).fetchone()
            from aiddos.runs.repository import timestamp

            assert row[:2] == (2, 4) and timestamp(row[2]) == queued["run"]["deadline_at"]
            assert row[3] == 8
        save(output / "result.json", {"attempt": row[0], "generation": row[1]})
        return
    if data["case"] == "compete":
        from contextlib import ExitStack

        seed(data, 3)
        output = Path(data["output"])
        with ExitStack() as stack, connect(data) as db:
            for i in range(2):
                stack.enter_context(
                    child(
                        data,
                        f"worker-{i}",
                        [
                            sys.executable,
                            str(Path(__file__)),
                            "--worker",
                            str(output / "handoff.json"),
                            "barrier",
                        ],
                    )
                )
            until(lambda: len(list(output.glob("entered-*.json"))) == 2)
            before = db.execute(
                "SELECT run_id,attempt,generation,owner_token,lease_until,event_count "
                "FROM aiddos_runs_v1.jobs WHERE state='RUNNING' ORDER BY run_id"
            ).fetchall()
            stack.enter_context(
                child(data, "worker-third", [sys.executable, "-m", "aiddos.runs.worker"])
            )
            try:
                samples = []
                end = time.monotonic() + 2.5
                while time.monotonic() < end:
                    samples.append(
                        db.execute("SELECT leased_count FROM aiddos_runs_v1.quota").fetchone()[0]
                    )
                    time.sleep(0.05)
                after = db.execute(
                    "SELECT run_id,attempt,generation,owner_token,lease_until,event_count "
                    "FROM aiddos_runs_v1.jobs WHERE state='RUNNING' ORDER BY run_id"
                ).fetchall()
                save(
                    output / "leases.json",
                    {
                        "before": [[str(v) for v in x] for x in before],
                        "after": [[str(v) for v in x] for x in after],
                        "samples": samples,
                    },
                )
                assert len(before) == len(after) == 2 and max(samples) == 2
                assert len({x[3] for x in before}) == 2
                assert all(
                    a[:4] == b[:4] and a[4] > b[4] and a[5] == b[5]
                    for a, b in zip(after, before, strict=True)
                ), "HEARTBEAT_NOT_RENEWED"
            finally:
                (output / "release").touch()
            until(
                lambda: (
                    db.execute(
                        "SELECT count(*) FROM aiddos_runs_v1.jobs WHERE state='SUCCEEDED'"
                    ).fetchone()[0]
                    == 3
                )
            )
            assert db.execute(
                "SELECT retained_count,unfinished_count,leased_count FROM aiddos_runs_v1.quota"
            ).fetchone() == (3, 0, 0)
            assert (
                db.execute("SELECT attempt,event_count FROM aiddos_runs_v1.jobs").fetchall()
                == [(1, 5)] * 3
            )
            assert db.execute("SELECT count(*) FROM aiddos_runs_v1.results").fetchone()[0] == 3
        save(output / "result.json", {"max_leased": 2, "terminal_count": 3})
        return
    if data["case"] == "pure":
        seed(data)
        with (
            child(
                data,
                "worker",
                [
                    sys.executable,
                    str(Path(__file__)),
                    "--worker",
                    str(Path(data["output"]) / "handoff.json"),
                    "pure",
                ],
            ),
            connect(data) as db,
        ):
            until(
                lambda: db.execute("SELECT state='SUCCEEDED' FROM aiddos_runs_v1.jobs").fetchone()[
                    0
                ]
            )
            result_raw = db.execute("SELECT result FROM aiddos_runs_v1.results").fetchone()[0]
            result = json.loads(result_raw)
            assert result["evaluation"] == "NOT_EVALUATED"
            assert result["measurements"] is None and result["defense_verdict"] is None
        observation = json.loads((Path(data["output"]) / "pure-calls.json").read_text())
        observation["state"] = "SUCCEEDED"
        save(Path(data["output"]) / "result.json", observation)
        assert all(
            c["thread"] != observation["main_thread"]
            and not c["transaction"]
            and c["driver_status"] == 0
            for c in observation["calls"]
        ), observation
        return
    with child(
        data,
        "worker",
        [
            sys.executable,
            str(Path(__file__)),
            "--worker",
            str(Path(data["output"]) / "handoff.json"),
            data["case"],
        ],
    ) as p:
        assert p.wait(timeout=10) == 0
    result = json.loads((Path(data["output"]) / "result.json").read_text())
    assert max(result["waiter_counts"]) <= 1, result


if __name__ == "__main__":
    if sys.argv[1] == "--worker":
        worker_child(json.loads(Path(sys.argv[2]).read_text()), sys.argv[3])
    else:
        execute(json.loads(Path(sys.argv[1]).read_text()))
