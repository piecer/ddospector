"""Registry corruption, ownership and publication fault regressions."""

import json
import os
from copy import deepcopy

import pytest
from scenario_producer import canonical, definition, digest, register_targets
from test_scenarios import assert_error, registry_path, set_field


def saved(client, state_path):
    value = definition(register_targets(client))
    response = client.post("/api/v1/scenarios", json={"revision": 0, "definition": value})
    assert response.status_code == 201
    return value, response.json()["scenario"], json.loads(registry_path(state_path).read_bytes())


@pytest.mark.parametrize(
    "damage",
    [
        "revision-count",
        "terminal-counter",
        "duplicate-identity",
        "owner-id",
        "sequence",
        "digest",
        "target-link",
        "sink-kind",
        "profile",
        "catalog",
        "missing-target-status",
        "execution-int",
        "format-bool",
        "format-float",
        "version-float",
        "oversized-record",
        "missing-field",
        "extra-field",
        "wrong-primitive",
        "target-extra",
        "target-address",
        "policy-cross-field",
    ],
)
def test_corrupt_registry_is_not_repaired_or_used(client, state_path, damage):
    value, first, state = saved(client, state_path)
    record = state["scenarios"][0]["versions"][0]
    if damage == "revision-count":
        state["revision"] = 0
    elif damage == "terminal-counter":
        state["revision"] = 9007199254740991
    elif damage == "duplicate-identity":
        state["scenarios"].append(deepcopy(state["scenarios"][0]))
        state["revision"] = 2
    elif damage == "owner-id":
        state["scenarios"][0]["id"] = "foreign"
    elif damage == "sequence":
        record["version"] = 2
    elif damage == "digest":
        record["digest"] = "0" * 64
    elif damage == "target-link":
        record["target_snapshot"]["id"] = "foreign"
    elif damage == "sink-kind":
        record["sink_snapshot"]["kind"] = "DUT"
    elif damage == "profile":
        record["profile_snapshot"]["name"]["en"] = "Invented profile"
    elif damage == "catalog":
        record["catalog_version"] = "2.0.0"
    elif damage == "missing-target-status":
        del record["target_snapshot"]["status"]
    elif damage == "execution-int":
        record["execution_enabled"] = 0
    elif damage == "format-bool":
        state["format_version"] = True
    elif damage == "format-float":
        state["format_version"] = 1.0
    elif damage == "version-float":
        record["version"] = 1.0
    elif damage == "oversized-record":
        record["definition"]["objective"] = "😀" * 2000
    elif damage == "missing-field":
        del record["definition"]["pcap_asset"]
    elif damage == "extra-field":
        state["future"] = None
    elif damage == "wrong-primitive":
        record["definition"]["traffic_budget"]["max_pps"] = True
    elif damage == "target-extra":
        record["target_snapshot"]["extra"] = None
    elif damage == "target-address":
        record["target_snapshot"]["address"] = "https://not-an-address"
    elif damage == "policy-cross-field":
        record["definition"]["delivery_expectation"] = "BLOCK"
    if damage != "digest":
        record["digest"] = digest(record)
    path = registry_path(state_path)
    path.write_bytes(canonical(state))
    before, source = path.read_bytes(), state_path.read_bytes()
    for response in (
        client.get("/api/v1/scenarios"),
        client.get(f"/api/v1/scenarios/{first['id']}"),
        client.post("/api/v1/scenarios", json={"revision": 1, "definition": value}),
    ):
        assert_error(response, 503, "SCENARIO_STATE_CORRUPT")
    assert path.read_bytes() == before and state_path.read_bytes() == source


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not-json",
        b"{}",
        b"[]",
        b"null",
        b"\xff",
        b'{"format_version":1,"revision":0,"revision":0,"scenarios":[]}',
        b'{"format_version":1,"revision":0,"\\u0072evision":0,"scenarios":[]}',
        b'{"format_version":1,"revision":NaN,"scenarios":[]}',
        b"[" * 33 + b"]" * 33,
    ],
)
def test_malformed_state_get_never_repairs(client, state_path, raw):
    path = registry_path(state_path)
    path.write_bytes(raw)
    assert_error(client.get("/api/v1/scenarios"), 503, "SCENARIO_STATE_CORRUPT")
    assert path.read_bytes() == raw and not state_path.exists()


@pytest.mark.parametrize(
    "kind,code",
    [
        ("symlink", "SCENARIO_STATE_UNAVAILABLE"),
        ("fifo", "SCENARIO_STATE_CORRUPT"),
        ("directory", "SCENARIO_STATE_CORRUPT"),
        ("oversized", "SCENARIO_STATE_CORRUPT"),
    ],
)
def test_nofollow_nonblocking_regular_bounded_reads(client, state_path, kind, code):
    path = registry_path(state_path)
    caller = state_path.parent / "caller-owned"
    caller.write_bytes(b"Do not change or read through a link")
    if kind == "symlink":
        path.symlink_to(caller)
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    else:
        with path.open("wb") as stream:
            stream.truncate(16 * 1024 * 1024 + 1)
    before = path.lstat()
    assert_error(client.get("/api/v1/scenarios"), 503, code)
    after = path.lstat()
    assert (before.st_ino, before.st_size, before.st_mtime_ns) == (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    assert caller.read_bytes() == b"Do not change or read through a link"
    assert not state_path.exists()


@pytest.mark.parametrize(
    "point", ["open", "mkstemp", "file-fsync", "replace", "directory-open", "directory-fsync"]
)
def test_filesystem_failure_has_truthful_preimage_or_uncertainty(
    client, state_path, monkeypatch, point
):
    from aiddos.api import scenario_store

    value, first, _ = saved(client, state_path)
    path = registry_path(state_path)
    before, source = path.read_bytes(), state_path.read_bytes()
    calls = []
    original_open, original_fsync, original_replace = os.open, os.fsync, os.replace
    published = False
    write_fds = set()

    def failing_open(file, flags, *args, **kwargs):
        if (
            (point == "open" and file == path)
            or (point == "directory-open" and published and flags & os.O_DIRECTORY)
            or (
                point == "mkstemp"
                and getattr(file, "name", None) == "candidate"
                and flags & os.O_CREAT
            )
        ):
            calls.append(point)
            raise PermissionError("private-path must not leak")
        fd = original_open(file, flags, *args, **kwargs)
        if getattr(file, "name", None) == "candidate" and flags & os.O_CREAT:
            write_fds.add(fd)
        return fd

    def publish(source, destination):
        nonlocal published
        result = original_replace(source, destination)
        published = True
        return result

    def failing_fsync(fd):
        import stat

        directory = stat.S_ISDIR(os.fstat(fd).st_mode)
        if (point == "directory-fsync" and published and directory) or (
            point == "file-fsync" and fd in write_fds
        ):
            calls.append(point)
            raise OSError("private failure")
        return original_fsync(fd)

    def fail(*args, **kwargs):
        calls.append(point)
        raise OSError("private failure")

    with monkeypatch.context() as faults:
        faults.setattr(scenario_store.os, "open", failing_open)
        faults.setattr(scenario_store.os, "fsync", failing_fsync)
        faults.setattr(scenario_store.os, "replace", fail if point == "replace" else publish)
        response = client.put(
            f"/api/v1/scenarios/{first['id']}", json={"revision": 1, "definition": value}
        )
    assert calls == [point]
    uncertain = point in {"directory-open", "directory-fsync"}
    assert_error(
        response, 503, "SCENARIO_COMMIT_UNCERTAIN" if uncertain else "SCENARIO_STATE_UNAVAILABLE"
    )
    assert state_path.read_bytes() == source
    if uncertain:
        history = client.get(f"/api/v1/scenarios/{first['id']}").json()
        assert history["revision"] == 2 and history["versions"][0] == first
        assert len(history["versions"]) == 2
    else:
        assert path.read_bytes() == before
    pending = path.with_name(path.name + ".s01-pending")
    receipt = path.with_name(path.name + ".s01-recovery")
    assert sorted(p.name for p in path.parent.iterdir()) == sorted(
        [state_path.name, path.name, pending.name, receipt.name]
    )
    assert receipt.stat().st_size <= 4096
    assert {p.name for p in pending.iterdir()} <= {"candidate", "publish"}


def test_returned_structures_never_alias_store_or_catalog(client, state_path):
    from aiddos.api.catalog import PROFILES_V1
    from aiddos.api.scenario_store import ScenarioStore
    from aiddos.api.scenarios import ScenarioInput
    from aiddos.api.store import DraftStore

    value = definition(register_targets(client))
    store = ScenarioStore(DraftStore(state_path))
    catalog = deepcopy(PROFILES_V1)
    request = ScenarioInput.model_validate({"revision": 0, "definition": value})
    receipt = store.save(request)
    original = deepcopy(receipt["scenario"])
    try:
        receipt["scenario"]["profile_snapshot"]["name"]["en"] = "mutated return"
        receipt["scenario"]["definition"]["traffic_budget"]["max_pps"] = 999
        request.definition.name = "mutated input"
        page = store.page()
        page["items"][0]["target_snapshot"]["name"] = "mutated page"
        history = store.history(original["id"])
        history["versions"].clear()
        assert store.history(original["id"])["versions"] == [original]
        assert catalog == PROFILES_V1
    finally:
        # Keep a future aliasing regression from contaminating unrelated tests.
        PROFILES_V1[:] = catalog


@pytest.mark.parametrize(
    "path,replacement",
    [
        ("execution_enabled", 0),
        ("execution_enabled", 0.0),
        ("definition.ip_version", 4.0),
        ("definition.stop_conditions.management_loss", 1),
    ],
)
def test_version_model_itself_rejects_numeric_literal_aliases(
    client, state_path, path, replacement
):
    from pydantic import ValidationError

    from aiddos.api.scenarios import ScenarioVersion

    _, record, _ = saved(client, state_path)
    set_field(record, path, replacement)
    record["digest"] = digest(record)
    with pytest.raises(ValidationError):
        ScenarioVersion.model_validate(record)


@pytest.mark.parametrize("fault", ["oversized", "invalid"])
def test_prewrite_validates_full_state_before_allocating_file(
    client, state_path, monkeypatch, fault
):
    from aiddos.api import scenario_store
    from aiddos.api.errors import DraftError
    from aiddos.api.store import DraftStore

    _, _, state = saved(client, state_path)
    store = scenario_store.ScenarioStore(DraftStore(state_path.parent / "other" / "drafts.json"))
    if fault == "oversized":
        monkeypatch.setattr(scenario_store, "MAX_STATE_BYTES", len(canonical(state)) - 1)
    else:
        state["revision"] += 1
    with pytest.raises(DraftError, match="VALIDATION_ERROR"):
        store._write(state)
    assert not store.path.exists() and not store.path.parent.exists()


@pytest.mark.parametrize("operation", ["list", "history", "post", "put"])
def test_serialized_response_budget_is_enforced_before_publication(
    client, state_path, monkeypatch, operation
):
    from aiddos.api import scenarios

    value, first, _ = saved(client, state_path)
    before = registry_path(state_path).read_bytes()
    limit = "MAX_PAGE_BYTES" if operation == "list" else "MAX_RESPONSE_BYTES"
    monkeypatch.setattr(scenarios, limit, 1)
    if operation == "list":
        response = client.get("/api/v1/scenarios")
    elif operation == "history":
        response = client.get(f"/api/v1/scenarios/{first['id']}")
    else:
        url = "/api/v1/scenarios" + (f"/{first['id']}" if operation == "put" else "")
        response = getattr(client, operation)(url, json={"revision": 1, "definition": value})
    assert_error(
        response,
        503 if operation in {"list", "history"} else 422,
        "SCENARIO_STATE_CORRUPT" if operation in {"list", "history"} else "VALIDATION_ERROR",
    )
    assert registry_path(state_path).read_bytes() == before


@pytest.mark.parametrize("after_publish", [False, True])
def test_cleanup_never_unlinks_replacement_at_owned_temp_name(
    client, state_path, monkeypatch, after_publish
):
    from pathlib import Path

    from aiddos.api import scenario_store

    value, first, _ = saved(client, state_path)
    original_replace = os.replace
    caller_files = []

    def substitute_temp(source, destination):
        # Move the allocated inode away, then install caller data at that name.
        if after_publish:
            original_replace(source, destination)
        else:
            original_replace(source, Path(source).with_suffix(".owned-retained"))
        Path(source).write_bytes(b"caller replacement")
        caller_files.append(Path(source))
        if not after_publish:
            raise OSError("failed before publication")

    monkeypatch.setattr(scenario_store.os, "replace", substitute_temp)
    response = client.put(
        f"/api/v1/scenarios/{first['id']}", json={"revision": 1, "definition": value}
    )
    if after_publish:
        assert response.status_code == 200
    else:
        assert_error(response, 503, "SCENARIO_STATE_UNAVAILABLE")
    assert len(caller_files) == 1 and caller_files[0].exists()
    assert caller_files[0].read_bytes() == b"caller replacement"


def test_write_fdopen_failure_closes_descriptor_and_retains_bounded_candidate(
    client, state_path, monkeypatch
):
    from aiddos.api import scenario_store

    value, first, _ = saved(client, state_path)
    before = registry_path(state_path).read_bytes()
    original_fdopen = os.fdopen
    allocated = []

    def fail_write_open(fd, mode, *args, **kwargs):
        if mode == "wb":
            allocated.append(fd)
            raise OSError("cannot wrap descriptor")
        return original_fdopen(fd, mode, *args, **kwargs)

    monkeypatch.setattr(scenario_store.os, "fdopen", fail_write_open)
    assert_error(
        client.put(f"/api/v1/scenarios/{first['id']}", json={"revision": 1, "definition": value}),
        503,
        "SCENARIO_STATE_UNAVAILABLE",
    )
    assert len(allocated) == 1
    with pytest.raises(OSError):
        os.fstat(allocated[0])
    assert registry_path(state_path).read_bytes() == before
    pending = registry_path(state_path).with_name(registry_path(state_path).name + ".s01-pending")
    assert [p.name for p in pending.iterdir()] == ["candidate"]
    assert (pending / "candidate").stat().st_size == 0
    assert not list(state_path.parent.glob(".scenarios-*"))


def test_new_version_can_bind_different_targets_without_rebinding_old_history(client, state_path):
    from aiddos.api.scenario_store import ScenarioStore
    from aiddos.api.store import DraftStore

    value, first, _ = saved(client, state_path)
    new_targets = register_targets(client)
    changed = deepcopy(value)
    changed.update(target_id=new_targets[0]["id"], sink_id=new_targets[1]["id"])
    response = client.put(
        f"/api/v1/scenarios/{first['id']}", json={"revision": 1, "definition": changed}
    )
    assert response.status_code == 200
    second = response.json()["scenario"]
    assert second["target_snapshot"] == new_targets[0]
    assert second["sink_snapshot"] == new_targets[1]
    state_path.unlink()
    # Digest is integrity, not authentication: a consistent local edit is admissible.
    path = registry_path(state_path)
    state = json.loads(path.read_bytes())
    record = state["scenarios"][0]["versions"][1]
    record["target_snapshot"]["name"] = "self-consistent historical declaration"
    record["digest"] = digest(record)
    path.write_bytes(canonical(state))
    before = path.read_bytes()
    history = ScenarioStore(DraftStore(state_path)).history(first["id"])
    assert history["versions"] == [first, record]
    assert path.read_bytes() == before and not state_path.exists()


def test_raw_state_size_exact_limit_is_read_only_and_plus_one_is_corrupt(client, state_path):
    raw = b'{"format_version":1,"revision":0,"scenarios":[]}'
    raw += b" " * (16 * 1024 * 1024 - len(raw))
    path = registry_path(state_path)
    path.write_bytes(raw)
    response = client.get("/api/v1/scenarios")
    assert response.status_code == 200 and response.json()["items"] == []
    assert path.read_bytes() == raw
    path.write_bytes(raw + b" ")
    assert_error(client.get("/api/v1/scenarios"), 503, "SCENARIO_STATE_CORRUPT")
    assert path.read_bytes() == raw + b" " and not state_path.exists()


def test_effective_path_and_lock_ownership_through_publication(client, state_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from aiddos.api import scenario_store
    from aiddos.api.scenarios import ScenarioInput
    from aiddos.api.store import DraftStore

    value = definition(register_targets(client))
    alias = state_path.parent / "parent-alias"
    alias.symlink_to(state_path.parent, target_is_directory=True)
    drafts = DraftStore(state_path)
    peer_drafts = DraftStore(alias / state_path.name)
    store = scenario_store.ScenarioStore(drafts)
    peer = scenario_store.ScenarioStore(peer_drafts)
    assert store.path == registry_path(state_path) == peer.path
    assert store.lock is peer.lock and drafts.lock is peer_drafts.lock
    original_replace = os.replace
    reads = []
    original_read = DraftStore._read

    def read_once(self):
        reads.append(self.path)
        return original_read(self)

    def lock_is_available(lock):
        acquired = lock.acquire(blocking=False)
        if acquired:
            lock.release()
        return acquired

    def checked_replace(source, destination):
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert not pool.submit(lock_is_available, peer.lock).result(timeout=5)
            assert not pool.submit(lock_is_available, peer_drafts.lock).result(timeout=5)
        return original_replace(source, destination)

    monkeypatch.setattr(DraftStore, "_read", read_once)
    monkeypatch.setattr(scenario_store.os, "replace", checked_replace)
    receipt = store.save(ScenarioInput.model_validate({"revision": 0, "definition": value}))
    assert reads == [state_path]
    assert peer.page()["items"] == [receipt["scenario"]]
    assert peer.history(receipt["scenario"]["id"])["versions"] == [receipt["scenario"]]
    assert reads == [state_path]
