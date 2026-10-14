"""Closed bounded binary registration contracts, independent of storage."""

import base64
import binascii

from aiddos.runs.contracts import identifier, raw_json, require

MAX_SIDE_BYTES = 65536
MAX_ENCODED = 87384
MAX_PAIRS = 16
MAX_METADATA = 4096
MAX_REPORT = 32768
MAX_RESPONSE = 65536


def name_value(value):
    require(type(value) is str and 1 <= len(value) <= 128)
    require(not any(
        ord(c) <= 0x1f or 0x7f <= ord(c) <= 0x9f or 0xd800 <= ord(c) <= 0xdfff
        or 0x202a <= ord(c) <= 0x202e or 0x2066 <= ord(c) <= 0x2069 for c in value
    ))
    require(len(value.encode("utf-8")) <= 256)
    return value


def side_value(value):
    require(type(value) is dict and set(value) == {"name", "base64"})
    name = name_value(value["name"])
    encoded = value["base64"]
    require(type(encoded) is str)
    require(len(encoded) <= MAX_ENCODED, "EVIDENCE_CAPTURE_TOO_LARGE")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        require(False)
    require(len(raw) <= MAX_SIDE_BYTES, "EVIDENCE_CAPTURE_TOO_LARGE")
    require(len(raw) >= 1 and base64.b64encode(raw).decode("ascii") == encoded)
    return {"name": name, "raw": raw}


def request_value(raw):
    value = raw_json(raw)
    require(type(value) is dict and set(value) == {"request_id", "run_id", "ingress", "egress"})
    return {"request_id": identifier(value["request_id"]), "run_id": identifier(value["run_id"]),
            "ingress": side_value(value["ingress"]), "egress": side_value(value["egress"])}
