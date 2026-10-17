"""Closed deployment-profile contract; fixtures are never dialed."""

import hashlib
import json

import pytest

from aiddos.lab import profile

TEMPLATE_SHA = "7c3c1e45082eb3870ccda5bb10566645da712a2fae31f6985202b3d7bd776b57"
FILLED_SHA = "02517fd83b442469510ac46fe420329e9e8e4db6c8b7e6a479bc82888f01ca0d"


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def filled():
    value = profile.template()
    value["target"].update(connect_ipv4="127.0.0.1", port=8080, scheme="http",
                           http_host="Example.test", path="/health?check=1")
    value["source"].update(bind_ipv4="127.0.0.1", interface="lo")
    value["expected"]["http_status"] = 200
    return value


def test_template_is_independent_canonical_oracle():
    value = profile.template()
    raw = wire(value)
    assert len(raw) == 382
    assert hashlib.sha256(raw).hexdigest() == TEMPLATE_SHA
    value["target"]["port"] = 123
    value["budget"]["retries"] = 8
    assert hashlib.sha256(wire(profile.template())).hexdigest() == TEMPLATE_SHA


def refused(code):
    return {"schema_version": 1, "status": "REFUSED", "code": code}


def success(digest=FILLED_SHA):
    return {"schema_version": 1, "status": "CONFIG_VALID_NO_NETWORK",
            "profile_sha256": digest, "network_io_performed": False,
            "site_verified": False, "baseline_execution_supported": False}


def test_valid_profile_canonical_digest_preserves_input():
    value = filled()
    raw = json.dumps(value, indent=3).encode()
    before = raw[:]
    assert profile.evaluate(raw) == success()
    assert profile.evaluate(wire(value)) == success()
    assert raw == before


@pytest.mark.parametrize("raw", [
    b"", b"{", b"[]", b"null", b"true", b"1", b"{}",
    b'{"schema_version":1,"schema_version":1}',
    b'{"x":{"duplicate":0,"duplicate":1}}',
    b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}',
    b'"\xff"', b'{"x":"\\ud800"}', b'[' * 1500 + b']' * 1500,
    b'{"x":' + b'1' * 5000 + b'}',
])
def test_invalid_wire_is_fixed_refusal(raw):
    assert profile.evaluate(raw) == refused("INVALID_PROFILE")


@pytest.mark.parametrize("section", [None, "target", "source", "budget", "expected"])
@pytest.mark.parametrize("mutation", ["missing", "unknown", "not-object"])
def test_closed_required_object_keys(section, mutation):
    value = filled()
    subject = value if section is None else value[section]
    if mutation == "missing":
        subject.pop(next(iter(subject)))
    elif mutation == "unknown":
        subject["PRIVATE_SENTINEL"] = 1
    elif section is None:
        value = []
    else:
        value[section] = []
    assert profile.evaluate(wire(value)) == refused("INVALID_PROFILE")


def test_exact_cap_and_size_precedes_parser():
    raw = wire(filled())
    assert profile.evaluate(raw + b" " * (16384 - len(raw))) == success()
    assert profile.evaluate(b"x" * 16385) == refused("PROFILE_TOO_LARGE")


def test_template_requires_site_configuration():
    assert profile.evaluate(wire(profile.template())) == refused("SITE_CONFIGURATION_REQUIRED")


NUMBERS = [
    (None, "schema_version", 1, 1), ("target", "port", 1, 65535),
    ("budget", "max_attempts", 1, 3), ("budget", "min_interval_ms", 1000, 30000),
    ("budget", "concurrency", 1, 1), ("budget", "request_timeout_ms", 1, 3000),
    ("budget", "overall_timeout_ms", 1, 30000), ("budget", "retries", 0, 0),
    ("expected", "http_status", 200, 299),
]


@pytest.mark.parametrize("section,key,low,high", NUMBERS)
@pytest.mark.parametrize("case", ["low", "high", "below", "above", "bool", "float", "str", "null"])
def test_numeric_closed_bounds_and_exact_types(section, key, low, high, case):
    value = filled()
    value["budget"]["request_timeout_ms"] = 1
    subject = value if section is None else value[section]
    subject[key] = {"low": low, "high": high, "below": low - 1, "above": high + 1,
                    "bool": bool(low), "float": float(low), "str": str(low), "null": None}[case]
    actual = profile.evaluate(wire(value))
    if case in ("low", "high"):
        assert actual == success(hashlib.sha256(wire(value)).hexdigest())
    elif case == "null" and section in ("target", "expected"):
        assert actual == refused("SITE_CONFIGURATION_REQUIRED")
    else:
        assert actual == refused("INVALID_PROFILE")


def test_negative_zero_is_integer_zero_and_deadline_may_limit_attempts():
    value = filled()
    value["budget"].update(request_timeout_ms=1, overall_timeout_ms=1)
    raw = wire(value)
    assert profile.evaluate(raw.replace(b'"retries":0', b'"retries":-0')) == success(
        hashlib.sha256(raw).hexdigest())
    value["budget"]["request_timeout_ms"] = 2
    assert profile.evaluate(wire(value)) == refused("INVALID_PROFILE")


@pytest.mark.parametrize("kind", [None, 1, True, "", "NORMAL", "normal_service_baseline"])
def test_kind_is_exact(kind):
    value = filled()
    value["kind"] = kind
    assert profile.evaluate(wire(value)) == refused("INVALID_PROFILE")


def test_invalid_numeric_wins_over_incomplete_site():
    value = profile.template()
    value["budget"]["concurrency"] = True
    assert profile.evaluate(wire(value)) == refused("INVALID_PROFILE")


STRING_FIELDS = [("target", k) for k in (
    "connect_ipv4", "scheme", "http_host", "path", "ca_file",
)] + [("source", "bind_ipv4"), ("source", "interface"), ("expected", "body_sha256")]


@pytest.mark.parametrize("section,key", STRING_FIELDS)
@pytest.mark.parametrize("bad", [False, 1, [], {}, ""])
def test_string_fields_require_strings(section, key, bad):
    value = filled()
    value["target"]["scheme"] = "https"
    value[section][key] = bad
    assert profile.evaluate(wire(value)) == refused("INVALID_PROFILE")


STRING_CASES = [
    ("target", "connect_ipv4", v, ok)
    for v, ok in [("127.0.0.1", True), ("192.0.2.1", True), ("10.0.0.1", True),
                  ("0.0.0.0", False), ("224.0.0.1", False), ("255.255.255.255", False),
                  ("127.00.0.1", False), ("127.1", False), ("::1", False),
                  ("127.0.0.1 ", False), ("example.test", False)]
] + [
    ("target", "http_host", v, ok)
    for v, ok in [("EXample.test", True), ("a", True), ("127.0.0.1", True),
                  ("a" * 63 + ".b", True), ("a" * 64, False),
                  (".".join(["a" * 63] * 3 + ["b" * 61]), True),
                  (".".join(["a" * 63] * 3 + ["b" * 62]), False),
                  ("a.", False), ("a..b", False), ("-a.b", False), ("a-.b", False),
                  ("a_b", False), ("a:80", False), ("user@a", False), ("a b", False),
                  ("a\n", False), ("é.test", False), ("127.00.0.1", False)]
] + [
    ("target", "path", v, ok)
    for v, ok in [("/", True), ("/a?secret=PRIVATE_SENTINEL&x=%2f%2F", True),
                  ("/" + "x" * 1023, True), ("/" + "x" * 1024, False),
                  ("//evil", False), ("relative", False), ("/#x", False),
                  ("/a\\b", False), ("/a b", False), ("/\n", False), ("/\x7f", False),
                  ("/é", False), ("/%", False), ("/%0", False), ("/%gg", False)]
] + [
    ("source", "interface", v, ok)
    for v, ok in [("eth0.1:a-b_c", True), ("a" * 64, True), ("a" * 65, False),
                  ("eth 0", False), ("eth0/", False), ("é", False), ("lo\n", False)]
] + [
    ("target", "ca_file", v, ok)
    for v, ok in [("/missing/PRIVATE_SENTINEL.pem", True), ("/", True),
                  ("/" + "x" * 4095, True), ("/" + "x" * 4096, False),
                  ("/" + "é" * 2047 + "a", True), ("/" + "é" * 2048, False),
                  ("relative.pem", False), ("C:\\ca.pem", False),
                  ("/a\x00b", False), ("/a\n", False), ("/a\x7f", False), ("/a\x85", False)]
] + [
    ("expected", "body_sha256", v, ok)
    for v, ok in [("a" * 64, True), ("0" * 64, True), ("a" * 63, False),
                  ("a" * 65, False), ("A" * 64, False), ("g" * 64, False)]
] + [("target", "scheme", "https", True), ("target", "scheme", "HTTP", False),
     ("target", "scheme", "tcp", False)]


@pytest.mark.parametrize("section,key,text,ok", STRING_CASES,
                         ids=[f"string-{i}" for i in range(len(STRING_CASES))])
def test_string_syntax_boundaries(section, key, text, ok):
    value = filled()
    value["target"]["scheme"] = "https"
    value[section][key] = text
    expected = (success(hashlib.sha256(wire(value)).hexdigest())
                if ok else refused("INVALID_PROFILE"))
    assert profile.evaluate(wire(value)) == expected
    if key == "connect_ipv4":
        value = filled()
        value["source"]["bind_ipv4"] = text
        expected = (success(hashlib.sha256(wire(value)).hexdigest())
                    if ok else refused("INVALID_PROFILE"))
        assert profile.evaluate(wire(value)) == expected


def test_ca_syntax_only_and_http_relationship_without_site_guessing(monkeypatch):
    import os
    from pathlib import Path

    def forbidden(*args, **kwargs):
        raise AssertionError("CA filesystem access")

    value = filled()
    value["target"].update(scheme="https", ca_file="/missing/PRIVATE_SENTINEL.pem")
    expected = success(hashlib.sha256(wire(value)).hexdigest())
    with monkeypatch.context() as patcher:
        for name in ("open", "stat", "lstat", "access"):
            patcher.setattr(os, name, forbidden)
        patcher.setattr(Path, "resolve", forbidden)
        assert profile.evaluate(wire(value)) == expected
    value["target"]["scheme"] = "http"
    assert profile.evaluate(wire(value)) == refused("INVALID_PROFILE")
    value["target"]["scheme"] = None
    assert profile.evaluate(wire(value)) == refused("SITE_CONFIGURATION_REQUIRED")


@pytest.mark.parametrize("section,key", STRING_FIELDS)
def test_null_site_fields_and_invalid_sibling_precedence(section, key):
    value = filled()
    value[section][key] = None
    expected = (success() if key in ("ca_file", "body_sha256")
                else refused("SITE_CONFIGURATION_REQUIRED"))
    assert profile.evaluate(wire(value)) == expected
    value["expected"]["body_sha256"] = "PRIVATE_SENTINEL"
    assert profile.evaluate(wire(value)) == refused("INVALID_PROFILE")


def test_lone_surrogate_and_noncanonical_strings_not_rewritten():
    value = filled()
    value["target"].update(scheme="https", ca_file="/\ud800")
    assert profile.evaluate(json.dumps(value).encode()) == refused("INVALID_PROFILE")
    value = filled()
    for text in ("/health?check=%2f", "/health?check=%2F", "/health?check=2"):
        value["target"]["path"] = text
        raw = wire(value)
        assert profile.evaluate(raw) == success(hashlib.sha256(raw).hexdigest())
        assert profile.evaluate(raw) != success()
