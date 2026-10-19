"""Finite scope producer contracts and native parser, no network or domain execution."""

import json

import pytest
from pydantic import TypeAdapter

from aiddos.api import chat_tool_models as m
from aiddos.api.chat_tool_runtime import schemas, tool_prompt
from aiddos.api.chat_tool_transport import NativeParser
from tests.chat.test_chat_skill_models import arguments


@pytest.mark.parametrize(
    "version,write,reads",
    [
        (1, "agent_profile_update", ["agent_profile", "skills", "skill"]),
        (2, "target_create", ["targets", "target"]),
        (3, "skill_create", ["skills", "skill"]),
    ],
)
def test_scope_selected_schemas_never_admit_other_writes(version, write, reads):
    grant = dict(schema_version=version)
    if version != 1:
        grant["scope"] = write
    exported = schemas(grant)
    assert [s["function"]["name"] for s in exported] == ["configuration_read", write]
    assert exported[0]["function"]["parameters"]["properties"]["kind"]["enum"] == reads
    assert exported[1]["function"]["parameters"]["additionalProperties"] is False
    assert write.split("_")[0].lower() in tool_prompt(grant).lower()
    if version == 3:
        assert set(exported[1]["function"]["parameters"]["required"]) == set(arguments())
        assert "execution" in tool_prompt(grant)
        with pytest.raises(ValueError):
            TypeAdapter(m.SkillReadArguments).validate_python(dict(kind="agent_profile"))
        assert TypeAdapter(m.SkillReadArguments).validate_python(
            dict(kind="skill", id="policy-validation")
        )


def test_unknown_or_mismatched_scope_never_falls_back_to_agent():
    for grant in (
        dict(schema_version=4),
        dict(schema_version=3, scope="target_create"),
        dict(schema_version=True),
        dict(schema_version=3.0, scope="skill_create"),
    ):
        with pytest.raises(ValueError):
            schemas(grant)
        with pytest.raises(ValueError):
            tool_prompt(grant)


def test_native_skill_transport_preserves_raw_padding_and_identifier():
    raw = m.encoded(arguments()).decode() + " \t\r\n"
    wire = json.dumps(
        dict(
            choices=[
                dict(
                    index=0,
                    finish_reason="tool_calls",
                    message=dict(
                        role="assistant",
                        content="inert narrative",
                        tool_calls=[
                            dict(
                                id='escaped"\\',
                                type="function",
                                function=dict(name="skill_create", arguments=raw),
                            )
                        ],
                    ),
                )
            ]
        )
    ).encode()
    events = NativeParser().completion(wire)
    assert events[-2] == dict(type="call", id='escaped"\\', name="skill_create", arguments=raw)
