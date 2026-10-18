"""Fixed public tool failures are available before component integration."""

import json

import pytest

from aiddos.api.errors import ERRORS, error_response


@pytest.mark.parametrize(
    "code,status",
    [
        ("CHAT_TOOL_GRANT_CONFLICT", 409),
        ("CHAT_TOOL_GRANT_INVALID", 409),
        ("CHAT_TOOL_APPROVAL_CONFLICT", 409),
        ("CHAT_TOOL_CONFLICT", 409),
        ("CHAT_TOOL_WRITE_FENCED", 409),
        ("CHAT_TOOL_DENIED", 403),
        ("CHAT_TOOL_LIMIT", 413),
        ("CHAT_TOOL_PROTOCOL", 502),
        ("CHAT_TOOL_UNCERTAIN", 503),
    ],
)
def test_tool_failure_has_fixed_closed_public_response(code, status):
    assert code in ERRORS
    response = error_response(code)
    assert response.status_code == status
    body = json.loads(bytes(response.body))
    assert body == {"code": code, "message": ERRORS[code][1]}
    assert isinstance(body["message"], str) and body["message"]
