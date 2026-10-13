"""Canonical target coverage without executing the printed workloads."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def dry_run(target):
    result = subprocess.run(
        ["/usr/bin/make", "--no-print-directory", "--dry-run", target],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    return result.stdout


def test_canonical_test_includes_tooling_and_retains_existing_suites():
    commands = dry_run("test")
    assert "pytest tests/tooling -q" in commands
    assert "pytest tests/api -q" in commands
    assert "pytest tests/runs -q" in commands
    assert "npm --prefix web test" in commands


def test_tooling_can_be_run_without_database_suite():
    commands = dry_run("test-tooling")
    assert "pytest tests/tooling -q" in commands
    assert "pytest tests/runs" not in commands


def test_canonical_lint_includes_tooling():
    commands = dry_run("lint")
    ruff = next(line for line in commands.splitlines() if "ruff check" in line)
    assert "tests/tooling" in ruff.split()
    assert {"src", "tests/api", "tests/runs", "tools"} <= set(ruff.split())
