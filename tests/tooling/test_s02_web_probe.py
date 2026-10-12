"""Harness-only admission tests: PG construction is a forbidden seam."""

import errno
import json
import sys
from pathlib import Path

import pytest

from tools import s02_harness as h
from tools import s02_web_probe as probe


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
