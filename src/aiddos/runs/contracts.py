"""Closed S02 request and canonical byte contracts (no external I/O)."""

import json
import re

from aiddos.api.encoding import strict_json
from aiddos.api.errors import DraftError
from aiddos.api.scenarios import canonical

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
DIGEST = re.compile(r"[0-9a-f]{64}")
REQUEST_KEYS = {"request_id", "mode", "scenario_id", "scenario_version", "scenario_digest"}


def require(ok, code="VALIDATION_ERROR"):
    if not ok:
        raise DraftError(code)


def identifier(value):
    require(type(value) is str and UUID.fullmatch(value) is not None)
    return value


def raw_json(raw):
    def integer(text):
        if text == "-0" or len(text) > 17:
            raise ValueError
        value = int(text)
        if abs(value) > 9007199254740991:
            raise ValueError
        return value

    def reject(text):
        raise ValueError

    try:
        strict_json(raw)  # bounded lexical depth, UTF8, duplicate keys and constants
        value = json.loads(raw.decode("utf-8"), parse_int=integer, parse_float=reject)
        canonical(value)  # rejects decoded lone surrogates at every depth
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise DraftError("VALIDATION_ERROR") from None


def request_value(raw):
    value = raw_json(raw)
    require(type(value) is dict and set(value) == REQUEST_KEYS)
    identifier(value["request_id"])
    identifier(value["scenario_id"])
    require(type(value["mode"]) is str and value["mode"] in {"OFFLINE", "LIVE"})
    require(type(value["scenario_version"]) is int and 1 <= value["scenario_version"] <= 10)
    require(
        type(value["scenario_digest"]) is str
        and DIGEST.fullmatch(value["scenario_digest"]) is not None
    )
    return value
