"""Phase2 operators and scoped verification remain explicit and separate."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def dry_run(target):
    result = subprocess.run(
        ["/usr/bin/make", "--no-print-directory", "--dry-run", target],
        cwd=ROOT, capture_output=True, text=True, timeout=5,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_storage_gate_collects_only_the_selected_database_path():
    command = dry_run("test-phase2-storage")
    for part in ("tests/evidence", "test_evidence_transport.py", "test_evidence_admission.py",
                 "test_boundary.py", "test_evidence_fresh_setup.py", "test_phase1_local.py",
                 "test_phase2_storage_targets.py", "test_evidence_postgres.py"):
        assert part in command
    assert "pytest tests/runs -q" not in command
    assert "test_worker_lifecycle.py" not in command
    assert "junit_family=legacy" in command


def test_phase2_local_is_an_explicit_fresh_create():
    command = dry_run("phase2-local")
    assert 'tools/phase1_local.py create --workspace "$PHASE1_WORKSPACE" --evidence' in command
    assert "worker" not in command


def test_existing_phase1_commands_do_not_implicitly_enable_evidence():
    for target in ("phase1-local", "phase1-open"):
        assert "--evidence" not in dry_run(target)
