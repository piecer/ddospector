"""Evidence gates are discoverable without running the deferred runs campaign."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def dry_run(target):
    return subprocess.run(
        ["/usr/bin/make", "--no-print-directory", "--dry-run", target],
        cwd=ROOT, capture_output=True, text=True, timeout=5,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )


def test_standalone_evidence_gate_is_file_only():
    result = dry_run("test-evidence")
    assert result.returncode == 0, result.stderr
    assert "pytest tests/evidence -q" in result.stdout
    assert "pytest tests/runs" not in result.stdout
    assert "npm" not in result.stdout


def test_default_gate_collects_evidence_without_dropping_other_suites():
    result = dry_run("test")
    assert result.returncode == 0, result.stderr
    for command in ("pytest tests/evidence -q", "pytest tests/api -q",
                    "pytest tests/runs -q", "pytest tests/tooling -q",
                    "npm --prefix web test"):
        assert command in result.stdout


def test_canonical_lint_collects_new_evidence_tests():
    result = dry_run("lint")
    assert result.returncode == 0, result.stderr
    ruff = next(line for line in result.stdout.splitlines() if "ruff check" in line)
    assert "tests/evidence" in ruff.split()
