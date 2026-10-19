"""Effect-free orchestration probes: no Product, provider or browser target entry."""

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/chat"))


def load_capture():
    assert importlib.util.find_spec("chat_skill_capture") is not None, (
        "missing all-variant capture helper"
    )
    return importlib.import_module("chat_skill_capture")


@pytest.mark.parametrize("variant", ["agent", "target", "skill"])
def test_capture_discovers_runtime_before_native_admission(monkeypatch, variant):
    capture = load_capture()
    events = []
    target_entries = []

    def forbidden(*args, **kwargs):
        target_entries.append((args, kwargs))
        pytest.fail("harness ordering probe entered actual target")

    class App:
        def request(self, path):
            assert path == "/api/v1/chat/tools/runtime"
            events.append("runtime")
            assert events == ["bootstrap", "workspace", "runtime"]
            return 200, {
                "schema_version": 3,
                "supported": True,
                "requires_write_approval": True,
                "max_calls": 3,
                "max_writes": 1,
                "tools": [
                    "configuration_read",
                    "agent_profile_update",
                    "target_create",
                    "skill_create",
                ],
            }

    class Provider:
        scenarios = ()

    def bootstrap(*args):
        events.append("bootstrap")
        return {"HARNESS_ONLY": True}

    def workspace(*args):
        events.append("workspace")
        return {
            "meta": {"audit_retention": {"total_recorded": 0}},
            "agent_profile": {"skill_ids": []},
        }

    def grant(*args):
        events.append("grant")
        return {}, {}

    def boundary(*args):
        events.append("admission-boundary")
        raise RuntimeError("HARNESS_ONLY: no native admission")

    monkeypatch.setattr(capture, "CaptureProduct", forbidden)
    monkeypatch.setattr(capture, "ProviderFixture", forbidden)
    monkeypatch.setattr(capture.agent, "session", bootstrap)
    monkeypatch.setattr(capture.agent, "workspace", workspace)
    monkeypatch.setattr(capture.agent, "grant", grant)
    monkeypatch.setattr(capture.target, "target_grant", grant)
    monkeypatch.setattr(capture.skill, "skill_grant", grant)
    monkeypatch.setattr(capture.agent, "admit", boundary)
    with pytest.raises(RuntimeError, match="HARNESS_ONLY"):
        capture.run_variant(App(), Provider(), variant)
    assert events == ["bootstrap", "workspace", "runtime", "grant", "admission-boundary"]
    assert target_entries == []


@pytest.mark.parametrize("variant", ["Skill", "", "skills", "real"])
def test_closed_capture_variant_rejects_before_bootstrap(monkeypatch, variant):
    capture = load_capture()
    entries = []

    def forbidden(*args):
        entries.append(args)
        pytest.fail("invalid capture selector reached target")

    monkeypatch.setattr(capture.agent, "session", forbidden)
    with pytest.raises(ValueError):
        capture.run_variant(None, None, variant)
    assert entries == []


def test_capture_requires_separate_explicit_admission_before_effect(tmp_path, monkeypatch):
    capture = load_capture()
    entries = []

    def forbidden(*args):
        entries.append(args)
        pytest.fail("non-admitted capture entered target")

    monkeypatch.setattr(capture, "CaptureProduct", forbidden)
    monkeypatch.setattr(capture, "ProviderFixture", forbidden)
    monkeypatch.setattr(capture.harness, "manifest", forbidden)
    out = tmp_path / "not-created"
    with pytest.raises(SystemExit) as caught:
        capture.main(["--output", str(out)])
    assert caught.value.code == 2
    assert entries == [] and not out.exists()
