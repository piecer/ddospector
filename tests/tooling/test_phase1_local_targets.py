"""Operator-facing Make targets must forward values without shell interpolation."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("target", "verb"),
    [("phase1-local", "create"), ("phase1-open", "open"), ("phase1-worker", "worker")],
)
def test_phase1_operator_targets(target, verb):
    result = subprocess.run(
        ["/usr/bin/make", "--no-print-directory", "--dry-run", target],
        cwd=ROOT, capture_output=True, text=True, timeout=5,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    assert result.returncode == 0, result.stderr
    assert f'tools/phase1_local.py {verb} --workspace "$PHASE1_WORKSPACE"' in result.stdout
    if verb == "worker":
        assert '--run-id "$PHASE1_RUN_ID"' in result.stdout


def test_missing_workspace_refused_before_provisioning():
    result = subprocess.run(
        ["/usr/bin/make", "--no-print-directory", "phase1-local", "WORKSPACE="],
        cwd=ROOT, capture_output=True, text=True, timeout=5,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    assert result.returncode != 0
    assert "DURABLE_SHORT_LITERAL_WORKSPACE_REQUIRED" in result.stderr
    assert not (ROOT / "workspace.json").exists()
