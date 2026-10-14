"""Actual capture bytes, not generator expectation lookups, drive the criterion."""
import importlib
import importlib.util

import pytest

from aiddos.evidence.samples import make_sample


def policy(minimum=95):
    return {"profile_id": "tcpreplay-policy", "ip_version": 4, "protocol": "TCP",
            "expected_action": "ALLOW", "delivery_expectation": "ALLOW",
            "detection_required": False, "detection_deadline_ms": None,
            "minimum_delivery_pct": minimum, "maximum_delivery_pct": 100,
            "evidence_requirements": ["ingress_pcap", "egress_pcap", "service_probe"]}


def analyzer():
    assert importlib.util.find_spec("aiddos.evidence.analysis") is not None
    return importlib.import_module("aiddos.evidence.analysis").analyze


@pytest.mark.parametrize("sample,outcome", [
    ("complete", "SATISFIED"), ("violation", "VIOLATED"), ("unknown", "UNKNOWN")])
def test_real_reference_records(sample, outcome):
    pair = make_sample(sample)
    result = analyzer()(pair.ingress, pair.egress, policy())
    assert result["outcome"] == outcome
    assert result["sample_id"] == sample
    facts = result["facts"]
    assert facts["matched_packets"] + facts["unmatched_ingress_packets"] == (
        result["captures"]["ingress"]["packet_count"])
    assert facts["matched_packets"] + facts["unmatched_egress_packets"] == (
        result["captures"]["egress"]["packet_count"])
    if sample == "violation":
        assert analyzer()(pair.ingress, pair.egress, policy(90))["outcome"] == "SATISFIED"


def test_duplicate_conservation_and_unverified_coverage(wire):
    capture, frame = wire
    a, b, c = frame(b"a"), frame(b"b"), frame(b"c")
    result = analyzer()(capture([a, a, b]), capture([a, c, c]), policy())
    assert result["facts"] == {"matched_packets": 1, "unmatched_ingress_packets": 2,
                               "unmatched_egress_packets": 2,
                               "delivery_basis_points_floor": 3333}
    assert result["outcome"] == "UNKNOWN"
    assert result["provenance"] == "UNVERIFIED"
    assert result["issues"] == ["CAPTURE_COVERAGE_UNKNOWN"]


@pytest.mark.parametrize("minimum,outcome", [(0, "SATISFIED"), (66, "SATISFIED"),
                                             (67, "VIOLATED"), (100, "VIOLATED")])
def test_threshold_uses_exact_cross_multiplication(minimum, outcome):
    from aiddos.evidence.analysis import decision
    assert decision(policy(minimum), "COMPLETE_SYNTHETIC", {"ingress": {"packet_count": 3}},
                    {"matched_packets": 2}) == ([], outcome)


@pytest.mark.parametrize("fault,code", [("checksum", "PCAP_CHECKSUM_UNVERIFIED"),
    ("unsupported", "PCAP_UNSUPPORTED"), ("truncated", "PCAP_TRUNCATED")])
def test_actual_parser_quality_errors_preserve_complete_original_digest(wire, fault, code):
    import hashlib
    import struct
    capture, frame = wire
    raw = capture([frame()])
    if fault == "checksum":
        raw = raw[:-1] + bytes([raw[-1] ^ 1])
    elif fault == "unsupported":
        raw = raw[:20] + struct.pack("<I", 101) + raw[24:]
    else:
        raw = raw[:36] + struct.pack("<I", len(frame()) + 1) + raw[40:]
    result = analyzer()(raw, capture([frame()]), policy())
    assert result["captures"]["ingress"]["parse_error"] == code
    assert result["captures"]["ingress"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["facts"] is None and result["outcome"] == "UNKNOWN"


def test_exact_side_limits_and_unverified_perfect_match(wire):
    from aiddos.api.errors import DraftError
    capture, frame = wire
    raw = capture([frame()])
    assert analyzer()(raw, raw, policy())["outcome"] == "UNKNOWN"
    assert analyzer()(b"x" * 65536, raw, policy())["captures"]["ingress"]["size_bytes"] == 65536
    for bad in (b"", b"x" * 65537):
        with pytest.raises(DraftError):
            analyzer()(bad, raw, policy())


def test_empty_and_parse_failure(wire):
    import hashlib
    capture, _ = wire
    result = analyzer()(capture(), capture(), policy())
    assert result["facts"]["delivery_basis_points_floor"] is None
    assert result["issues"] == ["CAPTURE_COVERAGE_UNKNOWN", "NO_INGRESS_RECORDS"]
    result = analyzer()(b"broken", capture(), policy())
    assert result["facts"] is None and result["outcome"] == "UNKNOWN"
    side = result["captures"]["ingress"]
    assert side["parse_error"] == "PCAP_MALFORMED"
    assert side["sha256"] == hashlib.sha256(b"broken").hexdigest()
    assert all(side[key] is None for key in ("packet_count", "wire_bytes", "payload_bytes",
                                            "first_timestamp_ns", "last_timestamp_ns",
                                            "timestamps_ordered"))


@pytest.mark.parametrize("error", [OSError("io"), TimeoutError("deadline"),
                                   RuntimeError("cancel")])
def test_checkpoint_exceptions_are_not_quality_results(error):
    def fail():
        raise error
    pair = make_sample("complete")
    with pytest.raises(type(error)) as caught:
        analyzer()(pair.ingress, pair.egress, policy(), check_work=fail)
    assert caught.value is error


def test_callback_pcap_error_is_not_parser_quality():
    from aiddos.evidence.pcap import PcapError
    error = PcapError("PCAP_MALFORMED")
    calls = 0
    def fail_inside_parser():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise error
    pair = make_sample("complete")
    with pytest.raises(PcapError) as caught:
        analyzer()(pair.ingress, pair.egress, policy(), check_work=fail_inside_parser)
    assert caught.value is error


@pytest.mark.parametrize("key,value", [("profile_id", "k6-http"), ("ip_version", 6),
    ("protocol", "UDP"), ("expected_action", "BLOCK"), ("delivery_expectation", "BLOCK"),
    ("detection_required", True)])
def test_unsupported_scenario_never_satisfies(key, value):
    pair = make_sample("complete")
    p = policy()
    p[key] = value
    result = analyzer()(pair.ingress, pair.egress, p)
    assert result["outcome"] == "UNKNOWN" and result["issues"] == ["UNSUPPORTED_SCENARIO"]
