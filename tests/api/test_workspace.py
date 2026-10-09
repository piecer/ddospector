from fastapi.testclient import TestClient

from aiddos.api.app import create_app


def test_health_is_offline_and_get_does_not_create_state(tmp_path):
    path = tmp_path / "drafts.json"
    with TestClient(create_app(state_path=path), base_url="http://localhost") as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0-ui", "mode": "OFFLINE"}
    assert not path.exists()


def test_workspace_has_real_versioned_catalog_and_no_fabricated_activity(tmp_path):
    path = tmp_path / "drafts.json"
    with TestClient(create_app(state_path=path), base_url="http://localhost") as client:
        response = client.get("/api/v1/workspace")
        assert response.status_code == 200
        data = response.json()
        assert data["meta"] == {
            "version": "0.1.0-ui",
            "mode": "OFFLINE",
            "live_enabled": False,
            "live_limit": 1,
            "storage": "local_drafts",
            "deployment": "loopback_development",
            "audit_retention": {"limit": 500, "retained": 0, "total_recorded": 0, "dropped": 0},
        }
        assert data["capabilities"] == {
            "draft_editing": True,
            "context_preview": True,
            "live_execution": False,
            "mcp_connect": False,
            "llm_inference": False,
        }
        assert [s["id"] for s in data["skills"]] == [
            "policy-validation",
            "mcp-measurement",
            "evidence-analysis",
        ]
        for skill in data["skills"]:
            assert skill["version"] == "1.0.0"
            assert skill["status"] == "template"
            for locale in ("en", "ko"):
                assert len(skill["instructions"][locale]) > 100
                assert skill["safety_rules"][0][locale]
            assert skill["allowed_operations"]
            assert skill["required_capabilities"]
        assert [p["id"] for p in data["profiles"]] == [
            "tcpreplay-policy",
            "tcpdump-observer",
            "k6-http",
        ]
        assert all(p["status"] == "template" for p in data["profiles"])
        assert data["agent_profile"] == {
            "name": "Review agent",
            "skill_ids": [],
            "mcp_server_ids": [],
            "autonomy": "REVIEW_ONLY",
            "execution_enabled": False,
        }
        for name in (
            "targets",
            "instruments",
            "mcp_servers",
            "campaigns",
            "runs",
            "findings",
            "evidence",
            "approvals",
            "audit",
        ):
            assert data[name] == []
        data["skills"][0]["instructions"]["en"] = "mutated"
        assert client.get("/api/v1/workspace").json()["skills"][0] != data["skills"][0]
    assert not path.exists()
