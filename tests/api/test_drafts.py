import json
from datetime import datetime

from fastapi.testclient import TestClient

from aiddos.api.app import create_app

TARGET = {"name": "방화벽", "address": "192.0.2.10", "kind": "DUT"}


def test_target_creation_is_durable_and_audited(client, state_path):
    response = client.post("/api/v1/targets", json=TARGET)
    assert response.status_code == 201
    target = response.json()
    assert set(target) == {"id", "name", "address", "kind", "status", "created_at"}
    assert target.items() >= TARGET.items()
    assert target["status"] == "draft"
    assert datetime.fromisoformat(target["created_at"]).tzinfo is not None
    assert state_path.is_file()
    assert state_path.stat().st_mode & 0o777 == 0o600
    with TestClient(create_app(state_path=state_path), base_url="http://localhost") as restarted:
        data = restarted.get("/api/v1/workspace").json()
        assert data["targets"] == [target]
        assert len(data["audit"]) == 1
        event = data["audit"][0]
        assert event["action"] == "target.created"
        assert event["entity_id"] == target["id"]
        assert event["origin"] == "local_operator"
        assert data["runs"] == []
    stored = json.loads(state_path.read_text())
    assert stored["format_version"] == 2  # AI-02 explicitly advances the persisted schema.
    assert stored["ai_settings"] == {
        "revision": 0,
        "profiles": [],
        "default_profile_id": None,
        "agent_profile_id": None,
        "updated_at": None,
        "execution_enabled": False,
        "connection_status": "not_tested",
    }
    assert stored["catalog_version"] == "1.0.0"
    assert not set(stored) & {"runs", "findings", "evidence", "profiles", "capabilities"}


def test_mcp_registration_is_durable_metadata_not_a_connection(client, state_path):
    drafts = []
    for endpoint, transport in [
        ("http://127.0.0.1:9999/mcp", "streamable_http"),
        ("lab-observer", "stdio"),
    ]:
        payload = {
            "name": "Observer",
            "endpoint": endpoint,
            "transport": transport,
            "usage_instructions": "Read approved counters only; no connection in UI-01.",
        }
        response = client.post("/api/v1/mcp-servers", json=payload)
        assert response.status_code == 201
        server = response.json()
        assert server.items() >= payload.items()
        assert server["status"] == "draft"
        assert server["tools_count"] == 0
        assert set(server) == {*payload, "id", "status", "tools_count", "created_at"}
        drafts.append(server)
    with TestClient(create_app(state_path=state_path), base_url="http://localhost") as restarted:
        data = restarted.get("/api/v1/workspace").json()
        assert data["mcp_servers"] == drafts
        assert [event["action"] for event in data["audit"]] == ["mcp_server.created"] * 2


def test_custom_skill_is_durable_versioned_guidance_not_permission(client, state_path):
    payload = {
        "name": "사용자 지침",
        "description": "Not translated",
        "category": "analysis",
        "instructions": "Review the retained evidence.\nNever invoke tools.",
    }
    response = client.post("/api/v1/skills", json=payload)
    assert response.status_code == 201
    skill = response.json()
    assert skill["version"] == "1.0.0"
    assert skill["status"] == "draft"
    assert skill["category"] == "analysis"
    for name in ("name", "description", "instructions"):
        assert skill[name] == {"en": payload[name], "ko": payload[name]}
    assert skill["allowed_operations"] == []
    assert skill["required_capabilities"] == []
    assert skill["safety_rules"]
    with TestClient(create_app(state_path=state_path), base_url="http://localhost") as restarted:
        data = restarted.get("/api/v1/workspace").json()
        assert data["skills"][-1] == skill
        assert len(data["skills"]) == 4
        assert data["audit"][0]["action"] == "skill.created"


def test_campaign_creation_requires_real_target_and_profile_and_survives_restart(
    client, state_path
):
    target = client.post("/api/v1/targets", json=TARGET).json()
    payload = {
        "name": "Policy review",
        "objective": "Prepare bounded lab validation",
        "target_id": target["id"],
        "profile_id": "tcpreplay-policy",
    }
    response = client.post("/api/v1/campaigns", json=payload)
    assert response.status_code == 201
    campaign = response.json()
    assert campaign.items() >= payload.items()
    assert campaign["status"] == "draft"
    assert set(campaign) == {*payload, "id", "created_at", "status"}
    before = state_path.read_bytes()
    for field in ("target_id", "profile_id"):
        response = client.post("/api/v1/campaigns", json={**payload, field: "missing"})
        assert response.status_code == 422
        assert response.json()["code"] == "INVALID_REFERENCE"
        assert state_path.read_bytes() == before
    with TestClient(create_app(state_path=state_path), base_url="http://localhost") as restarted:
        data = restarted.get("/api/v1/workspace").json()
        assert data["campaigns"] == [campaign]
        assert data["audit"][-1]["action"] == "campaign.created"
        assert data["runs"] == []
