"""Explicit real-Uvicorn smoke test; only its own ephemeral loopback socket is used.

Run with `uv run python tests/api/smoke_loopback.py`; not part of network-denied pytest.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    opener = build_opener(ProxyHandler({}))
    with tempfile.TemporaryDirectory(prefix="api-smoke-", dir=root / ".venv") as directory:
        state = Path(directory) / "drafts.json"
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "aiddos.api.app:app",
                    "--fd",
                    str(listener.fileno()),
                    "--log-level",
                    "warning",
                    "--no-access-log",
                    "--no-proxy-headers",
                ],
                cwd=root,
                env={**os.environ, "AIDDOS_UI_STATE_PATH": str(state)},
                pass_fds=(listener.fileno(),),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            def request(path, payload=None):
                raw = None if payload is None else json.dumps(payload).encode()
                message = Request(
                    f"http://127.0.0.1:{port}/api/v1/{path}",
                    data=raw,
                    headers={} if raw is None else {"Content-Type": "application/json"},
                )
                try:
                    with opener.open(message, timeout=1) as response:
                        return response.status, json.load(response)
                except HTTPError as response:
                    return response.code, json.load(response)

            try:
                deadline = time.monotonic() + 10
                while True:
                    if process.poll() is not None:
                        raise AssertionError("Owned Uvicorn process exited before readiness")
                    try:
                        status, health = request("health")
                        if status == 200:
                            break
                    except (URLError, TimeoutError):
                        pass
                    if time.monotonic() >= deadline:
                        raise AssertionError("Owned loopback API did not become ready")
                    time.sleep(0.02)
                assert health == {"status": "ok", "version": "0.1.0-ui", "mode": "OFFLINE"}
                assert not state.exists()
                status, target = request(
                    "targets",
                    {
                        "name": "Smoke draft",
                        "address": "localhost",
                        "kind": "DUT",
                    },
                )
                assert status == 201 and target["status"] == "draft"
                status, workspace = request("workspace")
                assert status == 200 and workspace["targets"] == [target]
                assert workspace["runs"] == [] and state.exists()
                status, preview = request("agent/preview", {"goal": "Review", "locale": "ko"})
                assert status == 200 and preview["origin"] == "deterministic_context_preview"
                for path in ("runs", "agent/execute"):
                    status, result = request(path, {"mode": "LIVE", "approved": True})
                    assert status == 409 and result["code"].endswith("NOT_AVAILABLE")
                print(
                    "PASS real Uvicorn: health, draft write/read, preview, both execution denials"
                )
            finally:
                process.terminate()
                try:
                    _, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    _, stderr = process.communicate(timeout=5)
                assert process.poll() is not None
                assert not stderr, stderr.decode(errors="replace")
        print("PASS owned process/socket stopped; temporary draft state cleaned on exit")
    assert not Path(directory).exists()


if __name__ == "__main__":
    main()
