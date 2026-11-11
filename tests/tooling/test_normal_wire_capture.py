"""Effect-free controls for the opt-in normal wire capture tool, not PG acceptance."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools import normal_wire as wire

ROOT = Path(__file__).resolve().parents[2]


def test_capture_help_is_available_without_acquiring_resources(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/normal_wire.py"), "--help"],
        cwd=ROOT, capture_output=True, text=True, timeout=5,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
             "TMPDIR": str(tmp_path), "LANG": "C.UTF-8",
             "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert "--output" in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_capture_requires_an_explicit_output_before_resource_acquisition(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/normal_wire.py")],
        cwd=ROOT, capture_output=True, text=True, timeout=5,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "TMPDIR": str(tmp_path),
             "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 2
    assert "--output" in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_existing_output_is_not_adopted_or_overwritten(tmp_path, monkeypatch):
    from tools import s02_harness, s02_web_probe

    sentinel = tmp_path / "caller-owned"
    sentinel.write_text("preserve")
    monkeypatch.setattr(s02_harness, "Harness", lambda *_: pytest.fail("PG acquired"))
    monkeypatch.setattr(s02_web_probe, "NativeChildren", lambda *_: pytest.fail("owner acquired"))
    with pytest.raises(FileExistsError):
        wire.capture(tmp_path)
    assert sentinel.read_text() == "preserve"


def test_model_failure_retires_native_tree_before_pg_and_restores_signals(tmp_path, monkeypatch):
    import signal

    from tools import s02_harness, s02_web_probe

    events = []
    primary = RuntimeError("synthetic probe launch fault")
    handlers = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}

    class Native:
        closed = False
        clean = False

        def __init__(self, *_):
            events.append("native-owner")

        def launch(self, *_):
            raise primary

        def retire_all(self):
            events.append("native-retired")
            self.closed = self.clean = True

    class PG:
        def __init__(self, path):
            self.directory = self.socket = path
            self.owner_process = {}

        def __enter__(self):
            events.append("pg-acquired")
            return self

        def bootstrap(self):
            events.append("pg-ready")

        def __exit__(self, *_):
            events.append("pg-retired")

    monkeypatch.setattr(s02_harness, "Harness", PG)
    monkeypatch.setattr(s02_web_probe, "NativeChildren", Native)
    with pytest.raises(RuntimeError) as caught:
        wire.capture(tmp_path / "new")
    assert caught.value is primary
    assert events == ["native-owner", "pg-acquired", "pg-ready", "native-retired", "pg-retired"]
    assert handlers == {s: signal.getsignal(s) for s in handlers}
    assert not (tmp_path / "new/normal-wire-current.json").exists()


@pytest.mark.parametrize("script,required", [
    ("import aiddos.runs.worker", "aiddos.runs.worker"),
    ("import aiddos.api.app; import scenario_producer", "aiddos.api.app"),
])
def test_actual_origin_observer_binds_checkout_without_secrets(tmp_path, script, required):
    target = tmp_path / "origins.json"
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "TMPDIR": str(tmp_path),
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
           "PYTHONPATH": os.pathsep.join(str(ROOT / p) for p in
               ("tools/normal_wire_observer", "src", "tests/api")),
           "NORMAL_WIRE_ROOT": str(ROOT), "NORMAL_WIRE_ORIGIN": str(target),
           "DDOSPECTOR_UI_STATE_PATH": str(tmp_path / "drafts.json"),
           "FAKE_SECRET": "must-not-appear-in-receipt"}
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    raw = target.read_text()
    assert env["FAKE_SECRET"] not in raw
    value = json.loads(raw)
    assert value["root"] == str(ROOT)
    assert value["identity"]["pid"] == value["pid"]
    assert required in value["modules"]
    source = wire.source_manifest(ROOT)
    for module in value["modules"].values():
        assert module["sha256"] == source[module["path"]]
