"""Synthetic B1 wire witnesses; real domain validators, no inference."""

import pytest
from pydantic import TypeAdapter

from aiddos.api import chat_tool_models as m
from aiddos.api.models import TargetInput


def test_target_native_arguments_use_literal_domain_validator():
    value = dict(expected_draft_revision=0, name="한🌍", address="Example.COM.", kind="DUT")
    assert m.parse_arguments("target_create", m.encoded(value).decode()) == value
    assert (
        TargetInput.model_validate(
            {k: v for k, v in value.items() if k != "expected_draft_revision"}
        ).address
        == value["address"]
    )
    assert m.parse_arguments(
        "configuration_read", '{"kind":"targets","offset":100,"limit":10}'
    ) == dict(kind="targets", offset=100, limit=10)
    assert m.parse_arguments("configuration_read", '{"kind":"target","id":"old-target"}') == dict(
        kind="target", id="old-target"
    )
    assert TypeAdapter(m.ReadArguments).validate_python(dict(kind="skills", offset=103, limit=10))
    with pytest.raises(ValueError):
        TypeAdapter(m.ReadArguments).validate_python(dict(kind="targets", offset=0, limit=10))
    for mutation in (
        {"expected_draft_revision": True},
        {"expected_draft_revision": 1.0},
        {"id": "forged"},
        {"status": "draft"},
        {"kind": "probe"},
    ):
        with pytest.raises(ValueError):
            m.parse_arguments("target_create", m.encoded(value | mutation).decode())
    for raw in (
        '{"kind":"targets","offset":101,"limit":10}',
        '{"kind":"targets","offset":false,"limit":10}',
        '{"kind":"target","id":"x","id":"x"}',
    ):
        with pytest.raises(ValueError):
            m.parse_arguments("configuration_read", raw)


@pytest.mark.parametrize(
    "change",
    [
        "id",
        "time",
        "revision",
        "name",
        "address",
        "kind",
        "status",
        "origin",
        "action",
        "generated-proposal",
    ],
)
def test_target_receipt_and_proposal_are_exactly_linked(tmp_path, change):
    from copy import deepcopy

    from tests.chat.test_chat_target_ledger import admitted, approved, receipt_for
    from tests.chat.test_chat_tool_storage import STAMP

    storage, ledger, turn, _ = admitted(tmp_path)
    try:
        call = approved(ledger, turn)
        result = receipt_for(call)
        bad = deepcopy(call | dict(status="succeeded", result=result, finished_at=STAMP))
        if change == "id":
            bad["result"]["audit"]["entity_id"] = "wrong"
        elif change == "time":
            bad["result"]["audit"]["created_at"] = "2026-01-01T00:00:01+00:00"
        elif change == "revision":
            bad["result"].update(before_revision=1, after_revision=2)
        elif change == "status":
            bad["result"]["target"].pop("status")
        elif change == "origin":
            bad["result"]["audit"].pop("origin")
        elif change == "action":
            bad["result"]["audit"]["action"] = "agent_profile.updated"
        elif change == "generated-proposal":
            bad["proposal"]["after"]["id"] = "forged"
        else:
            bad["result"]["target"][change] = "SINK" if change == "kind" else "different"
        with pytest.raises(ValueError):
            m.ToolCall.model_validate(bad)
    finally:
        storage.close()


@pytest.mark.parametrize(
    "arguments,result",
    [
        (
            dict(kind="target", id="selected"),
            dict(
                kind="target",
                draft_revision=0,
                target=dict(
                    id="other",
                    name="x",
                    address="host",
                    kind="DUT",
                    status="draft",
                    created_at="2026-01-01T00:00:00+00:00",
                ),
            ),
        ),
        (
            dict(kind="targets", offset=0, limit=1),
            dict(kind="targets", draft_revision=0, items=[], next_offset=1),
        ),
    ],
)
def test_target_read_receipt_selector_and_pagination_match(tmp_path, arguments, result):
    from tests.chat.test_chat_target_ledger import admitted, native
    from tests.chat.test_chat_tool_storage import STAMP

    storage, ledger, turn, _ = admitted(tmp_path)
    try:
        call = ledger.request_call(
            turn["id"], native("configuration_read", arguments), timestamp=STAMP
        )
        ledger.start_read(call["id"], timestamp=STAMP)
        with pytest.raises(ValueError):
            ledger.finish_call(call["id"], "succeeded", result=result, timestamp=STAMP)
        assert ledger.call(call["id"])["status"] == "executing"
    finally:
        storage.close()


@pytest.mark.parametrize(
    "address",
    [
        "001.002.003.004",
        "123",
        "Example.COM.",
        "2001:db8::1",
        "::ffff:192.0.2.1",
        "fe80::1%eth0",
        "bad host",
        "a\n.example",
        "\x00",
        "256.0.0.1",
        "[::1]",
        " localhost ",
    ],
)
def test_literal_address_admission_matches_actual_domain_oracle(address):
    value = dict(name="name 🌍", address=address, kind="DUT")
    try:
        oracle = TargetInput.model_validate(value).model_dump()
    except ValueError:
        with pytest.raises(ValueError):
            m.parse_arguments(
                "target_create", m.encoded(value | {"expected_draft_revision": 0}).decode()
            )
    else:
        assert m.parse_arguments(
            "target_create", m.encoded(value | {"expected_draft_revision": 0}).decode()
        ) == oracle | {"expected_draft_revision": 0}


def test_raw_target_argument_limit_and_duplicate_escaped_keys():
    raw = m.encoded(
        dict(expected_draft_revision=0, name="literal", address="host", kind="DUT")
    ).decode()
    assert m.parse_arguments("target_create", " " * (16384 - len(raw.encode())) + raw)
    with pytest.raises(ValueError):
        m.parse_arguments("target_create", " " * (16385 - len(raw.encode())) + raw)
    for bad in (
        raw[:-1] + ',"na\\u006de":"literal"}',
        raw.replace('"name":"literal"', '"name":"\\ud800"'),
    ):
        with pytest.raises(ValueError):
            m.parse_arguments("target_create", bad)
