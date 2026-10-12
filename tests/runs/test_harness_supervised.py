"""Adopted supervised I0: product-path witnesses, not primitive prototypes."""

import hashlib
import importlib.util
import json
import socket
import sys
from pathlib import Path

import psycopg
import pytest
from supervised_probe import launch
from supervised_probe import proof as synthetic_proof
from test_harness import ModelDocker

from tools import s02_harness as h


def test_pending_precedes_first_custody_preparation(tmp_path, monkeypatch):
    owner = h.Harness(tmp_path, backend=ModelDocker()).create()
    primary = OSError("PREPARATION_FAILURE")
    observations = []

    def preparation():
        observations.append(getattr(owner, "work_state", None))
        raise primary

    with monkeypatch.context() as patch:
        patch.setattr(owner, "revalidate", preparation)
        with pytest.raises(OSError) as caught:
            owner.probe("read")
    assert caught.value is primary
    assert observations == ["PENDING"]
    with pytest.raises(h.Blocked):
        owner.probe("write")
    owner.close()
    assert owner.state == "CLEAN"


@pytest.mark.parametrize("route", ["module", "class", "socket"])
def test_local_fixture_enrolls_before_native_and_denies_reentry(tmp_path, monkeypatch, route):
    spec = importlib.util.spec_from_file_location(
        "local_fixture", Path(__file__).with_name("conftest.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    owner = h.Harness(tmp_path, backend=ModelDocker()).create()
    owner.ready = True
    observations = []

    def boundary(*args, **kwargs):
        observations.append(getattr(owner, "work_state", None))
        if observations[-1] == "PENDING":
            with pytest.raises(h.Blocked):
                owner.probe("write")
        return None

    with monkeypatch.context() as patch:
        patch.setattr(psycopg, "connect", boundary)
        patch.setattr(socket.socket, "connect", boundary)
        guards = module.no_unowned_execution.__wrapped__(patch)
        guards["endpoints"][str(owner.socket)] = owner
        params = h.connection_parameters(owner.socket)
        if route == "socket":
            with socket.socket(socket.AF_UNIX) as wire:
                wire.connect(str(owner.socket / ".s.PGSQL.5432"))
        elif route == "class":
            psycopg.Connection.connect(**params)
        else:
            psycopg.connect(**params)
    assert observations == ["PENDING"]
    assert owner.work_state == "ELIGIBLE" and owner.attempt is None
    owner.close()


def test_unknown_diagnostic_never_publishes_or_restores_authority(tmp_path, monkeypatch):
    with h.Harness(tmp_path, backend=ModelDocker()) as owner:
        unknown = h.WARNING + b"PRIVATE_REJECTED_SUFFIX_sql_password_nonce\n"
        with (
            monkeypatch.context() as patch,
            launch(patch, owner, {"stderr_hex": unknown.hex()}, tmp_path),
            pytest.raises(h.Blocked),
        ):
            owner.probe("read")
        assert "PRIVATE_REJECTED_SUFFIX" not in owner.journal.read_text()
        assert owner.work_failed and owner.work_state == "REVOKED"
        with pytest.raises(h.Blocked):
            owner.probe("write")
    assert owner.state == "CLEAN"


@pytest.mark.parametrize("change", ["extra", "bool_major", "wrong_value", "long_path"])
def test_proof_invalid_shape_revokes_enrolled_owner(tmp_path, monkeypatch, change):
    output = synthetic_proof()
    if change == "extra":
        output["extra"] = "PRIVATE_REJECTED_PROOF"
    elif change == "bool_major":
        output["server_major"] = True
    elif change == "wrong_value":
        output["value"] = None
    else:
        output["prefix"] = "/" + "x" * 4096
    with h.Harness(tmp_path, backend=ModelDocker()) as owner:
        with (
            monkeypatch.context() as patch,
            launch(patch, owner, {"proof": output}, tmp_path),
            pytest.raises(h.Blocked),
        ):
            owner.probe("read")
        assert owner.work_failed
        assert "PRIVATE_REJECTED_PROOF" not in owner.journal.read_text()
    assert owner.state == "CLEAN"


@pytest.mark.parametrize("granted", [False, True])
def test_context_restoration_failure_retains_process_custody(tmp_path, monkeypatch, granted):
    import os
    import signal

    native = h.subprocess.Popen
    context = h.PROCESS_ARGV
    primary = OSError("POSTSPAWN_CONTEXT_RESET")
    children, fired = [], []
    owner = h.Harness(tmp_path, backend=None if granted else ModelDocker()).create()
    if granted:
        owner.bootstrap()

    class Context:
        def get(self):
            return context.get()

        def set(self, value):
            return context.set(value)

        def reset(self, token):
            current = context.get()
            context.reset(token)
            if not granted or "--pg-child" in current:
                fired.append("reset-after-effect")
                raise primary

    def spawn(*args, **kwargs):
        child = native(*args, **kwargs)
        if not granted or "--pg-child" in args[0]:
            children.append(child)
        return child

    with monkeypatch.context() as patch:
        patch.setattr(h, "PROCESS_ARGV", Context())
        patch.setattr(h.subprocess, "Popen", spawn)
        with pytest.raises(OSError) as caught:
            if granted:
                owner.probe("read")
            else:
                h.run_child(
                    [sys.executable, "-c", "import signal; signal.pause()"],
                    tmp_path,
                    0.01,
                    lambda _: None,
                )
    child = children[0]
    streams = [child.stdout, child.stderr] + ([child.stdin] if granted else [])
    before = {
        "code": child.returncode,
        "closed": [s.closed for s in streams],
        "absent": not Path(f"/proc/{child.pid}").exists(),
        "fired": fired,
        "primary_identity": caught.value is primary,
    }
    save(tmp_path, "context-before-rescue", before)
    try:
        assert before["primary_identity"] and fired == ["reset-after-effect"]
        assert before["code"] is not None and before["absent"] and all(before["closed"])
    finally:
        if child.returncode is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=2)
        for stream in streams:
            if not stream.closed:
                stream.close()
        owner.close()


def test_expired_acquired_real_connection_never_enters_sql(owned_pg, tmp_path, monkeypatch):
    owner = owned_pg
    with (
        monkeypatch.context() as patch,
        launch(
            patch,
            owner,
            {
                "fault": "post-connect-expiry",
                "synthetic": False,
                "class": "real-PG-connect-synthetic-original-D-clock-edge",
            },
            tmp_path,
        ) as (results, children),
        pytest.raises(h.Blocked),
    ):
        owner.probe("read")
    origin = json.loads((tmp_path / "child-origin.json").read_text())
    assert origin["fired"] == ["real-connect-return"]
    assert origin["late_sql_entries"] == 0
    assert results[0].code == 78 and children[0].returncode == 78
    assert owner.work_failed


def test_bootstrap_publication_failure_never_commits_ready(tmp_path, monkeypatch):
    with h.Harness(tmp_path) as owner:
        primary = OSError("READY_PUBLICATION")
        original = owner.note
        fired = []

        def note(event, **data):
            if event == "ready":
                fired.append(owner.work_state)
                raise primary
            return original(event, **data)

        with monkeypatch.context() as patch:
            patch.setattr(owner, "note", note)
            with pytest.raises(OSError) as caught:
                owner.bootstrap()
        assert caught.value is primary and fired == ["PENDING"]
        assert not owner.ready and owner.work_failed
    assert owner.state == "CLEAN"


def save(path, name, data):
    (path / (name + ".json")).write_text(json.dumps(data, indent=2) + "\n")


def test_real_owner_setup_write_raw_negative_read(tmp_path):
    notices = []
    with h.Harness(tmp_path) as owner:
        owner.bootstrap()
        before = owner.probe("write")
        raw = h.run_child(
            [sys.executable, h.__file__, "--pg-child", str(owner.directory), "--action", "read"],
            owner.socket.parent,
            10,
            notices.append,
        )
        save(
            tmp_path,
            "raw-refusal",
            {
                "code": raw.code,
                "stdout": raw.stdout,
                "stderr": raw.stderr,
                "timed_out": raw.timed_out,
                "notices": notices,
                "source": h.__file__,
                "source_sha256": hashlib.sha256(Path(h.__file__).read_bytes()).hexdigest(),
                "interpreter": sys.executable,
                "prefix": sys.prefix,
            },
        )
        assert raw.code == 78 and not raw.stdout and not raw.timed_out
        after = owner.probe("read")
        assert before["value"] == after["value"] == "i0-probe-not-application"
        assert before["connection_cap_enforced"] is True
        assert after["af_unix"] is True
        assert Path(after["interpreter"]).parent == Path(sys.executable).parent
        assert after["prefix"] == sys.prefix
    assert owner.state == "CLEAN"
    assert all(not Path(f"/proc/{row['pid']}").exists() for row in notices)


J = b'{"blocked": "UndefinedTable", "site": [["execute", 1]]}\n'


def framing_cases():
    cases = [
        ("empty", b"", 0, True),
        ("warning", h.WARNING, 0, True),
        ("nonzero-warning", h.WARNING, 78, False),
        ("json", J, 0, False),
        ("warning-json", h.WARNING + J, 78, False),
    ]
    invalid = {
        "wrong-path": h.WARNING.replace(b"/dev/null", b"/dev/zero"),
        "case": h.WARNING.lower(),
        "crlf": h.WARNING[:-1] + b"\r\n",
        "truncated": h.WARNING[:-1],
        "invalid-utf8": h.WARNING + b"\xff\n",
        "unknown": h.WARNING + b"PRIVATE_REJECTED_SUFFIX\n",
        "duplicate": b'{"blocked":"X","blocked":"Y","site":[]}\n',
        "extra": b'{"blocked":"X","site":[],"extra":1}\n',
        "second-json": J + J,
        "warning-after-json": J + h.WARNING,
        "escaped-warning": json.dumps({"blocked": h.WARNING.decode(), "site": []}).encode() + b"\n",
        "float-line": b'{"blocked":"X","site":[["f",1.0]]}\n',
        "bool-line": b'{"blocked":"X","site":[["f",true]]}\n',
        "deep-site": json.dumps({"blocked": "X", "site": [["f", 1]] * 17}).encode() + b"\n",
    }
    cases.extend((name, value, 0, False) for name, value in invalid.items())
    for index in (0, 8, 24, 53, 54):
        value = bytearray(h.WARNING)
        value[index] ^= 1
        cases.append((f"mutation-{index}", bytes(value), 0, False))
    base = h.WARNING + J
    exact = base[:-2] + b" " * (4096 - len(base)) + b"}\n"
    assert len(exact) == 4096
    cases.extend(
        [("valid-4096", exact, 78, False), ("overflow-4097", exact[:-2] + b" }\n", 78, False)]
    )
    return cases


@pytest.mark.parametrize(
    "name,data,code,success", framing_cases(), ids=[c[0] for c in framing_cases()]
)
@pytest.mark.parametrize("fragment", [1, 54, 4096])
def test_real_transport_warning_grammar(tmp_path, monkeypatch, name, data, code, success, fragment):
    import os

    native_read = os.read
    reads = []

    def fragmented_read(fd, size):
        target = children and not children[0].stderr.closed and fd == children[0].stderr.fileno()
        data = native_read(fd, min(size, fragment) if target else size)
        if target:
            reads.append(len(data))
        return data

    with h.Harness(tmp_path, backend=ModelDocker()) as owner:
        with (
            monkeypatch.context() as patch,
            launch(
                patch,
                owner,
                {
                    "stderr_hex": data.hex(),
                    "exit": code,
                    "fragment": fragment,
                },
                tmp_path,
            ) as (results, children),
        ):
            patch.setattr(os, "read", fragmented_read)
            if success:
                assert owner.probe("read")["af_unix"]
            else:
                with pytest.raises(h.Blocked):
                    owner.probe("read")
        representable = name in {
            "empty",
            "warning",
            "nonzero-warning",
            "json",
            "warning-json",
            "valid-4096",
        }
        assert bool(results) is representable
        assert reads and max(reads) <= fragment
        if results:
            assert results[0].stderr.encode() == data
            rows = [json.loads(line) for line in owner.journal.read_text().splitlines()]
            assert [r for r in rows if r["event"] == "pg_child_exit"][-1][
                "diagnostic"
            ].encode() == data
        assert "PRIVATE_REJECTED_SUFFIX" not in owner.journal.read_text()
        assert owner.work_failed is (not success)
        child = children[0]
        assert child.returncode is not None and not Path(f"/proc/{child.pid}").exists()
        assert all(stream.closed for stream in (child.stdin, child.stdout, child.stderr))
        save(
            tmp_path,
            "warning-transport",
            {
                "name": name,
                "bytes": len(data),
                "fragment": fragment,
                "actual_read_lengths": reads,
                "real_result": vars(results[0]) if results else None,
                "actual_exit": child.returncode,
                "revoked": owner.work_failed,
                "reaped_and_pipes_closed_before_rescue": True,
            },
        )
    assert owner.state == "CLEAN"


def test_private_grant_rejects_changed_command_before_spawn(tmp_path, monkeypatch):
    with h.Harness(tmp_path, backend=ModelDocker()) as owner:
        original, native = h.run_child, h.subprocess.Popen
        spawned = []

        def altered(argv, *args, **kwargs):
            if kwargs.get("_grant") is not None:
                argv = [sys.executable, "-c", "pass"]
            return original(argv, *args, **kwargs)

        def spawn(*args, **kwargs):
            spawned.append(True)
            return native(*args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(h, "run_child", altered)
            patch.setattr(h.subprocess, "Popen", spawn)
            with pytest.raises(h.Blocked):
                owner.probe("read")
        assert spawned == []
        assert owner.work_failed


@pytest.mark.parametrize(
    "mutation",
    [
        "empty",
        "short",
        "extra",
        "second",
        "magic",
        "owner_pid",
        "owner_start",
        "boot",
        "child_pid",
        "child_start",
        "source",
        "custody",
        "number",
        "action",
        "deadline",
    ],
)
def test_enrolled_native_grant_mutations_deny_before_pg(tmp_path, monkeypatch, mutation):
    native = h.GRANT
    fired = []
    fields = {
        "magic": 0,
        "owner_pid": 1,
        "owner_start": 2,
        "boot": 3,
        "child_pid": 4,
        "child_start": 5,
        "source": 6,
        "custody": 7,
        "number": 8,
        "action": 10,
        "deadline": 11,
    }

    class Frame:
        size = native.size

        def pack(self, *args):
            values = list(args)
            fired.append(mutation)
            if mutation in fields:
                index = fields[mutation]
                value = values[index]
                values[index] = bytes(len(value)) if isinstance(value, bytes) else value + 1
            data = native.pack(*values)
            if mutation == "empty":
                return b""
            if mutation == "short":
                return data[:-1]
            if mutation == "extra":
                return data + b" "
            if mutation == "second":
                return data + data
            return data

    with h.Harness(tmp_path, backend=ModelDocker()) as owner:
        with (
            monkeypatch.context() as patch,
            launch(patch, owner, {}, tmp_path) as (results, children),
        ):
            patch.setattr(h, "GRANT", Frame())
            with pytest.raises(h.Blocked):
                owner.probe("read")
        origin = json.loads((tmp_path / "child-origin.json").read_text())
        assert "synthetic-proof" not in origin["fired"]
        assert fired == [mutation]
        assert results[0].code == 78 and not results[0].stdout
        assert owner.work_failed and children[0].returncode == 78
        with pytest.raises(h.Blocked):
            owner.probe("write")
        save(
            tmp_path,
            "grant-denial",
            {
                "fault": mutation,
                "child_origin": origin,
                "actual_result": vars(results[0]),
                "control": owner.attempt.packed().hex(),
                "fired": fired,
                "cleanup_eligible": not owner.disposal_unconfirmed,
            },
        )
    assert owner.state == "CLEAN"


def test_original_ten_second_deadline_kills_verified_grant(
    owned_pg, no_unowned_execution, tmp_path, monkeypatch
):
    owner = owned_pg
    owner.probe("write")
    assert owner.probe("read")["value"] == "i0-probe-not-application"
    with (
        monkeypatch.context() as patch,
        launch(
            patch,
            owner,
            {
                "fault": "post-grant-barrier",
                "synthetic": False,
                "class": "actual-PG-owner-native-post-grant-timeout",
            },
            tmp_path,
        ) as (results, children),
        pytest.raises(h.Blocked, match="PG_PROBE_FAILED"),
    ):
        owner.probe("read")
    barrier = json.loads((tmp_path / "barrier.json").read_text())
    assert barrier["fired"] == ["verified-grant-before-PG"]
    assert barrier["barrier_ns"] < barrier["original_deadline"] == owner.attempt.deadline
    assert results[0].timed_out and results[0].code == -9
    child = children[0]
    assert child.returncode == -9 and not Path(f"/proc/{child.pid}").exists()
    assert all(stream.closed for stream in (child.stdin, child.stdout, child.stderr))
    owner.revalidate()
    with pytest.raises(h.Blocked):
        owner.probe("write")
    with pytest.raises(AssertionError):
        no_unowned_execution["validate"]("", h.connection_parameters(owner.socket))
    save(
        tmp_path,
        "timeout-before-rescue",
        {
            "barrier": barrier,
            "result": vars(results[0]),
            "code": child.returncode,
            "pipes_closed": True,
            "rescue_used": False,
        },
    )


def test_preparation_original_short_deadline_never_spawns(owned_pg, monkeypatch, tmp_path):
    owner = owned_pg
    native = h.subprocess.Popen
    spawned = []

    def spawn(argv, *args, **kwargs):
        if "--pg-child" in argv:
            spawned.append(argv)
        return native(argv, *args, **kwargs)

    before = owner.journal.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(h.subprocess, "Popen", spawn)
        with pytest.raises(h.Blocked, match="PG_PROBE_FAILED"):
            owner.probe("read", timeout=0.001)
    assert spawned == [] and owner.work_failed
    tail = owner.journal.read_bytes()[len(before) :]
    assert b'"event": "pg_child_exit"' not in tail
    assert owner.attempt.pid == 0 and owner.attempt.exit_known == 0
    save(tmp_path, "early-deadline", {"spawn_count": len(spawned), "no_fabricated_exit": True})


@pytest.mark.parametrize("fault", ["consume-twice", "replay"])
def test_consumed_grant_and_replay_are_terminal(tmp_path, monkeypatch, fault):
    with h.Harness(tmp_path, backend=ModelDocker()) as owner:
        if fault == "consume-twice":
            with (
                monkeypatch.context() as patch,
                launch(patch, owner, {"fault": fault}, tmp_path),
                pytest.raises(h.Blocked),
            ):
                owner.probe("read")
            origin = json.loads((tmp_path / "child-origin.json").read_text())
            assert origin["fired"] == ["synthetic-proof", "consume-twice"]
        else:
            native = h.GRANT
            previous = []

            class Frame:
                size = native.size

                def pack(self, *args):
                    if not previous:
                        previous.append(native.pack(*args))
                    return previous[0]

            for index in range(2):
                directory = tmp_path / str(index)
                directory.mkdir()
                with monkeypatch.context() as patch, launch(patch, owner, {}, directory):
                    patch.setattr(h, "GRANT", Frame())
                    if index == 0:
                        assert owner.probe("read")["af_unix"]
                        assert owner.attempt is None
                    else:
                        with pytest.raises(h.Blocked):
                            owner.probe("read")
        assert owner.work_failed
        with pytest.raises(h.Blocked):
            owner.probe("write")


@pytest.mark.parametrize(
    "phase",
    [
        "clock",
        "record",
        "argv",
        "env",
        "source",
        "spawn",
        "wrapper",
        "identity",
        "observer",
        "grant",
        "write",
        "read",
        "stdin-close",
        "postexit-close",
        "decode",
        "pg_child_exit",
        "pg_proof",
        "final-tail",
    ],
)
def test_enrolled_fault_preserves_primary_and_disposal(tmp_path, monkeypatch, phase):
    import os

    primary = OSError("PRIMARY_" + phase)
    fired = []
    with h.Harness(tmp_path, backend=ModelDocker()) as owner:

        def fail(*args, **kwargs):
            fired.append(owner.work_state)
            raise primary

        with (
            monkeypatch.context() as patch,
            launch(patch, owner, {"stderr_hex": h.WARNING.hex()}, tmp_path) as (results, children),
        ):
            if phase in {"clock", "record", "env", "source", "decode"}:
                obj, name = {
                    "clock": (h.time, "monotonic_ns"),
                    "record": (h, "Attempt"),
                    "env": (h, "child_environment"),
                    "source": (h, "source_digest"),
                    "decode": (h, "decode_proof"),
                }[phase]
                patch.setattr(obj, name, fail)
            elif phase == "argv":
                original = Path.resolve

                def resolve(path, *args, **kwargs):
                    if str(path) == h.__file__:
                        fail()
                    return original(path, *args, **kwargs)

                patch.setattr(Path, "resolve", resolve)
            elif phase == "spawn":
                patch.setattr(h.subprocess, "Popen", fail)
            elif phase == "wrapper":
                patch.setattr(h, "CapturedPipe", fail)
            elif phase == "identity":
                original = h.identity_of

                def identity(pid):
                    if children and pid == children[0].pid:
                        fail()
                    return original(pid)

                patch.setattr(h, "identity_of", identity)
            elif phase in {"observer", "pg_child_exit", "pg_proof"}:
                original = owner.note

                def note(event, **data):
                    if event == ("child_started" if phase == "observer" else phase):
                        fail()
                    return original(event, **data)

                patch.setattr(owner, "note", note)
            elif phase == "grant":

                class Frame:
                    size = h.GRANT.size
                    pack = staticmethod(fail)

                patch.setattr(h, "GRANT", Frame())
            elif phase in {"read", "write"}:
                original = getattr(os, phase)

                def io(fd, *args):
                    if children:
                        stream = children[0].stdin if phase == "write" else children[0].stdout
                        if not stream.closed and fd == stream.fileno() and not fired:
                            if phase == "write":
                                original(fd, *args)  # GO may already have effects.
                            fail()
                    return original(fd, *args)

                patch.setattr(os, phase, io)
            elif phase in {"stdin-close", "postexit-close"}:
                original = h.CapturedPipe.close

                def close(stream):
                    target = children[0].stdin if phase == "stdin-close" else children[0].stdout
                    original(stream)
                    if stream is target and not fired:
                        fail()

                patch.setattr(h.CapturedPipe, "close", close)
            else:
                patch.setattr(owner, "_settle", fail)
            with pytest.raises(OSError) as caught:
                owner.probe("read")
        assert caught.value is primary and fired == ["PENDING"]
        assert owner.work_failed and owner.work_state == "REVOKED"
        states = []
        for child in children:
            states.append(
                {
                    "pid": child.pid,
                    "code": child.returncode,
                    "absent": not Path(f"/proc/{child.pid}").exists(),
                    "closed": [
                        stream.closed for stream in (child.stdin, child.stdout, child.stderr)
                    ],
                }
            )
            assert (
                child.returncode is not None and states[-1]["absent"] and all(states[-1]["closed"])
            )
        with pytest.raises(h.Blocked):
            owner.probe("write")
        save(
            tmp_path,
            "fault-before-rescue",
            {
                "phase": phase,
                "fired": fired,
                "primary_identity": caught.value is primary,
                "type": type(caught.value).__name__,
                "message": str(caught.value),
                "children": states,
                "rescue_used": False,
            },
        )
    assert owner.state == "CLEAN"


def test_last_fallible_tail_cannot_refresh_original_deadline(tmp_path, monkeypatch):
    import os
    import select
    import time

    with h.Harness(tmp_path, backend=ModelDocker()) as owner:
        control = tmp_path / "control"
        control.mkdir()
        with monkeypatch.context() as patch, launch(patch, owner, {}, control):
            assert owner.probe("read")["af_unix"]
        original = owner._settle
        fired = []
        read_fd, write_fd = os.pipe()

        def late():
            original()
            deadline = owner.attempt.deadline
            entered = time.monotonic_ns()
            assert entered < deadline
            fired.append({"entered": entered, "original_deadline": deadline})
            select.select([read_fd], [], [], (deadline - entered) / 1e9 + 0.01)

        try:
            with monkeypatch.context() as patch, launch(patch, owner, {}, tmp_path):
                patch.setattr(owner, "_settle", late)
                with pytest.raises(h.Blocked):
                    owner.probe("read")
            assert owner.work_failed and len(fired) == 1
            save(tmp_path, "late-final-tail", {"fired": fired, "revoked": owner.work_failed})
        finally:
            os.close(read_fd)
            os.close(write_fd)


@pytest.mark.parametrize("fault", ["deep-error", "long-error-name"])
def test_child_unrepresentable_diagnostic_fails_without_truncation(tmp_path, monkeypatch, fault):
    with h.Harness(tmp_path, backend=ModelDocker()) as owner:
        with (
            monkeypatch.context() as patch,
            launch(patch, owner, {"fault": fault}, tmp_path) as (results, children),
            pytest.raises(h.Blocked),
        ):
            owner.probe("read")
        origin = json.loads((tmp_path / "child-origin.json").read_text())
        assert origin["fired"] == [fault] and origin["exit"] == 78
        assert results and results[0].code == 78
        assert results[0].stderr == "" and results[0].stdout == ""
        assert "PRIVATE_DRIVER_TEXT" not in owner.journal.read_text()
        assert owner.work_failed and children[0].returncode == 78
    assert owner.state == "CLEAN"


@pytest.mark.parametrize("state", ["pending", "revoked", "closed", "custody-loss"])
@pytest.mark.parametrize("route", ["module", "class", "socket"])
def test_fixture_registered_endpoint_terminal_matrix(tmp_path, monkeypatch, state, route):
    spec = importlib.util.spec_from_file_location(
        "matrix_fixture", Path(__file__).with_name("conftest.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    entries = []
    with monkeypatch.context() as patch:
        patch.setattr(psycopg, "connect", lambda *a, **k: entries.append("driver"))
        patch.setattr(socket.socket, "connect", lambda *a: entries.append("socket"))
        guards = module.no_unowned_execution.__wrapped__(patch)
        owner = h.Harness(tmp_path, backend=ModelDocker()).create()
        owner.ready = True
        guards["endpoints"][str(owner.socket)] = owner
        params = h.connection_parameters(owner.socket)

        def invoke():
            if route == "socket":
                with socket.socket(socket.AF_UNIX) as wire:
                    wire.connect(str(owner.socket / ".s.PGSQL.5432"))
            elif route == "class":
                psycopg.Connection.connect(**params)
            else:
                psycopg.connect(**params)

        invoke()
        assert len(entries) == 1
        if state == "pending":
            original = owner._check_custody

            def pending():
                with pytest.raises(AssertionError):
                    invoke()
                return original()

            patch.setattr(owner, "_check_custody", pending)
            owner._admit_connection(5, lambda: None)
        else:
            if state == "closed":
                owner.close()
            elif state == "revoked":
                with pytest.raises(h.Blocked):
                    owner.probe("unsupported")
            else:
                owner.backend.metadata["Labels"] = {}
            with pytest.raises(AssertionError):
                invoke()
        assert len(entries) == 1 and str(owner.socket) in guards["endpoints"]
        if state == "custody-loss":
            assert owner.state == "BLOCKED"
            with pytest.raises(h.Blocked):
                owner.close()
        else:
            owner.close()
            assert owner.state == "CLEAN"
        save(
            tmp_path,
            "fixture-matrix",
            {
                "state": state,
                "route": route,
                "positive": 1,
                "negative_entries": len(entries) - 1,
                "endpoint_registered": True,
                "custody": owner.state,
            },
        )


def test_real_warning_result_journal_roundtrip_restart(tmp_path, monkeypatch):
    results = []
    original = h.run_child

    def run(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get("_grant") is not None:
            results.append(result)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(h, "run_child", run)
        with h.Harness(tmp_path) as owner:
            owner.bootstrap()
            before = owner.probe("write")
            volume = dict(owner.volume)
            owner.restart()
            after = owner.probe("read")
            assert before["value"] == after["value"] == "i0-probe-not-application"
            assert volume == owner.volume and len(results) == 3
            events = [json.loads(line) for line in owner.journal.read_text().splitlines()]
            exits = [row for row in events if row["event"] == "pg_child_exit"]
            for result, event in zip(results, exits, strict=True):
                raw = result.stderr.encode()
                assert result.code == 0 and not result.timed_out
                assert raw and len(raw) <= 4096 and not h.diagnostic(raw)
                assert event["diagnostic"].encode() == raw
            save(
                tmp_path,
                "native-warning-results",
                {
                    "results": [vars(r) for r in results],
                    "journal": str(owner.journal),
                    "volume_before": volume,
                    "volume_after": owner.volume,
                    "libpq_version": psycopg.pq.version(),
                    "libpq_implementation": psycopg.pq.__impl__,
                },
            )
    assert owner.state == "CLEAN"


@pytest.mark.parametrize(
    "token", ["0", "01", "+1", "-1", "18446744073709551616", "1.0", "", "1" * 21]
)
def test_raw_noncanonical_binding_refuses_without_owner_revocation(tmp_path, token):
    with h.Harness(tmp_path, backend=ModelDocker()) as owner:
        result = h.run_child(
            [
                sys.executable,
                h.__file__,
                "--pg-child",
                str(owner.directory),
                "--action",
                "read",
                "--i0-attempt=" + token,
                "--i0-deadline-ns=1",
            ],
            owner.socket.parent,
            2,
            lambda _: None,
        )
        assert result.code == 78 and not result.stdout and not result.timed_out
        owner.check_work()
        with pytest.raises(h.Blocked):
            h.borrowed_socket(owner.directory)
        owner.check_work()


def test_granted_stdin_must_close_by_original_deadline(tmp_path, monkeypatch):
    import os
    import select
    import time

    with h.Harness(tmp_path, backend=ModelDocker()) as owner:
        original = h.granted_transport
        fired = []

        def held(process, frame, attempt):
            assert owner.work_state == "PENDING"
            os.write(process.stdin.fileno(), frame)
            entered = time.monotonic_ns()
            assert entered < attempt.deadline
            fired.append(entered)
            # The real child waits for EOF and refuses at the original deadline.
            assert select.select(
                [process.stderr.fileno()], [], [], h.remaining_ns(attempt.deadline) + 2
            )[0]
            process.wait(timeout=2)
            assert process.returncode == 78
            return original(process, frame, attempt)

        with monkeypatch.context() as patch, launch(patch, owner, {}, tmp_path) as (_, children):
            patch.setattr(h, "granted_transport", held)
            with pytest.raises(h.Blocked):
                owner.probe("read")
        origin = json.loads((tmp_path / "child-origin.json").read_text())
        assert fired and not origin["fired"] and owner.work_failed
        assert children[0].returncode == 78
        assert all(s.closed for s in (children[0].stdin, children[0].stdout, children[0].stderr))


def test_raw_regular_stdin_is_not_authority(tmp_path, monkeypatch):
    native = h.subprocess.Popen
    with h.Harness(tmp_path, backend=ModelDocker()) as owner:
        frame = tmp_path / "not-a-grant"
        frame.write_bytes(bytes(161))
        with frame.open("rb") as stream:

            def spawn(*args, **kwargs):
                kwargs["stdin"] = stream
                return native(*args, **kwargs)

            with monkeypatch.context() as patch:
                patch.setattr(h.subprocess, "Popen", spawn)
                result = h.run_child(
                    [
                        sys.executable,
                        h.__file__,
                        "--pg-child",
                        str(owner.directory),
                        "--action",
                        "read",
                        "--i0-attempt=1",
                        "--i0-deadline-ns=18446744073709551615",
                    ],
                    owner.socket.parent,
                    2,
                    lambda _: None,
                )
        assert result.code == 78 and not result.stdout
        owner.check_work()


@pytest.mark.parametrize(
    "boundary", ["acquire", "validation", "go", "result", "proof-journal", "finalizer"]
)
def test_original_deadline_is_checked_after_fallible_boundaries(
    tmp_path, monkeypatch, boundary, request
):
    import os
    import select
    import time

    read_fd, write_fd = os.pipe()
    request.addfinalizer(lambda: os.close(read_fd))
    request.addfinalizer(lambda: os.close(write_fd))

    with h.Harness(tmp_path, backend=ModelDocker()) as owner:
        control = tmp_path / "control"
        control.mkdir()
        with monkeypatch.context() as patch, launch(patch, owner, {}, control):
            assert owner.probe("read")["af_unix"]
        fired = []
        barriers = []

        def expire():
            assert owner.work_state == "PENDING" and time.monotonic_ns() < owner.attempt.deadline
            fired.append(boundary)
            entered = time.monotonic_ns()
            barriers.append({"entered": entered, "original_deadline": owner.attempt.deadline})
            select.select([read_fd], [], [], (owner.attempt.deadline - entered) / 1e9 + 0.01)
            assert time.monotonic_ns() >= owner.attempt.deadline

        with monkeypatch.context() as patch, launch(patch, owner, {}, tmp_path) as (_, children):
            if boundary == "validation":
                original = owner.revalidate

                def validate():
                    original()
                    expire()

                patch.setattr(owner, "revalidate", validate)
            elif boundary == "acquire":
                original = h.identity_of

                def identity(pid):
                    result = original(pid)
                    if children and pid == children[0].pid:
                        expire()
                    return result

                patch.setattr(h, "identity_of", identity)
            elif boundary == "go":
                original = os.write

                def write(fd, data):
                    result = original(fd, data)
                    if children and fd == children[0].stdin.fileno():
                        expire()
                    return result

                patch.setattr(os, "write", write)
            elif boundary == "result":
                original = h.Result

                def result(*args, **kwargs):
                    value = original(*args, **kwargs)
                    expire()
                    return value

                # ModelDocker also constructs Results; arm only the PG return.
                def observe(event, **data):
                    original_note(event, **data)
                    if event == "child_reaped":
                        patch.setattr(h, "Result", result)

                original_note = owner.note
                patch.setattr(owner, "note", observe)
            elif boundary == "proof-journal":
                original = owner.note

                def note(event, **data):
                    original(event, **data)
                    if event == "pg_proof":
                        expire()

                patch.setattr(owner, "note", note)
            else:
                original = h.CapturedPipe.close

                def close(stream):
                    original(stream)
                    if children and stream is children[0].stdout:
                        expire()

                patch.setattr(h.CapturedPipe, "close", close)
            with pytest.raises(h.Blocked):
                owner.probe("read")
        assert fired == [boundary] and owner.work_failed
        for child in children:
            assert child.returncode is not None and not Path(f"/proc/{child.pid}").exists()
            assert all(s.closed for s in (child.stdin, child.stdout, child.stderr))
        save(
            tmp_path,
            "original-D-boundary",
            {
                "fired": fired,
                "clock": "actual-monotonic-original-D-barrier",
                "barriers": barriers,
                "revoked": owner.work_failed,
                "before_rescue_disposed": True,
            },
        )


@pytest.mark.parametrize("phase", ["before-GO", "after-GO"])
def test_original_parent_death_denies_next_child_checkpoint(tmp_path, phase):
    import tempfile

    helper = Path(__file__).with_name("supervised_probe.py")
    result = h.run_child(
        [sys.executable, str(helper), "--parent-death-supervisor", str(tmp_path), phase],
        Path(tempfile.gettempdir()),
        10,
        lambda _: None,
    )
    save(tmp_path, "death-supervisor-result", vars(result))
    assert result.code == 0 and not result.timed_out, result.stderr
    row = json.loads((tmp_path / "parent-death.json").read_text())
    assert row["child_exit"] == 78 and row["parent_absent"] and row["child_absent"]
    assert row["rollback_claim"] is False


@pytest.mark.parametrize("length", [81920, 81921])
def test_stdout_transport_exact_and_overflow_before_append(tmp_path, monkeypatch, length):
    import os

    requests, retained = [], []
    with h.Harness(tmp_path, backend=ModelDocker()) as owner:
        original = os.read

        def read(fd, size):
            if children and not children[0].stdout.closed and fd == children[0].stdout.fileno():
                requests.append(size)
                assert 1 <= size <= 4096
            return original(fd, size)

        def trace(frame, event, arg):
            if frame.f_code is h.granted_transport.__code__ and event == "line":
                buffers = frame.f_locals.get("buffers")
                if buffers:
                    retained.append([len(b) for b in buffers])
            return trace

        with (
            monkeypatch.context() as patch,
            launch(patch, owner, {"stdout_size": length}, tmp_path) as (_, children),
        ):
            patch.setattr(os, "read", read)
            previous = sys.gettrace()
            sys.settrace(trace)
            try:
                with pytest.raises(h.Blocked):
                    owner.probe("read")
            finally:
                sys.settrace(previous)
        assert requests and retained
        assert max(row[0] for row in retained) <= 81920
        assert max(sum(row) for row in retained) <= 86016
        assert 1 in requests
        assert owner.work_failed
        save(
            tmp_path,
            "output-bound",
            {
                "emitted": length,
                "read_requests": requests,
                "max_stdout": max(row[0] for row in retained),
                "max_aggregate": max(map(sum, retained)),
                "child_exit": children[0].returncode,
                "no_rescue": True,
            },
        )


@pytest.mark.parametrize("overflow", [False, True])
def test_proof_path_preallocation_boundary(tmp_path, monkeypatch, overflow):
    output = synthetic_proof()
    for key in ("module", "prefix", "interpreter"):
        output[key] = "/" + "\x01" * (4095 + int(overflow))
    output["driver"] = "v" * 256
    with h.Harness(tmp_path, backend=ModelDocker()) as owner:
        with monkeypatch.context() as patch, launch(patch, owner, {"proof": output}, tmp_path):
            if overflow:
                with pytest.raises(h.Blocked):
                    owner.probe("read")
            else:
                assert owner.probe("read") == output
        assert owner.work_failed is overflow
    if overflow:
        calls = []
        with monkeypatch.context() as patch:
            patch.setattr(h.json, "dumps", lambda *_a, **_k: calls.append(True))
            with pytest.raises(h.Blocked):
                h.encode_proof({"proof": output, "grant_sha256": "0" * 64}, "read")
        assert calls == []


def test_distinct_supervised_successes_release_live_process_slot(tmp_path, monkeypatch):
    import gc
    import weakref

    references, digests = [], []
    with h.Harness(tmp_path, backend=ModelDocker()) as owner:
        initial = owner.journal.read_bytes()
        for index in range(3):
            directory = tmp_path / str(index)
            directory.mkdir()
            with (
                monkeypatch.context() as patch,
                launch(patch, owner, {}, directory) as (results, children),
            ):
                assert owner.probe("read")["af_unix"]
            references.extend(weakref.ref(child) for child in children)
            envelope = json.loads(results[0].stdout)
            digests.append(envelope["grant_sha256"])
            children.clear()
            gc.collect()
            assert all(ref() is None for ref in references)
            assert owner.attempt is None and owner.sequence == index + 1
        assert len(set(digests)) == 3 and owner.journal.read_bytes().startswith(initial)
        owner.sequence = h.UINT64
        with pytest.raises(h.Blocked, match="ATTEMPT_SEQUENCE_EXHAUSTED"):
            owner.probe("read")
        assert owner.work_failed
        save(
            tmp_path,
            "slot-retention",
            {
                "distinct_digests": digests,
                "process_weakrefs_dead": True,
                "control_bytes": h.CONTROL.size,
                "grant_bytes": h.GRANT.size,
                "input_limit": 162,
                "sequence_overflow_refused": True,
                "old_journal_prefix_preserved": True,
            },
        )


def test_granted_wait_refusal_is_unconfirmed_and_forbids_cleanup(tmp_path, monkeypatch):
    primary = OSError("OBSERVER_PRIMARY")
    fired = []
    owner = h.Harness(tmp_path, backend=ModelDocker()).create()
    with monkeypatch.context() as patch, launch(patch, owner, {}, tmp_path) as (_, children):
        original = owner.note

        def note(event, **data):
            if event == "child_started":
                child = children[0]
                waits.append(child.wait)

                def refuse(*_a, **_k):
                    fired.append("wait-refused")
                    raise OSError("WAIT_REFUSAL")

                child.wait = refuse
                raise primary
            original(event, **data)

        waits = []
        patch.setattr(owner, "note", note)
        with pytest.raises(OSError) as caught:
            owner.probe("read")
    child = children[0]
    before = {
        "primary_identity": caught.value is primary,
        "fired": fired,
        "returncode": child.returncode,
        "disposal_unconfirmed": owner.disposal_unconfirmed,
        "pipes_closed": [s.closed for s in (child.stdin, child.stdout, child.stderr)],
    }
    save(tmp_path, "granted-before-rescue", before)
    try:
        assert caught.value is primary and fired == ["wait-refused"]
        assert child.returncode is None and owner.disposal_unconfirmed
        assert all(before["pipes_closed"])
        cut = len(owner.backend.calls)
        with pytest.raises(h.Blocked, match="CHILD_DISPOSAL_UNCONFIRMED"):
            owner.close()
        assert len(owner.backend.calls) == cut and owner.state != "CLEAN"
    finally:
        child.wait = waits[0]
        child.wait(timeout=2)
        save(
            tmp_path,
            "granted-after-rescue",
            {
                "code": child.returncode,
                "pid_absent": not Path(f"/proc/{child.pid}").exists(),
                "model_only_resources": True,
                "product_still_unconfirmed": owner.disposal_unconfirmed,
            },
        )


@pytest.mark.parametrize(
    "phase,code", [("source", 1), ("spawn", 2), ("grant", 4), ("publication", 9), ("proof", 8)]
)
def test_control_retains_first_failure_classification(tmp_path, monkeypatch, phase, code):
    primary = OSError("FIRST_" + phase)
    fired = []
    with h.Harness(tmp_path, backend=ModelDocker()) as owner:

        def fail(*_a, **_k):
            fired.append(phase)
            raise primary

        with monkeypatch.context() as patch, launch(patch, owner, {}, tmp_path):
            if phase == "source":
                patch.setattr(h, "source_digest", fail)
            elif phase == "spawn":
                patch.setattr(h.subprocess, "Popen", fail)
            elif phase == "grant":

                class Frame:
                    size = h.GRANT.size
                    pack = staticmethod(fail)

                patch.setattr(h, "GRANT", Frame())
            elif phase == "proof":
                patch.setattr(h, "decode_proof", fail)
            else:
                original = owner._append_note

                def append(event, **data):
                    if event == "pg_proof":
                        fail()
                    original(event, **data)

                patch.setattr(owner, "_append_note", append)
            with pytest.raises(OSError) as caught:
                owner.probe("read")
        assert caught.value is primary and fired == [phase]
        assert owner.attempt.failure == code and len(owner.attempt.packed()) == 87
        owner.revoke_work()
        assert owner.attempt.failure == code


def test_preserved_native_warning_bytes_use_product_parser_only(tmp_path):
    path = (
        Path(__file__).resolve().parents[2]
        / "inputs/stopped-author/implementation-evidence/diagnostic-boundary.json"
    )
    archived = json.loads(path.read_text())
    assert archived["raw_authority_RED"] == {
        "expected": 78,
        "actual": 0,
        "assertion": "test_harness_supervised.py:33",
    }
    for row in archived["rows"]:
        raw = row["stderr"].encode()
        assert len(raw) == row["stderr_bytes"] and h.diagnostic(raw) is False
    save(
        tmp_path,
        "saved-warning-replay",
        {
            "source": str(path),
            "classification": "saved-native-bytes-through-current-product-parser-not-new-SQL",
            "raw_authority_defect_still_historical_RED": True,
        },
    )


def test_generic_child_stderr_does_not_use_granted_grammar(tmp_path):
    result = h.run_child(
        [sys.executable, "-c", "import sys;sys.stderr.write('generic unstructured diagnostic\\n')"],
        tmp_path,
        2,
        lambda _: None,
    )
    assert result.code == 0 and result.stderr == "generic unstructured diagnostic\n"


@pytest.mark.parametrize("binding", ["identity", "source"])
def test_local_admission_checks_original_owner_binding_before_connector(
    tmp_path, monkeypatch, binding
):
    entered = []
    with h.Harness(tmp_path, backend=ModelDocker()) as owner:
        owner.ready = True
        with monkeypatch.context() as patch:
            if binding == "identity":
                original = h.identity_of
                patch.setattr(h, "identity_of", lambda pid: {**original(pid), "start_ticks": "0"})
            else:
                patch.setattr(h, "source_digest", lambda: "0" * 64)
            with pytest.raises(h.Blocked):
                owner._admit_connection(5, lambda: entered.append(True))
        assert not entered and owner.work_failed


@pytest.mark.parametrize("fault,kind", [("grant-read", "OSError"), ("encode", "MemoryError")])
def test_child_input_and_encoding_faults_revoke_without_private_text(
    tmp_path, monkeypatch, fault, kind
):
    with h.Harness(tmp_path, backend=ModelDocker()) as owner:
        with (
            monkeypatch.context() as patch,
            launch(patch, owner, {"fault": fault}, tmp_path) as (results, children),
            pytest.raises(h.Blocked),
        ):
            owner.probe("read")
        origin = json.loads((tmp_path / "child-origin.json").read_text())
        assert fault in origin["fired"] and origin["exit"] == 78
        assert results[0].code == 78 and not results[0].stdout
        assert json.loads(results[0].stderr)["blocked"] == kind
        assert "PRIVATE_" not in results[0].stderr and "PRIVATE_" not in owner.journal.read_text()
        assert owner.work_failed and children[0].returncode == 78


def test_native_pipe_preparation_failure_is_enrolled(tmp_path, monkeypatch):
    import os

    primary = OSError("PIPE_PREPARATION")
    with h.Harness(tmp_path, backend=ModelDocker()) as owner:
        entered = []

        def pipe():
            entered.append(owner.work_state)
            raise primary

        with monkeypatch.context() as patch:
            patch.setattr(os, "pipe", pipe)
            with pytest.raises(OSError) as caught:
                owner.probe("read")
        assert caught.value is primary and entered == ["PENDING"]
        assert owner.work_failed and owner.attempt.pid == 0
        assert owner.attempt.exit_known == 0 and owner.attempt.failure == 2
