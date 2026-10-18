"""Offline Pydantic oracle for explicit wire derivatives (not producer output)."""
import json
from pathlib import Path
import socket
import sys

source = Path(sys.argv[1]).resolve(strict=True)
sys.path.insert(0, str(source))
from aiddos.api import chat_tool_models  # noqa: E402
from pydantic import ValidationError  # noqa: E402

assert Path(chat_tool_models.__file__).resolve().is_relative_to(source)


def denied(*_args, **_kwargs):
    raise AssertionError("No network in wire oracle")


socket.socket.connect = denied
socket.getaddrinfo = denied
results = []
for row in json.load(sys.stdin):
    try:
        chat_tool_models.ToolTranscript.model_validate(row["value"])
        accepted = True
    except (ValueError, ValidationError):
        accepted = False
    results.append(dict(label=row["label"], accepted=accepted))
print(json.dumps(results))
