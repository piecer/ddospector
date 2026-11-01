"""Retain actual public HTTP bytes for cross-runtime consumer qualification."""

import hashlib
import json
import os
from pathlib import Path


class ScenarioCapture:
    def __init__(self, operation):
        root = os.environ.get("STAGE3_CORPUS")
        self.root = Path(root) / ("public-" + operation) if root else None
        self.bodies = {}
        if self.root is not None:
            self.root.mkdir(parents=True, exist_ok=False)

    def record(self, name, response):
        if self.root is None:
            return response
        assert name not in self.bodies
        # Copy the actual response, never JSON-decode/re-encode an expected body.
        raw = response.content
        path = name + ".bin"
        (self.root / path).write_bytes(raw)
        self.bodies[name] = {
            "path": path,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw),
            "status": response.status_code,
            "media_type": response.headers.get("content-type"),
            "method": response.request.method,
            "path_and_query": response.request.url.raw_path.decode("ascii"),
            "request_sha256": hashlib.sha256(response.request.content).hexdigest(),
        }
        return response

    def finish(self):
        if self.root is None:
            return
        root = Path(__file__).resolve().parents[2]
        files = (
            "src/aiddos/api/chat_tool_routes.py",
            "src/aiddos/api/chat_tool_runtime.py",
            "src/aiddos/api/chat_tool_storage.py",
            "src/aiddos/api/chat_scenario_orchestration.py",
            "src/aiddos/api/chat_scenario_models.py",
            "tests/api/test_chat_scenario_public_workflow.py",
            "tests/chat/chat_scenario_capture.py",
            "tools/chat_tools_acceptance.py",
        )
        manifest = {
            "schema_version": 1,
            "provenance": "actual-public-ASGI-controlled-native-provider-not-live-model",
            "source_root": str(root),
            "source_sha256": {
                name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files
            },
            "bodies": self.bodies,
        }
        (self.root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    import argparse
    import sys

    import pytest

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(source / path) for path in ("src", "tests/api", "tests/chat")]
    os.environ["STAGE3_CORPUS"] = str(output / "corpus")
    denied = []

    def audit(event, arguments):
        if event in {
            "socket.connect", "socket.bind", "socket.getaddrinfo", "subprocess.Popen",
            "os.system", "os.posix_spawn",
        }:
            denied.append(event)
            raise RuntimeError("Offline scenario producer denied: " + event)

    sys.addaudithook(audit)
    exit_code = pytest.main([
        str(source / "tests/api/test_chat_scenario_public_workflow.py"),
        "-q", "-p", "no:cacheprovider", "--basetemp=" + str(output / "pytest"),
        "--junitxml=" + str(output / "junit.xml"),
    ])
    origins = {
        name: str(Path(module.__file__).resolve())
        for name, module in list(sys.modules.items())
        if name.startswith("aiddos") and getattr(module, "__file__", None)
    }
    assert origins and all(Path(p).is_relative_to(source / "src") for p in origins.values())
    assert not denied
    (output / "producer.json").write_text(json.dumps({
        "raw_exit": int(exit_code), "origins": origins, "denied": denied,
    }, indent=2) + "\n")
    sys.exit(exit_code)
