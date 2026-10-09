"""Offline producer oracle. Every wire body comes from the actual TestClient.

Input is a JSON list of full AISettingsInput objects. Each case gets its own
owned empty state. No listeners; all sockets/DNS/process execution are denied.
"""

import json
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from generate_unicode import require_runtime

from aiddos.api.app import create_app


def forbidden(*args, **kwargs):
    raise AssertionError("Producer oracle attempted network/DNS/process execution")


def main():
    require_runtime()
    root = Path(__file__).resolve().parents[5]
    assert Path(sys.prefix).resolve() == root / ".venv", "Use the project virtualenv"
    cases = json.load(sys.stdin)
    results = []
    with (
        tempfile.TemporaryDirectory(prefix="ai-producer-", dir=root / ".venv") as temporary,
        patch.object(socket.socket, "connect", forbidden),
        patch.object(socket.socket, "connect_ex", forbidden),
        patch.object(socket.socket, "bind", forbidden),
        patch.object(socket, "getaddrinfo", forbidden),
        patch.object(subprocess, "Popen", forbidden),
    ):
        for index, value in enumerate(cases):
            with TestClient(
                create_app(state_path=Path(temporary) / f"{index}.json"),
                base_url="http://localhost",
                raise_server_exceptions=False,
            ) as client:
                put = client.put("/api/v1/ai-settings", json=value)
                get = client.get("/api/v1/ai-settings")
                results.append({"status": put.status_code, "body": put.text, "get": get.text})
    print(json.dumps(results, ensure_ascii=True))


if __name__ == "__main__":
    main()
