import pytest


@pytest.mark.parametrize(
    "route,payload,collection,expected",
    [
        ("targets", {"name": "Lab", "address": "localhost", "kind": "DUT"}, "targets", 100),
        (
            "mcp-servers",
            {
                "name": "Observer",
                "endpoint": "observer",
                "transport": "stdio",
                "usage_instructions": "Review only",
            },
            "mcp_servers",
            100,
        ),
        (
            "skills",
            {
                "name": "Guide",
                "description": "Scope",
                "instructions": "Review",
                "category": "planning",
            },
            "skills",
            103,
        ),
        ("campaigns", None, "campaigns", 100),
    ],
)
def test_each_draft_collection_has_atomic_100_item_admission_cap(
    client, state_path, route, payload, collection, expected
):
    if route == "campaigns":
        target = client.post(
            "/api/v1/targets", json={"name": "Lab", "address": "localhost", "kind": "DUT"}
        ).json()
        payload = {
            "name": "Plan",
            "objective": "Review",
            "target_id": target["id"],
            "profile_id": "tcpreplay-policy",
        }
    for index in range(100):
        response = client.post(f"/api/v1/{route}", json={**payload, "name": str(index)})
        assert response.status_code == 201
    before = state_path.read_bytes()
    rejected = client.post(f"/api/v1/{route}", json=payload)
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "DRAFT_LIMIT_REACHED"
    assert state_path.read_bytes() == before
    workspace = client.get("/api/v1/workspace").json()
    assert len(workspace[collection]) == expected
    if collection == "skills":
        identifiers = [skill["id"] for skill in workspace["skills"]]
        assert (
            client.put(
                "/api/v1/agent-profile",
                json={
                    "name": "All guidance",
                    "skill_ids": identifiers,
                    "mcp_server_ids": [],
                },
            ).status_code
            == 200
        )
        preview = client.post("/api/v1/agent/preview", json={"goal": "Review all", "locale": "en"})
        assert preview.status_code == 200
        assert preview.json()["skill_ids"] == identifiers


def test_audit_counter_cannot_overflow_json_safe_integer_and_poison_state(client, state_path):
    import json
    from uuid import uuid4

    payload = {"name": "Review", "skill_ids": [], "mcp_server_ids": []}
    assert client.put("/api/v1/agent-profile", json=payload).status_code == 200
    value = json.loads(state_path.read_text())
    event = value["audit"][0]
    value["audit"] = [{**event, "id": str(uuid4())} for _ in range(500)]
    value["audit_total"] = 9007199254740991
    state_path.write_text(json.dumps(value))
    before = state_path.read_bytes()
    response = client.put("/api/v1/agent-profile", json=payload)
    assert response.status_code == 409
    assert response.json()["code"] == "AUDIT_LIMIT_REACHED"
    assert state_path.read_bytes() == before
    assert client.get("/api/v1/workspace").status_code == 200


def test_audit_retains_latest_500_with_truthful_retention_metadata(client, state_path):
    payload = {"name": "Review", "skill_ids": [], "mcp_server_ids": []}
    for _ in range(500):
        assert client.put("/api/v1/agent-profile", json=payload).status_code == 200
    before = client.get("/api/v1/workspace").json()["audit"]
    assert len(before) == 500
    for _ in range(2):
        assert client.put("/api/v1/agent-profile", json=payload).status_code == 200
    workspace = client.get("/api/v1/workspace").json()
    assert len(workspace["audit"]) == 500
    assert workspace["audit"][:498] == before[2:]
    assert workspace["meta"]["audit_retention"] == {
        "limit": 500,
        "retained": 500,
        "total_recorded": 502,
        "dropped": 2,
    }
    assert len({event["id"] for event in workspace["audit"]}) == 500
