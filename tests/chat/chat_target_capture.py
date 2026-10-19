#!/usr/bin/env python3
"""Capture actual CHAT02B1 HTTP response bytes; never synthesize B wire success.

Run only on the combined producer tree. Outputs are new, invocation-owned files;
legacy A corpora are never opened for writing. A failed run retains diagnostics
and verdict HOLD, not a usable success corpus. Provider responses are SYNTHETIC;
API response bytes, IDs, times, receipts and restart reads are actual producers.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import httpx2
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests/chat"))

from test_chat_target_integration import (  # noqa: E402
    Product,
    ProviderFixture,
    Scenario,
    assert_saved,
    decision,
    harness,
    inspection,
    proposal,
    setup_plan,
    tools,
    wait_turn,
    workspace,
)

from aiddos.api.models import TargetInput  # noqa: E402


def literal_oracle():
    """Domain-derived validator oracle, NOT an independent validator implementation."""
    addresses = [
        "Example.COM.",
        "127.0.0.1",
        "010.001.002.003",
        "12345",
        "::1",
        "::ffff:192.0.2.1",
        "2001:db8::1",
        "fe80::1%eth0",
        "fe80::1%25eth0",
        "example.com",
        "example..com",
        "https://example.com",
        " example.com",
        "example.com\n",
        "a\u0000b",
        "",
        "256.1.1.1",
        "1.2.3",
        "🌍.example",
    ]
    rows = []
    for index, address in enumerate(addresses):
        value = {"name": "CHAT02B1 literal 승인 🌍", "address": address, "kind": "DUT"}
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        try:
            found = TargetInput.model_validate_json(raw).model_dump(mode="json")
        except ValidationError:
            accepted, found = False, None
        else:
            accepted = True
            assert found == value, "domain oracle unexpectedly normalized literal data"
        rows.append({"case": index, "raw_utf8": raw.decode(), "accepted": accepted, "value": found})
    return {
        "provenance": "actual Python TargetInput validator; domain-derived oracle",
        "cases": rows,
    }


class CaptureProduct(Product):
    def __init__(self, directory):
        self.captures = []
        super().__init__(directory)

    def request(self, path, method="GET", body=None):
        # The base is allocated by Product.launch_api; no caller-supplied host.
        with httpx2.Client(trust_env=False, timeout=10, follow_redirects=False) as client:
            response = client.request(method, self.base + path, json=body)
        raw = response.content
        name = f"chat_target_http_{len(self.captures):04d}.json"
        with (self.directory / name).open("xb") as stream:
            stream.write(raw)  # no parse/re-encode: insertion order and escaped bytes retained
        self.captures.append(
            {
                "file": name,
                "method": method,
                "path": path,
                "status": response.status_code,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "content_type": response.headers.get("content-type"),
            }
        )
        return response.status_code, json.loads(raw)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    source = harness.manifest()
    result = {
        "verdict": "HOLD",
        "real_model_requests": 0,
        "source_sha256": harness.digest(source),
        "synthetic_provider_requests": 0,
    }
    harness.dump(directory / "source-pre.json", source)
    harness.dump(directory / "chat_target_literal_oracle.json", literal_oracle())
    app = provider = None

    def capture_runtime(product):
        # Metadata shares the no-queue worker: observe before native admission.
        status, runtime = product.request("/api/v1/chat/tools/runtime")
        assert status == 200 and runtime["schema_version"] == 2

    try:
        app = CaptureProduct(directory)
        with ProviderFixture([Scenario.text()], max_requests=3) as provider:
            _, before, _, turn = setup_plan(app, provider, before_admit=capture_runtime)
            call = proposal(app, turn)
            assert workspace(app) == before and len(provider.requests) == 2
            decision(app, call)
            assert wait_turn(app, turn)["status"] == "succeeded"
            completed = tools(app, turn)
            after = assert_saved(app, before, completed["calls"][1])
            app.restart()
            assert tools(app, turn) == completed and workspace(app) == after
            assert inspection(app)["targets"] == after["targets"]
            assert len(provider.requests) == 3
            result["verdict"] = "ACTUAL_PRODUCER_CAPTURE_NOT_REAL_MODEL"
    except Exception as exc:
        result.update(verdict="HOLD", error=f"{type(exc).__name__}: {exc}")
    finally:
        if provider is not None:
            result["synthetic_provider_requests"] = len(provider.requests)
            result["provider_handlers_closed"] = provider.opened == provider.closed
            harness.dump(directory / "synthetic-provider-requests.json", provider.requests)
        if app is not None:
            try:
                app.child.stop()
                result["cleanup"] = app.child.receipt()
            except Exception as exc:
                result.update(verdict="HOLD", cleanup_error=f"{type(exc).__name__}: {exc}")
            result["captures"] = app.captures
        after = harness.manifest()
        harness.dump(directory / "source-post.json", after)
        if source != after:
            result.update(verdict="HOLD", error="source changed during capture")
        harness.dump(directory / "capture-result.json", result)
        print(json.dumps(result, ensure_ascii=False))
    return 0 if result["verdict"] == "ACTUAL_PRODUCER_CAPTURE_NOT_REAL_MODEL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
