"""CHAT02B2 harness-only controls; no browser/capture/native target execution."""

import json
import socket
import sys
import time
from pathlib import Path

import httpx2
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import chat_tools_acceptance as harness  # noqa: E402


def test_frozen_historical_sidecar_binds_all_base_blobs_without_live_fallback():
    import hashlib
    import subprocess

    path = ROOT / "web/src/pages/ai/chat-target-producer-data/producer-baseline.json"
    assert path.is_file(), "historical sidecar not yet materialized"
    binding = json.loads(path.read_bytes())
    assert binding["base_commit"] == "5d41294644f1138f6638e69451e1e565a42c3b54"
    assert (
        subprocess.check_output(["git", "rev-parse", binding["base_commit"] + "^{tree}"], cwd=ROOT)
        .decode()
        .strip()
        == binding["base_tree"]
    )
    raw = (ROOT / binding["corpus_path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == binding["corpus_sha256"]
    corpus = json.loads(raw)
    rows = binding["producer_inputs"]
    assert len(rows) == len({row["path"] for row in rows}) == 92
    assert [
        {"path": row["path"], "sha256": row["sha256"], "mode": row["recorded_mode"]} for row in rows
    ] == corpus["producer_inputs"]
    for row in rows:
        entry = subprocess.check_output(
            ["git", "ls-tree", binding["base_commit"], "--", row["path"]], cwd=ROOT
        ).decode()
        metadata, name = entry.rstrip("\n").split("\t")
        mode, kind, oid = metadata.split()
        assert (name, kind, mode, oid) == (
            row["path"],
            "blob",
            row["git_mode"],
            row["base_blob_oid"],
        )
        blob = subprocess.check_output(["git", "cat-file", "blob", row["base_blob_oid"]], cwd=ROOT)
        assert hashlib.sha256(blob).hexdigest() == row["sha256"]
        assert oct(int(mode, 8) & 0o777) == row["recorded_mode"]


def test_capture_discovers_runtime_before_native_admission(monkeypatch):
    from test_chat_skill_capture_ordering import (
        test_capture_discovers_runtime_before_native_admission as ordering_probe,
    )

    ordering_probe(monkeypatch, "skill")


def test_skill_plan_has_only_literal_native_creation():
    before = {"meta": {"audit_retention": {"total_recorded": 47}}}
    scenarios = harness.plan(before, fixture_case="skill")
    assert len(scenarios) == 3
    calls = [
        json.loads(s.chunks[0][6:])["choices"][0]["delta"]["tool_calls"][0] for s in scenarios[:2]
    ]
    assert calls[0]["function"]["name"] == "configuration_read"
    assert json.loads(calls[0]["function"]["arguments"]) == {
        "kind": "skills",
        "offset": 0,
        "limit": 10,
    }
    assert calls[1]["function"]["name"] == "skill_create"
    arguments = json.loads(calls[1]["function"]["arguments"])
    assert set(arguments) == {
        "expected_draft_revision",
        "name",
        "description",
        "instructions",
        "category",
    }
    assert arguments == {"expected_draft_revision": 47, **harness.SKILL_INPUT}
    assert calls[0]["id"] != calls[1]["id"]
    assert b"SYNTHETIC" in b"".join(scenarios[2].chunks)
    with pytest.raises(ValueError):
        harness.plan(before, fixture_case="skill", skills=[])


@pytest.mark.parametrize(
    "mode,extra",
    [
        ("real", []),
        ("preflight", []),
        ("fixture", ["--serve-api", "99"]),
    ],
)
def test_skill_fixture_selector_refuses_real_mode_before_side_effects(
    tmp_path,
    monkeypatch,
    mode,
    extra,
):
    entries = []

    def forbidden(*args, **kwargs):
        entries.append((args, kwargs))
        pytest.fail("denied selector entered a target")

    for name in ("run_browser", "parent_gate", "observer_preflight", "manifest", "serve_api"):
        monkeypatch.setattr(harness, name, forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    out = tmp_path / "denied"
    with pytest.raises(SystemExit) as caught:
        harness.main(
            [
                "--mode",
                mode,
                "--fixture-case",
                "skill",
                "--artifacts",
                str(out),
                *extra,
            ]
        )
    assert caught.value.code == 2
    assert entries == [] and not out.exists()


def test_skill_fixture_routes_only_to_intercepted_runner(tmp_path, monkeypatch):
    entries = []

    def forbidden(*args, **kwargs):
        pytest.fail("harness-only selector entered network/native target")

    def runner(mode, directory, result, admission=None, *, fixture_case="agent"):
        entries.append((mode, fixture_case, admission))
        result.update(verdict="HARNESS_SELECTOR_ONLY", wrapper_exit=0)

    monkeypatch.setattr(harness, "run_browser", runner)
    monkeypatch.setattr(harness, "observer_preflight", lambda _: {"harness_only": True})
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    out = tmp_path / "selector"
    assert (
        harness.main(["--mode", "fixture", "--fixture-case", "skill", "--artifacts", str(out)]) == 0
    )
    assert entries == [("fixture", "skill", None)]
    result = json.loads((out / "result.json").read_bytes())
    assert result["product_green"] is False and result["real_model_requests"] == 0
    assert result["wall_seconds"] == 900 and result["hard_dispatch_cap"] == 6


@pytest.mark.parametrize("mode,admission", [("real", None), ("preflight", None), ("fixture", {})])
def test_skill_direct_runner_denies_before_any_target(tmp_path, monkeypatch, mode, admission):
    entries = []

    def forbidden(*args, **kwargs):
        entries.append((args, kwargs))
        pytest.fail("denied direct runner entered target")

    for name in ("launch_api", "ProviderFixture", "record_provider", "require_runtime"):
        monkeypatch.setattr(harness, name, forbidden)
    with pytest.raises(RuntimeError):
        harness.run_browser(mode, tmp_path, {}, admission, fixture_case="skill")
    assert entries == []


def test_skill_registry_cannot_debit_real_ledger(tmp_path):
    ledger = tmp_path / "ledger.json"
    started = time.monotonic()
    harness.initialize_ledger(ledger, started, started + 30)
    before = ledger.read_bytes()
    request = httpx2.Request(
        "POST",
        harness.COMPLETIONS,
        json={
            **harness.observer_payload(),
            "tools": [
                {"type": "function", "function": {"name": name}}
                for name in ("configuration_read", "skill_create")
            ],
        },
    )
    with pytest.raises(RuntimeError, match="unapproved tool registry"):
        harness.debit(ledger, request)
    assert ledger.read_bytes() == before


@pytest.mark.parametrize(
    "case,version,accepted",
    [
        ("agent", 1, True),
        ("agent", 2, True),
        ("agent", 3, True),
        ("target", 1, False),
        ("target", 2, True),
        ("target", 3, True),
        ("skill", 1, False),
        ("skill", 2, False),
        ("skill", 3, True),
        ("skill", 4, False),
        ("bogus", 3, False),
    ],
)
def test_explicit_runtime_variant_metadata(tmp_path, monkeypatch, case, version, accepted):
    tools = ["configuration_read", "agent_profile_update"]
    if version in (2, 3, 4):
        tools.append("target_create")
    if version in (3, 4):
        tools.append("skill_create")
    body = {
        "supported": True,
        "requires_write_approval": True,
        "schema_version": version,
        "tools": tools,
    }
    monkeypatch.setattr(harness, "http", lambda *a: (200, body))
    if accepted:
        harness.require_runtime("HARNESS_ONLY", tmp_path, fixture_case=case)
    else:
        with pytest.raises((AssertionError, ValueError)):
            harness.require_runtime("HARNESS_ONLY", tmp_path, fixture_case=case)
