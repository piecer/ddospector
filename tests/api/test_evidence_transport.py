"""Evidence admission refuses invalid input before database custody."""

import base64
import json
from uuid import uuid4

import pytest

from aiddos.runs.lifetime import Manager


def valid():
    return {"request_id": str(uuid4()), "run_id": str(uuid4()),
            "ingress": {"name": " i ", "base64": "AA=="},
            "egress": {"name": " e ", "base64": "/w=="}}


@pytest.fixture
def no_manager(monkeypatch):
    calls = []
    async def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("database admission")
    monkeypatch.setattr(Manager, "perform", forbidden)
    yield calls
    assert calls == []


def test_invalid_registration_never_enters_manager(client, no_manager):
    response = client.post("/api/v1/evidence", json={})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("field,bad", [
    ("request_id", True), ("request_id", "A0000000-0000-4000-8000-000000000000"),
    ("run_id", None), ("run_id", "00000000-0000-1000-8000-000000000000"),
    ("ingress", []), ("egress", None), ("ingress", {"name": "a", "base64": "AA==", "x": 1}),
    ("report", {}), ("provenance", "SYNTHETIC"),
])
def test_closed_fields(client, no_manager, field, bad):
    data = valid()
    data[field] = bad
    assert client.post("/api/v1/evidence", json=data).status_code == 422


@pytest.mark.parametrize("field,bad,status", [
    ("name", "", 422), ("name", "x" * 129, 422), ("name", "界" * 86, 422),
    ("name", "\u202a", 422), ("name", "\u2069", 422), ("name", "\ud800", 422),
    ("name", True, 422), ("name", None, 422), ("name", "\x9f", 422),
    ("base64", "AB==", 422), ("base64", "AA==\n", 422), ("base64", [], 422),
    ("base64", "", 422), ("base64", "_w==", 422),
    ("base64", base64.b64encode(b"x" * 65537).decode("ascii"), 413),
    ("base64", "A" * 87385, 413),
])
def test_side_boundaries(client, no_manager, field, bad, status):
    data = valid()
    data["ingress"][field] = bad
    response = client.post("/api/v1/evidence", content=json.dumps(data),
                           headers={"content-type": "application/json"})
    assert response.status_code == status


@pytest.mark.parametrize("raw", [b'{"x":0,"x":0}', b'[]', b'true', b'null',
                                b'{"x":NaN}', b'{"x":-0}', b'\xff'])
def test_bad_json(client, no_manager, raw):
    assert client.post("/api/v1/evidence", content=raw,
                       headers={"content-type": "application/json"}).status_code == 422


@pytest.mark.parametrize("path", [
    "?after=0", "?x=1&x=2", "/BAD", "/by-request/BAD",
    "/00000000-0000-4000-8000-000000000001/raw/both",
    "/00000000-0000-4000-8000-000000000001?x=1",
])
def test_bad_read_parameters(client, no_manager, path):
    assert client.get("/api/v1/evidence" + path).status_code == 422


def test_valid_exact_limits_enter_existing_manager(client, monkeypatch):
    observed = []
    async def accepted(self, deadline, work, disconnected):
        observed.append((deadline, disconnected))
        # Admission-only control, not a storage or public response-schema acceptance fixture.
        return 200, b'{}'
    monkeypatch.setattr(Manager, "perform", accepted)
    data = valid()
    for side in ("ingress", "egress"):
        data[side] = {"name": "é" * 128,
                      "base64": base64.b64encode(bytes(range(256)) * 256).decode("ascii")}
    assert client.post("/api/v1/evidence", json=data).status_code == 200
    assert len(observed) == 1 and callable(observed[0][1])
