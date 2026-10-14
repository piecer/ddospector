"""Closed, bounded registration values; raw bytes never decoded as text."""

import base64
from uuid import uuid4

import pytest

from aiddos.api.errors import DraftError
from aiddos.api.scenarios import canonical
from aiddos.evidence import contracts


def payload(raw=b"\xff", name=" original "):
    return {"request_id": str(uuid4()), "run_id": str(uuid4()),
            "ingress": {"name": name, "base64": base64.b64encode(raw).decode("ascii")},
            "egress": {"name": name, "base64": "AA=="}}


def test_closed_registration_preserves_binary_and_verbatim_names():
    original = payload(bytes(range(256)) * 256, "é" * 128)
    value = contracts.request_value(canonical(original))
    assert value["ingress"] == {"name": "é" * 128, "raw": bytes(range(256)) * 256}
    assert value["egress"]["raw"] == b"\0"
    assert value["request_id"] == original["request_id"]


@pytest.mark.parametrize("raw,code", [(b"", "VALIDATION_ERROR"),
                                      (b"x" * 65537, "EVIDENCE_CAPTURE_TOO_LARGE")])
def test_capture_boundaries(raw, code):
    with pytest.raises(DraftError, match=code):
        contracts.request_value(canonical(payload(raw)))


@pytest.mark.parametrize("encoded", ["AB==", "A===", "AA", "AA==\n", "-w==", "", True, [], 1])
def test_noncanonical_base64(encoded):
    value = payload()
    value["ingress"]["base64"] = encoded
    with pytest.raises(DraftError, match="VALIDATION_ERROR"):
        contracts.request_value(canonical(value))


@pytest.mark.parametrize("name", ["", "x" * 129, "界" * 86, "\x00", "\x1f", "\x7f", "\x9f",
                                 "\u202a", "\u202e", "\u2066", "\u2069", True, 1, None, []])
def test_bad_names(name):
    with pytest.raises(DraftError, match="VALIDATION_ERROR"):
        contracts.request_value(canonical(payload(name=name)))


@pytest.mark.parametrize("raw", [b'{"request_id":1,"request_id":2}', b'[]', b'true',
                                b'{"name":"\\ud800"}'])
def test_wrong_json(raw):
    with pytest.raises(DraftError, match="VALIDATION_ERROR"):
        contracts.request_value(raw)


def test_encoded_bound_is_checked_before_decode(monkeypatch):
    value = payload()
    value["ingress"]["base64"] = "A" * 87385
    def forbidden(*args, **kwargs):
        raise AssertionError("decoded oversized input")
    monkeypatch.setattr(base64, "b64decode", forbidden)
    with pytest.raises(DraftError, match="EVIDENCE_CAPTURE_TOO_LARGE"):
        contracts.request_value(canonical(value))
