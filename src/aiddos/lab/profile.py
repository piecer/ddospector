"""Closed deploy-time profile validation without network operations."""

import hashlib
import ipaddress
import json
import re
import unicodedata

MAX_PROFILE_BYTES = 16384


def canonical(value: dict) -> bytes:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text.encode("utf-8")


def refused(code: str) -> dict:
    return {"schema_version": 1, "status": "REFUSED", "code": code}


def _invalid(*_args):
    raise ValueError("INVALID_PROFILE")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _invalid()
        result[key] = value
    return result


def _keys(value, expected):
    if type(value) is not dict or value.keys() != expected.keys():
        _invalid()


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        _invalid()


def _ipv4(value):
    if type(value) is not str:
        _invalid()
    address = ipaddress.IPv4Address(value)
    if str(address) != value or address.is_unspecified or address.is_multicast:
        _invalid()
    if value == "255.255.255.255":
        _invalid()


def _ascii(value, maximum):
    if type(value) is not str or not 1 <= len(value) <= maximum or not value.isascii():
        _invalid()


def _host(value):
    _ascii(value, 253)
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", value):
        # Host literals need canonical syntax, not the connect-address scope policy.
        if str(ipaddress.IPv4Address(value)) != value:
            _invalid()
    elif any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
             for label in value.split(".")):
        _invalid()


def _path(value):
    _ascii(value, 1024)
    if not value.startswith("/") or value.startswith("//"):
        _invalid()
    if any(ord(c) <= 32 or ord(c) == 127 or c in "#\\" for c in value):
        _invalid()
    if re.search(r"%(?![0-9A-Fa-f]{2})", value):
        _invalid()


def _ca(value):
    if type(value) is not str or not value.startswith("/"):
        _invalid()
    if len(value.encode("utf-8")) > 4096 or any(unicodedata.category(c) == "Cc" for c in value):
        _invalid()


def _strings(value):
    target, source, expected = value["target"], value["source"], value["expected"]
    for subject, key, validator in (
        (target, "connect_ipv4", _ipv4), (source, "bind_ipv4", _ipv4),
        (target, "http_host", _host), (target, "path", _path), (target, "ca_file", _ca),
    ):
        if subject[key] is not None:
            validator(subject[key])
    scheme = target["scheme"]
    if scheme is not None and scheme not in ("http", "https"):
        _invalid()
    if scheme == "http" and target["ca_file"] is not None:
        _invalid()
    interface = source["interface"]
    if interface is not None:
        _ascii(interface, 64)
        if not re.fullmatch(r"[A-Za-z0-9_.:-]+", interface):
            _invalid()
    digest = expected["body_sha256"]
    if digest is not None and (
        type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest)
    ):
        _invalid()


def _validate(value):
    shape = template()
    _keys(value, shape)
    for section in ("target", "source", "budget", "expected"):
        _keys(value[section], shape[section])
    _integer(value["schema_version"], 1, 1)
    if value["kind"] != "NORMAL_SERVICE_BASELINE":
        _invalid()
    target, budget, expected = value["target"], value["budget"], value["expected"]
    if target["port"] is not None:
        _integer(target["port"], 1, 65535)
    if expected["http_status"] is not None:
        _integer(expected["http_status"], 200, 299)
    for key, low, high in (
        ("max_attempts", 1, 3), ("min_interval_ms", 1000, 30000), ("concurrency", 1, 1),
        ("request_timeout_ms", 1, 3000), ("overall_timeout_ms", 1, 30000), ("retries", 0, 0),
    ):
        _integer(budget[key], low, high)
    if budget["request_timeout_ms"] > budget["overall_timeout_ms"]:
        _invalid()
    _strings(value)
    return any(value[section][key] is None for section, keys in (
        ("target", ("connect_ipv4", "port", "scheme", "http_host", "path")),
        ("source", ("bind_ipv4", "interface")), ("expected", ("http_status",)),
    ) for key in keys)


def evaluate(raw: bytes) -> dict:
    """Return the public configuration result."""
    if len(raw) > MAX_PROFILE_BYTES:
        return refused("PROFILE_TOO_LARGE")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                           parse_float=_invalid, parse_constant=_invalid)
        incomplete = _validate(value)
        encoded = canonical(value)
    except (ValueError, UnicodeError, RecursionError):
        return refused("INVALID_PROFILE")
    if incomplete:
        return refused("SITE_CONFIGURATION_REQUIRED")
    return {
        "schema_version": 1, "status": "CONFIG_VALID_NO_NETWORK",
        "profile_sha256": hashlib.sha256(encoded).hexdigest(),
        "network_io_performed": False, "site_verified": False,
        "baseline_execution_supported": False,
    }


def template():
    """Return a fresh incomplete template, with no inferred site values."""
    return {
        "schema_version": 1,
        "kind": "NORMAL_SERVICE_BASELINE",
        "target": dict.fromkeys(("connect_ipv4", "port", "scheme", "http_host", "path", "ca_file")),
        "source": dict.fromkeys(("bind_ipv4", "interface")),
        "budget": {
            "max_attempts": 3, "min_interval_ms": 1000, "concurrency": 1,
            "request_timeout_ms": 3000, "overall_timeout_ms": 30000, "retries": 0,
        },
        "expected": dict.fromkeys(("http_status", "body_sha256")),
    }
