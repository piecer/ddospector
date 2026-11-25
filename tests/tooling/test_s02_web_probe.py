"""Harness-only admission tests: PG construction is a forbidden seam."""

import errno
import json
import sys
from pathlib import Path

import pytest

from tools import s02_harness as h
from tools import s02_web_probe as probe


def test_node_executable_resolves_the_installed_binary(tmp_path, monkeypatch):
    target = tmp_path / "node-real"
    target.write_text("#!/bin/sh\n")
    target.chmod(0o755)
    link = tmp_path / "node"
    link.symlink_to(target)
    monkeypatch.setattr(probe.shutil, "which", lambda name: str(link) if name == "node" else None)
    assert probe.node_executable() == str(target.resolve())


def test_node_executable_refuses_a_missing_runtime(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="Node.js executable not found"):
        probe.node_executable()


def test_node_commands_use_the_exact_resolved_executable():
    node = "/owned/node"
    assert probe.vite_argv(node, 5175) == [
        node,
        str(probe.ROOT / "web/node_modules/vite/bin/vite.js"),
        str(probe.ROOT / "web"),
        "--host",
        "127.0.0.1",
        "--port",
        "5175",
        "--strictPort",
    ]
    assert probe.playwright_argv(node, "full") == [
        node,
        str(probe.ROOT / "web/node_modules/playwright/cli.js"),
        "test",
        "--config",
        str(probe.ROOT / "web/playwright.runs.config.ts"),
        "--grep",
        "real EN/KO|exact-byte",
    ]


def test_node_preflight_refuses_before_socket_or_pg(tmp_path, monkeypatch):
    config = {
        "root": str(probe.ROOT),
        "runtime": str(tmp_path),
        "env": {"HOME": str(tmp_path / "home")},
        "authorized_web_port": 5175,
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    touched = []

    def forbidden(*args, **kwargs):
        touched.append("resource")
        raise AssertionError("resource acquisition preceded Node preflight")

    def missing():
        raise RuntimeError("Node.js executable not found on PATH")

    monkeypatch.setattr(probe, "node_executable", missing)
    monkeypatch.setattr(probe.socket, "socket", forbidden)
    monkeypatch.setattr(h, "Harness", forbidden)
    monkeypatch.setattr(sys, "argv", [probe.__file__, str(path), "full"])
    with pytest.raises(RuntimeError, match="Node.js executable not found"):
        probe.main()
    assert touched == []


def test_product_harnesses_do_not_pin_a_system_node_path():
    phase1 = probe.ROOT / "tools/phase1_local.py"
    for path in (Path(probe.__file__), phase1):
        source = path.read_text()
        assert '"/usr/bin/node"' not in source, path
        assert "node_executable" in source, path
    phase1_source = phase1.read_text()
    assert phase1_source.index("args.node = node_executable()") < phase1_source.index(
        "os.environ.clear()"
    )


@pytest.mark.parametrize("port", [None, 0, 5173, 5180, 9999, True, "5175"])
def test_full_mode_rejects_unapproved_origin_before_pg(tmp_path, monkeypatch, port):
    config = {
        "root": str(probe.ROOT),
        "runtime": str(tmp_path),
        "env": {"HOME": str(tmp_path / "home")},
    }
    if port is not None:
        config["authorized_web_port"] = port
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    touched = []

    def forbidden(*args, **kwargs):
        touched.append("PG")
        raise RuntimeError("FORBIDDEN_RESOURCE_ACQUISITION")

    monkeypatch.setattr(h, "Harness", forbidden)
    monkeypatch.setattr(sys, "argv", [str(Path(probe.__file__)), str(path), "full"])
    with pytest.raises(ValueError, match="explicit allowed test port"):
        probe.main()
    assert touched == []


def test_readiness_never_requests_without_owned_binding(monkeypatch):
    """A live child is not evidence that it owns the requested listener."""

    class Child:
        def poll(self):
            return None

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    requested = []

    def http(url, **kwargs):
        requested.append(url)
        return Response()

    monkeypatch.setattr(probe.urllib.request, "urlopen", http)
    with pytest.raises(RuntimeError, match="owned.*binding"):
        probe.ready("http://127.0.0.1:5175", Child())
    assert requested == []


def test_bind_collision_refuses_before_pg(tmp_path, monkeypatch):
    config = {
        "root": str(probe.ROOT),
        "runtime": str(tmp_path),
        "env": {"HOME": str(tmp_path / "home")},
        "authorized_web_port": 5175,
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    touched = []

    def forbidden(*args, **kwargs):
        touched.append("PG")
        raise RuntimeError("FORBIDDEN_PG")

    class Collision:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def bind(self, address):
            raise OSError(errno.EADDRINUSE, "owned model collision")

    monkeypatch.setattr(h, "Harness", forbidden)
    monkeypatch.setattr(probe.socket, "socket", Collision)
    monkeypatch.setattr(sys, "argv", [probe.__file__, str(path), "full"])
    with pytest.raises(OSError, match="owned model collision"):
        probe.main()
    assert touched == []


@pytest.mark.parametrize("number", [errno.ENOENT, errno.ESRCH, errno.EACCES])
def test_identity_narrow_transient_proc_errors(monkeypatch, number):
    def fail(*args, **kwargs):
        raise OSError(number, "synthetic proc read")

    monkeypatch.setattr(Path, "read_text", fail)
    if number == errno.EACCES:
        with pytest.raises(PermissionError):
            probe.identity(123)
    else:
        assert probe.identity(123) is None
