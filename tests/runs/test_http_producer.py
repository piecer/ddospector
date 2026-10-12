"""Real HTTP producer cases on an exclusively owned PostgreSQL instance."""

import hashlib
import json
import sys
from pathlib import Path

from tools import s02_harness as h

ROOT = Path(__file__).resolve().parents[2]


def probe(owner, case):
    owner.check_work()
    owner.revalidate()
    output = owner.directory / ("http-" + case)
    output.mkdir()
    handoff = {
        "root": str(ROOT),
        "prefix": str(ROOT / ".venv"),
        "python": str(ROOT / ".venv/bin/python"),
        "owner": owner.owner_process,
        "socket": str(owner.socket),
        "output": str(output),
        "case": case,
        "source": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "src").rglob("*.py"))
        },
    }
    path = output / "handoff.json"
    path.write_text(json.dumps(handoff, indent=2) + "\n")
    assert Path(sys.prefix) == ROOT / ".venv"
    observations = []

    def launch():
        return h.run_child(
            [handoff["python"], str(ROOT / "tests/runs/http_producer_probe.py"), str(path)],
            output,
            60,
            observations.append,
        )

    if case == "outage":
        import time
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(launch)
            for action in ("stop", "start"):
                until = time.monotonic() + 30
                while not (output / ("request-" + action)).exists():
                    assert not pending.done() and time.monotonic() < until
                    time.sleep(0.02)
                owner.revalidate()
                if action == "stop":
                    owner.call("stop", "--timeout", "2", owner.cid, timeout=5)
                else:
                    owner.call("start", owner.cid)
                owner.revalidate()
                (output / ("done-" + action)).write_text("owned exact container action complete\n")
            result = pending.result(timeout=30)
    else:
        result = launch()
    (output / "launch.json").write_text(
        json.dumps(
            {
                "observations": observations,
                "actual_exit": result.code,
                "timed_out": result.timed_out,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
            indent=2,
        )
        + "\n"
    )
    assert not result.timed_out
    assert result.code == 0, f"HTTP_PROBE_FAILED: {output}"
    return json.loads((output / "result.json").read_text())


def test_http_list_stable_through_and_raw_query(owned_pg):
    assert probe(owned_pg, "list")["verified"]


def test_http_events_pagination_existence_integrity(owned_pg):
    assert probe(owned_pg, "events")["verified"]


def test_http_failed_snapshot_summary_is_not_detail(owned_pg):
    assert probe(owned_pg, "failed-summary")["verified"]


def test_http_queued_cancel_atomic_idempotent(owned_pg):
    assert probe(owned_pg, "cancel-queued")["verified"]


def test_http_running_cancel_truthful_pending(owned_pg):
    assert probe(owned_pg, "cancel-running")["verified"]


def test_http_expired_cancel_revokes_lease(owned_pg):
    assert probe(owned_pg, "cancel-expired")["verified"]


def test_http_deadline_precedes_new_cancellation(owned_pg):
    assert probe(owned_pg, "cancel-deadline")["verified"]


def test_http_outage_restart_all_read_families_no_cache(owned_pg):
    assert probe(owned_pg, "outage")["verified"]


def test_http_sql_lock_orders_atomic_visibility_and_fresh_clock(owned_pg):
    assert probe(owned_pg, "locks")["verified"]


def test_http_natural_16_unfinished_128_retained_and_full_pagination(owned_pg):
    assert probe(owned_pg, "caps")["verified"]


def test_http_cancel_uncommitted_visibility_and_rollback(owned_pg):
    assert probe(owned_pg, "atomic")["verified"]


def test_http_cancel_readiness_existence_integrity_before_arbitration(owned_pg):
    assert probe(owned_pg, "priority")["verified"]


def test_http_sql_terminal_stickiness_and_long_event_pages(owned_pg):
    assert probe(owned_pg, "terminal")["verified"]


def test_http_cancel_uncertain_ack_recovers_exact_committed_terminal(owned_pg):
    assert probe(owned_pg, "uncertain")["verified"]


def test_http_missing_job_is_corrupt_not_missing_identity(owned_pg):
    assert probe(owned_pg, "orphan")["verified"]
