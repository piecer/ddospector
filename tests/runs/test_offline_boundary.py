"""First admission contracts, through the existing ASGI HTTP transport."""

import json
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from aiddos.api.app import create_app


def request_body(**updates):
    return {
        "request_id": str(uuid4()),
        "mode": "OFFLINE",
        "scenario_id": str(uuid4()),
        "scenario_version": 1,
        "scenario_digest": "a" * 64,
        **updates,
    }


def test_offline_missing_configuration_preserves_legacy(tmp_path, monkeypatch):
    monkeypatch.delenv("AIDDOS_RUN_DB_SOCKET", raising=False)
    with TestClient(
        create_app(state_path=tmp_path / "draft.json"), base_url="http://localhost"
    ) as client:
        response = client.post("/api/v1/offline-runs", json=request_body())
        assert response.status_code == 503
        assert response.json() == {
            "code": "RUN_DB_NOT_CONFIGURED",
            "message": "Offline run storage is not configured.",
        }
        assert client.get("/api/v1/health").status_code == 200
        assert (
            client.post(
                "/api/v1/runs", content="!", headers={"Content-Type": "application/json"}
            ).json()["code"]
            == "LIVE_NOT_AVAILABLE"
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "live",
        "null",
        "array",
        "extra",
        "missing",
        "version_bool",
        "version_string",
        "version_zero",
        "version_eleven",
        "uuid_upper",
        "uuid_variant",
        "digest_upper",
        "float",
        "exponent",
        "negative_zero",
        "unsafe",
        "infinity",
        "bom",
        "utf8",
        "surrogate",
        "duplicate",
        "escaped_duplicate",
        "deep",
        "trailing",
        "query",
        "oversize",
        "get_body",
        "get_transfer",
        "bad_id",
        "get_query",
    ],
)
def test_offline_closed_boundary_before_database(tmp_path, monkeypatch, mutation):
    def forbidden(*args, **kwargs):
        raise AssertionError("boundary touched driver")

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", forbidden)
    value = request_body()
    status, code = 422, "VALIDATION_ERROR"
    path, method = "/api/v1/offline-runs", "POST"
    headers = {"Content-Type": "application/json"}
    if mutation == "live":
        value["mode"] = "LIVE"
        status, code = 409, "LIVE_NOT_AVAILABLE"
    elif mutation in {"null", "array"}:
        value = None if mutation == "null" else []
    elif mutation == "extra":
        value["extra"] = 1
    elif mutation == "missing":
        del value["request_id"]
    elif mutation.startswith("version_"):
        value["scenario_version"] = {"bool": True, "string": "1", "zero": 0, "eleven": 11}[
            mutation[8:]
        ]
    elif mutation == "uuid_upper":
        value["request_id"] = value["request_id"].upper()
    elif mutation == "uuid_variant":
        value["scenario_id"] = "00000000-0000-1000-0000-000000000000"
    elif mutation == "digest_upper":
        value["scenario_digest"] = "A" * 64
    raw = json.dumps(value).encode()
    if mutation in {"float", "exponent", "negative_zero", "unsafe", "infinity"}:
        raw = raw.replace(
            b'"scenario_version": 1',
            b'"scenario_version": '
            + {
                "float": b"1.0",
                "exponent": b"1e0",
                "negative_zero": b"-0",
                "unsafe": b"9007199254740992",
                "infinity": b"Infinity",
            }[mutation],
        )
    elif mutation == "bom":
        raw = b"\xef\xbb\xbf" + raw
    elif mutation == "utf8":
        raw = b'"\xff"'
    elif mutation == "surrogate":
        raw = raw.replace(b'"OFFLINE"', b'"\\ud800"')
    elif mutation in {"duplicate", "escaped_duplicate"}:
        key = b"mode" if mutation == "duplicate" else b"m\\u006fde"
        raw = b'{"' + key + b'":"LIVE",' + raw[1:]
    elif mutation == "deep":
        raw = b"[" * 33 + b"0" + b"]" * 33
    elif mutation == "trailing":
        raw += b"{}"
    elif mutation == "query":
        path += "?extra=1"
    elif mutation == "oversize":
        raw += b" " * 1025
        status, code = 413, "RUN_BODY_TOO_LARGE"
    elif mutation.startswith("get_") or mutation == "bad_id":
        path += "/" + ("bad" if mutation == "bad_id" else str(uuid4()))
        method = "GET"
        raw = b""
        if mutation in {"get_body", "get_transfer"}:
            headers.update(
                {"Content-Length": "1"}
                if mutation == "get_body"
                else {"Transfer-Encoding": "chunked"}
            )
            status, code = 400, "INVALID_FRAMING"
        elif mutation == "get_query":
            path += "?extra=1"
    with TestClient(
        create_app(state_path=tmp_path / "draft.json"), base_url="http://localhost"
    ) as client:
        response = client.request(method, path, content=raw, headers=headers)
        assert (response.status_code, response.json()["code"]) == (status, code)
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("size", [1024, 1025])
def test_offline_exact_body_limit_before_driver(tmp_path, monkeypatch, size):
    def forbidden(*args, **kwargs):
        raise AssertionError("body admission touched driver")

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", forbidden)
    raw = json.dumps(request_body(mode="LIVE")).encode()
    raw += b" " * (size - len(raw))
    with TestClient(
        create_app(state_path=tmp_path / "draft.json"), base_url="http://localhost"
    ) as client:
        response = client.post(
            "/api/v1/offline-runs", content=raw, headers={"Content-Type": "application/json"}
        )
    assert (response.status_code, response.json()["code"]) == (
        (409, "LIVE_NOT_AVAILABLE") if size == 1024 else (413, "RUN_BODY_TOO_LARGE")
    )


@pytest.mark.parametrize("kind", ["relative", "comma", "whitespace", "nul", "absent", "ambient"])
def test_offline_configuration_has_no_fallback(tmp_path, monkeypatch, kind):
    from aiddos.api.errors import DraftError
    from aiddos.runs.config import parameters

    socket = str(tmp_path)
    if kind == "relative":
        socket = "relative"
    elif kind == "comma":
        socket += ",/other"
    elif kind == "whitespace":
        socket += " "
    elif kind == "nul":
        socket += "\x00"
    elif kind == "absent":
        socket += "/missing"
    elif kind == "ambient":
        monkeypatch.setenv("PGI1_TEST", "owned-sentinel")
    with pytest.raises(DraftError) as captured:
        parameters(socket)
    assert captured.value.code == "RUN_DB_UNAVAILABLE"
