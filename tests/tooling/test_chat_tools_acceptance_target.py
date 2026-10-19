"""Fixture harness controls, not B product acceptance; zero real model calls."""

import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import chat_tools_acceptance as harness  # noqa: E402


@pytest.mark.parametrize("case", ["agent", "target"])
def test_fixture_selector_reaches_only_fixture_runner(tmp_path, monkeypatch, case):
    observed = []

    def forbidden(*_args, **_kwargs):
        pytest.fail("selector control attempted network")

    def browser(mode, directory, result, admission=None, *, fixture_case="agent"):
        observed.append((mode, fixture_case, admission))
        result.update(verdict="HARNESS_SELECTOR_ONLY", wrapper_exit=0)

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(harness, "run_browser", browser)
    out = tmp_path / "fixture"
    assert harness.main(["--mode", "fixture", "--fixture-case", case, "--artifacts", str(out)]) == 0
    assert observed == [("fixture", case, None)]
    result = json.loads((out / "result.json").read_text())
    assert result["real_model_requests"] == 0 and result["product_green"] is False
    assert result["fixture_case"] == case


@pytest.mark.parametrize("mode", ["preflight", "real"])
@pytest.mark.parametrize("case", ["agent", "target"])
def test_explicit_selector_denied_outside_fixture_before_any_side_effect(
    tmp_path, monkeypatch, mode, case
):
    def forbidden(*_args, **_kwargs):
        pytest.fail("denied selector reached runner or admission")

    for name in ("run_browser", "parent_gate", "observer_preflight", "manifest"):
        monkeypatch.setattr(harness, name, forbidden)
    out = tmp_path / "denied"
    with pytest.raises(SystemExit) as caught:
        harness.main(
            [
                "--mode",
                mode,
                "--fixture-case",
                case,
                "--allow-real-model",
                "--parent-admission",
                "/nonexistent",
                "--artifacts",
                str(out),
            ]
        )
    assert caught.value.code == 2 and not out.exists()


@pytest.mark.parametrize("case", ["Target", "", "targets", "agent_v1"])
def test_closed_fixture_selector(tmp_path, case):
    out = tmp_path / "denied"
    with pytest.raises(SystemExit) as caught:
        harness.main(["--mode", "fixture", "--fixture-case", case, "--artifacts", str(out)])
    assert caught.value.code == 2 and not out.exists()


def test_target_plan_native_bytes_use_current_revision_without_generated_fields():
    before = {"meta": {"audit_retention": {"total_recorded": 47}}}
    scenarios = harness.plan(before, fixture_case="target")
    assert len(scenarios) == 3
    calls = [
        json.loads(s.chunks[0][6:])["choices"][0]["delta"]["tool_calls"][0] for s in scenarios[:2]
    ]
    assert calls[0]["function"]["name"] == "configuration_read"
    assert json.loads(calls[0]["function"]["arguments"]) == {
        "kind": "targets",
        "offset": 0,
        "limit": 10,
    }
    assert calls[1]["function"]["name"] == "target_create"
    assert json.loads(calls[1]["function"]["arguments"]) == {
        "expected_draft_revision": 47,
        "name": "CHAT02B1 승인된 대상 🌍",
        "address": "Example.COM.",
        "kind": "DUT",
    }
    assert calls[0]["id"] != calls[1]["id"]
    assert b"SYNTHETIC" in b"".join(scenarios[2].chunks)


def test_agent_plan_default_keeps_existing_native_calls():
    before = {
        "meta": {"audit_retention": {"total_recorded": 8}},
        "agent_profile": {"skill_ids": ["literal-skill"]},
    }
    assert harness.plan(before) == harness.plan(before, fixture_case="agent")
    calls = [
        json.loads(s.chunks[0][6:])["choices"][0]["delta"]["tool_calls"][0]
        for s in harness.plan(before)[:2]
    ]
    assert [call["function"]["name"] for call in calls] == [
        "configuration_read",
        "agent_profile_update",
    ]
    assert json.loads(calls[1]["function"]["arguments"])["skill_ids"] == ["literal-skill"]


def test_default_fixture_selects_agent(tmp_path, monkeypatch):
    observed = []

    def browser(mode, directory, result, admission=None, *, fixture_case="agent"):
        observed.append((mode, fixture_case, admission))
        result.update(verdict="HARNESS_SELECTOR_ONLY", wrapper_exit=0)

    monkeypatch.setattr(harness, "run_browser", browser)
    assert harness.main(["--mode", "fixture", "--artifacts", str(tmp_path / "default")]) == 0
    assert observed == [("fixture", "agent", None)]


@pytest.mark.parametrize(
    "mode,case,admission",
    [
        ("real", "target", None),
        ("fixture", "bogus", None),
        ("fixture", "target", {"ledger": "forbidden"}),
    ],
)
def test_runner_defense_in_depth_before_startup(tmp_path, monkeypatch, mode, case, admission):
    def forbidden(*_args, **_kwargs):
        pytest.fail("invalid fixture runner reached startup")

    monkeypatch.setattr(harness, "launch_api", forbidden)
    monkeypatch.setattr(harness, "ProviderFixture", forbidden)
    with pytest.raises(RuntimeError):
        harness.run_browser(mode, tmp_path, {}, admission, fixture_case=case)


@pytest.mark.parametrize("case", ["agent", "target"])
def test_actual_playwright_fixture_collection_is_one_closed_case(tmp_path, case):
    env = harness.clean_env(
        {
            "CHAT02A_DIR": str(tmp_path),
            "CHAT02A_MODE": "fixture",
            "CHAT02A_WEB": "http://127.0.0.1:5175",
            "CHAT02B1_FIXTURE_CASE": case,
        }
    )
    result = subprocess.run(
        [
            "/usr/bin/node",
            "node_modules/@playwright/test/cli.js",
            "test",
            "--list",
            "--config",
            "playwright.chat-tools.config.ts",
        ],
        cwd=ROOT / "web",
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Total: 1 test in 1 file" in result.stdout
    assert (
        "native fixture approved target creation"
        if case == "target"
        else "native fixture approved Agent write"
    ) in result.stdout
    assert "native real model" not in result.stdout


@pytest.mark.parametrize(
    "mode,case", [("real", "agent"), ("real", "target"), ("fixture", "unknown")]
)
def test_actual_playwright_config_rejects_invalid_selector(tmp_path, mode, case):
    result = subprocess.run(
        [
            "/usr/bin/node",
            "node_modules/@playwright/test/cli.js",
            "test",
            "--list",
            "--config",
            "playwright.chat-tools.config.ts",
        ],
        cwd=ROOT / "web",
        env=harness.clean_env(
            {
                "CHAT02A_DIR": str(tmp_path),
                "CHAT02A_MODE": mode,
                "CHAT02A_WEB": "http://127.0.0.1:5175",
                "CHAT02B1_FIXTURE_CASE": case,
            }
        ),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode != 0
    assert "Fixture case is closed and forbidden outside fixture mode" in result.stderr


def test_target_registry_still_cannot_debit_real_ledger(tmp_path):
    import time

    import httpx2

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
                for name in ("configuration_read", "target_create")
            ],
        },
    )
    with pytest.raises(RuntimeError, match="unapproved tool registry"):
        harness.debit(ledger, request)
    assert ledger.read_bytes() == before


def test_actual_domain_literal_oracle_does_not_normalize_or_claim_independence():
    sys.path.insert(0, str(ROOT / "tests/chat"))
    from chat_target_capture import literal_oracle

    result = literal_oracle()
    assert "domain-derived" in result["provenance"]
    cases = result["cases"]
    assert len(cases) == 19 and len({item["case"] for item in cases}) == 19
    trailing = next(
        item for item in cases if json.loads(item["raw_utf8"])["address"] == "Example.COM."
    )
    assert trailing["accepted"] is True
    assert trailing["value"]["address"] == "Example.COM."
    assert any(not item["accepted"] for item in cases)
    for item in cases:
        if item["accepted"]:
            assert item["value"] == json.loads(item["raw_utf8"])


def test_target_provider_plan_real_loopback_wire_has_only_three_synthetic_requests():
    import httpx2

    before = {"meta": {"audit_retention": {"total_recorded": 11}}}
    with harness.ProviderFixture(
        harness.plan(before, fixture_case="target"), max_requests=3
    ) as provider:
        with httpx2.Client(trust_env=False, timeout=5) as client:
            for _ in range(3):
                response = client.post(
                    provider.base_url + "/chat/completions", json={"model": "SYNTHETIC"}
                )
                assert response.status_code == 200
            assert (
                client.post(
                    provider.base_url + "/chat/completions", json={"model": "SYNTHETIC"}
                ).status_code
                == 429
            )
        assert len(provider.requests) == 3
    assert provider.opened == provider.closed == 4


def test_capture_failure_keeps_observed_synthetic_count_not_success(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "tests/chat"))
    import chat_target_capture as capture

    class Provider:
        requests = []
        opened = closed = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.closed = self.opened

    class Child:
        def stop(self):
            pass

        def receipt(self):
            return {"cleanup_verified": True}

    class Product:
        captures = []
        child = Child()

    provider = Provider()

    def fail(_app, observed, **_kwargs):
        observed.requests = [{"HARNESS_ONLY": 1}, {"HARNESS_ONLY": 2}]
        observed.opened = 2
        raise AssertionError("SYNTHETIC capture failure after two observed requests")

    monkeypatch.setattr(capture, "CaptureProduct", lambda _: Product())
    monkeypatch.setattr(capture, "ProviderFixture", lambda *a, **k: provider)
    monkeypatch.setattr(capture, "setup_plan", fail)
    out = tmp_path / "capture"
    assert capture.main(["--output", str(out)]) == 1
    result = json.loads((out / "capture-result.json").read_text())
    assert result["verdict"] == "HOLD" and result["real_model_requests"] == 0
    assert result["synthetic_provider_requests"] == 2
    assert result["provider_handlers_closed"] is True
    assert result["captures"] == []
