"""Supervised entrypoint contracts; no database or external network in these tests."""

import asyncio
import fcntl
import os
import sys

import pytest

from aiddos.runs import worker


@pytest.mark.parametrize("value", ["not-an-id", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA", ""])
def test_invalid_selected_run_is_rejected_before_worker_entry(monkeypatch, value):
    entered = []

    async def run(**kwargs):
        entered.append(kwargs)
        return 0

    monkeypatch.setattr(worker, "run", run)
    monkeypatch.setattr(sys, "argv", ["worker", "--run-id", value])
    with pytest.raises(SystemExit) as refused:
        worker.main()
    assert refused.value.code == 2
    assert entered == []


def test_selected_run_id_is_forwarded_without_normalization(monkeypatch):
    run_id = "b81c0a84-4c4a-441f-a969-afd548e700d0"
    entered = []

    async def run(**kwargs):
        entered.append(kwargs)
        return 0

    monkeypatch.setattr(worker, "run", run)
    monkeypatch.setattr(sys, "argv", ["worker", "--run-id", run_id])
    assert worker.main() == 0
    assert entered == [{"run_id": run_id}]


@pytest.fixture
def coordinator_model(monkeypatch, tmp_path):
    """Control-flow model only; separate PostgreSQL tests prove real storage."""
    events = []

    class Connection:
        closed = False

        async def close(self):
            self.closed = True

    async def acquire(owner, pg, kwargs):
        events.append("connect")
        owner.connection = Connection()

    async def settings(execute):
        pass

    async def forbidden_recovery(owner):
        events.append("recovery")
        raise RuntimeError("automatic recovery must not run")

    async def no_claim(owner, **kwargs):
        events.append(("claim", kwargs))
        return None

    monkeypatch.setattr(worker, "parameters", lambda value: {"host": str(tmp_path)})
    monkeypatch.setattr(worker, "driver", lambda: object())
    monkeypatch.setattr(worker.ConnectionOwner, "acquire", acquire)
    monkeypatch.setattr(worker.schema, "settings", settings)
    monkeypatch.setattr(worker.schema, "ready", settings)
    monkeypatch.setattr(worker.transitions, "recover", forbidden_recovery)
    monkeypatch.setattr(worker.transitions, "claim", no_claim)
    return events


def test_selected_run_without_eligible_claim_exits_without_recovery(coordinator_model):
    run_id = "b81c0a84-4c4a-441f-a969-afd548e700d0"
    assert asyncio.run(worker.run(run_id=run_id)) == 69
    assert coordinator_model == ["connect", ("claim", {"run_id": run_id})]


def test_selected_run_completes_once_and_never_drains_queue(monkeypatch, coordinator_model):
    run_id = "b81c0a84-4c4a-441f-a969-afd548e700d0"
    calls = []

    async def claim(owner, **kwargs):
        calls.append(("claim", kwargs))
        if len(calls) > 1:
            raise RuntimeError("unexpected extra claim")
        return {"run_id": run_id}

    async def publish(owner, owned, step, result=None, **kwargs):
        calls.append(("publish", step))

    monkeypatch.setattr(worker.transitions, "claim", claim)
    monkeypatch.setattr(worker.transitions, "publish", publish)
    monkeypatch.setattr(worker.offline, "verify_claim", lambda owned, **kwargs: {})
    monkeypatch.setattr(worker.offline, "compile_manifest", lambda value, **kwargs: b"{}")
    assert asyncio.run(worker.run(run_id=run_id)) == 0
    assert coordinator_model == ["connect"]
    assert calls == [("claim", {"run_id": run_id}), ("publish", 1), ("publish", 2), ("publish", 3)]


@pytest.mark.parametrize("stopped_at", [1, 2, 3, "failure", "control"])
def test_non_success_never_claims_again(monkeypatch, coordinator_model, stopped_at):
    calls = []

    async def claim(owner, **kwargs):
        calls.append("claim")
        if calls.count("claim") > 1:
            raise RuntimeError("unexpected extra claim")
        return {"run_id": "b81c0a84-4c4a-441f-a969-afd548e700d0"}

    async def publish(owner, owned, step, result=None, **kwargs):
        calls.append(step)
        if step == 1 and stopped_at == "control":
            raise worker.ControlRequested()
        if step == stopped_at:
            return False

    def verify(owned, **kwargs):
        if stopped_at == "failure":
            raise ValueError("invalid snapshot")
        return {}

    monkeypatch.setattr(worker.transitions, "claim", claim)
    monkeypatch.setattr(worker.transitions, "publish", publish)
    monkeypatch.setattr(worker.offline, "verify_claim", verify)
    monkeypatch.setattr(worker.offline, "compile_manifest", lambda value, **kwargs: b"{}")
    assert asyncio.run(worker.run(run_id="b81c0a84-4c4a-441f-a969-afd548e700d0")) == 1
    assert calls.count("claim") == 1
    assert coordinator_model == ["connect"]


def test_repository_error_exits_without_reconnect(monkeypatch, coordinator_model):
    calls = []

    async def claim(owner, **kwargs):
        calls.append("claim")
        if len(calls) == 1:
            raise TimeoutError()
        raise RuntimeError("unexpected automatic retry")

    monkeypatch.setattr(worker.transitions, "claim", claim)
    assert asyncio.run(worker.run(run_id="b81c0a84-4c4a-441f-a969-afd548e700d0")) == 75
    assert calls == ["claim"]
    assert coordinator_model == ["connect"]


def test_stale_claim_is_not_retried(monkeypatch, coordinator_model):
    calls = []

    async def claim(owner, **kwargs):
        calls.append("claim")
        if len(calls) == 1:
            raise worker.transitions.StaleClaim()
        raise RuntimeError("unexpected extra claim")

    monkeypatch.setattr(worker.transitions, "claim", claim)
    assert asyncio.run(worker.run(run_id="b81c0a84-4c4a-441f-a969-afd548e700d0")) == 75
    assert calls == ["claim"]


def test_stop_is_not_reported_as_success(monkeypatch, coordinator_model):
    async def claim(owner, **kwargs):
        raise worker.Stopping()

    monkeypatch.setattr(worker.transitions, "claim", claim)
    assert asyncio.run(worker.run(run_id="b81c0a84-4c4a-441f-a969-afd548e700d0")) == 130


@pytest.mark.parametrize("held_mode", [fcntl.LOCK_EX, fcntl.LOCK_SH])
def test_busy_directory_refuses_before_database_connect(coordinator_model, tmp_path, held_mode):
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, held_mode | fcntl.LOCK_NB)
        assert asyncio.run(worker.run(run_id="b81c0a84-4c4a-441f-a969-afd548e700d0")) == 78
        assert coordinator_model == []
    finally:
        os.close(fd)


def test_supervised_holds_exclusive_directory_lock_through_driver_close(
    monkeypatch, coordinator_model, tmp_path
):
    observations = []

    class Connection:
        closed = False

        async def close(self):
            fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError:
                    observations.append("exclusive_through_close")
                else:
                    observations.append("unlocked_during_close")
            finally:
                os.close(fd)
            self.closed = True

    async def acquire(owner, pg, kwargs):
        owner.connection = Connection()

    monkeypatch.setattr(worker.ConnectionOwner, "acquire", acquire)
    assert asyncio.run(worker.run(run_id="b81c0a84-4c4a-441f-a969-afd548e700d0")) == 69
    assert observations == ["exclusive_through_close"]
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(fd)
