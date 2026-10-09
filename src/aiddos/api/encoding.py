"""Small bounded JSON grammar shared by HTTP and local draft replay."""

import json


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _no_constant(value: str):
    raise ValueError("Non-finite JSON constant")


def strict_json(raw: bytes) -> object:
    text = raw.decode("utf-8", errors="strict")
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > 32:
                raise ValueError("JSON nesting limit exceeded")
        elif character in "]}":
            depth -= 1
    return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_no_constant)
