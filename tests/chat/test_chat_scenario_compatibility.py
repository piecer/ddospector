"""Frozen native-schema contract and unchanged historical export algorithms."""

import hashlib

import pytest

from aiddos.api.chat_models import encoded
from aiddos.api.chat_tool_runtime import schemas as old_schemas
from tests.chat.test_chat_scenario_models import definition, grant, module

EXPECTED_NATIVE = {
    "scenario_create": "c5e5f9511d8662e360ff503525cdb009a125831d8dbf57b85628ae5c1e2a7f4e",
    "scenario_append": "69c362e362202ec793632e120fd43cdabb3f1344f825aad2ab4aa159115654da",
}


def test_native_schema_exact_frozen_export_and_selected_tool():
    m = module()
    assert hasattr(m, "native_schemas"), "Missing standalone selected native schema export"
    for operation in ("scenario_create", "scenario_append"):
        g = grant()
        if operation == "scenario_append":
            g["intent"].update(
                operation=operation,
                expected_scenario_revision=1,
                base=dict(id="legacy-scenario", version=1, digest="a" * 64),
            )
            g["proposal_tools"] = [operation]
        result = m.native_schemas(g)
        assert [x["function"]["name"] for x in result] == ["configuration_read", operation]
        assert m.digest(result) == EXPECTED_NATIVE[operation]
        assert '"$ref"' not in str(result).replace("'", '"')
        for tool in ("configuration_read", operation):
            args = (
                dict(kind="scenario_context")
                if tool == "configuration_read"
                else dict(
                    expected_scenario_revision=g["intent"]["expected_scenario_revision"],
                    expected_draft_revision=0,
                    definition=definition(),
                )
            )
            if operation == "scenario_append" and tool == operation:
                args["base"] = g["intent"]["base"]
            assert m.allows_call(g, tool, args)
            if tool != "configuration_read":
                args["expected_draft_revision"] = 1
                assert not m.allows_call(g, tool, args)


@pytest.mark.parametrize(
    "version,expected",
    [
        (1, "9dc6d6811fd75c59bef77c473c2dc21d5de7224b393c3a224e85e972b2d1dc06"),
        (2, "51626c0f8002fe152c64ef816563bccbd63b87ac07e0b45fa39e16d46a632297"),
        (3, "f391464d50e42a0410838c50957747d31e5343f41e250c56a372469dc004e6e6"),
    ],
)
def test_old_versioned_exports_are_byte_identical(version, expected):
    module()
    value = (
        None
        if version == 1
        else dict(schema_version=version, scope={2: "target_create", 3: "skill_create"}[version])
    )
    assert hashlib.sha256(encoded(old_schemas(value))).hexdigest() == expected


def test_old_unversioned_export_is_byte_identical():
    module()
    assert (
        hashlib.sha256(encoded(old_schemas())).hexdigest()
        == "9dc6d6811fd75c59bef77c473c2dc21d5de7224b393c3a224e85e972b2d1dc06"
    )
