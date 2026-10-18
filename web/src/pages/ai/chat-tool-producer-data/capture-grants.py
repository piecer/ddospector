"""Capture actual ToolLedger grants, not a frontend-computed hash oracle.

Run with the backend source and its component tests on absolute PYTHONPATH.
The output is an explicit NEW path; existing captures are never overwritten.
No HTTP, provider, domain worker or shared database is used.
"""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import tempfile

from aiddos.api import chat_tool_models, chat_tool_storage
from aiddos.api.chat_models import encoded
from aiddos.api.chat_tool_models import Grant
from aiddos.api.chat_tool_storage import ToolLedger
from test_chat_tool_storage import STAMP, admission, grant_body, setup_store


def denied(*_args, **_kwargs):
    raise AssertionError("Network forbidden in grant capture")


socket.socket.connect = denied
socket.getaddrinfo = denied
parser = argparse.ArgumentParser()
parser.add_argument("output", type=Path)
parser.add_argument("--state-parent", type=Path, required=True)
args = parser.parse_args()
assert not args.output.exists()
vectors = [
    ("ascii", "hello"),
    ("non-bmp", "hello 한😀"),
    ("quotes", 'say "hello"'),
    ("backslash", "path\\to\\settings"),
    ("newline", "first\nsecond\r\nthird\tend"),
    ("combined", 'hello 한😀\n"quoted"\\'),
    ("ascii-boundary-8192", "x" * 8192),
    ("non-bmp-boundary-8192-bytes", "😀" * 2048),
]
rows = []
args.state_parent.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix="grant-vectors-", dir=args.state_parent) as state:
    for label, text in vectors:
        location = Path(state) / label
        location.mkdir()
        storage, session = setup_store(location)
        try:
            ledger = ToolLedger(storage)
            updated, turn, body = admission(session)
            body["text"] = text
            turn["user_text"] = text
            input_ = grant_body(session, body)
            grant, replay = ledger.create_grant(input_, timestamp=STAMP)
            assert not replay
            Grant.model_validate(grant)
            # Preserve exact encoded producer bytes, including its stored digest.
            wire = encoded(grant).decode()
            recovered, replay = ledger.create_grant(input_, timestamp=STAMP)
            assert replay and encoded(recovered).decode() == wire
            admitted, replay = ledger.admit(grant["id"], updated, turn, body, timestamp=STAMP)
            assert not replay and admitted == turn
            storage.validate()
            rows.append(dict(label=label, session=session, input=input_, wire=wire, turn_wire=encoded(admitted).decode()))
        finally:
            storage.close()
sources = {}
for module in [chat_tool_models, chat_tool_storage]:
    p = Path(module.__file__)
    sources[p.name] = dict(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest())
args.output.write_bytes(encoded(dict(source="actual ToolLedger.create_grant/admit; owned SQLite; no HTTP/model", sources=sources, grants=rows)))
print(json.dumps(dict(grants=len(rows), output=str(args.output), sha256=hashlib.sha256(args.output.read_bytes()).hexdigest(), owned_state_removed=True)))
