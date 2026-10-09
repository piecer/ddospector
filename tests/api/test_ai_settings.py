import json
from copy import deepcopy
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from aiddos.api.app import create_app

URL = "/api/v1/ai-settings"
EMPTY = {
    "revision": 0,
    "profiles": [],
    "default_profile_id": None,
    "agent_profile_id": None,
    "updated_at": None,
    "execution_enabled": False,
    "connection_status": "not_tested",
}


def test_empty_ai_settings_is_closed_no_write_snapshot(client, state_path):
    response = client.get(URL)
    assert response.status_code == 200
    assert response.json() == EMPTY
    assert not state_path.exists()
    assert "ai_settings" not in client.get("/api/v1/workspace").json()


def put_image(snapshot=EMPTY):
    return {
        key: snapshot[key]
        for key in ("revision", "profiles", "default_profile_id", "agent_profile_id")
    }


def test_empty_put_publishes_v2_snapshot_and_same_file_audit(client, state_path):
    response = client.put(URL, json=put_image())
    assert response.status_code == 200
    saved = response.json()
    assert set(saved) == set(EMPTY)
    assert saved == {**EMPTY, "revision": 1, "updated_at": saved["updated_at"]}
    assert datetime.fromisoformat(saved["updated_at"]).utcoffset() is not None
    persisted = json.loads(state_path.read_text())
    assert persisted["format_version"] == 2
    assert persisted["ai_settings"] == saved
    assert persisted["audit_total"] == len(persisted["audit"]) == 1
    assert persisted["audit"][0] == {
        "id": persisted["audit"][0]["id"],
        "action": "ai_settings.updated",
        "entity_id": "ai-settings",
        "created_at": saved["updated_at"],
        "origin": "local_operator",
    }
    before = state_path.read_bytes()
    with TestClient(create_app(state_path=state_path), base_url="http://localhost") as restarted:
        assert restarted.get(URL).json() == saved
        assert restarted.get("/api/v1/workspace").json()["audit"] == persisted["audit"]
    assert state_path.read_bytes() == before


def test_stale_revision_has_no_write_or_audit(client, state_path):
    assert client.put(URL, json=put_image()).status_code == 200
    before = state_path.read_bytes()
    response = client.put(URL, json=put_image())
    assert response.status_code == 409
    assert response.json()["code"] == "AI_SETTINGS_CONFLICT"
    assert set(response.json()) == {"code", "message"}
    assert state_path.read_bytes() == before


def test_concurrent_app_instances_accept_exactly_one_revision(state_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    gate = Barrier(2)
    with (
        TestClient(create_app(state_path=state_path), base_url="http://localhost") as one,
        TestClient(create_app(state_path=state_path), base_url="http://localhost") as two,
    ):

        def save(client):
            gate.wait(timeout=5)
            return client.put(URL, json=put_image())

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(save, [one, two]))
        assert sorted(response.status_code for response in responses) == [200, 409]
        assert one.get(URL).json() == two.get(URL).json()
    stored = json.loads(state_path.read_text())
    assert stored["ai_settings"]["revision"] == 1
    assert stored["audit_total"] == len(stored["audit"]) == 1


PROFILE = {
    "id": "llm-first",
    "name": "First model",
    "format": "openai",
    "model": "vendor/model-literal",
    "base_url": "https://api.example.test/v1",
    "credential_env": "FUTURE_MODEL_API_KEY",
    "rate_per_second": 0,
    "rate_per_minute": 0,
    "context_window_k": 0,
    "streaming": True,
    "max_tokens": 0,
    "max_tokens_field": "",
    "thinking_type": "",
    "reasoning_effort": "",
    "retry": {key: {"attempts": 0, "interval_ms": 0} for key in ("connect", "empty", "stream")},
}


def image_with_profile(**changes):
    return {**put_image(), "profiles": [{**deepcopy(PROFILE), **changes}]}


def assert_rejected(client, state_path, payload):
    before = state_path.read_bytes() if state_path.exists() else None
    response = client.put(URL, json=payload)
    assert response.status_code == 422
    assert response.json() == {"code": "VALIDATION_ERROR", "message": "Invalid request data."}
    assert (state_path.read_bytes() if state_path.exists() else None) == before


@pytest.mark.parametrize("field", list(PROFILE))
def test_every_profile_field_is_required(client, state_path, field):
    payload = image_with_profile()
    del payload["profiles"][0][field]
    assert_rejected(client, state_path, payload)


@pytest.mark.parametrize("field", ["api_key", "headers", "enabled", "health", "latency", "extra"])
def test_profile_unknown_keys_are_rejected_not_persisted(client, state_path, field):
    assert_rejected(client, state_path, image_with_profile(**{field: "private-do-not-reflect"}))


@pytest.mark.parametrize(
    "field,maximum",
    [
        ("rate_per_second", 1000000),
        ("rate_per_minute", 1000000),
        ("context_window_k", 1000),
        ("max_tokens", 1000000),
    ],
)
@pytest.mark.parametrize("bad", [-1, True, False, "1", 1.0, None, [], "over"])
def test_profile_numeric_fields_are_strict_and_bounded(client, state_path, field, maximum, bad):
    assert_rejected(
        client, state_path, image_with_profile(**{field: maximum + 1 if bad == "over" else bad})
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"streaming": 1},
        {"streaming": "true"},
        {"streaming": None},
        {"format": "google"},
        {"format": "OPENAI"},
        {"format": None},
        {"max_tokens_field": "max_tokens"},
        {"thinking_type": "auto"},
        {"reasoning_effort": "automatic"},
        *[{"context_window_k": value} for value in (1, 31)],
        *[
            {"format": value, "max_tokens_field": "max_completion_tokens"}
            for value in ("anthropic", "openai-responses")
        ],
    ],
)
def test_protocol_options_and_context_capacity_are_validated(client, state_path, changes):
    assert_rejected(client, state_path, image_with_profile(**changes))


@pytest.mark.parametrize("layer", ["connect", "empty", "stream"])
@pytest.mark.parametrize(
    "bad",
    [
        "missing",
        "extra",
        "missing_attempts",
        "missing_interval",
        "extra_rule",
        "attempts_low",
        "attempts_high",
        "attempts_bool",
        "attempts_float",
        "attempts_string",
        "interval_low",
        "interval_high",
        "interval_bool",
    ],
)
def test_retry_layers_are_closed_required_strict_and_bounded(client, state_path, layer, bad):
    payload = image_with_profile()
    retry = payload["profiles"][0]["retry"]
    if bad == "missing":
        del retry[layer]
    elif bad == "extra":
        retry["other"] = retry[layer]
    elif bad == "missing_attempts":
        del retry[layer]["attempts"]
    elif bad == "missing_interval":
        del retry[layer]["interval_ms"]
    elif bad == "extra_rule":
        retry[layer]["backoff"] = True
    else:
        field, value = {
            "attempts_low": ("attempts", -2),
            "attempts_high": ("attempts", 21),
            "attempts_bool": ("attempts", True),
            "attempts_float": ("attempts", 1.0),
            "attempts_string": ("attempts", "1"),
            "interval_low": ("interval_ms", -1),
            "interval_high": ("interval_ms", 3600001),
            "interval_bool": ("interval_ms", False),
        }[bad]
        retry[layer][field] = value
    assert_rejected(client, state_path, payload)


def test_full_profile_crud_default_and_agent_binding_survive_restart(client, state_path):
    response = client.put(URL, json=image_with_profile())
    assert response.status_code == 200
    first = response.json()
    assert first["profiles"] == [PROFILE]
    assert first["default_profile_id"] is first["agent_profile_id"] is None
    second = {**deepcopy(PROFILE), "id": "llm-second", "name": "Second", "format": "anthropic"}
    payload = {
        **put_image(first),
        "profiles": [PROFILE, second],
        "default_profile_id": PROFILE["id"],
        "agent_profile_id": second["id"],
    }
    response = client.put(URL, json=payload)
    assert response.status_code == 200
    selected = response.json()
    assert selected["revision"] == 2
    assert selected["profiles"] == [PROFILE, second]
    with TestClient(create_app(state_path=state_path), base_url="http://localhost") as restarted:
        assert restarted.get(URL).json() == selected
        edited = {
            **second,
            "name": "수정 모델",
            "max_tokens": 123,
            "streaming": False,
            "thinking_type": "enabled",
            "reasoning_effort": "high",
        }
        response = restarted.put(URL, json={**put_image(selected), "profiles": [PROFILE, edited]})
        assert response.status_code == 200
        changed = response.json()
        assert changed["profiles"][1] == edited
        assert changed["default_profile_id"] == PROFILE["id"]
        assert changed["agent_profile_id"] == second["id"]
        # Clear the independent binding, then select the remaining profile before deletion.
        response = restarted.put(
            URL,
            json={
                **put_image(changed),
                "default_profile_id": second["id"],
                "agent_profile_id": None,
            },
        )
        assert response.status_code == 200
        unbound = response.json()
        response = restarted.put(URL, json={**put_image(unbound), "profiles": [edited]})
        assert response.status_code == 200
        deleted = response.json()
        response = restarted.put(
            URL, json={**put_image(deleted), "profiles": [], "default_profile_id": None}
        )
        assert response.status_code == 200
        final = response.json()
    with TestClient(create_app(state_path=state_path), base_url="http://localhost") as restarted:
        assert restarted.get(URL).json() == final
        assert final["profiles"] == []
        assert final["revision"] == 6
        assert final["execution_enabled"] is False
        assert final["connection_status"] == "not_tested"
        assert len(restarted.get("/api/v1/workspace").json()["audit"]) == 6


@pytest.mark.parametrize(
    "field,values",
    [
        ("id", ["", "A", "1a", "a.b", "a/b", "가", "a" * 65, "a\n", "a "]),
        ("credential_env", ["a", "1A", "A-B", "A.B", " KEY", "KEY ", "Ａ", "A" * 65, "KEY\n"]),
        (
            "name",
            [
                "",
                " ",
                " spaced",
                "spaced ",
                "a" * 121,
                "x\x00y",
                "x\x7fy",
                "x\x85y",
                "x\u202ey",
                "x\u200by",
            ],
        ),
        ("model", ["", " ", " spaced", "spaced ", "a" * 201, "x\ny", "x\ty", "x\u2066y"]),
    ],
)
def test_text_and_identifier_safety(client, state_path, field, values):
    for value in values:
        assert_rejected(client, state_path, image_with_profile(**{field: value}))


@pytest.mark.parametrize(
    "case",
    ["id", "casefold", "unicode_casefold", "default", "agent", "delete_default", "delete_agent"],
)
def test_snapshot_identity_uniqueness_and_selection_integrity(client, state_path, case):
    payload = image_with_profile()
    if case == "id":
        payload["profiles"].append({**PROFILE, "name": "Other"})
    elif case in {"casefold", "unicode_casefold"}:
        payload["profiles"][0]["name"] = "Straße" if case == "unicode_casefold" else "Name"
        payload["profiles"].append(
            {**PROFILE, "id": "other", "name": "STRASSE" if case == "unicode_casefold" else "NAME"}
        )
    elif case in {"default", "agent"}:
        payload[f"{case}_profile_id"] = "missing"
    else:
        field = "default_profile_id" if case == "delete_default" else "agent_profile_id"
        payload[field] = PROFILE["id"]
        created = client.put(URL, json=payload)
        assert created.status_code == 200
        payload = {**put_image(created.json()), "profiles": []}
    assert_rejected(client, state_path, payload)


@pytest.mark.parametrize("field", list(put_image()))
def test_every_put_field_is_required(client, state_path, field):
    payload = put_image()
    del payload[field]
    assert_rejected(client, state_path, payload)


@pytest.mark.parametrize(
    "field",
    ["api_key", "headers", "enabled", "updated_at", "execution_enabled", "connection_status"],
)
def test_put_rejects_output_only_and_unknown_fields(client, state_path, field):
    assert_rejected(client, state_path, {**put_image(), field: "private-do-not-reflect"})


@pytest.mark.parametrize("revision", [True, False, 0.0, "0", None, -1, 9007199254740991])
def test_put_revision_is_a_strict_safe_incrementable_integer(client, state_path, revision):
    assert_rejected(client, state_path, {**put_image(), "revision": revision})


@pytest.mark.parametrize(
    "changes",
    [
        {"profiles": None},
        {"profiles": {}},
        {"profiles": [None]},
        {"profiles": ["profile"]},
        {"agent_profile_id": False},
        {"default_profile_id": []},
    ],
)
def test_snapshot_rejects_non_contract_types(client, state_path, changes):
    assert_rejected(client, state_path, {**put_image(), **changes})


def test_exact_limits_and_independent_protocol_controls_round_trip(client, state_path):
    profiles = [
        {
            **deepcopy(PROFILE),
            "id": f"a_{index}-".ljust(64, "x"),
            "name": f"{index:02}" + "가" * 118,
            "model": "😀" * 200,
            "base_url": "",
            "credential_env": "A" * 64,
            "rate_per_second": 1000000,
            "rate_per_minute": 1000000,
            "context_window_k": 1000,
            "streaming": False,
            "max_tokens": 1000000,
            "max_tokens_field": "max_completion_tokens",
            "thinking_type": "disabled",
            "reasoning_effort": "max",
            "retry": {
                "connect": {"attempts": -1, "interval_ms": 0},
                "empty": {"attempts": 0, "interval_ms": 3600000},
                "stream": {"attempts": 20, "interval_ms": 1},
            },
        }
        for index in range(20)
    ]
    response = client.put(URL, json={**put_image(), "profiles": profiles})
    assert response.status_code == 200
    saved = response.json()
    assert saved["profiles"] == profiles
    assert client.get(URL).json() == saved
    assert_rejected(
        client,
        state_path,
        {**put_image(saved), "profiles": [*profiles, {**PROFILE, "id": "overflow"}]},
    )
    for protocol in ("anthropic", "openai", "openai-responses"):
        for effort in ("", "low", "medium", "high", "xhigh", "max"):
            profile = {
                **PROFILE,
                "format": protocol,
                "reasoning_effort": effort,
                "thinking_type": "enabled",
                "context_window_k": 32,
                "credential_env": "",
                "base_url": "",
            }
            response = client.put(URL, json={**put_image(saved), "profiles": [profile]})
            assert response.status_code == 200
            saved = response.json()
            assert saved["profiles"] == [profile]


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.test/v1",
        "//example.test/v1",
        "/v1",
        "https:///v1",
        "https://",
        "https://user:password@example.test/v1",
        "https://@example.test",
        "https://:pass@example.test",
        "https://example.test?",
        "https://example.test#",
        "https://example.test/v1?key=private",
        "https://example.test/v1#private",
        "https://example.test\\v1",
        "https://example.test/a b",
        "https://example.test/\tpath",
        "https://exam\nple.test",
        " https://example.test",
        "https://example.test/\u00a0",
        "https://example.test/\u200b",
        "https://example.test/\u202e",
        "https://example.test/\x00",
        "https://example.test/\x7f",
        "https://%65xample.test",
        "https://example%2etest",
        "https://[fe80::1%25eth0]",
        "https://bad_host",
        "https://-bad.test",
        "https://bad-.test",
        "https://a..test",
        "https://" + "a" * 64 + ".test",
        "https://999.999.999.999",
        "https://example.test:0",
        "https://example.test:65536",
        "https://example.test:",
        "https://example.test:abc",
        "https://example.test:+443",
        "https://[::1",
        "https://[::1]junk",
        "https://[::1]:",
        "https://[::1]:443:5",
        "https://::1",
        "https://example.test/" + "x" * 513,
        "https://exam／ple.test",
        "https://example.test／@evil.test",
    ],
)
def test_unsafe_base_urls_reject_without_effects(client, state_path, url):
    assert_rejected(client, state_path, image_with_profile(base_url=url))


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://localhost",
        "http://127.0.0.1:1/v1",
        "https://[::1]:65535/v1",
        "https://[2001:db8::1]/v1",
        "HTTPS://Example.TEST:443/CaseSensitive",
        "https://example.test./v1",
        "https://모델.example/수동",
        "https://xn--bcher-kva.example/v1",
        "https://example.test/v1/%20/%2F/%3F/%23",
        "https://example.test/한글/😀",
        "https://example.test/" + "x" * (512 - len("https://example.test/")),
    ],
)
def test_base_urls_are_literal_offline_metadata(client, state_path, url):
    response = client.put(URL, json=image_with_profile(base_url=url))
    assert response.status_code == 200
    saved = response.json()
    assert saved["profiles"][0]["base_url"] == url
    assert saved["connection_status"] == "not_tested"
    assert client.get(URL).json() == saved


# Frozen output of the unchanged UI-01 app at 389db9f4; not a v2 projection.
LEGACY_V1 = {
    "format_version": 1,
    "catalog_version": "1.0.0",
    "targets": [
        {
            "name": "Old target",
            "address": "192.0.2.10",
            "kind": "DUT",
            "id": "8457578f-9002-41d7-bd66-fad565b0a6b5",
            "status": "draft",
            "created_at": "2026-10-09T06:58:59.872143+00:00",
        }
    ],
    "mcp_servers": [
        {
            "name": "Old server",
            "endpoint": "observer",
            "transport": "stdio",
            "usage_instructions": "Metadata only",
            "id": "cfe885ea-f5dd-4c8b-93db-692306a43d35",
            "status": "draft",
            "tools_count": 0,
            "created_at": "2026-10-09T06:58:59.891440+00:00",
        }
    ],
    "skills": [
        {
            "id": "2f9621b0-a7f6-45fb-b2f6-34b8142c1aca",
            "name": {"en": "Old skill", "ko": "Old skill"},
            "description": {"en": "Preserve all original text", "ko": "Preserve all original text"},
            "instructions": {"en": "Review only", "ko": "Review only"},
            "version": "1.0.0",
            "category": "analysis",
            "status": "draft",
            "allowed_operations": [],
            "required_capabilities": [],
            "safety_rules": [
                {
                    "en": "Guidance is not authority. LIVE, MCP connections and "
                    "inference are disabled in UI-01.",
                    "ko": "지침은 실행 권한이 아닙니다. "
                    "UI-01에서는 LIVE, MCP 연결, 추론이 비활성화됩니다.",
                },
                {
                    "en": "Require operator scope approval and a future Safety Gate "
                    "before any device operation; never place secrets in "
                    "drafts or instructions.",
                    "ko": "장비 작업 전 운영자의 범위 승인과 향후 Safety Gate 검증이 필요합니다. "
                    "초안이나 지침에 "
                    "비밀 정보를 넣지 마세요.",
                },
            ],
        }
    ],
    "agent_profile": {
        "name": "Old review agent",
        "skill_ids": ["2f9621b0-a7f6-45fb-b2f6-34b8142c1aca"],
        "mcp_server_ids": ["cfe885ea-f5dd-4c8b-93db-692306a43d35"],
        "autonomy": "REVIEW_ONLY",
        "execution_enabled": False,
    },
    "campaigns": [
        {
            "name": "Old campaign",
            "objective": "Read only",
            "target_id": "8457578f-9002-41d7-bd66-fad565b0a6b5",
            "profile_id": "tcpreplay-policy",
            "id": "a0ad4ecd-069d-4ffc-8ea3-5930a150be54",
            "status": "draft",
            "created_at": "2026-10-09T06:58:59.918217+00:00",
        }
    ],
    "audit": [
        {
            "id": "55e7a36d-6477-42eb-8073-7a54b2eb18a9",
            "action": "target.created",
            "entity_id": "8457578f-9002-41d7-bd66-fad565b0a6b5",
            "created_at": "2026-10-09T06:58:59.872143+00:00",
            "origin": "local_operator",
        },
        {
            "id": "e62bd427-a2e4-401c-abb2-ac7d136b4625",
            "action": "mcp_server.created",
            "entity_id": "cfe885ea-f5dd-4c8b-93db-692306a43d35",
            "created_at": "2026-10-09T06:58:59.891440+00:00",
            "origin": "local_operator",
        },
        {
            "id": "ca5f2b5a-5f6c-4e71-b5c9-b536e3ede429",
            "action": "skill.created",
            "entity_id": "2f9621b0-a7f6-45fb-b2f6-34b8142c1aca",
            "created_at": "2026-10-09T06:58:59.900331+00:00",
            "origin": "local_operator",
        },
        {
            "id": "cac69d22-ff7e-45ad-afe3-911b93ee5be3",
            "action": "agent_profile.updated",
            "entity_id": "agent-profile",
            "created_at": "2026-10-09T06:58:59.909000+00:00",
            "origin": "local_operator",
        },
        {
            "id": "8736e344-b8f6-4c2c-83a3-43e6f5bdded1",
            "action": "campaign.created",
            "entity_id": "a0ad4ecd-069d-4ffc-8ea3-5930a150be54",
            "created_at": "2026-10-09T06:58:59.918217+00:00",
            "origin": "local_operator",
        },
    ],
    "audit_total": 5,
}


@pytest.mark.parametrize("mutation", ["ai", "old_target"])
def test_exact_v1_migrates_only_in_memory_until_authorized_write(client, state_path, mutation):
    original = deepcopy(LEGACY_V1)
    raw = json.dumps(original, ensure_ascii=False, indent=2).encode()
    state_path.write_bytes(raw)
    response = client.get(URL)
    assert response.status_code == 200
    assert response.json() == EMPTY
    workspace = client.get("/api/v1/workspace").json()
    for key in ("targets", "mcp_servers", "agent_profile", "campaigns", "audit"):
        assert workspace[key] == original[key]
    assert workspace["skills"][-1:] == original["skills"]
    assert state_path.read_bytes() == raw
    with TestClient(create_app(state_path=state_path), base_url="http://localhost") as restarted:
        assert restarted.get(URL).json() == EMPTY
        assert state_path.read_bytes() == raw
        if mutation == "ai":
            response = restarted.put(URL, json=image_with_profile())
            assert response.status_code == 200
        else:
            response = restarted.post(
                "/api/v1/targets", json={"name": "New", "address": "localhost", "kind": "DUT"}
            )
            assert response.status_code == 201
    stored = json.loads(state_path.read_text())
    assert stored["format_version"] == 2
    for key in ("catalog_version", "mcp_servers", "skills", "agent_profile", "campaigns"):
        assert stored[key] == original[key]
    assert stored["targets"][: len(original["targets"])] == original["targets"]
    assert stored["targets"] == (
        original["targets"] if mutation == "ai" else [*original["targets"], response.json()]
    )
    assert stored["audit"][:-1] == original["audit"]
    assert stored["audit_total"] == original["audit_total"] + 1
    assert stored["ai_settings"] == (response.json() if mutation == "ai" else EMPTY)
    assert client.get(URL).json() == stored["ai_settings"]


def nested_objects(value, path=()):
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from nested_objects(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from nested_objects(child, (*path, index))


LEGACY_REQUIRED_KEYS = [(path, key) for path, obj in nested_objects(LEGACY_V1) for key in obj]


@pytest.mark.parametrize("path,key", LEGACY_REQUIRED_KEYS)
def test_v1_migration_rejects_every_missing_original_field(client, state_path, path, key):
    image = deepcopy(LEGACY_V1)
    obj = image
    for part in path:
        obj = obj[part]
    del obj[key]
    assert_corrupt_preserved(client, state_path, image)


@pytest.mark.parametrize("path", [path for path, _ in nested_objects(LEGACY_V1)])
def test_v1_migration_rejects_unknown_keys_at_every_object(client, state_path, path):
    image = deepcopy(LEGACY_V1)
    obj = image
    for part in path:
        obj = obj[part]
    obj["unknown"] = "private-do-not-reflect"
    assert_corrupt_preserved(client, state_path, image)


def assert_corrupt_preserved(client, state_path, image):
    raw = json.dumps(image).encode()
    state_path.write_bytes(raw)
    for method, route, options in (
        ("get", URL, {}),
        ("get", "/api/v1/workspace", {}),
        ("put", URL, {"json": image_with_profile()}),
        (
            "post",
            "/api/v1/targets",
            {"json": {"name": "New", "address": "localhost", "kind": "DUT"}},
        ),
    ):
        response = getattr(client, method)(route, **options)
        assert response.status_code == 503
        assert response.json() == {
            "code": "STATE_CORRUPT",
            "message": "Draft state is invalid; restore it before editing.",
        }
        assert state_path.read_bytes() == raw


@pytest.mark.parametrize(
    "case",
    [
        "true_version",
        "float_version",
        "unknown_version",
        "ai_field",
        "ai_event",
        "duplicate",
        "agent_ref",
        "campaign_ref",
        "authority",
        "audit_ref",
        "audit_total",
        "counter_bool",
        "live",
        "tools_bool",
        "bad_timestamp",
    ],
)
def test_v1_migration_validates_original_invariants_not_just_keys(client, state_path, case):
    image = deepcopy(LEGACY_V1)
    if case == "true_version":
        image["format_version"] = True
    elif case == "float_version":
        image["format_version"] = 1.0
    elif case == "unknown_version":
        image["format_version"] = 3
    elif case == "ai_field":
        image["ai_settings"] = EMPTY
    elif case == "ai_event":
        image["audit"][0].update(action="ai_settings.updated", entity_id="ai-settings")
    elif case == "duplicate":
        image["targets"].append(image["targets"][0])
    elif case == "agent_ref":
        image["agent_profile"]["skill_ids"] = ["missing"]
    elif case == "campaign_ref":
        image["campaigns"][0]["target_id"] = "missing"
    elif case == "authority":
        image["skills"][0]["allowed_operations"] = ["execute"]
    elif case == "audit_ref":
        image["audit"][0]["entity_id"] = "missing"
    elif case == "audit_total":
        image["audit_total"] = 4
    elif case == "counter_bool":
        image["audit_total"] = True
    elif case == "live":
        image["agent_profile"]["execution_enabled"] = True
    elif case == "tools_bool":
        image["mcp_servers"][0]["tools_count"] = False
    elif case == "bad_timestamp":
        image["targets"][0]["created_at"] = "2026-10-09T01:00:00"
    assert_corrupt_preserved(client, state_path, image)


@pytest.mark.parametrize(
    "route,code",
    [
        (URL + "/test", "AI_CONNECTION_NOT_AVAILABLE"),
        (URL + "/models", "AI_CONNECTION_NOT_AVAILABLE"),
        ("/api/v1/runs", "LIVE_NOT_AVAILABLE"),
        ("/api/v1/agent/execute", "AGENT_EXECUTION_NOT_AVAILABLE"),
    ],
)
def test_denied_actions_never_access_corrupt_storage_or_credentials(
    client, state_path, monkeypatch, route, code
):
    import os

    from aiddos.api.store import DraftStore

    raw = b"corrupt storage must not matter to an execution denial"
    state_path.write_bytes(raw)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("Denial touched storage or credentials")

    original_getitem = os._Environ.__getitem__

    def guarded_getitem(self, key):
        if key == PROFILE["credential_env"]:
            return forbidden()
        return original_getitem(self, key)

    monkeypatch.setattr(DraftStore, "_read", forbidden)
    monkeypatch.setattr(DraftStore, "_write", forbidden)
    monkeypatch.setattr(os._Environ, "__getitem__", guarded_getitem)
    response = client.post(
        route,
        json={
            "profile_id": PROFILE["id"],
            "credential_env": PROFILE["credential_env"],
            "approved": True,
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == code
    assert set(response.json()) == {"code", "message"}
    assert calls == []
    assert state_path.read_bytes() == raw


V2_AI = {**EMPTY, "revision": 1, "profiles": [PROFILE], "updated_at": "2026-10-09T01:02:03+00:00"}
V2_REQUIRED_KEYS = [(path, key) for path, obj in nested_objects(V2_AI) for key in obj]


@pytest.mark.parametrize(
    "path,key",
    [((), "ai_settings"), *[(("ai_settings", *path), key) for path, key in V2_REQUIRED_KEYS]],
)
def test_v2_missing_ai_fields_are_corruption_never_legacy_defaults(client, state_path, path, key):
    image = {**deepcopy(LEGACY_V1), "format_version": 2, "ai_settings": deepcopy(V2_AI)}
    obj = image
    for part in path:
        obj = obj[part]
    del obj[key]
    assert_corrupt_preserved(client, state_path, image)


@pytest.mark.parametrize(
    "changes",
    [
        {"updated_at": None},
        {"updated_at": "2026-10-09T01:02:03"},
        {"execution_enabled": True},
        {"execution_enabled": 0},
        {"connection_status": "healthy"},
        {"health": "ok"},
        {"revision": True},
        {"revision": 1.0},
        {"revision": -1},
        {"revision": 9007199254740992},
        {"revision": 0},
        {"revision": 0, "updated_at": None},
        {"default_profile_id": "missing"},
        {"agent_profile_id": "missing"},
    ],
)
def test_v2_image_cannot_invent_health_or_invalid_revision_state(client, state_path, changes):
    image = {
        **deepcopy(LEGACY_V1),
        "format_version": 2,
        "ai_settings": {**deepcopy(V2_AI), **changes},
    }
    assert_corrupt_preserved(client, state_path, image)


def test_ai_projections_and_caller_inputs_are_not_aliased(state_path, monkeypatch):
    from aiddos.api.models import AISettingsInput
    from aiddos.api.store import DraftStore

    store = DraftStore(state_path)
    request = AISettingsInput.model_validate(image_with_profile())
    saved = store.save_ai_settings(request)
    expected = deepcopy(saved)
    request.profiles[0].retry.connect.attempts = 10
    saved["profiles"][0]["retry"]["empty"]["interval_ms"] = 99
    assert store.ai_snapshot() == expected
    state = store._read()
    monkeypatch.setattr(store, "_read", lambda: state)
    projection = store.ai_snapshot()
    projection["profiles"][0]["retry"]["stream"]["attempts"] = 17
    projection["profiles"].clear()
    assert store.ai_snapshot() == expected
    assert state.ai_settings.model_dump() == expected


def test_ai_revision_safe_ceiling_and_unrelated_drafts_do_not_rebase(client, state_path):
    assert client.put(URL, json=image_with_profile()).status_code == 200
    image = json.loads(state_path.read_text())
    image["ai_settings"]["revision"] = 9007199254740990
    state_path.write_text(json.dumps(image))
    snapshot = client.get(URL).json()
    assert snapshot["revision"] == 9007199254740990
    assert (
        client.post(
            "/api/v1/targets", json={"name": "Unrelated", "address": "localhost", "kind": "DUT"}
        ).status_code
        == 201
    )
    assert client.get(URL).json() == snapshot
    response = client.put(URL, json=put_image(snapshot))
    assert response.status_code == 200
    assert response.json()["revision"] == 9007199254740991
    assert_rejected(client, state_path, put_image(response.json()))
    assert client.get(URL).json() == response.json()


@pytest.mark.parametrize("failure", ["replace", "file_fsync", "directory_fsync"])
def test_ai_atomic_failure_keeps_settings_and_audit_together(
    client, state_path, monkeypatch, failure
):
    import os
    import stat

    first = client.put(URL, json=image_with_profile()).json()
    before = state_path.read_bytes()
    real_replace, real_fsync = os.replace, os.fsync
    calls = []

    def replace(*args):
        if failure == "replace":
            calls.append("replace")
            raise OSError("private path /must-not-leak")
        return real_replace(*args)

    def fsync(descriptor):
        kind = "directory_fsync" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file_fsync"
        if failure == kind:
            calls.append(kind)
            raise OSError("private path /must-not-leak")
        return real_fsync(descriptor)

    payload = {**put_image(first), "profiles": [{**PROFILE, "name": "Changed"}]}
    with monkeypatch.context() as faults:
        faults.setattr(os, "replace", replace)
        faults.setattr(os, "fsync", fsync)
        response = client.put(URL, json=payload)
    assert calls == [failure]
    assert response.status_code == 503
    assert "/must-not-leak" not in response.text
    assert list(state_path.parent.glob(".ui-drafts-*")) == []
    current = client.get(URL).json()
    stored = json.loads(state_path.read_text())
    if failure == "directory_fsync":
        assert response.json()["code"] == "STATE_COMMIT_UNCERTAIN"
        assert current["revision"] == 2
        assert current["profiles"] == payload["profiles"]
        assert stored["audit_total"] == len(stored["audit"]) == 2
        post_publish = state_path.read_bytes()
        assert client.put(URL, json=payload).status_code == 409
        assert state_path.read_bytes() == post_publish
    else:
        assert response.json()["code"] == "STATE_UNAVAILABLE"
        assert state_path.read_bytes() == before
        assert current == first
        assert stored["audit_total"] == len(stored["audit"]) == 1
    assert stored["ai_settings"] == current
    assert stored["audit"][-1]["created_at"] == current["updated_at"]


def test_ai_updates_share_audit_retention_and_safe_counter(client, state_path):
    assert client.put(URL, json=image_with_profile()).status_code == 200
    image = json.loads(state_path.read_text())
    event = image["audit"][0]
    image["audit"] = [{**event, "id": f"event-{index}"} for index in range(500)]
    image["audit_total"] = 500
    state_path.write_text(json.dumps(image))
    snapshot = client.get(URL).json()
    response = client.put(URL, json=put_image(snapshot))
    assert response.status_code == 200
    stored = json.loads(state_path.read_text())
    assert stored["audit"][:-1] == image["audit"][1:]
    assert stored["audit"][-1]["action"] == "ai_settings.updated"
    assert len(stored["audit"]) == 500
    assert stored["audit_total"] == 501
    stored["audit_total"] = 9007199254740991
    state_path.write_text(json.dumps(stored))
    before = state_path.read_bytes()
    rejected = client.put(URL, json=put_image(response.json()))
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "AUDIT_LIMIT_REACHED"
    assert state_path.read_bytes() == before
    assert client.get(URL).status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        b'{"revision":0,"revision":1}',
        b'{"profiles":[{"retry":{"connect":{"attempts":0,"attempts":1}}}]}',
        b'{"revision":NaN}',
        b'{"revision":Infinity}',
        b"\xff",
        b"{",
        b"[]",
        b"null",
        b"0",
        b"[" * 33 + b"]" * 33,
    ],
)
def test_ai_put_uses_existing_strict_json_boundary(client, state_path, body):
    response = client.put(URL, content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert response.json() == {"code": "VALIDATION_ERROR", "message": "Invalid request data."}
    assert not state_path.exists()


@pytest.mark.parametrize("field", ["name", "model", "base_url", "id", "credential_env"])
def test_unpaired_unicode_surrogates_are_rejected_without_reflection(client, state_path, field):
    body = json.dumps(image_with_profile(**{field: "unsafe\ud800"})).encode()
    response = client.put(URL, content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert response.json() == {"code": "VALIDATION_ERROR", "message": "Invalid request data."}
    assert not state_path.exists()


@pytest.mark.parametrize(
    "headers,status,code",
    [
        ({"Origin": "https://evil.example"}, 403, "ORIGIN_NOT_ALLOWED"),
        ({"Host": "evil.example"}, 403, "HOST_NOT_ALLOWED"),
        ({"Content-Type": "text/plain"}, 415, "JSON_REQUIRED"),
        ({"Content-Type": "application/json; charset=utf-16"}, 415, "JSON_REQUIRED"),
        ({"Content-Encoding": "gzip"}, 415, "UNSUPPORTED_ENCODING"),
        ({"Content-Length": "262145"}, 413, "BODY_TOO_LARGE"),
    ],
)
def test_ai_put_retains_host_origin_encoding_and_size_boundaries(
    client, state_path, headers, status, code
):
    response = client.put(URL, json=image_with_profile(), headers=headers)
    assert response.status_code == status
    assert response.json()["code"] == code
    assert not state_path.exists()


def test_ai_body_byte_limit_is_inclusive(client, state_path):
    body = json.dumps(image_with_profile()).encode()
    response = client.put(
        URL,
        content=body + b" " * (262144 - len(body)),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    assert response.status_code == 200
    before = state_path.read_bytes()
    response = client.put(URL, content=b" " * 262145, headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert state_path.read_bytes() == before


def test_credential_reference_is_never_resolved_by_read_write_or_restart(
    client, state_path, monkeypatch
):
    import os

    original_getitem = os._Environ.__getitem__
    lookups = []

    def guarded_getitem(self, key):
        if key == PROFILE["credential_env"]:
            lookups.append(key)
            raise AssertionError("Credential references must never be resolved")
        return original_getitem(self, key)

    monkeypatch.setattr(os._Environ, "__getitem__", guarded_getitem)
    saved = client.put(URL, json=image_with_profile())
    assert saved.status_code == 200
    assert saved.json()["profiles"][0]["credential_env"] == PROFILE["credential_env"]
    with TestClient(create_app(state_path=state_path), base_url="http://localhost") as restarted:
        assert restarted.get(URL).json() == saved.json()
        for path in (URL + "/test", URL + "/models"):
            assert restarted.post(path, json={}).status_code == 409
    assert lookups == []
    assert set(json.loads(state_path.read_text())["ai_settings"]["profiles"][0]) == set(PROFILE)


@pytest.mark.parametrize("missing", [None, *LEGACY_V1])
def test_empty_v1_still_requires_all_original_keys(client, state_path, missing):
    image = deepcopy(LEGACY_V1)
    for key in ("targets", "mcp_servers", "skills", "campaigns", "audit"):
        image[key] = []
    image["audit_total"] = 0
    image["agent_profile"]["skill_ids"] = []
    image["agent_profile"]["mcp_server_ids"] = []
    if missing is not None:
        del image[missing]
        assert_corrupt_preserved(client, state_path, image)
    else:
        raw = json.dumps(image).encode()
        state_path.write_bytes(raw)
        assert client.get(URL).json() == EMPTY
        assert state_path.read_bytes() == raw


def test_failed_first_mutation_keeps_genuine_v1_bytes(client, state_path, monkeypatch):
    import os

    raw = json.dumps(LEGACY_V1).encode()
    state_path.write_bytes(raw)
    calls = []

    def fail_replace(*args):
        calls.append(True)
        raise OSError("private")

    monkeypatch.setattr(os, "replace", fail_replace)
    response = client.put(URL, json=image_with_profile())
    assert response.status_code == 503
    assert response.json()["code"] == "STATE_UNAVAILABLE"
    assert calls == [True]
    assert state_path.read_bytes() == raw
    assert client.get(URL).json() == EMPTY
    assert list(state_path.parent.glob(".ui-drafts-*")) == []
