import pytest

TARGET = {"name": "Lab", "address": "localhost", "kind": "DUT"}
MCP = {
    "name": "Observer",
    "endpoint": "http://localhost:9999/mcp",
    "transport": "streamable_http",
    "usage_instructions": "Review only",
}
SKILL = {
    "name": "Review",
    "description": "Human guidance",
    "instructions": "Do not execute",
    "category": "planning",
}
PROFILE = {"name": "Reviewer", "skill_ids": [], "mcp_server_ids": []}
PREVIEW = {"goal": "Review the setup", "locale": "en"}


@pytest.mark.parametrize(
    "method,route,payload,field,limit",
    [
        ("post", "targets", TARGET, "name", 120),
        ("post", "targets", TARGET, "address", 255),
        ("post", "mcp-servers", MCP, "name", 120),
        ("post", "mcp-servers", MCP, "endpoint", 512),
        ("post", "mcp-servers", MCP, "usage_instructions", 8000),
        ("post", "skills", SKILL, "name", 120),
        ("post", "skills", SKILL, "description", 1000),
        ("post", "skills", SKILL, "instructions", 8000),
        ("put", "agent-profile", PROFILE, "name", 120),
        ("post", "agent/preview", PREVIEW, "goal", 2000),
        (
            "post",
            "campaigns",
            {"name": "N", "objective": "O", "target_id": "x", "profile_id": "tcpreplay-policy"},
            "objective",
            2000,
        ),
    ],
)
@pytest.mark.parametrize("invalid", ["", " \t\n", 7, None, "control\x00text", "oversized"])
def test_string_validation_is_bounded_strict_and_sanitized(
    client,
    state_path,
    method,
    route,
    payload,
    field,
    limit,
    invalid,
):
    value = "x" * (limit + 1) if invalid == "oversized" else invalid
    response = getattr(client, method)(f"/api/v1/{route}", json={**payload, field: value})
    assert response.status_code == 422
    assert response.json() == {"code": "VALIDATION_ERROR", "message": "Invalid request data."}
    assert not state_path.exists()


@pytest.mark.parametrize(
    "address",
    [
        "http://localhost",
        "bad host",
        "-host",
        "host_1",
        "a..b",
        "999.999.999.999",
        "192.168.0.999",
        "127.000.0.1",
        "::ffff:not-ip",
        "host/path",
        "a" * 64 + ".lab",
        "localhost\n",
        "fe80::1%eth0",
        " host",
        "h\u202eost",
    ],
)
def test_target_address_is_literal_ip_or_hostname(client, state_path, address):
    response = client.post("/api/v1/targets", json={**TARGET, "address": address})
    assert response.status_code == 422
    assert not state_path.exists()


@pytest.mark.parametrize(
    "address", ["localhost", "lab.example", "lab.example.", "192.0.2.1", "2001:db8::1", "::1"]
)
def test_valid_addresses_are_preserved_exactly(client, address):
    response = client.post("/api/v1/targets", json={**TARGET, "address": address})
    assert response.status_code == 201
    assert response.json()["address"] == address


@pytest.mark.parametrize(
    "endpoint,transport",
    [
        ("file:///etc/passwd", "streamable_http"),
        ("ftp://lab.local", "streamable_http"),
        ("https://user:secret@lab.local/mcp", "streamable_http"),
        ("https://lab.local/mcp#fragment", "streamable_http"),
        ("https://lab.local/mcp?token=secret", "streamable_http"),
        ("https://lab.local:99999/mcp", "streamable_http"),
        ("https:///mcp", "streamable_http"),
        ("http://bad host", "streamable_http"),
        ("http://lab.local\\evil", "streamable_http"),
        ("http://lab.local\nmcp", "streamable_http"),
        ("python -m server", "stdio"),
        ("../observer", "stdio"),
        ("Observer", "stdio"),
        ("a" * 65, "stdio"),
        ("$(touch pwned)", "stdio"),
        ("observer", "sse"),
    ],
)
def test_mcp_endpoint_is_not_credentials_or_an_executable_command(
    client, state_path, endpoint, transport
):
    response = client.post(
        "/api/v1/mcp-servers", json={**MCP, "endpoint": endpoint, "transport": transport}
    )
    assert response.status_code == 422
    assert not state_path.exists()


@pytest.mark.parametrize(
    "method,route,payload",
    [
        ("post", "targets", TARGET),
        ("post", "mcp-servers", MCP),
        ("post", "skills", SKILL),
        ("put", "agent-profile", PROFILE),
        ("post", "agent/preview", PREVIEW),
    ],
)
def test_unknown_fields_and_wrong_top_level_types_are_rejected(
    client, state_path, method, route, payload
):
    for value in ({**payload, "execution_enabled": True}, [], "text", True):
        response = getattr(client, method)(f"/api/v1/{route}", json=value)
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"
    assert not state_path.exists()


@pytest.mark.parametrize(
    "field,ids",
    [
        ("skill_ids", ["policy-validation"] * 2),
        ("skill_ids", ["policy-validation"] * 104),
        ("mcp_server_ids", ["unknown"] * 101),
        ("skill_ids", [1]),
        ("skill_ids", "policy-validation"),
    ],
)
def test_assignment_lists_have_raw_caps_strict_items_and_no_duplicates(
    client, state_path, field, ids
):
    response = client.put("/api/v1/agent-profile", json={**PROFILE, field: ids})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert not state_path.exists()


def test_exact_text_boundaries_and_multiline_guidance_are_accepted(client):
    response = client.post(
        "/api/v1/skills",
        json={
            **SKILL,
            "name": "이" * 120,
            "description": "d" * 1000,
            "instructions": "line\n" * 1600,
        },
    )
    assert response.status_code == 201
    assert len(response.json()["instructions"]["en"]) == 8000
    response = client.post("/api/v1/agent/preview", json={**PREVIEW, "goal": "g" * 2000})
    assert response.status_code == 200
