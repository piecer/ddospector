"""W1 real-process witnesses; no inherited results are counted here."""

import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from tools import s02_harness as h

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def tmp_path(request, tmp_path_factory):
    if "W1_EVIDENCE" not in os.environ:
        return tmp_path_factory.mktemp("worker-lifecycle")
    path = Path(os.environ["W1_EVIDENCE"]) / "resources" / (request.node.name + "-" + uuid4().hex)
    path.mkdir(parents=True)
    return path


def run_case(owner, case, budget=60):
    owner.revalidate()
    output = owner.directory / case
    output.mkdir()
    handoff = {
        "root": str(ROOT),
        "socket": str(owner.socket),
        "output": str(output),
        "owner": owner.owner_process,
        "case": case,
    }
    path = output / "handoff.json"
    path.write_text(json.dumps(handoff) + "\n")
    events = []
    controller = None
    errors = []
    if case.startswith("outage-"):
        import threading
        import time

        def control():
            try:
                until = time.monotonic() + 15
                while not (output / "outage-ready.json").exists():
                    assert time.monotonic() < until
                    time.sleep(0.02)
                owner.revalidate()
                owner.call("stop", "--timeout", "2", owner.cid, timeout=5)
                (output / "db-stopped").touch()
                if case == "outage-recover":
                    time.sleep(2)
                    owner.revalidate()
                    owner.call("start", owner.cid)
                    (output / "db-restarted").touch()
            except BaseException as error:
                errors.append(type(error).__name__)

        controller = threading.Thread(target=control)
        controller.start()
    result = h.run_child(
        [sys.executable, str(ROOT / "tests/runs/worker_lifecycle_probe.py"), str(path)],
        output,
        budget,
        events.append,
    )
    if controller is not None:
        controller.join(timeout=20)
        assert not controller.is_alive() and not errors, errors
    (output / "launch.json").write_text(
        json.dumps(
            {
                "code": result.code,
                "timed_out": result.timed_out,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "events": events,
            },
            indent=2,
        )
        + "\n"
    )
    assert not result.timed_out, str(output)
    assert result.code == 0, str(output)
    return json.loads((output / "result.json").read_text())


def test_worker_fixture_without_supervisor_environment(monkeypatch, request, tmp_path_factory):
    monkeypatch.delenv("W1_EVIDENCE", raising=False)
    assert tmp_path.__wrapped__(request, tmp_path_factory).is_dir()


def test_worker_completion_precommit_atomic_rollback(owned_pg):
    assert run_case(owned_pg, "atomic-complete")["no_partial_writes"]


def test_worker_deadline_after_real_row_lock_wait(owned_pg):
    result = run_case(owned_pg, "row-lock-deadline")
    assert result["lock_observed"] and result["state"] == "TIMED_OUT"


def test_worker_unaccelerated_300s_queued_deadline(owned_pg):
    result = run_case(owned_pg, "real-deadline", budget=360)
    assert result["age_seconds"] >= 300 and result["attempt"] == 0


def test_worker_idle_waiters_bounded(owned_pg):
    result = run_case(owned_pg, "idle")
    assert max(result["waiter_counts"]) <= 1


def test_worker_pure_steps_outside_transaction(owned_pg):
    result = run_case(owned_pg, "pure")
    assert result["state"] == "SUCCEEDED"
    assert all(
        x["thread"] != result["main_thread"] and x["transaction"] is False for x in result["calls"]
    )
    assert len({x["thread"] for x in result["calls"]}) == 1


def test_worker_two_competitors_third_heartbeat(owned_pg):
    result = run_case(owned_pg, "compete")
    assert result["max_leased"] == 2 and result["terminal_count"] == 3


def test_worker_sigkill_restart_recovers_expired_claim(owned_pg):
    result = run_case(owned_pg, "restart")
    assert result["attempt"] == 2 and result["generation"] == 4


def test_worker_three_interrupted_claims_exhausted(owned_pg):
    result = run_case(owned_pg, "exhausted")
    assert result["state"] == "FAILED" and result["attempt"] == 3


def test_worker_sigstop_old_generation_fenced(owned_pg):
    result = run_case(owned_pg, "stale")
    assert result["same_connection"] and result["unchanged"]


def test_worker_observes_committed_cancel_intent(owned_pg):
    result = run_case(owned_pg, "cancel")
    assert result["state"] == "CANCELLED" and result["reason"] == "WORKER_ACK"


@pytest.mark.parametrize("case", ["deadline-queued", "deadline-owner"])
def test_worker_deadline_arbitration(owned_pg, case):
    result = run_case(owned_pg, case)
    assert result["state"] == "TIMED_OUT"


def test_worker_expired_cancel_precedes_deadline(owned_pg):
    result = run_case(owned_pg, "cancel-expired")
    assert result["reason"] == "LEASE_REVOKED"


@pytest.mark.parametrize("case", ["refuse-config", "refuse-schema", "refuse-driver"])
def test_worker_startup_refusal78(owned_pg, case):
    assert run_case(owned_pg, case)["exit"] == 78


@pytest.mark.parametrize("case", ["watchdog", "term-stuck"])
def test_worker_nonquiescent_actual_exit75(owned_pg, case):
    assert run_case(owned_pg, case)["exit"] == 75


def test_worker_cooperative_term_shared_grace(owned_pg):
    assert run_case(owned_pg, "term-cooperative")["exit"] == 0


def test_worker_heartbeat_quiesces_cancelled_work(owned_pg):
    assert run_case(owned_pg, "cancel-cooperative")["reason"] == "WORKER_ACK"


@pytest.mark.parametrize("case", ["close-unconfirmed", "close-pending"])
def test_worker_disposal_uncertainty_exit75(owned_pg, case):
    assert run_case(owned_pg, case)["exit"] == 75


@pytest.mark.parametrize("case", ["outage-recover", "outage-exhaust"])
def test_worker_real_outage_reconnect(owned_pg, case):
    assert run_case(owned_pg, case)["verified"]


@pytest.mark.parametrize(
    "case,code",
    [
        ("pure-invalid", "SNAPSHOT_INVALID"),
        ("pure-failure", "OFFLINE_PREPARATION_FAILED"),
        ("pure-limit", "RESULT_LIMIT_EXCEEDED"),
    ],
)
def test_worker_pure_failure_not_repository_failure(owned_pg, case, code):
    assert run_case(owned_pg, case)["failure_code"] == code
