"""Bounded packet-record correspondence; never a DUT/session/service verdict."""
import hashlib
from io import BytesIO

from .contracts import MAX_SIDE_BYTES
from .pcap import PcapError, parse_capture
from .validation import check, provenance

STATISTICS = ("packet_count", "wire_bytes", "payload_bytes", "first_timestamp_ns",
              "last_timestamp_ns", "timestamps_ordered")


def applicable(policy):
    return (policy["profile_id"] == "tcpreplay-policy" and policy["ip_version"] == 4
            and policy["protocol"] == "TCP" and policy["expected_action"] == "ALLOW"
            and policy["delivery_expectation"] == "ALLOW" and not policy["detection_required"])


def decision(policy, coverage, captures, facts):
    issues = []
    if not applicable(policy):
        issues.append("UNSUPPORTED_SCENARIO")
    if coverage != "COMPLETE_SYNTHETIC":
        issues.append("CAPTURE_COVERAGE_UNKNOWN")
    if captures["ingress"]["packet_count"] == 0:
        issues.append("NO_INGRESS_RECORDS")
    outcome = "UNKNOWN"
    if not issues and facts is not None:
        n = captures["ingress"]["packet_count"]
        m = facts["matched_packets"]
        outcome = ("SATISFIED" if policy["minimum_delivery_pct"] * n <= 100 * m
                   <= policy["maximum_delivery_pct"] * n else "VIOLATED")
    return issues, outcome


def analyze(ingress, egress, policy, *, check_work=None):
    captures, parsed = {}, {}
    callback_error = None

    def checkpoint():
        nonlocal callback_error
        if check_work is not None:
            try:
                check_work()
            except PcapError as error:
                callback_error = error
                raise

    for side, raw in (("ingress", ingress), ("egress", egress)):
        if check_work is not None:
            check_work()
        check(type(raw) is bytes and 1 <= len(raw) <= MAX_SIDE_BYTES)
        facts = {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw),
                 "parse_error": None, **dict.fromkeys(STATISTICS)}
        try:
            parsed[side] = parse_capture(BytesIO(raw), check=checkpoint)
        except PcapError as error:
            if error is callback_error:
                raise
            facts["parse_error"] = error.code
        else:
            value = parsed[side]
            facts.update({key: getattr(value, key) for key in STATISTICS})
            for key in ("first_timestamp_ns", "last_timestamp_ns"):
                if facts[key] is not None:
                    facts[key] = str(facts[key])
        captures[side] = facts
    matching = None
    if len(parsed) == 2:
        before, after = parsed["ingress"], parsed["egress"]
        remaining = dict(after.fingerprints)
        matched = 0
        for fingerprint, count in before.fingerprints:
            if check_work is not None:
                check_work()
            matched += min(count, remaining.get(fingerprint, 0))
        matching = {"matched_packets": matched,
                    "unmatched_ingress_packets": before.packet_count - matched,
                    "unmatched_egress_packets": after.packet_count - matched,
                    "delivery_basis_points_floor": (10000 * matched // before.packet_count
                                                    if before.packet_count else None)}
    origin = provenance(captures["ingress"], captures["egress"])
    issues, outcome = decision(policy, origin["coverage"], captures, matching)
    if check_work is not None:
        check_work()
    return {**origin, "captures": captures, "facts": matching, "issues": issues,
            "outcome": outcome}
