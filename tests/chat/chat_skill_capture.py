#!/usr/bin/env python3
"""Future separately admitted current-source Agent v1/Target v2/Skill v3 capture.

No capture has been performed by authoring this helper. Provider messages are
SYNTHETIC; every positive response must be the actual HTTP body's exact bytes.
Historical corpora are never opened for writing. No real-model mode exists.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import httpx2

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/chat"))
sys.path.insert(0, str(ROOT / "tools"))

import chat_tools_acceptance as harness  # noqa: E402
import test_chat_skill_integration as skill  # noqa: E402
import test_chat_target_integration as target  # noqa: E402
import test_chat_tools_integration as agent  # noqa: E402
from provider_fixture import ProviderFixture, Scenario  # noqa: E402
from test_chat_integration import wait_turn  # noqa: E402

VARIANTS = ("agent", "target", "skill")


class CaptureProduct(agent.Product):
    def __init__(self, directory):
        self.captures = []
        super().__init__(directory)

    def request(self, path, method="GET", body=None):
        with httpx2.Client(trust_env=False, timeout=10, follow_redirects=False) as client:
            response = client.request(method, self.base + path, json=body)
        raw = response.content
        name = f"http_{len(self.captures):04d}.json"
        with (self.directory / name).open("xb") as stream:
            stream.write(raw)
        self.captures.append(
            {
                "file": name,
                "method": method,
                "path": path,
                "status": response.status_code,
                "content_type": response.headers.get("content-type"),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "raw_utf8": raw.decode("utf-8", errors="strict"),
            }
        )
        return response.status_code, json.loads(raw)


def run_variant(app, provider, variant):
    if variant not in VARIANTS:
        raise ValueError("unknown capture variant")
    # Bootstrap/runtime share a capacity-one domain owner. Metadata discovery
    # must precede grant/native admission; no CHAT_BUSY retry hides misordering.
    saved = agent.session(app, provider)
    before = agent.workspace(app)
    status, runtime = app.request("/api/v1/chat/tools/runtime")
    assert status == 200 and type(runtime["schema_version"]) is int
    assert runtime["schema_version"] == 3
    assert runtime["supported"] is True and runtime["requires_write_approval"] is True
    assert runtime["max_calls"] == 3 and runtime["max_writes"] == 1
    assert runtime["tools"] == [
        "configuration_read",
        "agent_profile_update",
        "target_create",
        "skill_create",
    ]
    provider.scenarios = tuple(harness.plan(before, fixture_case=variant))
    if variant == "agent":
        integration, grant = agent, agent.grant
    elif variant == "target":
        integration, grant = target, target.target_grant
    else:
        integration, grant = skill, skill.skill_grant
    granted, value = grant(app, saved)
    turn = agent.admit(app, saved, granted, value)
    call = integration.proposal(app, turn)
    assert agent.workspace(app) == before and len(provider.requests) == 2
    agent.decision(app, call)
    assert wait_turn(app, turn)["status"] == "succeeded"
    completed = integration.tools(app, turn)
    if variant == "agent":
        after = agent.workspace(app)
        agent.assert_saved(before, after, completed["calls"][1])
        persisted = json.loads(app.state.read_bytes())
        assert persisted["audit"] == after["audit"]
        assert persisted["audit_total"] == harness.revision(after)
    else:
        after = integration.assert_saved(app, before, completed["calls"][1])
    assert len(provider.requests) == 3
    app.restart()
    assert integration.tools(app, turn) == completed
    assert agent.workspace(app) == after and len(provider.requests) == 3
    if variant == "target":
        assert integration.inspection(app)["targets"] == after["targets"]
    elif variant == "skill":
        result = completed["calls"][1]["result"]
        assert integration.inspection(app, result["skill"]["id"])["skill"] == result["skill"]
    return {
        "variant": variant,
        "grant": granted,
        "session": saved,
        "turn": turn,
        "before": before,
        "after": after,
        "completed": completed,
        "request": value,
        "real_model_requests": 0,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--admitted-current-capture",
        action="store_true",
        help="Parent must separately admit frozen-source all-variant capture",
    )
    args = parser.parse_args(argv)
    if not args.admitted_current_capture:
        parser.error("separate parent capture admission is required; offline TDD does not grant it")
    directory = args.output.resolve()
    if (
        directory == ROOT
        or ROOT / "web" in directory.parents
        or ROOT / "src" in directory.parents
        or ROOT / "tests" in directory.parents
    ):
        parser.error("capture output must not overwrite source or historical corpora")
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    source = harness.manifest()
    result = {
        "verdict": "HOLD",
        "real_model_requests": 0,
        "variants": [],
        "source_sha256": harness.digest(source),
        "synthetic_provider_requests": 0,
    }
    harness.dump(directory / "source-pre.json", source)
    try:
        for variant in VARIANTS:
            own = directory / variant
            own.mkdir(mode=0o700)
            app = provider = None
            row = {"variant": variant, "verdict": "HOLD", "captures": []}
            result["variants"].append(row)
            try:
                app = CaptureProduct(own)
                with ProviderFixture([Scenario.text()], max_requests=3) as provider:
                    row["proof"] = run_variant(app, provider, variant)
                row["verdict"] = "ACTUAL_NATIVE_CAPTURE_NOT_REAL_MODEL"
            finally:
                if provider is not None:
                    row["synthetic_provider_requests"] = len(provider.requests)
                    result["synthetic_provider_requests"] += len(provider.requests)
                    row["provider_handlers_closed"] = provider.opened == provider.closed
                    harness.dump(own / "synthetic-provider-requests.json", provider.requests)
                if app is not None:
                    app.child.stop()
                    row["cleanup"] = app.child.receipt()
                    row["captures"] = app.captures
                harness.dump(own / "capture-result.json", row)
            assert row["provider_handlers_closed"] and row["cleanup"]["cleanup_verified"]
        assert [row["variant"] for row in result["variants"]] == list(VARIANTS)
        result["verdict"] = "ACTUAL_ALL_VARIANT_CAPTURE_NOT_REAL_MODEL"
    except Exception as exc:
        result.update(verdict="HOLD", error=f"{type(exc).__name__}: {exc}")
    finally:
        after = harness.manifest()
        harness.dump(directory / "source-post.json", after)
        if source != after:
            result.update(verdict="HOLD", error="source changed during capture")
        harness.dump(directory / "capture-result.json", result)
        if result["verdict"] == "ACTUAL_ALL_VARIANT_CAPTURE_NOT_REAL_MODEL":
            # Packaging keeps every raw_utf8 string byte-exact. Output stays in
            # the new owned directory; parent alone promotes it after review.
            harness.dump(
                directory / "producer.json",
                {
                    "schema_version": 1,
                    "provenance": (
                        "actual_current_native_http_all_variants_synthetic_provider_not_real_model"
                    ),
                    "capture": result,
                    "source_pre": source,
                    "source_post": after,
                    "producer_inputs": [
                        entry
                        for entry in source
                        if (
                            entry["path"].startswith(
                                ("src/", "tests/chat/", "tests/tooling/", "tools/")
                            )
                            or entry["path"] in {"pyproject.toml", "uv.lock"}
                        )
                    ],
                },
            )
        print(json.dumps(result, ensure_ascii=False))
    return 0 if result["verdict"] == "ACTUAL_ALL_VARIANT_CAPTURE_NOT_REAL_MODEL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
