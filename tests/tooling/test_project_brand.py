"""Current branding and public commands, without loading the application."""

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_distribution_names_and_positioning():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["name"] == "ddospector"
    assert project["description"] == "AI-Powered DDoS Defense Validation Framework"
    package = json.loads((ROOT / "web/package.json").read_text())
    lock = json.loads((ROOT / "web/package-lock.json").read_text())
    assert package["name"] == lock["name"] == lock["packages"][""]["name"] == "ddospector-ui"


def test_current_documentation_uses_requested_identity():
    readme = (ROOT / "README.md").read_text()
    assert readme.startswith("# DDoSpector\n")
    assert "AI-Powered DDoS Defense Validation Framework" in readme
    assert "Find the gaps before attackers do." in readme
    assert (
        "AI-powered open-source framework for automated DDoS defense testing, "
        "mitigation gap discovery, and security validation."
    ) in readme
    assert (ROOT / "docs/UI_GUIDE_KO.md").read_text().startswith("# DDoSpector")


def test_public_make_commands_use_ddospector_entrypoints():
    makefile = (ROOT / "Makefile").read_text()
    assert "DDoSpector · local UI workspace" in makefile
    assert ".venv/bin/python -m uvicorn ddospector.api.app:app" in makefile
    assert ".venv/bin/python -m ddospector.runs.migrate" in makefile


def test_setup_installs_the_browser_used_by_playwright():
    makefile = (ROOT / "Makefile").read_text()
    assert "npm --prefix web exec -- playwright install --no-shell chromium" in makefile
    for name in (
        "playwright.config.ts",
        "playwright.chat.config.ts",
        "playwright.chat-tools.config.ts",
        "playwright.phase1.config.ts",
        "playwright.runs.config.ts",
    ):
        assert 'channel: "chromium"' in (ROOT / "web" / name).read_text(), name
    focus = (ROOT / "web/playwright.runs-focus.config.ts").read_text()
    parity = (ROOT / "web/playwright.runs-parity.config.ts").read_text()
    assert "executablePath: process.env.FOCUS_CHROMIUM" in focus
    assert 'from "./playwright.runs-focus.config"' in parity
