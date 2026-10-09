import pytest


@pytest.mark.parametrize(
    "route,code",
    [
        ("/api/v1/runs", "LIVE_NOT_AVAILABLE"),
        ("/api/v1/agent/execute", "AGENT_EXECUTION_NOT_AVAILABLE"),
    ],
)
@pytest.mark.parametrize("body", [b"{}", b'{"mode":"LIVE","approved":true}', b"not-json", b""])
def test_execution_is_unconditionally_denied_without_state_access(
    client, state_path, route, code, body
):
    state_path.write_bytes(b"corrupt state must not be read or overwritten by execution denial")
    before = state_path.read_bytes()
    response = client.post(route, content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 409
    assert response.json()["code"] == code
    assert set(response.json()) == {"code", "message"}
    assert state_path.read_bytes() == before
