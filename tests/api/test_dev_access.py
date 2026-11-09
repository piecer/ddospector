import pytest
from fastapi.testclient import TestClient

from aiddos.api.app import create_app

ORIGIN = "http://10.0.0.2:5173"


def test_explicit_development_origin_allows_lan_mutation(monkeypatch, state_path):
    monkeypatch.setenv("DDOSPECTOR_ALLOW_INSECURE_DEV", "1")
    monkeypatch.setenv("DDOSPECTOR_DEV_ORIGIN", ORIGIN)
    with TestClient(create_app(state_path=state_path), base_url=ORIGIN) as client:
        response = client.post(
            "/api/v1/targets",
            json={"name": "LAN", "address": "localhost", "kind": "DUT"},
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 201
        assert response.headers["access-control-allow-origin"] == ORIGIN
        assert state_path.exists()


@pytest.fixture
def lan(monkeypatch, state_path):
    monkeypatch.setenv("DDOSPECTOR_ALLOW_INSECURE_DEV", "1")
    monkeypatch.setenv("DDOSPECTOR_DEV_ORIGIN", ORIGIN)
    with TestClient(create_app(state_path=state_path), base_url=ORIGIN) as client:
        yield client


@pytest.mark.parametrize("flag", [None, "", "0"])
def test_disabled_mode_preserves_loopback_only(monkeypatch, state_path, flag):
    for prefix in ("DDOSPECTOR", "AIDDOS"):
        monkeypatch.delenv(f"{prefix}_ALLOW_INSECURE_DEV", raising=False)
    if flag is not None:
        monkeypatch.setenv("DDOSPECTOR_ALLOW_INSECURE_DEV", flag)
    monkeypatch.setenv("DDOSPECTOR_DEV_ORIGIN", ORIGIN)
    with TestClient(create_app(state_path=state_path), base_url=ORIGIN) as client:
        assert client.get("/api/v1/health").json()["code"] == "HOST_NOT_ALLOWED"
        response = client.get("/api/v1/health", headers={"Host": "localhost", "Origin": ORIGIN})
        assert response.json()["code"] == "ORIGIN_NOT_ALLOWED"
        assert not state_path.exists()


@pytest.mark.parametrize("origin", [
    "", "*", "null", "http://0.0.0.0:5173", "http://[::]:5173",
    "http://10.0.0.2", "http://10.0.0.2:0", "http://10.0.0.2:65536",
    "http://10.0.0.2:80", "https://10.0.0.2:443",
    "http://10.0.0.2:05173", "http://10.0.0.2:abc", "http://10.0.0.2:5173/",
    "http://10.0.0.2:5173/path", "http://10.0.0.2:5173?x=1",
    "http://10.0.0.2:5173#fragment", "http://user:password@10.0.0.2:5173",
    "http://10.0.0.2:5173\n", "http://10.0.0.2:5173\x01",
    "ftp://10.0.0.2:5173", "https://*.example:5173", "http://EXAMPLE:5173",
    "http://-example:5173", "http://example..test:5173", "http://999.0.0.2:5173",
    "http://[fe80::1%zone]:5173",
    "http://" + "a" * 301 + ":5173",
])
def test_bad_origin_fails_before_store_construction(monkeypatch, state_path, origin):
    import importlib
    app_module = importlib.import_module("aiddos.api.app")

    def forbidden(*args, **kwargs):
        pytest.fail("Configuration failure must precede resource construction")

    monkeypatch.setattr(app_module, "DraftStore", forbidden)
    monkeypatch.setenv("DDOSPECTOR_ALLOW_INSECURE_DEV", "1")
    monkeypatch.setenv("DDOSPECTOR_DEV_ORIGIN", origin)
    with pytest.raises(ValueError, match="DDOSPECTOR_DEV_ORIGIN"):
        create_app(state_path=state_path)
    assert not state_path.exists()


@pytest.mark.parametrize("flag", ["true", "yes", "2", " 1", "1\n"])
def test_bad_flag_is_not_truthy(monkeypatch, state_path, flag):
    monkeypatch.setenv("DDOSPECTOR_ALLOW_INSECURE_DEV", flag)
    with pytest.raises(ValueError, match="DDOSPECTOR_ALLOW_INSECURE_DEV"):
        create_app(state_path=state_path)


@pytest.mark.parametrize("headers,code", [
    ({"Host": "evil.test:5173"}, "HOST_NOT_ALLOWED"),
    ({"Host": "10.0.0.2:5174"}, "HOST_NOT_ALLOWED"),
    ({"Origin": "http://10.0.0.1:5173"}, "ORIGIN_NOT_ALLOWED"),
    ({"Origin": "http://10.0.0.2:5173/"}, "ORIGIN_NOT_ALLOWED"),
    ({"Origin": "https://10.0.0.2:5173"}, "ORIGIN_NOT_ALLOWED"),
    ({"Origin": "null"}, "ORIGIN_NOT_ALLOWED"),
    ({"Sec-Fetch-Site": "cross-site"}, "ORIGIN_NOT_ALLOWED"),
])
def test_lan_mode_does_not_allow_unrelated_requests(lan, state_path, headers, code):
    response = lan.post("/api/v1/targets", json={}, headers=headers)
    assert response.status_code == 403
    assert response.json()["code"] == code
    assert "access-control-allow-origin" not in response.headers
    assert not state_path.exists()


def test_lan_preflight_is_exact_and_bounded(lan):
    headers = {"Origin": ORIGIN, "Access-Control-Request-Method": "PUT",
               "Access-Control-Request-Headers": "content-type"}
    response = lan.options("/api/v1/ai-settings", headers=headers)
    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["vary"] == "Origin"
    assert "access-control-allow-credentials" not in response.headers
    for extra in ({"Access-Control-Request-Method": "DELETE"},
                  {"Access-Control-Request-Headers": "authorization"}):
        assert lan.options("/api/v1/ai-settings", headers=headers | extra).status_code == 403


def test_lan_body_and_duplicate_header_guards_remain(lan, state_path):
    headers = {"Origin": ORIGIN, "Content-Type": "application/json"}
    assert lan.post("/api/v1/targets", content=b" " * (256 * 1024 + 1),
                    headers=headers).json()["code"] == "BODY_TOO_LARGE"
    assert lan.post("/api/v1/targets", content=b'{"x":1,"x":2}',
                    headers=headers).json()["code"] == "VALIDATION_ERROR"
    assert lan.post("/api/v1/targets", json={}, headers=[("Origin", ORIGIN),
                    ("Origin", ORIGIN)]).json()["code"] == "INVALID_FRAMING"
    assert not state_path.exists()


@pytest.mark.parametrize("path,code", [
    ("/api/v1/runs", "LIVE_NOT_AVAILABLE"),
    ("/api/v1/agent/execute", "AGENT_EXECUTION_NOT_AVAILABLE"),
    ("/api/v1/ai-settings/test", "AI_CONNECTION_NOT_AVAILABLE"),
])
def test_development_mode_does_not_enable_execution(lan, path, code):
    response = lan.post(path, json={}, headers={"Origin": ORIGIN})
    assert response.status_code == 409
    assert response.json()["code"] == code


def test_policy_is_per_app_and_public_setting_wins(monkeypatch, state_path, caplog):
    monkeypatch.setenv("AIDDOS_ALLOW_INSECURE_DEV", "1")
    monkeypatch.setenv("AIDDOS_DEV_ORIGIN", ORIGIN)
    monkeypatch.delenv("DDOSPECTOR_ALLOW_INSECURE_DEV", raising=False)
    monkeypatch.delenv("DDOSPECTOR_DEV_ORIGIN", raising=False)
    first = create_app(state_path=state_path)
    monkeypatch.setenv("DDOSPECTOR_ALLOW_INSECURE_DEV", "0")
    second = create_app(state_path=state_path)
    with TestClient(first, base_url=ORIGIN) as a, TestClient(second, base_url=ORIGIN) as b:
        assert a.get("/api/v1/health").status_code == 200
        assert b.get("/api/v1/health").status_code == 403
        assert a.get("/api/v1/health").status_code == 200
    assert caplog.text.count("INSECURE DEVELOPMENT ACCESS enabled") == 1


@pytest.mark.parametrize("origin", ["https://dev.example:8443", "http://[fd00::2]:5173"])
def test_explicit_dns_and_ipv6_origins(monkeypatch, state_path, origin):
    monkeypatch.setenv("DDOSPECTOR_ALLOW_INSECURE_DEV", "1")
    monkeypatch.setenv("DDOSPECTOR_DEV_ORIGIN", origin)
    with TestClient(create_app(state_path=state_path), base_url=origin) as client:
        assert client.get("/api/v1/health", headers={"Origin": origin}).status_code == 200
