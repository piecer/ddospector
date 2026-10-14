"""Retained local operator lifecycle; no external resources in these unit tests."""

import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def local():
    path = ROOT / "tools/phase1_local.py"
    assert path.is_file(), "the retained operator entrypoint must exist"
    spec = importlib.util.spec_from_file_location("phase1_local", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_durable_workspace_exclusive_create_and_socket(tmp_path):
    module = local()
    workspace = tmp_path / "retained"
    module.new_workspace(workspace)
    pg = module.PersistentPG(workspace)
    assert pg.socket == workspace / "d/s"
    assert pg.socket.parent.stat().st_mode & 0o777 == 0o700
    assert pg.socket.stat().st_mode & 0o777 == 0o777
    assert pg.journal.is_file()
    assert pg.receipt is None
    import pytest

    with pytest.raises(FileExistsError):
        module.new_workspace(workspace)
    assert pg.socket.is_dir()


def registered(workspace):
    module = local()
    module.new_workspace(workspace)
    owner = module.PersistentPG(workspace)
    cid = "a" * 64
    receipt = {"code": 0, "stdout": cid + "\n", "stderr": "", "timed_out": False}
    owner.cidfile.write_text(cid + "\n")
    owner.note("create_result", **receipt)
    owner.note(
        "registered",
        cid=cid,
        volume={"Name": "b" * 64, "CreatedAt": "now"},
        metadata={"Created": "now"},
    )
    owner.note("ready")
    state = {
        "format": 1,
        "root": str(ROOT),
        "phase": "STOPPED",
        "socket_identity": module.socket_identity(owner.socket),
        "helper_sha256": module.h.source_digest(),
    }
    module.save_state(workspace, state)
    return module, owner, state


def test_reopen_requires_original_receipt_not_just_labels(tmp_path, monkeypatch):
    module, owner, state = registered(tmp_path / "kept")
    calls = []
    monkeypatch.setattr(
        module.h.CustodyInspector, "_check_custody", lambda self: calls.append(self.cid)
    )
    retained = module.retained_pg(tmp_path / "kept", state)
    assert retained.cid == "a" * 64 and calls == ["a" * 64]
    events = [json.loads(line) for line in owner.journal.read_text().splitlines()]
    events = [e for e in events if e["event"] != "create_result"]
    owner.journal.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    with pytest.raises(module.h.Blocked, match="RECEIPT"):
        module.retained_pg(tmp_path / "kept", state)
    assert calls == ["a" * 64]  # No external lookup on insufficient authority.


@pytest.mark.parametrize(
    "fault", ["nonzero", "timeout", "wrong-id", "duplicate", "revoked", "inode"]
)
def test_reopen_refuses_ambiguous_receipt_or_replaced_socket(tmp_path, monkeypatch, fault):
    module, owner, state = registered(tmp_path / "kept")
    monkeypatch.setattr(
        module.h.CustodyInspector,
        "_check_custody",
        lambda self: pytest.fail("must refuse before Docker"),
    )
    events = [json.loads(line) for line in owner.journal.read_text().splitlines()]
    receipt = next(e for e in events if e["event"] == "create_result")
    if fault == "nonzero":
        receipt["code"] = 1
    elif fault == "timeout":
        receipt["timed_out"] = True
    elif fault == "wrong-id":
        receipt["stdout"] = "c" * 64
    elif fault == "duplicate":
        events.append(receipt)
    elif fault == "revoked":
        events.append({"event": "blocked"})
    else:
        owner.socket.rename(owner.socket.with_name("old"))
        owner.socket.mkdir(mode=0o777)
        owner.socket.chmod(0o777)
    owner.journal.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    with pytest.raises(module.h.Blocked):
        module.retained_pg(tmp_path / "kept", state)


def test_state_atomic_and_private(tmp_path):
    module = local()
    workspace = tmp_path / "kept"
    module.new_workspace(workspace)
    module.save_state(workspace, {"phase": "STARTING"})
    module.save_state(workspace, {"phase": "STOPPED"})
    assert json.loads((workspace / "workspace.json").read_text()) == {"phase": "STOPPED"}
    assert (workspace / "workspace.json").stat().st_mode & 0o777 == 0o600
    assert not (workspace / "workspace.json.pending").exists()


def test_location_denies_transient_long_symlink_and_ambient_pg(tmp_path, monkeypatch):
    module = local()
    with pytest.raises(module.h.Blocked):
        module.check_location(tmp_path)
    with pytest.raises(module.h.Blocked):
        module.check_location(Path("/" + "x" * 80))
    monkeypatch.setenv("PGHOST", "not-to-be-read")
    with pytest.raises(module.h.Blocked, match="AMBIENT_PG"):
        module.clean_environment(tmp_path)
    monkeypatch.delenv("PGHOST")
    env = module.clean_environment(tmp_path)
    assert not any(k.startswith(("PG", "AIDDOS_", "DDOSPECTOR_")) for k in env)
    assert env["HOME"] == str(tmp_path / "home")
    assert "HTTP_PROXY" not in env and "NODE_OPTIONS" not in env
    assert "PATH" in os.environ


def test_port_collision_never_adopts_or_probes_listener():
    import socket

    module = local()
    with socket.socket() as foreign:
        foreign.bind(("127.0.0.1", 0))
        foreign.listen()
        with pytest.raises(OSError):
            module.reserve_port(foreign.getsockname()[1])
    for port in (5173, 5180):
        with pytest.raises(module.h.Blocked):
            module.reserve_port(port)


def test_stop_preserves_database_and_requires_stopped_readback():
    module = local()
    calls = []

    class Owner:
        cid = "a" * 64

        def _check_custody(self):
            calls.append("validate")

        def call(self, *args, **kwargs):
            calls.append(args)

        def metadata(self):
            return {"Status": "exited"}

    module.stop_pg(Owner())
    assert calls == ["validate", ("stop", "--timeout", "10", "a" * 64), "validate"]


def test_command_line_is_explicit_no_daemon_or_automatic_worker():
    module = local()
    parser = module.parser()
    args = parser.parse_args(["create", "--workspace", "/durable/new"])
    assert args.web_port == 5175 and args.command == "create"
    with pytest.raises(SystemExit):
        parser.parse_args(["worker", "--workspace", "/durable/new"])
    with pytest.raises(SystemExit):
        parser.parse_args(["purge", "--workspace", "/durable/new"])


def test_lock_exclusion_and_shared_worker_shutdown_gate(tmp_path):
    import fcntl

    module = local()
    path = tmp_path / "activity.lock"
    path.touch(mode=0o600)
    with (
        module.locked(path, exclusive=False),
        module.locked(path, exclusive=False),
        pytest.raises(BlockingIOError),
        module.locked(path, exclusive=True),
    ):
        pytest.fail("exclusive admission while worker borrows")
    with module.locked(path, exclusive=True) as fd:
        assert os.fstat(fd).st_ino == path.stat().st_ino
        fcntl.flock(fd, fcntl.LOCK_UN)


def test_serve_normal_stop_keeps_draft_and_runs_no_worker(tmp_path, monkeypatch):
    from types import SimpleNamespace

    module = local()
    workspace = tmp_path / "kept"
    module.new_workspace(workspace)
    for name in ("session.lock", "activity.lock"):
        (workspace / name).touch(mode=0o600)
    module.save_state(workspace, {"format": 1, "root": str(ROOT), "phase": "NEW"})
    draft = workspace / "draft.json"
    draft.write_text('{"retained":true}')
    owner = module.PersistentPG(workspace)
    launches = []
    monkeypatch.setattr(owner, "create", lambda: None)
    monkeypatch.setattr(owner, "bootstrap", lambda: None)
    monkeypatch.setattr(module, "PersistentPG", lambda w: owner)
    monkeypatch.setattr(module, "retained_pg", lambda w, s: owner)
    monkeypatch.setattr(module, "stop_pg", lambda o: launches.append("stop-pg"))

    class Native:
        def __init__(self, *args):
            pass

        def launch(self, name, argv, extra=None):
            launches.append(argv)
            return SimpleNamespace(wait=lambda timeout: 0)

        def retire_all(self):
            launches.append("retire-native")

        def discover(self):
            pass

    monkeypatch.setattr(module, "NativeChildren", Native)
    monkeypatch.setattr(module, "launch_servers", lambda *a: ([], "http://127.0.0.1:5175"))
    args = SimpleNamespace(workspace=workspace, command="create", web_port=0)
    assert module.serve(args, lambda: True) == 0
    assert draft.read_text() == '{"retained":true}'
    assert json.loads((workspace / "workspace.json").read_text())["phase"] == "STOPPED"
    assert launches[0][-1] == "ddospector.runs.migrate"
    assert launches[-2:] == ["retire-native", "stop-pg"]
    assert all("worker" not in str(item) for item in launches)


def test_open_refuses_unclean_state_before_database_lookup(tmp_path, monkeypatch):
    from types import SimpleNamespace

    module = local()
    workspace = tmp_path / "kept"
    module.new_workspace(workspace)
    for name in ("session.lock", "activity.lock"):
        (workspace / name).touch(mode=0o600)
    module.save_state(workspace, {"phase": "RUNNING"})
    monkeypatch.setattr(module, "retained_pg", lambda *a: pytest.fail("no adoption"))
    args = SimpleNamespace(workspace=workspace, command="open", web_port=5175)
    with pytest.raises(module.h.Blocked, match="CLEAN_STOP"):
        module.serve(args, lambda: True)


def test_actual_cli_refuses_bad_run_id_before_workspace_access(tmp_path):
    import subprocess
    import sys

    path = tmp_path / "never-created"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/phase1_local.py"),
            "worker",
            "--workspace",
            str(path),
            "--run-id",
            "NOT-A-UUID",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 78
    assert not path.exists()


def test_worker_forwards_exact_id_once_and_preserves_nonzero(tmp_path, monkeypatch):
    from types import SimpleNamespace

    module = local()
    workspace = tmp_path / "kept"
    module.new_workspace(workspace)
    (workspace / "activity.lock").touch(mode=0o600)
    module.save_state(workspace, {"phase": "RUNNING", "supervisor": module.h.process_identity()})
    owner = SimpleNamespace(socket=workspace / "d/s", metadata=lambda: {"Status": "running"})
    monkeypatch.setattr(module, "retained_pg", lambda *a: owner)
    launches = []

    class Native:
        def __init__(self, *a):
            pass

        def launch(self, name, argv, extra):
            launches.append((argv, extra))
            return SimpleNamespace(poll=lambda: 69, wait=lambda: 69)

        def retire_all(self):
            pass

    monkeypatch.setattr(module, "NativeChildren", Native)
    run_id = "00000000-0000-4000-8000-000000000001"
    args = SimpleNamespace(workspace=workspace, run_id=run_id)
    assert module.worker(args, lambda: False) == 69
    assert len(launches) == 1
    assert launches[0][0][-3:] == ["ddospector.runs.worker", "--run-id", run_id]
    assert launches[0][1] == {"DDOSPECTOR_RUN_DB_SOCKET": str(owner.socket)}


def test_cli_removes_ambient_proxy_and_loader_settings_before_readiness(tmp_path, monkeypatch):
    from types import SimpleNamespace

    module = local()
    monkeypatch.setattr(
        module.os,
        "environ",
        {
            "HTTP_PROXY": "http://not-an-endpoint.invalid",
            "NODE_OPTIONS": "untrusted",
            "HOME": "/caller",
        },
    )
    args = SimpleNamespace(command="open", workspace=tmp_path)
    monkeypatch.setattr(module, "parser", lambda: SimpleNamespace(parse_args=lambda: args))
    monkeypatch.setattr(module, "check_location", lambda path: None)
    monkeypatch.setattr(module.signal, "signal", lambda *args: None)
    monkeypatch.setattr(module.os, "umask", lambda *args: None)
    observed = []
    monkeypatch.setattr(
        module, "serve", lambda *args: observed.append(dict(module.os.environ)) or 0
    )
    assert module.main() == 0
    assert "HTTP_PROXY" not in observed[0] and "NODE_OPTIONS" not in observed[0]
    assert observed[0]["HOME"] == str(tmp_path / "home")
