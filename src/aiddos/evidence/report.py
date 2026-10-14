"""Closed report v1: bounded validation precedes encoding and publication."""
import re

from aiddos.api.encoding import strict_json
from aiddos.api.errors import DraftError
from aiddos.api.scenarios import canonical, record_digest
from aiddos.runs.contracts import identifier
from aiddos.runs.validation import moment

from .analysis import STATISTICS, analyze, decision
from .contracts import MAX_REPORT, MAX_SIDE_BYTES
from .validation import check, digest, originals, provenance, summary_value

POLICY_KEYS = {"profile_id", "ip_version", "protocol", "expected_action", "delivery_expectation",
               "detection_required", "detection_deadline_ms", "minimum_delivery_pct",
               "maximum_delivery_pct", "evidence_requirements"}
KEYS = {"schema_version", "kind", "rule_id", "scope", "evidence_id", "run_id",
        "run_snapshot_digest", "created_at", "provenance", "sample_id", "coverage", "outcome",
        "scenario_evaluation", "defense_verdict", "policy", "captures", "facts", "issues",
        "unassessed_requirements", "digest"}
ERRORS = {"PCAP_TOO_LARGE", "PCAP_TOO_MANY_PACKETS", "PCAP_MALFORMED", "PCAP_UNSUPPORTED",
          "PCAP_TRUNCATED", "PCAP_CHECKSUM_UNVERIFIED"}
REQUIREMENTS = {"ingress_pcap", "egress_pcap", "dut_events", "service_probe", "resource_metrics"}
MATCH_KEYS = {"matched_packets", "unmatched_ingress_packets", "unmatched_egress_packets",
              "delivery_basis_points_floor"}


def shape(value, keys):
    check(type(value) is dict and set(value) == keys)


def integer(value, lower, upper):
    check(type(value) is int and lower <= value <= upper)


def enum(value, choices):
    check(type(value) is str and value in choices)


def strings(value, allowed, maximum):
    check(type(value) is list and len(value) <= maximum)
    for item in value:
        enum(item, allowed)
    check(len(set(value)) == len(value))


def timestamp_value(value):
    check(type(value) is str and len(value) == 27)
    try:
        moment(value)
    except (ValueError, TypeError, OverflowError):
        raise DraftError("EVIDENCE_STATE_CORRUPT") from None


def policy_value(value):
    shape(value, POLICY_KEYS)
    enum(value["profile_id"], {"tcpreplay-policy", "k6-http"})
    enum(value["protocol"], {"TCP", "UDP", "DNS", "HTTP"})
    integer(value["ip_version"], 4, 6)
    check(value["ip_version"] in (4, 6))
    enum(value["expected_action"], {"ALLOW", "BLOCK", "ALERT"})
    enum(value["delivery_expectation"], {"ALLOW", "BLOCK"})
    check(type(value["detection_required"]) is bool)
    for key in ("minimum_delivery_pct", "maximum_delivery_pct"):
        integer(value[key], 0, 100)
    deadline = value["detection_deadline_ms"]
    if deadline is not None:
        integer(deadline, 1, 60000)
    check(value["detection_required"] == (deadline is not None))
    replay = value["profile_id"] == "tcpreplay-policy"
    check(replay != (value["protocol"] == "HTTP"))
    if value["expected_action"] == "ALERT":
        check(value["detection_required"])
    else:
        check(value["expected_action"] == value["delivery_expectation"])
    low, high = value["minimum_delivery_pct"], value["maximum_delivery_pct"]
    check(low <= high)
    check(high == 100 if value["delivery_expectation"] == "ALLOW" else low == 0)
    strings(value["evidence_requirements"], REQUIREMENTS, 5)
    required = {"service_probe"}
    if replay:
        required.update(("ingress_pcap", "egress_pcap"))
    if value["detection_required"]:
        required.add("dut_events")
    check(required <= set(value["evidence_requirements"]))
    return value


def policy_from_definition(definition):
    # Called only with the verified immutable ScenarioDefinition, not live drafts.
    value = {key: definition[key] for key in POLICY_KEYS
             - {"minimum_delivery_pct", "maximum_delivery_pct", "detection_deadline_ms"}}
    value.update(definition["success_criteria"])
    return policy_value(value)


def side_value(value):
    shape(value, {"sha256", "size_bytes", "parse_error", *STATISTICS})
    digest(value["sha256"])
    integer(value["size_bytes"], 1, MAX_SIDE_BYTES)
    if value["parse_error"] is not None:
        enum(value["parse_error"], ERRORS)
        check(all(value[key] is None for key in STATISTICS))
        return
    n = value["packet_count"]
    integer(n, 0, 4096)
    integer(value["wire_bytes"], 0, MAX_SIDE_BYTES)
    integer(value["payload_bytes"], 0, MAX_SIDE_BYTES)
    check(value["wire_bytes"] == value["size_bytes"] - 24 - 16 * n)
    check(value["payload_bytes"] <= value["wire_bytes"] - 54 * n)
    check(type(value["timestamps_ordered"]) is bool)
    first, last = value["first_timestamp_ns"], value["last_timestamp_ns"]
    if n == 0:
        check(first is None and last is None and value["timestamps_ordered"])
        check(value["wire_bytes"] == value["payload_bytes"] == 0)
    else:
        for stamp in (first, last):
            check(type(stamp) is str and 1 <= len(stamp) <= 19
                  and re.fullmatch(r"0|[1-9][0-9]*", stamp) is not None)
            check(int(stamp) <= 4294967295999999999)
        if value["timestamps_ordered"]:
            check(int(first) <= int(last))
        if n == 1:
            check(first == last and value["timestamps_ordered"])


def validate(value):
    try:
        shape(value, KEYS)
        integer(value["schema_version"], 1, 1)
        for key, literal in (("kind", "offline_capture_criterion"),
                             ("rule_id", "TCP_ALLOW_CAPTURE_V1"),
                             ("scope", "CAPTURE_RECORDSET_ONLY"),
                             ("scenario_evaluation", "NOT_EVALUATED")):
            enum(value[key], {literal})
        check(value["defense_verdict"] is None)
        for key in ("evidence_id", "run_id"):
            identifier(value[key])
        digest(value["run_snapshot_digest"])
        timestamp_value(value["created_at"])
        digest(value["digest"])
        policy = policy_value(value["policy"])
        shape(value["captures"], {"ingress", "egress"})
        captures = value["captures"]
        for side in captures.values():
            side_value(side)
        enum(value["provenance"], {"SYNTHETIC", "UNVERIFIED"})
        enum(value["coverage"], {"COMPLETE_SYNTHETIC", "UNKNOWN"})
        if value["sample_id"] is not None:
            enum(value["sample_id"], {"complete", "violation", "unknown"})
        check({key: value[key] for key in ("provenance", "sample_id", "coverage")}
              == provenance(captures["ingress"], captures["egress"]))
        facts = value["facts"]
        if any(side["parse_error"] is not None for side in captures.values()):
            check(facts is None)
        else:
            shape(facts, MATCH_KEYS)
            for key in MATCH_KEYS - {"delivery_basis_points_floor"}:
                integer(facts[key], 0, 4096)
            n, e = captures["ingress"]["packet_count"], captures["egress"]["packet_count"]
            m = facts["matched_packets"]
            check(m + facts["unmatched_ingress_packets"] == n)
            check(m + facts["unmatched_egress_packets"] == e)
            if n:
                integer(facts["delivery_basis_points_floor"], 0, 10000)
                check(facts["delivery_basis_points_floor"] == 10000 * m // n)
            else:
                check(facts["delivery_basis_points_floor"] is None)
        strings(value["issues"], {"UNSUPPORTED_SCENARIO", "CAPTURE_COVERAGE_UNKNOWN",
                                  "NO_INGRESS_RECORDS"}, 3)
        enum(value["outcome"], {"SATISFIED", "VIOLATED", "UNKNOWN"})
        check((value["issues"], value["outcome"]) == decision(
            policy, value["coverage"], captures, facts))
        strings(value["unassessed_requirements"], REQUIREMENTS, 3)
        check(value["unassessed_requirements"] == [key for key in policy["evidence_requirements"]
                                                  if key not in {"ingress_pcap", "egress_pcap"}])
        # Every container and leaf is now closed and bounded, before serialization.
        check(value["digest"] == record_digest(value))
        return value
    except (ValueError, TypeError, KeyError, OverflowError, DraftError):
        raise DraftError("EVIDENCE_STATE_CORRUPT") from None


def encode(value):
    validate(value)
    raw = canonical(value)
    check(len(raw) <= MAX_REPORT)
    return raw


def decode(raw):
    try:
        check(type(raw) is bytes and 1 <= len(raw) <= MAX_REPORT)
        value = strict_json(raw)
        check(encode(value) == raw)
        return value
    except (ValueError, TypeError, RecursionError, DraftError):
        raise DraftError("EVIDENCE_STATE_CORRUPT") from None


def bind(value, summary, policy=None):
    validate(value)
    summary_value(summary)
    check((value["evidence_id"], value["run_id"], value["run_snapshot_digest"])
          == (summary["id"], summary["run_id"], summary["run_snapshot_digest"]))
    for side in ("ingress", "egress"):
        check(all(value["captures"][side][key] == summary[side][key]
                  for key in ("sha256", "size_bytes")))
    check(all(value[key] == summary[key] for key in ("provenance", "sample_id", "coverage")))
    if policy is not None:
        check(value["policy"] == policy_value(policy))


def build(summary, policy, created_at, ingress, egress, *, check_work=None):
    summary_value(summary)
    originals(summary, ingress, egress)
    policy_value(policy)
    timestamp_value(created_at)
    value = {"schema_version": 1, "kind": "offline_capture_criterion",
             "rule_id": "TCP_ALLOW_CAPTURE_V1", "scope": "CAPTURE_RECORDSET_ONLY",
             "evidence_id": summary["id"], "run_id": summary["run_id"],
             "run_snapshot_digest": summary["run_snapshot_digest"], "created_at": created_at,
             "scenario_evaluation": "NOT_EVALUATED", "defense_verdict": None,
             "policy": policy, "unassessed_requirements": [key for key in
                 policy["evidence_requirements"] if key not in {"ingress_pcap", "egress_pcap"}],
             **analyze(ingress, egress, policy, check_work=check_work)}
    value["digest"] = record_digest(value)
    # Return a detached closed value, never share caller-owned policy lists.
    return decode(encode(value))
