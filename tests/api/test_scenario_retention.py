"""Actual ScenarioStore/API retention and fresh-process admission regressions."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from scenario_producer import definition, register_targets
from test_scenarios import assert_error, registry_path

from aiddos.api.app import create_app

REAL_POPEN = subprocess.Popen


def paths(state_path):
    registry = registry_path(state_path)
    return (
        registry,
        registry.with_name(registry.name + ".s01-recovery"),
        registry.with_name(registry.name + ".s01-pending"),
    )


def read_frame(path):
    raw = path.read_bytes()
    assert len(raw) == 4096 and raw[:8] == b"S01RR001"
    assert hashlib.sha256(raw[:4064]).digest() == raw[4064:]
    length = int.from_bytes(raw[8:12], "big")
    assert length <= 4052 and raw[12 + length : 4064] == bytes(4052 - length)
    return json.loads(raw[12 : 12 + length])


def test_failed_publication_retains_one_candidate_and_fences_all_peers(
    client, state_path, monkeypatch
):
    value = definition(register_targets(client))
    first = client.post("/api/v1/scenarios", json={"revision": 0, "definition": value})
    assert first.status_code == 201
    registry, receipt, pending = paths(state_path)
    before, draft = registry.read_bytes(), state_path.read_bytes()
    fired = []

    def fail(source, destination):
        fired.append((str(source), str(destination)))
        raise OSError("publish refused")

    with monkeypatch.context() as fault:
        fault.setattr(os, "replace", fail)
        response = client.post("/api/v1/scenarios", json={"revision": 1, "definition": value})
    assert len(fired) == 1
    assert_error(response, 503, "SCENARIO_STATE_UNAVAILABLE")
    assert {p.name for p in pending.iterdir()} == {"candidate", "publish"}
    assert (pending / "candidate").stat().st_ino == (pending / "publish").stat().st_ino
    frame = read_frame(receipt)
    assert frame["phase"] == "PREPARED"
    assert frame["post"] == hashlib.sha256((pending / "candidate").read_bytes()).hexdigest()
    snapshot = {
        p: p.read_bytes() for p in (registry, receipt, pending / "candidate", pending / "publish")
    }
    with TestClient(create_app(state_path=state_path), base_url="http://localhost") as peer:
        for connection in (client, peer, client):
            assert connection.get("/api/v1/scenarios").status_code == 200
            # Quarantine is before CAS, even for the stale revision.
            assert_error(
                connection.post("/api/v1/scenarios", json={"revision": 0, "definition": value}),
                503,
                "SCENARIO_STATE_UNAVAILABLE",
            )
    assert all(p.read_bytes() == raw for p, raw in snapshot.items())
    assert registry.read_bytes() == before and state_path.read_bytes() == draft
    assert Path(fired[0][0]) == pending / "publish"


def test_registry_close_enoent_is_not_a_missing_registry(client, state_path, monkeypatch):
    from test_scenario_storage import saved

    saved(client, state_path)
    registry, _, _ = paths(state_path)
    real_open, real_close = os.open, os.close
    owned, fired = set(), []

    def opened(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        if path == registry:
            owned.add(fd)
        return fd

    def close(fd):
        real_close(fd)
        if fd in owned:
            owned.remove(fd)
            fired.append(fd)
            raise FileNotFoundError("synthetic close failure, not absent file")

    with monkeypatch.context() as fault:
        fault.setattr(os, "open", opened)
        fault.setattr(os, "close", close)
        response = client.get("/api/v1/scenarios")
    assert len(fired) == 1 and not owned
    assert_error(response, 503, "SCENARIO_STATE_UNAVAILABLE")


class IOFault:
    """One fired fault at an actual syscall/stream operation, with real close."""

    def __init__(self, monkeypatch, registry, role, operation):
        from aiddos.api import scenario_persistence as io

        self.role, self.operation = role, operation
        self.fired = []
        self.primary = OSError("primary synthetic " + role + "/" + operation)
        self.fds, self.closed = {}, []
        self.stage = None
        self.published, self.retired = False, False
        receipt = registry.with_name(registry.name + ".s01-recovery")
        pending = registry.with_name(registry.name + ".s01-pending")
        original_open, original_close = os.open, os.close
        original_fstat, original_fsync = os.fstat, os.fsync
        original_fdopen, original_pwrite = os.fdopen, os.pwrite
        original_link, original_replace, original_unlink = os.link, os.replace, Path.unlink
        original_frame, original_sync = io.write_frame, io.sync_directory
        owner = self

        def opened(path, flags, *args, **kwargs):
            name = Path(path).name
            selected = self.stage
            if selected is None:
                selected = (
                    "candidate"
                    if name == "candidate" and flags & os.O_CREAT
                    else "archive-" + name
                    if name in {"receipt.bin", "decision.json"} and flags & os.O_CREAT
                    else "read-registry"
                    if path == registry
                    else "read-receipt"
                    if path == receipt
                    else "archived-payload"
                    if Path(path).parent.name == "pending"
                    else "other"
                )
            self.hit(selected, "open")
            fd = original_open(path, flags, *args, **kwargs)
            if selected != "other":
                self.fds[fd] = selected
            return fd

        def close(fd):
            selected = self.fds.pop(fd, "other")
            original_close(fd)
            self.closed.append((fd, selected))
            self.hit(selected, "close")

        def fstat(fd):
            self.hit(self.fds.get(fd), "fstat")
            return original_fstat(fd)

        def fsync(fd):
            self.hit(self.fds.get(fd), "fsync")
            return original_fsync(fd)

        def pwrite(fd, data, offset):
            selected = self.fds.get(fd)
            if self.matches(selected, "zero-write"):
                self.fired.append((selected, "zero-write"))
                return 0
            self.hit(selected, "write")
            return original_pwrite(fd, data, offset)

        class Stream:
            def __init__(self, stream, selected):
                self.stream, self.selected = stream, selected

            def read(self, size):
                owner.hit(self.selected, "read")
                return self.stream.read(size)

            def write(self, data):
                if owner.matches(self.selected, "zero-write"):
                    owner.fired.append((self.selected, "zero-write"))
                    return 0
                owner.hit(self.selected, "write")
                return self.stream.write(data)

            def flush(self):
                owner.hit(self.selected, "flush")
                return self.stream.flush()

            def close(self):
                self.stream.close()
                owner.hit(self.selected, "stream-close")

        def fdopen(fd, mode, *args, **kwargs):
            selected = self.fds.get(fd)
            self.hit(selected, "fdopen")
            stream = original_fdopen(fd, mode, *args, **kwargs)
            return stream if selected in (None, "other") else Stream(stream, selected)

        def frame(path, data, **kwargs):
            previous = self.stage
            self.stage = json.loads(data[12 : 12 + int.from_bytes(data[8:12], "big")])["phase"]
            try:
                return original_frame(path, data, **kwargs)
            finally:
                self.stage = previous

        def sync(path):
            previous = self.stage
            if path == pending:
                self.stage = (
                    "slot-retired"
                    if self.retired
                    else "slot-published"
                    if self.published
                    else "slot-before"
                )
            elif path == registry.parent:
                self.stage = "parent-published" if self.published else "parent-before"
            else:
                self.stage = "archive-payload-dir" if path.name == "pending" else "archive-dir"
            try:
                return original_sync(path)
            finally:
                self.stage = previous

        def link(source, destination, *args, **kwargs):
            self.hit("publish", "link")
            return original_link(source, destination, *args, **kwargs)

        def replace(source, destination):
            self.hit("publish", "replace")
            result = original_replace(source, destination)
            self.published = True
            return result

        def unlink(path, *args, **kwargs):
            if path == pending / "candidate":
                self.hit("candidate", "retire")
                result = original_unlink(path, *args, **kwargs)
                self.retired = True
                return result
            return original_unlink(path, *args, **kwargs)

        for name, replacement in (
            ("open", opened),
            ("close", close),
            ("fstat", fstat),
            ("fsync", fsync),
            ("pwrite", pwrite),
            ("fdopen", fdopen),
            ("link", link),
            ("replace", replace),
        ):
            monkeypatch.setattr(os, name, replacement)
        monkeypatch.setattr(Path, "unlink", unlink)
        monkeypatch.setattr(io, "write_frame", frame)
        monkeypatch.setattr(io, "sync_directory", sync)

    def matches(self, role, operation):
        return not self.fired and (role, operation) == (self.role, self.operation)

    def hit(self, role, operation):
        if self.matches(role, operation):
            self.fired.append((role, operation))
            raise self.primary


SAVE_FAULTS = (
    [
        ("candidate", op)
        for op in (
            "open",
            "fstat",
            "fdopen",
            "write",
            "zero-write",
            "flush",
            "fsync",
            "stream-close",
            "close",
            "retire",
        )
    ]
    + [
        (phase, op)
        for phase in ("PREPARED", "PUBLISHED", "CLEAN")
        for op in ("open", "fstat", "write", "zero-write", "fsync", "close")
    ]
    + [
        (phase, op)
        for phase in ("slot-before", "slot-published", "parent-published", "slot-retired")
        for op in ("open", "fsync", "close")
    ]
    + [("publish", "link"), ("publish", "replace")]
)


@pytest.mark.parametrize("role,operation", SAVE_FAULTS)
def test_actual_save_fault_matrix_retains_bounded_material_and_fences_owner(
    client, state_path, monkeypatch, role, operation
):
    from test_scenario_recovery import api_child
    from test_scenario_storage import saved

    value, first, _ = saved(client, state_path)
    registry, receipt, pending = paths(state_path)
    before, draft = registry.read_bytes(), state_path.read_bytes()
    with monkeypatch.context() as scope:
        fault = IOFault(scope, registry, role, operation)
        response = client.post("/api/v1/scenarios", json={"revision": 1, "definition": value})
    assert fault.fired == [(role, operation)]
    assert not fault.fds
    uncertain = (
        role in {"PUBLISHED", "CLEAN", "slot-published", "parent-published", "slot-retired"}
        or operation == "retire"
    )
    assert_error(
        response, 503, "SCENARIO_COMMIT_UNCERTAIN" if uncertain else "SCENARIO_STATE_UNAVAILABLE"
    )
    if not uncertain:
        assert registry.read_bytes() == before
    else:
        assert json.loads(registry.read_bytes())["scenarios"][0]["versions"] == [first]
        assert json.loads(registry.read_bytes())["revision"] == 2
    assert state_path.read_bytes() == draft
    assert receipt.stat().st_size <= 4096
    assert {p.name for p in pending.iterdir()} <= {"candidate", "publish"}
    assert all(p.stat().st_size <= 16777216 for p in pending.iterdir())
    material = {p: p.read_bytes() for p in (registry, receipt, *pending.iterdir())}
    assert client.get("/api/v1/scenarios").status_code == 200
    assert_error(
        client.post("/api/v1/scenarios", json={"revision": 0, "definition": value}),
        503,
        "SCENARIO_STATE_UNAVAILABLE",
    )
    assert all(p.read_bytes() == raw for p, raw in material.items())
    # Approved four-condition CLEAN restart also covers effect-free PREPARED
    # acquisition/write refusal: the prior CLEAN frame/R/empty slot are unchanged.
    can_restart = (role == "CLEAN" and operation in {"fsync", "close"}) or (
        role == "PREPARED" and operation in {"open", "fstat", "write", "zero-write"}
    )
    restarted = api_child(monkeypatch, state_path, value, 2 if uncertain else 1)
    assert restarted["status"] == (201 if can_restart else 503)
    if not can_restart:
        assert all(p.read_bytes() == raw for p, raw in material.items())


@pytest.mark.parametrize("operation", ["open", "fstat", "write", "zero-write", "fsync", "close"])
def test_partial_initialization_is_retained_and_never_automatically_repaired(
    client, state_path, monkeypatch, operation
):
    from test_scenario_recovery import api_child

    value = definition(register_targets(client))
    registry, receipt, pending = paths(state_path)
    with monkeypatch.context() as scope:
        fault = IOFault(scope, registry, "ACTIVE", operation)
        response = client.post("/api/v1/scenarios", json={"revision": 0, "definition": value})
    assert fault.fired == [("ACTIVE", operation)] and not fault.fds
    assert_error(response, 503, "SCENARIO_STATE_UNAVAILABLE")
    assert not registry.exists() and pending.is_dir() and not list(pending.iterdir())
    assert api_child(monkeypatch, state_path, value, 0)["status"] == 503


def wire_frame(value):
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    body = b"S01RR001" + len(raw).to_bytes(4, "big") + raw + bytes(4052 - len(raw))
    return body + hashlib.sha256(body).digest()


@pytest.mark.parametrize(
    "damage",
    [
        "checksum",
        "magic",
        "padding",
        "length",
        "canonical",
        "duplicate",
        "depth",
        "extra",
        "missing",
        "version-bool",
        "size-float",
        "size-over",
        "phase",
        "generation",
        "pre",
        "post",
        "token",
        "recovery",
    ],
)
def test_untrusted_receipt_never_admits_a_save(client, state_path, monkeypatch, damage):
    from test_scenario_recovery import api_child, cli
    from test_scenario_storage import saved

    value, _, _ = saved(client, state_path)
    registry, receipt, pending = paths(state_path)
    frame = read_frame(receipt)
    changes = {
        "version-bool": ("version", True),
        "size-float": ("size", 1.0),
        "size-over": ("size", 16777217),
        "phase": ("phase", "UNKNOWN"),
        "generation": ("generation", "A" * 32),
        "pre": ("pre", "x"),
        "post": ("post", None),
        "token": ("token_hash", "a" * 64),
        "recovery": ("recovery", {}),
        "extra": ("extra", 1),
    }
    if damage in changes:
        key, val = changes[damage]
        frame[key] = val
    elif damage == "missing":
        del frame["generation"]
    if damage == "depth":
        frame["unknown"] = [[[[[[[[[0]]]]]]]]]
    raw = bytearray(wire_frame(frame))
    if damage == "checksum":
        raw[-1] ^= 1
    elif damage in {"magic", "padding", "length"}:
        if damage == "magic":
            raw[0] = 0
        elif damage == "padding":
            raw[4063] = 1
        else:
            raw[8:12] = (4053).to_bytes(4, "big")
        raw[4064:] = hashlib.sha256(raw[:4064]).digest()
    elif damage in {"canonical", "duplicate"}:
        text = (
            json.dumps(frame).encode()
            if damage == "canonical"
            else (json.dumps(frame).encode()[:-1] + b',"version":1}')
        )
        body = b"S01RR001" + len(text).to_bytes(4, "big") + text + bytes(4052 - len(text))
        raw = body + hashlib.sha256(body).digest()
    receipt.write_bytes(raw)
    before = registry.read_bytes()
    inspected = cli(monkeypatch, state_path)
    assert inspected.returncode == 0
    assert json.loads(inspected.stdout)["phase"] == "MALFORMED"
    assert api_child(monkeypatch, state_path, value, 1)["status"] == 503
    assert registry.read_bytes() == before and receipt.read_bytes() == raw
    assert not list(pending.iterdir())


@pytest.mark.parametrize(
    "damage",
    ["digest", "size", "missing-slot", "missing-receipt", "nonempty", "nonclean", "slot-link"],
)
def test_fresh_process_requires_all_clean_restart_witnesses(
    client, state_path, monkeypatch, damage
):
    from test_scenario_recovery import api_child
    from test_scenario_storage import saved

    value, _, _ = saved(client, state_path)
    registry, receipt, pending = paths(state_path)
    if damage in {"digest", "size", "nonclean"}:
        frame = read_frame(receipt)
        if damage == "digest":
            frame["post"] = "0" * 64
        elif damage == "size":
            frame["size"] += 1
        else:
            frame["phase"] = "PUBLISHED"
        receipt.write_bytes(wire_frame(frame))
    elif damage == "nonempty":
        (pending / "publish").write_bytes(b"late caller entry")
    elif damage == "missing-receipt":
        receipt.rename(state_path.parent / "caller-receipt")
    else:
        pending.rename(state_path.parent / "caller-slot")
        if damage == "slot-link":
            pending.symlink_to(state_path.parent / "caller-slot", target_is_directory=True)
    before = registry.read_bytes()
    for _ in range(2):
        assert api_child(monkeypatch, state_path, value, 1)["status"] == 503
    assert registry.read_bytes() == before


@pytest.mark.parametrize(
    "role,operation",
    [
        (role, op)
        for role in ("read-registry", "candidate")
        for op in ("fstat", "fdopen", "stream-close")
    ]
    + [
        ("read-registry", "read"),
        ("candidate", "write"),
        ("candidate", "flush"),
        ("candidate", "fsync"),
    ],
)
def test_primary_exception_survives_secondary_close_and_reused_fd(
    client, state_path, monkeypatch, role, operation
):
    from test_scenario_storage import saved

    from aiddos.api.errors import DraftError
    from aiddos.api.scenario_store import ScenarioStore
    from aiddos.api.scenarios import ScenarioInput
    from aiddos.api.store import DraftStore

    value, _, _ = saved(client, state_path)
    registry, _, _ = paths(state_path)
    store = ScenarioStore(DraftStore(state_path))
    caller = state_path.parent / "caller-fd"
    caller.write_bytes(b"caller descriptor must survive")
    real_open, real_close = os.open, os.close
    replacement, close_attempts = [], []
    secondary = OSError("secondary real-close-then-EIO")
    with monkeypatch.context() as scope:
        fault = IOFault(scope, registry, role, operation)
        instrumented_close = os.close

        def close(fd):
            selected = fault.fds.get(fd)
            instrumented_close(fd)
            if selected == role and fault.fired:
                close_attempts.append(fd)
                new = real_open(caller, os.O_RDONLY)
                replacement.append(new)
                assert new == fd
                raise secondary

        scope.setattr(os, "close", close)
        with pytest.raises(DraftError) as error:
            if role == "read-registry":
                store._read()
            else:
                store.save(ScenarioInput.model_validate({"revision": 1, "definition": value}))
    assert fault.fired == [(role, operation)]
    assert error.value.__cause__ is fault.primary
    assert len(close_attempts) == len(replacement) == 1
    assert os.read(replacement[0], 100) == b"caller descriptor must survive"
    real_close(replacement[0])
    assert caller.read_bytes() == b"caller descriptor must survive"


@pytest.mark.parametrize("role", ["candidate", "PREPARED", "PUBLISHED", "CLEAN"])
def test_positive_short_writes_finish_exact_bytes_without_append_or_truncation(
    client, state_path, monkeypatch, role
):
    from test_scenario_storage import saved

    from aiddos.api import scenario_persistence as io

    value, _, _ = saved(client, state_path)
    registry, receipt, pending = paths(state_path)
    real_pwrite, real_fdopen, real_frame = os.pwrite, os.fdopen, io.write_frame
    selected = [None]
    calls = []

    def frame(path, raw, **kwargs):
        selected[0] = json.loads(raw[12 : 12 + int.from_bytes(raw[8:12], "big")])["phase"]
        return real_frame(path, raw, **kwargs)

    def pwrite(fd, data, offset):
        if selected[0] == role:
            data = data[:31]
            calls.append((offset, len(data)))
        return real_pwrite(fd, data, offset)

    class Stream:
        def __init__(self, stream):
            self.stream = stream

        def write(self, data):
            chunk = data[:31]
            calls.append((None, len(chunk)))
            return self.stream.write(chunk)

        def flush(self):
            return self.stream.flush()

        def close(self):
            return self.stream.close()

    def fdopen(fd, mode, *args, **kwargs):
        stream = real_fdopen(fd, mode, *args, **kwargs)
        return Stream(stream) if role == "candidate" and mode == "wb" else stream

    with monkeypatch.context() as scope:
        scope.setattr(io, "write_frame", frame)
        scope.setattr(os, "pwrite", pwrite)
        scope.setattr(os, "fdopen", fdopen)
        response = client.post("/api/v1/scenarios", json={"revision": 1, "definition": value})
    assert response.status_code == 201 and len(calls) > 1
    assert read_frame(receipt)["phase"] == "CLEAN" and not list(pending.iterdir())
    if role != "candidate":
        assert calls[0][0] == 0 and sum(length for _, length in calls) == 4096
        assert all(offset + length <= 4096 for offset, length in calls)
    else:
        assert sum(length for _, length in calls) == len(registry.read_bytes())


def test_new_ancestor_entries_are_synced_up_to_existing_parent_before_candidate(
    tmp_path, monkeypatch
):
    from aiddos.api import scenario_persistence as io
    from aiddos.api.scenario_store import ScenarioStore
    from aiddos.api.store import DraftStore

    store = ScenarioStore(DraftStore(tmp_path / "new" / "deep" / "drafts.json"))
    seen = []
    real_sync, real_write = io.sync_directory, io.write_candidate

    def sync(path):
        real_sync(path)
        seen.append(path)

    def write(path, raw):
        assert tmp_path in seen and tmp_path / "new" in seen
        assert tmp_path / "new" / "deep" in seen
        assert store.pending_path in seen
        return real_write(path, raw)

    monkeypatch.setattr(io, "sync_directory", sync)
    monkeypatch.setattr(io, "write_candidate", write)
    store._write({"format_version": 1, "revision": 0, "scenarios": []})
    assert read_frame(store.receipt_path)["phase"] == "CLEAN"


def test_quarantine_preserves_source_error_precedence(client, state_path, monkeypatch):
    from test_scenario_recovery import failed_attempt

    value, _ = failed_attempt(client, state_path, monkeypatch)
    registry, _, _ = paths(state_path)
    state_path.write_bytes(b"invalid draft")
    assert_error(
        client.post("/api/v1/scenarios", json={"revision": 999, "definition": value}),
        503,
        "STATE_CORRUPT",
    )
    registry.write_bytes(b"invalid registry")
    assert_error(
        client.post("/api/v1/scenarios", json={"revision": 999, "definition": value}),
        503,
        "SCENARIO_STATE_CORRUPT",
    )


@pytest.mark.parametrize("role", ["read-registry", "candidate", "PREPARED", "slot-published"])
@pytest.mark.parametrize("same_inode", [False, True])
def test_close_only_failure_never_retries_reused_descriptor(
    client, state_path, monkeypatch, role, same_inode
):
    from test_scenario_storage import saved

    from aiddos.api.errors import DraftError
    from aiddos.api.scenario_store import ScenarioStore
    from aiddos.api.scenarios import ScenarioInput
    from aiddos.api.store import DraftStore

    value, _, _ = saved(client, state_path)
    registry, receipt, pending = paths(state_path)
    store = ScenarioStore(DraftStore(state_path))
    caller = state_path.parent / "caller-independent-handle"
    caller.write_bytes(b"caller-owned")
    target = (
        {
            "read-registry": registry,
            "candidate": pending / "candidate",
            "PREPARED": receipt,
            "slot-published": pending,
        }[role]
        if same_inode
        else caller
    )
    real_open, real_close = os.open, os.close
    replacement, attempts = [], []
    primary = OSError("close-only real-close-then-EIO")
    with monkeypatch.context() as scope:
        fault = IOFault(scope, registry, "never", "never")
        instrumented_close = os.close

        def close(fd):
            selected = fault.fds.get(fd)
            instrumented_close(fd)
            if selected == role and not attempts:
                attempts.append(fd)
                reopened = real_open(target, os.O_RDONLY)
                replacement.append(reopened)
                assert reopened == fd
                raise primary

        scope.setattr(os, "close", close)
        with pytest.raises(DraftError) as error:
            if role == "read-registry":
                store._read()
            else:
                store.save(ScenarioInput.model_validate({"revision": 1, "definition": value}))
    assert error.value.__cause__ is primary and len(attempts) == 1
    assert not fault.fds
    assert os.fstat(replacement[0]).st_ino == target.stat().st_ino
    real_close(replacement[0])
    assert caller.read_bytes() == b"caller-owned"


def test_storage_errors_explain_quarantine_without_promising_get_unlock():
    from aiddos.api.errors import ERRORS

    assert ERRORS["SCENARIO_STATE_UNAVAILABLE"][1] == (
        "Scenario storage is unavailable or write-quarantined. History reads do not unlock saves; "
        "follow the offline recovery guide."
    )
    assert ERRORS["SCENARIO_COMMIT_UNCERTAIN"][1] == (
        "Scenario may have been saved. Read its history; unresolved storage failure requires "
        "offline recovery. Do not resubmit automatically."
    )
