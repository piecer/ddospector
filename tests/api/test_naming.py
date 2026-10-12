"""Public naming and startup selection without storage, SQL, or network work."""

import importlib
from pathlib import Path

import pytest

app_module = importlib.import_module("aiddos.api.app")
CASES = [
    pytest.param(None, None, None, id="no-env"),
    pytest.param("legacy", None, "legacy", id="old-only"),
    pytest.param(None, "preferred", "preferred", id="new-only"),
    pytest.param("legacy", "preferred", "preferred", id="both"),
    pytest.param("legacy", "", "", id="empty-new"),
    pytest.param("", None, "", id="empty-old"),
]


def setting(monkeypatch, suffix, old, new):
    for prefix, value in (("AIDDOS", old), ("DDOSPECTOR", new)):
        key = f"{prefix}_{suffix}"
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)


def app_inputs(monkeypatch):
    monkeypatch.setattr(app_module, "scenario_router", lambda store, *, ticket: ticket)
    monkeypatch.setattr(app_module, "runs_router", lambda store: None)
    monkeypatch.setattr(app_module, "_compose_app", lambda store, ticket, runs: (store, ticket))


@pytest.mark.parametrize("old,new,expected", CASES)
def test_app_state_selection(monkeypatch, tmp_path, old, new, expected):
    monkeypatch.chdir(tmp_path)
    setting(monkeypatch, "UI_STATE_PATH", old, new)
    app_inputs(monkeypatch)
    store, _ = app_module.create_app()
    selected = expected if expected is not None else ".local/ui-drafts.json"
    assert store.path == Path(selected).resolve()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("explicit", ["explicit.json", "", Path("explicit-path.json")])
def test_explicit_state_path_precedes_environment(monkeypatch, tmp_path, explicit):
    monkeypatch.chdir(tmp_path)
    setting(monkeypatch, "UI_STATE_PATH", "legacy", "preferred")
    app_inputs(monkeypatch)
    store, _ = app_module.create_app(state_path=explicit)
    assert store.path == Path(explicit or "preferred").resolve()


@pytest.mark.parametrize("old,new,expected", CASES)
def test_app_recovery_ticket_selection(monkeypatch, tmp_path, old, new, expected):
    setting(monkeypatch, "SCENARIO_RECOVERY_TICKET", old, new)
    app_inputs(monkeypatch)
    _, ticket = app_module.create_app(state_path=tmp_path / "draft.json")
    assert ticket == expected


@pytest.mark.parametrize("old,new,expected", CASES)
def test_run_router_socket_selection(monkeypatch, tmp_path, old, new, expected):
    runs = importlib.import_module("aiddos.api.runs")
    setting(monkeypatch, "RUN_DB_SOCKET", old, new)
    monkeypatch.setattr(runs, "_compose_runs", lambda peer, socket: (peer, socket))
    peer, socket = runs.runs_router(app_module.DraftStore(tmp_path / "draft.json"))
    assert socket == expected
    assert peer.coordinator.ticket is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("old,new,expected", CASES)
def test_migration_main_socket_selection(monkeypatch, capsys, old, new, expected):
    migration = importlib.import_module("aiddos.runs.migrate")
    setting(monkeypatch, "RUN_DB_SOCKET", old, new)
    seen = []

    async def capture(socket):
        seen.append(socket)
        return "MATCHING"

    monkeypatch.setattr(migration, "migrate", capture)
    assert migration.main() == 0
    assert seen == [expected]
    assert capsys.readouterr().out == '{"schema_version":1,"status":"MATCHING"}\n'


@pytest.mark.parametrize("old,new,expected", CASES)
def test_worker_config_socket_selection(monkeypatch, old, new, expected):
    import asyncio

    worker = importlib.import_module("aiddos.runs.worker")
    config = importlib.import_module("aiddos.runs.config")
    setting(monkeypatch, "RUN_DB_SOCKET", old, new)
    seen = []

    def capture(socket):
        seen.append(socket)
        # All matrix values are intentionally invalid: no driver/SQL is entered.
        return config.parameters(socket)

    def forbidden():
        pytest.fail("Configuration rejection must precede driver acquisition")

    async def check():
        monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", lambda *args: None)
        return await worker.run()

    monkeypatch.setattr(worker, "parameters", capture)
    monkeypatch.setattr(worker, "driver", forbidden)
    assert asyncio.run(check()) == 78
    assert seen == [expected]


def test_distribution_metadata_and_wheel_packages():
    import tomllib

    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    assert project["project"]["name"] == "ddospector"
    assert project["project"]["description"] == "AI-Powered DDoS Defense Validation Framework"
    assert project["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "src/ddospector", "src/aiddos"
    ]
    lock = tomllib.loads((root / "uv.lock").read_text())
    editable = [p for p in lock["package"] if p["source"] == {"editable": "."}]
    assert len(editable) == 1
    assert editable[0]["name"] == "ddospector"


def test_public_uvicorn_app_identity():
    from uvicorn.importer import import_from_string

    assert importlib.util.find_spec("ddospector") is not None
    public = importlib.import_module("ddospector.api.app")
    assert public.app is app_module.app
    assert public.create_app is app_module.create_app
    assert import_from_string("ddospector.api.app:app") is app_module.app


@pytest.mark.parametrize("entry", ["api.scenario_recovery", "runs.migrate", "runs.worker"])
def test_public_entry_main_identity(entry):
    assert importlib.util.find_spec("ddospector") is not None
    public = importlib.import_module(f"ddospector.{entry}")
    legacy = importlib.import_module(f"aiddos.{entry}")
    assert public.main is legacy.main


@pytest.mark.parametrize("entry", ["api.scenario_recovery", "runs.migrate", "runs.worker"])
def test_public_module_delegates_exit(monkeypatch, entry):
    import runpy
    import sys

    assert importlib.util.find_spec("ddospector") is not None
    legacy = importlib.import_module(f"aiddos.{entry}")
    calls = []

    def main():
        calls.append(entry)
        return 23

    monkeypatch.setattr(legacy, "main", main)
    monkeypatch.delitem(sys.modules, f"ddospector.{entry}", raising=False)
    with pytest.raises(SystemExit) as exc:
        runpy.run_module(f"ddospector.{entry}", run_name="__main__")
    assert exc.value.code == 23
    assert calls == [entry]


def test_empty_explicit_path_preserves_legacy_fallback(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    setting(monkeypatch, "UI_STATE_PATH", "legacy.json", None)
    app_inputs(monkeypatch)
    store, _ = app_module.create_app(state_path="")
    assert store.path == (tmp_path / "legacy.json").resolve()
