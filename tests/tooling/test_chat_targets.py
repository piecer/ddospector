"""The chat feature participates in the canonical project gates."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_chat_has_a_canonical_target_and_is_in_aggregate_test():
    makefile = (ROOT / "Makefile").read_text()
    assert "test-chat:\n\tuv run --frozen pytest tests/chat -q\n" in makefile
    aggregate = next(line for line in makefile.splitlines() if line.startswith("test:"))
    assert "test-chat" in aggregate.split()[1:]


def test_chat_tests_participate_in_default_collection_and_lint():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "tests/chat" in config["tool"]["pytest"]["ini_options"]["testpaths"]
    makefile = (ROOT / "Makefile").read_text()
    ruff_line = next(line for line in makefile.splitlines() if "ruff check " in line)
    assert "tests/chat" in ruff_line.split()


def test_chat_http_client_is_a_runtime_dependency_with_existing_lock():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "httpx2>=2.13,<3" in config["project"]["dependencies"]
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    package = next(item for item in lock["package"] if item["name"] == "ddospector")
    assert {"name": "httpx2"} in package["dependencies"]
