"""Harness Origin binding, without launching services or making requests."""

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from aiddos.api.boundary import checked_headers
from aiddos.api.errors import DraftError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import chat_tools_acceptance as harness  # noqa: E402


class AtVite(Exception):
    pass


@pytest.fixture
def browser_setup(tmp_path, monkeypatch):
    class Provider:
        base_url = "http://127.0.0.1:42000/v1"
        requests = []
        opened = closed = 0
        retired = False

        def __enter__(self):
            return self

        def __exit__(self):
            self.retired = True

    class API:
        retired = False

        def stop(self):
            self.retired = True

        def receipt(self):
            return {"cleanup_verified": self.retired}

    provider, api = Provider(), API()
    monkeypatch.setattr(harness, "ProviderFixture", lambda _: provider)
    monkeypatch.setattr(harness, "record_provider", lambda *_: None)
    monkeypatch.setattr(harness, "launch_api", lambda *a, **k: (api, "http://127.0.0.1:42001"))
    monkeypatch.setattr(harness.legacy, "bootstrap", lambda *_: None)
    monkeypatch.setattr(harness, "http", lambda *_: (200, {}))
    monkeypatch.setattr(harness, "plan", lambda _: [])
    monkeypatch.setattr(harness, "require_runtime", lambda *_: None)
    result = {"children": []}
    return tmp_path, provider, api, result


def test_browser_origin_uses_existing_allowlist_without_policy_change(browser_setup, monkeypatch):
    directory, provider, api, result = browser_setup
    ports, launches = [], []

    @contextmanager
    def reserve(port=0):
        ports.append(port)

        class Bound:
            def getsockname(self):
                return "127.0.0.1", port or 41408

        yield Bound()

    def launch(command, **kwargs):
        launches.append((command, kwargs))
        raise AtVite

    monkeypatch.setattr(harness.legacy, "reserved_port", reserve)
    monkeypatch.setattr(harness.legacy, "OwnedProcess", launch)
    with pytest.raises(AtVite):
        harness.run_browser("fixture", directory, result)
    assert ports == [5175]
    assert len(launches) == 1
    command, _ = launches[0]
    assert command[command.index("--port") + 1] == "5175"
    assert "--strictPort" in command
    scope = {"headers": [(b"host", b"127.0.0.1:42001"), (b"origin", b"http://127.0.0.1:5175")]}
    assert checked_headers(scope)["origin"] == "http://127.0.0.1:5175"
    scope["headers"][1] = (b"origin", b"http://127.0.0.1:41408")
    with pytest.raises(DraftError, match="ORIGIN_NOT_ALLOWED"):
        checked_headers(scope)
    assert api.retired and provider.retired and not provider.requests


def test_origin_port_collision_has_no_fallback_or_process_adoption(browser_setup, monkeypatch):
    directory, provider, api, result = browser_setup
    ports = []
    failure = OSError("invocation collision control")

    @contextmanager
    def reserve(port=0):
        ports.append(port)
        raise failure
        yield

    def forbidden(*args, **kwargs):
        pytest.fail("collision must not launch or adopt Vite")

    monkeypatch.setattr(harness.legacy, "reserved_port", reserve)
    monkeypatch.setattr(harness.legacy, "OwnedProcess", forbidden)
    with pytest.raises(OSError) as caught:
        harness.run_browser("fixture", directory, result)
    assert caught.value is failure and ports == [5175]
    assert api.retired and provider.retired and not provider.requests
