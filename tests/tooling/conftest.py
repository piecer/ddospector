"""Portable tooling prerequisites without weakening subprocess isolation."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def portable_system_node(monkeypatch):
    """Use the installed Node when the historical /usr/bin path is absent."""
    if Path("/usr/bin/node").is_file():
        yield
        return
    discovered = shutil.which("node")
    if discovered is None:
        pytest.fail("Node.js is required; run make setup with node available on PATH")
    node = str(Path(discovered).resolve(strict=True))
    if not Path(node).is_file() or not os.access(node, os.X_OK):
        pytest.fail("Resolved Node.js executable is not an executable file")
    original = subprocess.Popen

    def popen(args, *positional, **keywords):
        if (
            isinstance(args, (list, tuple))
            and args
            and os.fspath(args[0]) == "/usr/bin/node"
        ):
            args = [node, *args[1:]]
        return original(args, *positional, **keywords)

    monkeypatch.setattr(subprocess, "Popen", popen)
    yield
