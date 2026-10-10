"""Durable S01-B01/B02 acceptance regressions, intentionally not xfailed.

The unchanged reviewer tests and their original RED are retained separately.
These tests require real replacement/fault firing before checking preservation.
A live anchor may eliminate inode reuse, but never the replacement obligation.
"""

import errno
import json
import os
import socket
import stat
from pathlib import Path

import pytest
from test_scenario_storage import saved
from test_scenarios import assert_error, registry_path


@pytest.fixture(autouse=True)
def no_listeners_or_extra_connections(monkeypatch):
    def deny(*args, **kwargs):
        pytest.fail("Scenario ownership test attempted a network or listener action")

    monkeypatch.setattr(socket.socket, "bind", deny)
    monkeypatch.setattr(socket.socket, "listen", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)


def receipt(state_path, observation):
    (state_path.parent / "ownership-receipt.json").write_text(
        json.dumps(observation, indent=2) + "\n"
    )


@pytest.mark.parametrize("schedule", ["unlink-recreate", "after-observation"])
def test_caller_replacement_survives_failed_publication(client, state_path, monkeypatch, schedule):
    from aiddos.api import scenario_store

    value, first, _ = saved(client, state_path)
    registry = registry_path(state_path)
    preimage, draft = registry.read_bytes(), state_path.read_bytes()
    real_lstat = Path.lstat
    paths, fired = [], []
    observation = {"schedule": schedule}
    foreign = b"caller-owned replacement; scenario cleanup must preserve it"

    def replace(temporary, destination):
        path = Path(temporary)
        paths.append(path)
        if schedule == "unlink-recreate":
            before = path.stat()
            path.unlink()
            path.write_bytes(foreign)
            after = path.stat()
            fired.append(schedule)
            observation["inode_reused"] = (before.st_dev, before.st_ino) == (
                after.st_dev,
                after.st_ino,
            )
            observation["old_identity"] = [before.st_dev, before.st_ino]
            observation["new_identity"] = [after.st_dev, after.st_ino]
        raise OSError(errno.EIO, "publication failure")

    def lstat(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        # S01 addendum: final observation moved before replace, not failure cleanup.
        if schedule == "after-observation" and path.name == "publish" and not fired:
            path.rename(path.with_suffix(".original-retained"))
            path.write_bytes(foreign)
            fired.append(schedule)
        return info

    with monkeypatch.context() as fault:
        fault.setattr(scenario_store.os, "replace", replace)
        fault.setattr(Path, "lstat", lstat)
        response = client.put(
            f"/api/v1/scenarios/{first['id']}", json={"revision": 1, "definition": value}
        )
    survived = bool(paths and paths[0].exists())
    observation.update(
        fired=fired,
        replace_calls=len(paths),
        path=str(paths[0]) if paths else None,
        foreign_survived=survived,
        foreign_bytes_match=survived and paths[0].read_bytes() == foreign,
        registry_preimage_preserved=registry.read_bytes() == preimage,
        draft_preimage_preserved=state_path.read_bytes() == draft,
        status=response.status_code,
        body=response.json(),
    )
    receipt(state_path, observation)
    assert fired == [schedule] and len(paths) == 1, observation
    assert_error(response, 503, "SCENARIO_STATE_UNAVAILABLE")
    assert registry.read_bytes() == preimage and state_path.read_bytes() == draft
    assert survived and paths[0].read_bytes() == foreign, observation


@pytest.mark.parametrize(
    "point",
    [
        "mkdir",
        "mkstemp",
        "fstat",
        "fdopen",
        "write",
        "flush",
        "file-fsync",
        "stream-close",
        "raw-close",
        "replace",
        "directory-open",
        "directory-fsync",
        "directory-close",
    ],
)
def test_owned_acquisition_and_publication_faults(client, state_path, monkeypatch, point):

    from scenario_producer import definition, register_targets

    if point == "mkdir":
        value, first = definition(register_targets(client)), {"id": "unused"}
    else:
        value, first, _ = saved(client, state_path)
    registry = registry_path(state_path)
    pending = registry.with_name(registry.name + ".s01-pending")
    preimage = registry.read_bytes() if registry.exists() else None
    draft = state_path.read_bytes()
    real_fstat, real_fdopen, real_close = os.fstat, os.fdopen, os.close
    real_mkdir, real_open, real_fsync, real_replace = Path.mkdir, os.open, os.fsync, os.replace
    acquired, retired, write_fds, fired = [], [], set(), []
    published = False

    def fail():
        fired.append(point)
        raise OSError(errno.EIO, "injected ownership regression fault")

    def fstat(fd):
        if point == "fstat" and fd in write_fds and not fired:
            fail()
        return real_fstat(fd)

    def close(fd):
        info = real_fstat(fd)
        is_owned = fd in write_fds and stat.S_ISREG(info.st_mode)
        eligible = (point == "raw-close" and is_owned) or (
            point == "directory-close" and published and stat.S_ISDIR(info.st_mode)
        )
        real_close(fd)
        if is_owned:
            retired.append({"fd": fd, "identity": [info.st_dev, info.st_ino]})
            write_fds.remove(fd)
        if eligible and not fired:
            fail()

    class Stream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def close(self):
            self.stream.close()
            if point == "stream-close" and not fired:
                fail()

        def write(self, data):
            if point == "write" and not fired:
                fail()
            return self.stream.write(data)

        def flush(self):
            if point == "flush" and not fired:
                fail()
            return self.stream.flush()

        def fileno(self):
            return self.stream.fileno()

    def fdopen(fd, mode, *args, **kwargs):
        if mode == "wb" and point == "fdopen":
            fail()
        stream = real_fdopen(fd, mode, *args, **kwargs)
        return Stream(stream) if mode == "wb" else stream

    def mkdir(path, *args, **kwargs):
        if point == "mkdir" and path == pending and not fired:
            fail()
        return real_mkdir(path, *args, **kwargs)

    def open_file(path, flags, *args, **kwargs):
        if point == "directory-open" and published and flags & os.O_DIRECTORY and not fired:
            fail()
        candidate = Path(path) == pending / "candidate" and flags & os.O_CREAT
        if candidate and point == "mkstemp":  # eliminated mkstemp -> exclusive candidate open
            fail()
        fd = real_open(path, flags, *args, **kwargs)
        if candidate:
            info = real_fstat(fd)
            write_fds.add(fd)
            acquired.append({"fd": fd, "identity": [info.st_dev, info.st_ino], "path": str(path)})
        return fd

    def fsync(fd):
        directory = stat.S_ISDIR(real_fstat(fd).st_mode)
        eligible = (point == "file-fsync" and fd in write_fds) or (
            point == "directory-fsync" and published and directory
        )
        if eligible and not fired:
            fail()
        return real_fsync(fd)

    def replace(source, destination):
        nonlocal published
        if point == "replace" and not fired:
            fail()
        result = real_replace(source, destination)
        published = True
        return result

    with monkeypatch.context() as fault:
        fault.setattr(os, "fstat", fstat)
        fault.setattr(os, "fdopen", fdopen)
        fault.setattr(os, "close", close)
        fault.setattr(os, "open", open_file)
        fault.setattr(os, "fsync", fsync)
        fault.setattr(os, "replace", replace)
        fault.setattr(Path, "mkdir", mkdir)
        if point == "mkdir":
            response = client.post("/api/v1/scenarios", json={"revision": 0, "definition": value})
        else:
            response = client.put(
                f"/api/v1/scenarios/{first['id']}", json={"revision": 1, "definition": value}
            )
    leftovers = sorted(path.name for path in pending.iterdir()) if pending.exists() else []
    retained_registry = registry.read_bytes() if registry.exists() else None
    uncertain = point in {"directory-open", "directory-fsync", "directory-close"}
    observation = {
        "point": point,
        "fault_fired": fired,
        "acquired": acquired,
        "retired": retired,
        "unretired_fds": sorted(write_fds),
        "temporary_files": leftovers,
        "registry_preimage_preserved": retained_registry == preimage,
        "draft_preimage_preserved": state_path.read_bytes() == draft,
        "status": response.status_code,
        "body": response.json(),
    }
    receipt(state_path, observation)
    assert fired == [point], observation
    assert_error(
        response, 503, "SCENARIO_COMMIT_UNCERTAIN" if uncertain else "SCENARIO_STATE_UNAVAILABLE"
    )
    assert state_path.read_bytes() == draft
    if uncertain:
        history = client.get(f"/api/v1/scenarios/{first['id']}").json()
        assert history["revision"] == 2 and history["versions"][0] == first
        assert len(history["versions"]) == 2
    else:
        assert retained_registry == preimage
    assert not write_fds and len(acquired) == len(retired), observation
    assert set(leftovers) <= {"candidate", "publish"}, observation
    assert len(leftovers) <= 2
    retained = {p: p.read_bytes() for p in pending.iterdir()} if pending.exists() else {}
    # Approved semantic delta: bounded retention and repeat refusal, never deletion.
    assert_error(
        client.post("/api/v1/scenarios", json={"revision": 0, "definition": value}),
        503,
        "SCENARIO_STATE_UNAVAILABLE",
    )
    assert all(p.read_bytes() == data for p, data in retained.items())
