"""Collection-only config checks; no webServer/browser/PG is launched."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5180",
        "https://example.com",
        "http://127.0.0.1:5175/path",
    ],
)
def test_config_refuses_missing_or_foreign_origin(tmp_path, origin):
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path),
        "I3_WEB_OUTPUT": str(tmp_path),
        "LANG": "C.UTF-8",
    }
    if origin is not None:
        env["I3_WEB_ORIGIN"] = origin
    result = collect(env)
    assert result.returncode == 1
    assert "explicit owned I3_WEB_ORIGIN" in result.stdout + result.stderr


def collect(env):
    with subprocess.Popen(
        [
            "/usr/bin/node",
            str(ROOT / "web/node_modules/playwright/cli.js"),
            "test",
            "--config",
            str(ROOT / "web/playwright.runs.config.ts"),
            "--list",
        ],
        cwd=ROOT,
        env=env,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as process:
        stdout, stderr = process.communicate(timeout=15)
        return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)


def test_config_requires_explicit_output(tmp_path):
    result = collect(
        {
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "TMPDIR": str(tmp_path),
            "I3_WEB_ORIGIN": "http://127.0.0.1:5175",
        }
    )
    assert result.returncode == 1
    assert "explicit owned I3_WEB_OUTPUT" in result.stdout + result.stderr


def test_repository_relative_full_collection_without_resources(tmp_path):
    result = collect(
        {
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "TMPDIR": str(tmp_path),
            "I3_WEB_ORIGIN": "http://127.0.0.1:5175",
            "I3_WEB_OUTPUT": str(tmp_path),
        }
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Total: 2 tests in 1 file" in result.stdout
    assert "real EN/KO" in result.stdout and "exact-byte" in result.stdout
    assert "owned ephemeral-origin" not in result.stdout
