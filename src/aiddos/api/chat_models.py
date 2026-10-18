"""Pure profile selection; this module never resolves names or credentials."""

import json
import re
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, Field

from .ai_settings import AIIdentifier, AIModel
from .errors import ERRORS, DraftError
from .models import ClosedModel

SAFE_INT = 9007199254740991
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


def uid(value):
    try:
        parsed = UUID(value)
        if parsed.version != 4 or str(parsed) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid chat identifier") from None
    return value


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def now():
    return datetime.now(UTC).isoformat()


ChatID = Annotated[str, AfterValidator(uid)]
Counter = Annotated[int, Field(ge=0, le=SAFE_INT)]


def valid_text(value, limit=None, *, nonblank=False):
    if not isinstance(value, str) or "\x00" in value:
        raise ValueError("Invalid text")
    size = len(value.encode("utf-8", errors="strict"))
    if (limit is not None and size > limit) or (nonblank and not value.strip()):
        raise ValueError("Invalid text")
    return value


def user_text(value):
    return valid_text(value, 8192, nonblank=True)


class TurnInput(ClosedModel):
    request_id: ChatID
    expected_sequence: Counter
    text: Annotated[str, AfterValidator(user_text)]


class EmptyInput(ClosedModel):
    pass


class SessionInput(ClosedModel):
    request_id: ChatID
    settings_revision: Counter
    profile_id: AIIdentifier
    approved_endpoint: str = Field(max_length=2048)
    locale: Literal["en", "ko"]


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("UTC required")
    return value


ChatTime = Annotated[str, Field(max_length=40), AfterValidator(timestamp)]


def chat_code(value):
    if value not in ERRORS or not value.startswith("CHAT_"):
        raise ValueError("Invalid code")
    return value


class Session(ClosedModel):
    schema_version: Literal[1]
    id: ChatID
    request_id: ChatID
    settings_revision: Counter
    profile_id: AIIdentifier
    model: AIModel
    endpoint: str = Field(max_length=2048)
    streaming: bool
    locale: Literal["en", "ko"]
    created_at: ChatTime
    sequence: int = Field(ge=0, le=64)
    active_turn_id: ChatID | None


class Turn(ClosedModel):
    schema_version: Literal[1]
    id: ChatID
    request_id: ChatID
    session_id: ChatID
    sequence: int = Field(ge=1, le=64)
    revision: int = Field(ge=1, le=SAFE_INT)
    status: Literal[
        "accepted", "running", "cancel_requested", "succeeded", "failed", "cancelled", "interrupted"
    ]
    user_text: Annotated[str, AfterValidator(user_text)]
    assistant_text: Annotated[str, AfterValidator(lambda s: valid_text(s, 65536))]
    error_code: Annotated[str, AfterValidator(chat_code)] | None
    transport: Literal["not_started", "open", "closed", "unknown"]
    provider_stop: Literal["not_dispatched", "unknown"]
    created_at: ChatTime
    finished_at: ChatTime | None


LIMITS = {
    "input_bytes": 8192,
    "output_bytes": 65536,
    "sessions": 32,
    "session_turns": 64,
    "history_bytes": 8388608,
    "turn_seconds": 120,
}


def selected(snapshot):
    identifier = snapshot["agent_profile_id"] or snapshot["default_profile_id"]
    profile = next((p for p in snapshot["profiles"] if p["id"] == identifier), None)
    if profile is None:
        raise DraftError("CHAT_NOT_CONFIGURED")
    match = re.fullmatch(
        r"http://(localhost|127\.0\.0\.1|\[::1\])(?::([0-9]{1,5}))?/v1/?", profile["base_url"]
    )
    if (
        profile["format"] != "openai"
        or profile["credential_env"]
        or match is None
        or (match[2] is not None and not 1 <= int(match[2]) <= 65535)
    ):
        raise DraftError("CHAT_UNSUPPORTED_PROFILE")
    if (
        profile["max_tokens"] > 4096
        or profile["thinking_type"]
        or profile["reasoning_effort"]
        or profile["rate_per_second"]
        or profile["rate_per_minute"]
        or any(rule["attempts"] > 0 for rule in profile["retry"].values())
    ):
        raise DraftError("CHAT_UNSUPPORTED_OPTIONS")
    endpoint = profile["base_url"].rstrip("/") + "/chat/completions"
    return profile, endpoint


def runtime_view(snapshot):
    reason, view = None, None
    try:
        profile, endpoint = selected(snapshot)
        view = {key: profile[key] for key in ("id", "name", "model", "format", "streaming")}
        view["endpoint"] = endpoint
    except DraftError as exc:
        reason = exc.code
    return {
        "schema_version": 1,
        "mode": "chat_only",
        "supported": reason is None,
        "reason": reason,
        "settings_revision": snapshot["revision"],
        "profile": view,
        "limits": LIMITS,
        "history": "persistent",
        "configuration_tools": False,
        "live_execution": False,
        "mcp_execution": False,
    }
