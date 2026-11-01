"""Native capture admission follows the public runtime tool registry."""

from types import SimpleNamespace

import chat_skill_capture as capture
import pytest


class MetadataAccepted(Exception):
    pass


def probe(monkeypatch, version, tools, variant):
    runtime = {
        "schema_version": version,
        "supported": True,
        "requires_write_approval": True,
        "max_calls": 3,
        "max_writes": 1,
        "tools": tools,
    }
    monkeypatch.setattr(capture.agent, "session", lambda *args: {})
    monkeypatch.setattr(capture.agent, "workspace", lambda *args: {})

    def plan(*args, **kwargs):
        raise MetadataAccepted

    monkeypatch.setattr(capture.harness, "plan", plan)
    app = SimpleNamespace(request=lambda path: (200, runtime))
    capture.run_variant(app, SimpleNamespace(), variant)


LEGACY_TOOLS = ["configuration_read", "agent_profile_update", "target_create", "skill_create"]
SCENARIO_TOOLS = LEGACY_TOOLS + ["scenario_create", "scenario_append"]


@pytest.mark.parametrize("variant", capture.VARIANTS)
@pytest.mark.parametrize("version,tools", [(3, LEGACY_TOOLS), (4, SCENARIO_TOOLS)])
def test_capture_accepts_supported_public_metadata(monkeypatch, variant, version, tools):
    with pytest.raises(MetadataAccepted):
        probe(monkeypatch, version, tools, variant)


@pytest.mark.parametrize("version", [True, 4.0, 2, 5])
def test_capture_rejects_unrecognized_runtime_version(monkeypatch, version):
    with pytest.raises(AssertionError):
        probe(monkeypatch, version, SCENARIO_TOOLS, "skill")


@pytest.mark.parametrize(
    "tools", [LEGACY_TOOLS, SCENARIO_TOOLS[::-1], SCENARIO_TOOLS + ["execute"]]
)
def test_capture_requires_exact_v4_tool_registry(monkeypatch, tools):
    with pytest.raises(AssertionError):
        probe(monkeypatch, 4, tools, "skill")
