"""Raw tokens are distinct from decoded direct objects; protected fields stay absent."""

import json

import pytest

from tests.chat.test_chat_scenario_models import definition, module, protected


@pytest.mark.parametrize(
    "raw",
    [
        b'{"kind":"scenario_context","kind":"scenario_context"}',
        b'{"kind":"scenario_context","k\\u0069nd":"scenario_context"}',
        b'{"kind":"\\ud800"}',
        b'{"kind":"\xff"}',
        b'{"kind":NaN}',
        b'{"kind":Infinity}',
        b'{"kind":' + b"[" * 33 + b"0" + b"]" * 33 + b"}",
    ],
)
def test_native_raw_json_admission(raw):
    with pytest.raises(ValueError):
        module().parse_arguments("configuration_read", raw)


def test_raw_companion_admission_preserves_tokens_duplicates_and_size():
    from tests.chat.test_chat_scenario_models import grant

    m = module()
    assert hasattr(m, "parse_value"), "Missing bounded companion raw decoder"
    raw = json.dumps(grant()).encode()
    assert m.parse_value("GrantV4", raw) == grant()
    for altered in (
        raw.replace(b'"schema_version": 4', b'"schema_version": 4e0'),
        raw.replace(b'"schema_version": 4', b'"schema_version": 4, "schema_version": 4'),
        raw + b" " * 32768,
    ):
        with pytest.raises(ValueError):
            m.parse_value("GrantV4", altered)
        with pytest.raises(ValueError):
            m.GrantV4.model_validate_json(altered)
    with pytest.raises(ValueError):
        m.GrantV4.model_validate({**grant(), "created_at": "2026-02-30T00:00:00Z"})


def test_exact_raw_byte_caps_and_container_depth():
    m = module()
    raw = b'{"kind":"scenario_context"}'
    assert m.parse_arguments("configuration_read", raw + b" " * (16384 - len(raw))) == dict(
        kind="scenario_context"
    )
    with pytest.raises(ValueError):
        m.parse_arguments("configuration_read", raw + b" " * (16385 - len(raw)))
    with pytest.raises(ValueError):
        m.parse_value("ContextArgs", b"\xef\xbb\xbf" + raw)
    nested = 0
    for _ in range(32):
        nested = [nested]
    assert m.json_value(nested) == nested
    with pytest.raises(ValueError):
        m.json_value([nested])


def test_exact_canonical_record_byte_bound_with_non_bmp():
    from aiddos.api.scenarios import canonical, record_digest
    from tests.chat.scenario_model_wire import record

    m = module()
    value = record()
    value["definition"]["objective"] = ""
    remaining = 8192 - len(canonical(value))
    value["definition"]["objective"] = "😀" * (remaining // 4) + "a" * (remaining % 4)
    value["digest"] = record_digest(value)
    assert len(canonical(value)) == 8192
    assert m.ScenarioVersion.model_validate(value).model_dump() == value
    value["definition"]["objective"] += "a"
    value["digest"] = record_digest(value)
    assert len(canonical(value)) == 8193
    with pytest.raises(ValueError):
        m.ScenarioVersion.model_validate(value)


@pytest.mark.parametrize(
    "name", ["GrantInputV4", "CreateArgs", "AppendArgs", "RuntimeV4", "ReconcileInputV4"]
)
def test_every_integer_input_path_rejects_direct_coercion_and_noninteger_tokens(name):
    from copy import deepcopy

    from tests.chat.scenario_model_wire import examples

    m = module()
    original = examples()[name]

    def paths(value, path=()):
        if type(value) is int:
            yield path
        elif isinstance(value, dict):
            for key, item in value.items():
                yield from paths(item, (*path, key))
        elif isinstance(value, list):
            for key, item in enumerate(value):
                yield from paths(item, (*path, key))

    for path in paths(original):
        for replacement in (True, 1.0, "1"):
            value = deepcopy(original)
            target = value
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = replacement
            with pytest.raises(ValueError):
                m.validate_value(name, value)
        value = deepcopy(original)
        target = value
        for key in path[:-1]:
            target = target[key]
        number = target[path[-1]]
        target[path[-1]] = "NUMERIC_TOKEN"
        encoded = json.dumps(value).encode()
        for token in (f"{number}.0".encode(), f"{number}e0".encode()):
            with pytest.raises(ValueError):
                m.parse_value(name, encoded.replace(b'"NUMERIC_TOKEN"', token))


def test_native_parser_preserves_integer_tokens_and_protected_boundary():
    m = module()
    assert hasattr(m, "parse_arguments"), "Missing v4 lexical native ingress"
    value = dict(expected_scenario_revision=0, expected_draft_revision=0, definition=definition())
    raw = json.dumps(value).encode()
    assert m.parse_arguments("scenario_create", raw) == value
    for token in (b"4.0", b"4e0", b"true", b'"4"'):
        with pytest.raises(ValueError):
            m.parse_arguments(
                "scenario_create", raw.replace(b'"ip_version": 4', b'"ip_version": ' + token)
            )
    for key, item in protected().items():
        for location in (value, value["definition"]):
            location[key] = item
            with pytest.raises(ValueError):
                m.CreateArgs.model_validate(value)
            del location[key]
    for wrong in (4.0, True, "4"):
        value["definition"]["ip_version"] = wrong
        with pytest.raises(ValueError):
            m.CreateArgs.model_validate(value)


@pytest.mark.parametrize("name,field,wrong", [
    ("GrantV4", "schema_version", 4.0),
    ("GrantV4", "expected_sequence", False),
    ("RuntimeV4", "requires_write_approval", 1),
    ("RuntimeV4", "max_writes", True),
    ("ReconcileInputV4", "acknowledge_uncertain", 1),
    ("ReconcileReceiptV4", "write_fenced", 0),
    ("ScenarioRef", "version", True),
    ("ModelDefinition", "ip_version", "4"),
    ("ModelDefinition", "detection_required", 0),
    ("ListArgs", "offset", False),
    ("DetailArgs", "version", 1.0),
])
def test_model_revalidation_exact_scalars_match_dictionary_and_raw(name, field, wrong):
    from tests.chat.scenario_model_wire import examples

    m = module()
    model = getattr(m, name)
    original = examples()[name]
    bad = {**original, field: wrong}
    for value in (bad, model.model_validate(original).model_copy(update={field: wrong})):
        with pytest.raises(ValueError):
            m.validate_value(name, value)
        with pytest.raises(ValueError):
            model.model_validate(value)
    with pytest.raises(ValueError):
        m.parse_value(name, json.dumps(bad))


@pytest.mark.parametrize("name,tool", [
    ("ContextArgs", "configuration_read"),
    ("ListArgs", "configuration_read"),
    ("DetailArgs", "configuration_read"),
    ("CreateArgs", "scenario_create"),
    ("AppendArgs", "scenario_append"),
])
def test_model_revalidation_native_arguments_and_union_aliases(name, tool):
    from tests.chat.scenario_model_wire import examples

    m = module()
    original = examples()[name]
    instance = getattr(m, name).model_validate(original)
    assert m.validate_arguments(tool, instance) == original
    assert m.parse_arguments(tool, instance.model_dump_json()) == original
    bad = instance.model_copy(update={"target_id": "dut"})
    with pytest.raises(ValueError):
        m.validate_arguments(tool, bad)
    if tool == "configuration_read":
        assert m.validate_value("ReadArgs", instance) == original
        with pytest.raises(ValueError):
            m.validate_value("ReadArgs", bad)


@pytest.mark.parametrize("alias,name", [
    ("InputSource", "OperatorSource"), ("InputSource", "VersionSource"),
    ("ResultV4", "ContextResult"), ("ResultV4", "ListResult"),
    ("ResultV4", "DetailResult"), ("ResultV4", "CreatedResult"),
    ("ResultV4", "AppendedResult"),
])
def test_model_revalidation_named_union_closed_instances(alias, name):
    from tests.chat.scenario_model_wire import examples

    m = module()
    value = examples()[name]
    instance = getattr(m, name).model_validate(value)
    assert m.validate_value(alias, instance) == value
    with pytest.raises(ValueError):
        m.validate_value(alias, instance.model_copy(update={"unexpected": 1}))
