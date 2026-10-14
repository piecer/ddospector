"""Malformed retained metadata cannot be hydrated or serialized as public evidence."""

from copy import deepcopy

import pytest

from aiddos.api.errors import DraftError
from aiddos.api.scenarios import canonical
from aiddos.evidence import validation as v


def value():
    ingress, egress = v.descriptor("a", b"a"), v.descriptor("b", b"b")
    return {"id": "00000000-0000-4000-8000-000000000001",
            "request_id": "00000000-0000-4000-8000-000000000002", "ordinal": 1,
            "run_id": "00000000-0000-4000-8000-000000000003",
            "run_snapshot_digest": "a" * 64, "created_at": "2026-01-01T00:00:00.000000Z",
            "analysis_state": "REGISTERED", "ingress": ingress, "egress": egress,
            **v.provenance(ingress, egress)}


def test_detail_rejects_oversized_scalar_before_serializer(monkeypatch):
    data = value()
    data["ingress"]["name"] = "x" * 100000
    calls = []
    real = v.canonical
    def observed(data):
        calls.append(True)
        return real(data)
    monkeypatch.setattr(v, "canonical", observed)
    with pytest.raises(DraftError, match="EVIDENCE_STATE_CORRUPT"):
        v.detail(data)
    assert calls == []


@pytest.mark.parametrize("key,bad", [
    ("ordinal", True), ("ordinal", 17), ("ordinal", 0), ("ordinal", "1"),
    ("id", None), ("request_id", "A" * 36), ("run_id", []),
    ("run_snapshot_digest", "A" * 64), ("run_snapshot_digest", "a" * 65),
    ("created_at", "2026-01-01T00:00:00Z"), ("created_at", "2026-99-01T00:00:00.000000Z"),
    ("coverage", "COMPLETE_SYNTHETIC"), ("provenance", "SYNTHETIC"),
    ("sample_id", "complete"), ("analysis_state", "ANALYZED"), ("ingress", []),
])
def test_corrupt_summary_scalars(key, bad):
    data = value()
    data[key] = bad
    with pytest.raises(DraftError, match="EVIDENCE_STATE_CORRUPT"):
        v.summary(canonical(data))


@pytest.mark.parametrize("key,bad", [("size_bytes", True), ("size_bytes", 65537),
                                     ("name", "\u202e"), ("sha256", "z" * 64)])
def test_corrupt_side_scalars(key, bad):
    data = value()
    data["ingress"][key] = bad
    with pytest.raises(DraftError, match="EVIDENCE_STATE_CORRUPT"):
        v.summary(canonical(data))


@pytest.mark.parametrize("raw", [b"[]", b"null", b"true", b"{}", b" " * 4097,
                                b'{"ordinal":1,"ordinal":1}'])
def test_metadata_budget_and_shape(raw):
    with pytest.raises(DraftError, match="EVIDENCE_STATE_CORRUPT"):
        v.summary(raw)


def test_positive_original_and_integrity_controls():
    data = value()
    assert v.summary(canonical(data)) == data
    v.originals(data, b"a", b"b")
    for ingress, egress in ((b"A", b"b"), (b"a", b""), (b"aa", b"b")):
        with pytest.raises(DraftError, match="EVIDENCE_STATE_CORRUPT"):
            v.originals(deepcopy(data), ingress, egress)
