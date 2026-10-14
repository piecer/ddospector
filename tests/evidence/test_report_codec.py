"""Closed immutable report bytes and source-binding controls."""
import hashlib
import importlib
import importlib.util
from copy import deepcopy

import pytest
from test_evaluation import policy
from test_retained_validation import value

from aiddos.api.errors import DraftError
from aiddos.api.scenarios import canonical, record_digest
from aiddos.evidence.contracts import MAX_REPORT
from aiddos.evidence.samples import make_sample
from aiddos.evidence.validation import descriptor, provenance


def codec():
    assert importlib.util.find_spec("aiddos.evidence.report") is not None
    return importlib.import_module("aiddos.evidence.report")


def inputs():
    pair = make_sample("complete")
    summary = value()
    for side in ("ingress", "egress"):
        summary[side] = descriptor(side, getattr(pair, side))
    summary.update(provenance(summary["ingress"], summary["egress"]))
    return summary, pair


def report():
    summary, pair = inputs()
    return codec().build(summary, policy(), "2026-01-01T00:01:00.000000Z",
                         pair.ingress, pair.egress)


def test_closed_report_roundtrip_and_binding():
    data = report()
    raw = codec().encode(data)
    assert codec().decode(raw) == data
    assert data["digest"] == record_digest(data)
    assert data["scope"] == "CAPTURE_RECORDSET_ONLY"
    assert data["scenario_evaluation"] == "NOT_EVALUATED" and data["defense_verdict"] is None
    assert data["unassessed_requirements"] == ["service_probe"]
    summary, _ = inputs()
    codec().bind(data, summary, policy())
    foreign = deepcopy(summary)
    foreign["run_snapshot_digest"] = "b" * 64
    with pytest.raises(DraftError, match="EVIDENCE_STATE_CORRUPT"):
        codec().bind(data, foreign, policy())
    with pytest.raises(DraftError, match="EVIDENCE_STATE_CORRUPT"):
        codec().bind(data, summary, policy(90))


@pytest.mark.parametrize("path,bad", [
    (("schema_version",), True), (("schema_version",), 1.0), (("scope",), "DUT"),
    (("outcome",), "VIOLATED"), (("sample_id",), None), (("digest",), "0" * 64),
    (("policy", "minimum_delivery_pct"), True), (("policy", "minimum_delivery_pct"), -1),
    (("policy", "maximum_delivery_pct"), 99), (("policy", "detection_required"), 0),
    (("policy", "evidence_requirements"), ["service_probe"]),
    (("policy", "detection_deadline_ms"), 0), (("issues",), ["CAPTURE_COVERAGE_UNKNOWN"]),
    (("issues",), ["x"] * 10000), (("unassessed_requirements",), []),
    (("facts", "matched_packets"), True), (("facts", "matched_packets"), 0),
    (("facts", "delivery_basis_points_floor"), 9999),
    (("captures", "ingress", "packet_count"), 4097),
    (("captures", "ingress", "size_bytes"), 65537),
    (("captures", "ingress", "first_timestamp_ns"), "01"),
    (("captures", "ingress", "last_timestamp_ns"), "9" * 100000),
    (("captures", "ingress", "timestamps_ordered"), 1),
    (("captures", "ingress", "parse_error"), "PCAP_MALFORMED"),
])
def test_reject_semantic_shape_scalar_tampering_before_encoding(path, bad):
    data = report()
    node = data
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = bad
    if path != ("digest",):
        data["digest"] = record_digest(data)
    with pytest.raises(DraftError, match="EVIDENCE_STATE_CORRUPT"):
        codec().encode(data)


@pytest.mark.parametrize("path", [(), ("policy",), ("captures",),
                                   ("captures", "ingress"), ("facts",)])
def test_unknown_fields_rejected_even_with_fresh_digest(path):
    data = report()
    node = data
    for key in path:
        node = node[key]
    node["extra"] = None
    data["digest"] = record_digest(data)
    with pytest.raises(DraftError, match="EVIDENCE_STATE_CORRUPT"):
        codec().decode(canonical(data))


def test_raw_budget_before_decode_and_invalid_before_serialize(monkeypatch):
    module = codec()
    data = report()
    calls = []
    def forbidden(*args):
        calls.append(True)
        raise AssertionError("must reject before encoding/decoding")
    monkeypatch.setattr(module, "strict_json", forbidden)
    with pytest.raises(DraftError, match="EVIDENCE_STATE_CORRUPT"):
        module.decode(b" " * 32769)
    assert not calls
    data["policy"]["evidence_requirements"] = ["service_probe"] * 10000
    monkeypatch.setattr(module, "canonical", forbidden)
    with pytest.raises(DraftError, match="EVIDENCE_STATE_CORRUPT"):
        module.encode(data)
    assert not calls


def test_all_required_fields_and_ordered_issue_consistency():
    baseline = report()
    for path in ((), ("policy",), ("captures",), ("captures", "ingress"), ("facts",)):
        original = baseline
        for key in path:
            original = original[key]
        for missing in original:
            data = deepcopy(baseline)
            node = data
            for key in path:
                node = node[key]
            del node[missing]
            if not (not path and missing == "digest"):
                data["digest"] = record_digest(data)
            with pytest.raises(DraftError, match="EVIDENCE_STATE_CORRUPT"):
                codec().decode(canonical(data))


def test_report_keeps_observed_timestamp_order(wire):
    capture, frame = wire
    raw = capture([frame(), frame()], timestamps=[(2, 0), (1, 0)])
    summary, _ = inputs()
    for side in ("ingress", "egress"):
        summary[side] = descriptor(side, raw)
    summary.update(provenance(summary["ingress"], summary["egress"]))
    data = codec().build(summary, policy(), "2026-01-01T00:01:00.000000Z", raw, raw)
    side = data["captures"]["ingress"]
    assert side["first_timestamp_ns"] == "2000000000"
    assert side["last_timestamp_ns"] == "1000000000" and not side["timestamps_ordered"]
    assert data["outcome"] == "UNKNOWN"


def test_raw_exact_cap_reaches_decoder_but_plus_one_does_not(monkeypatch):
    module = codec()
    seen = []
    def reject(raw):
        seen.append(len(raw))
        raise ValueError("not a report")
    monkeypatch.setattr(module, "strict_json", reject)
    for size in (32768, 32769):
        with pytest.raises(DraftError, match="EVIDENCE_STATE_CORRUPT"):
            module.decode(b"x" * size)
    assert seen == [32768]


@pytest.mark.parametrize("side", ["ingress", "egress"])
def test_binding_rejects_rehashed_foreign_capture(side):
    data = report()
    summary, _ = inputs()
    summary[side]["sha256"] = "f" * 64
    summary.update(provenance(summary["ingress"], summary["egress"]))
    with pytest.raises(DraftError, match="EVIDENCE_STATE_CORRUPT"):
        codec().bind(data, summary)


def test_parser_failure_and_empty_roundtrip_preserve_nulls_and_order(wire):
    capture, _ = wire
    summary, _ = inputs()
    p = policy()
    p["evidence_requirements"] = ["resource_metrics", "egress_pcap", "dut_events",
                                  "ingress_pcap", "service_probe"]
    for ingress, egress in ((capture(), capture()), (b"bad", capture())):
        summary["ingress"] = descriptor("ingress", ingress)
        summary["egress"] = descriptor("egress", egress)
        summary.update(provenance(summary["ingress"], summary["egress"]))
        data = codec().build(summary, p, "2026-01-01T00:01:00.000000Z", ingress, egress)
        assert data["unassessed_requirements"] == [
            "resource_metrics", "dut_events", "service_probe"]
        assert codec().decode(codec().encode(data)) == data and data["outcome"] == "UNKNOWN"


def test_duplicate_noncanonical_alias_and_exact_byte_cap():
    raw = codec().encode(report())
    for bad in (b"{}", b"[]", raw + b" ", raw.replace(b'"schema_version":1',
                b'"schema_version":1,"schema_version":1'),
                raw.replace(b'"schema_version":1', b'"schema_version":1.0'),
                b" " * 32768, b" " * 32769):
        with pytest.raises(DraftError, match="EVIDENCE_STATE_CORRUPT"):
            codec().decode(bad)


@pytest.mark.parametrize("stamp", [
    pytest.param("x" * (MAX_REPORT + 1), id="oversized"),
    pytest.param(None, id="null"),
    pytest.param(True, id="bool"),
    pytest.param(2026, id="integer"),
    pytest.param([], id="list"),
    pytest.param({}, id="object"),
    pytest.param("2026-02-29T00:00:00.000000Z", id="invalid-calendar"),
    pytest.param("2026-01-01T24:00:00.000000Z", id="invalid-hour"),
    pytest.param("2026-01-01 00:00:00.000000Z", id="space-separator"),
    pytest.param("2026-01-01T00:00:00.000000z", id="lowercase-zone"),
    pytest.param("2026-01-01T00:00:00.000000+00:00", id="offset-alias"),
    pytest.param("2026-01-01T00:00:00Z", id="missing-microseconds"),
])
def test_builder_rejects_timestamp_before_real_report_encoder(
    monkeypatch, stamp, record_property,
):
    from aiddos.api import scenarios

    module = codec()
    summary, pair = inputs()
    real = scenarios.canonical
    calls = []

    def observing(data):
        if isinstance(data, dict) and data.get("kind") == "offline_capture_criterion":
            calls.append(type(data["created_at"]).__name__)
        return real(data)

    monkeypatch.setattr(scenarios, "canonical", observing)
    monkeypatch.setattr(module, "canonical", observing)
    with pytest.raises(DraftError, match="EVIDENCE_STATE_CORRUPT") as caught:
        module.build(summary, policy(), stamp, pair.ingress, pair.egress)
    record_property("error_code", caught.value.code)
    record_property("real_report_encoder_calls", len(calls))
    assert calls == [], "rejected builder scalar reached the real Report encoder"


@pytest.mark.parametrize("sample,stamp,expected_sha256", [
    ("complete", "2026-01-01T00:01:00.000000Z",
     "4ace37077e7c941e11672da1d911691b4754ffcb1cb9469fb97ed6a2ffc12039"),
    ("violation", "2024-02-29T23:59:59.123456Z",
     "be31254fa5520c1f982c3630f3a8b61a1783e0d09d588cbb1e2b8fbc469299ce"),
    ("unknown", "2026-01-01T00:01:00.000000Z",
     "7758a4c2cac5d0637e297b258cd5bf8f8c1b5211fe68ebdb270da9c92a8a2a76"),
])
def test_builder_valid_bytes_match_pre_admission_repair(sample, stamp, expected_sha256):
    pair = make_sample(sample)
    summary = value()
    for side in ("ingress", "egress"):
        summary[side] = descriptor(side, getattr(pair, side))
    summary.update(provenance(summary["ingress"], summary["egress"]))
    p = policy()
    before = deepcopy((summary, p))
    data = codec().build(summary, p, stamp, pair.ingress, pair.egress)
    raw = codec().encode(data)
    # Recorded from the frozen pre-repair builder, not recomputed by this test.
    assert hashlib.sha256(raw).hexdigest() == expected_sha256
    assert codec().decode(raw) == data
    assert (summary, p) == before
    p["evidence_requirements"].append("resource_metrics")
    assert "resource_metrics" not in data["policy"]["evidence_requirements"]
