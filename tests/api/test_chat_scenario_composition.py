"""D05: one store, one worker, same coordinator for manual/chat paths."""

import asyncio
import inspect

import pytest
from chat_scenario_support import prepare, reference, setup, worker_for
from fastapi.testclient import TestClient
from scenario_producer import definition, register_targets

from aiddos.api import app as app_module
from aiddos.api import scenario_store


def runs_peer(router):
    # Inspect the real route closure without executing a Runs request/worker.
    routes = list(router.routes)
    while routes:
        route = routes.pop()
        if hasattr(route, "original_router"):
            routes.extend(route.original_router.routes)
        elif route.path == "/api/v1/offline-runs" and route.methods == {"POST"}:
            return inspect.getclosurevars(route.endpoint).nonlocals["peer"]
    raise AssertionError("actual Runs create route missing")


@pytest.mark.parametrize("falsey", [False, True])
def test_runs_router_borrows_actual_injected_store_without_second_ticket(
    tmp_path, monkeypatch, falsey
):
    from aiddos.api import runs
    from aiddos.api.store import DraftStore

    class FalseyStore(scenario_store.ScenarioStore):
        def __bool__(self):
            return False

    drafts = DraftStore(tmp_path / "draft.json")
    store_type = FalseyStore if falsey else scenario_store.ScenarioStore
    store = store_type(drafts, ticket=None)
    initialized, settings = [], []
    real_init = scenario_store.ScenarioStore.__init__
    real_setting = runs.startup_setting

    def observed_init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        initialized.append(self)

    def setting(name, *args):
        settings.append(name)
        return real_setting(name, *args)

    monkeypatch.setattr(scenario_store.ScenarioStore, "__init__", observed_init)
    monkeypatch.setattr(runs, "startup_setting", setting)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    router = runs.runs_router(drafts, scenarios=store)
    assert runs_peer(router) is store
    assert initialized == []
    assert settings == ["RUN_DB_SOCKET"]
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("explicit_none", [False, True])
def test_runs_router_standalone_default_constructs_one_ticketless_store(
    tmp_path, monkeypatch, explicit_none
):
    from aiddos.api import runs
    from aiddos.api.store import DraftStore

    drafts = DraftStore(tmp_path / "draft.json")
    initialized, tickets, settings = [], [], []
    real_init = scenario_store.ScenarioStore.__init__
    real_setting = runs.startup_setting

    def observed_init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        initialized.append(self)
        tickets.append(kwargs)

    def setting(name, *args):
        settings.append(name)
        return real_setting(name, *args)

    monkeypatch.setattr(scenario_store.ScenarioStore, "__init__", observed_init)
    monkeypatch.setattr(runs, "startup_setting", setting)
    router = runs.runs_router(drafts, **({"scenarios": None} if explicit_none else {}))
    assert len(initialized) == 1
    assert runs_peer(router) is initialized[0]
    assert initialized[0].drafts is drafts
    assert tickets == [{"ticket": None}]
    assert settings == ["RUN_DB_SOCKET"]
    assert [(route.methods, route.path) for route in router.routes] == [
        ({"POST"}, "/api/v1/offline-runs"),
        ({"GET"}, "/api/v1/offline-runs"),
        ({"GET"}, "/api/v1/offline-runs/by-request/{request_id}"),
        ({"GET"}, "/api/v1/offline-runs/{run_id}"),
        ({"GET"}, "/api/v1/offline-runs/{run_id}/events"),
        ({"POST"}, "/api/v1/offline-runs/{run_id}/cancel"),
    ]
    assert not list(tmp_path.iterdir())


def test_app_injects_exact_single_store_once(tmp_path, monkeypatch):
    stores = []
    ticket_reads = []
    real_setting = app_module.startup_setting

    real_init = scenario_store.ScenarioStore.__init__

    def observed_init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        stores.append(self)

    def setting(name, *args):
        if name == "SCENARIO_RECOVERY_TICKET":
            ticket_reads.append(name)
        return real_setting(name, *args)

    monkeypatch.setattr(scenario_store.ScenarioStore, "__init__", observed_init)
    monkeypatch.setattr(app_module, "startup_setting", setting)
    app = app_module.create_app(state_path=tmp_path / "draft.json")
    assert len(stores) == 1 and len(ticket_reads) == 1
    worker = app.state.chat.worker
    assert worker.scenarios is stores[0], "chat and manual routes must borrow one store"
    assert app.state.chat.scenarios is stores[0]
    assert runs_peer(app) is stores[0]
    with TestClient(app, base_url="http://localhost") as client:
        value = definition(register_targets(client))
        first = client.post("/api/v1/scenarios", json={"revision": 0, "definition": value}).json()[
            "scenario"
        ]

        async def append():
            grant, args, proposal, settings = await prepare(
                worker, worker.draft, stores[0], value, base=reference(first)
            )
            return await worker.save_scenario(grant, args, proposal, lambda: None, settings)

        result = client.portal.call(append)
        history = client.get("/api/v1/scenarios/" + first["id"]).json()
        assert history["versions"] == [first, result["scenario"]]
        assert len(stores) == 1 and len(ticket_reads) == 1
    assert worker._thread is not None and not worker._thread.is_alive()


def test_old_worker_absent_dependency_is_unavailable_without_peer(tmp_path):
    import pytest

    from aiddos.api.chat_tool_domain import DomainWorker
    from aiddos.api.errors import DraftError
    from aiddos.api.store import DraftStore

    draft = DraftStore(tmp_path / "draft.json")
    worker = DomainWorker(draft)

    async def exercise():
        try:
            with pytest.raises(DraftError) as exc:
                await worker.resolve_scenario_intent({}, 0)
            assert exc.value.code == "CHAT_STORAGE_ERROR"
            assert not list(tmp_path.iterdir())
        finally:
            await worker.shutdown()

    asyncio.run(exercise())


def test_reconciliation_bridge_owner_loop_under_scenario_then_draft(tmp_path):
    import sqlite3
    import threading

    draft, store, _ = setup(tmp_path)
    worker = worker_for(draft, store)
    assert callable(getattr(worker, "locked_scenario_revisions", None)), "revision bridge missing"
    owner = threading.get_ident()
    order = []

    class ObservedLock:
        def __init__(self, lock, name):
            self.lock, self.name = lock, name

        def __enter__(self):
            self.lock.acquire()
            order.append(self.name)
            return self

        def __exit__(self, *args):
            self.lock.release()

    native_scenario, native_draft = store.lock, draft.lock
    store.lock = ObservedLock(native_scenario, "scenario")
    draft.lock = ObservedLock(native_draft, "draft")
    connection = sqlite3.connect(tmp_path / "bridge.sqlite")
    connection.execute("CREATE TABLE observations(draft INTEGER, scenario INTEGER)")
    before = draft.path.read_bytes()

    def callback(draft_revision, scenario_revision):
        assert threading.get_ident() == owner
        assert not native_scenario.acquire(blocking=False)
        assert not native_draft.acquire(blocking=False)
        connection.execute(
            "INSERT INTO observations VALUES (?, ?)", (draft_revision, scenario_revision)
        )
        connection.commit()
        return (draft_revision, scenario_revision)

    async def exercise():
        try:
            result = await worker.locked_scenario_revisions(callback)
            assert result == (2, 0)
            assert order == ["scenario", "draft"]
            assert connection.execute("SELECT * FROM observations").fetchall() == [(2, 0)]
            assert draft.path.read_bytes() == before and not store.path.exists()
            assert not worker.busy
        finally:
            await worker.shutdown()
            connection.close()

    asyncio.run(exercise())


def test_manual_writer_cannot_deadlock_chat_waiting_for_scenario(tmp_path):
    import threading
    from time import monotonic

    import pytest

    from aiddos.api.errors import DraftError
    from aiddos.api.models import TargetInput

    draft, store, value = setup(tmp_path)
    worker = worker_for(draft, store)
    native = store.lock
    attempted = threading.Event()
    owner = threading.get_ident()

    class ObservedLock:
        def __enter__(self):
            if threading.get_ident() != owner:
                attempted.set()
            native.acquire()
            return self

        def __exit__(self, *args):
            native.release()

    async def exercise():
        task = None
        try:
            grant, args, proposal, settings = await prepare(worker, draft, store, value)
            store.lock = ObservedLock()
            native.acquire()
            try:
                task = asyncio.create_task(
                    worker.save_scenario(grant, args, proposal, lambda: None, settings)
                )
                end = monotonic() + 4
                while not attempted.is_set() and monotonic() < end:
                    await asyncio.sleep(0.001)
                assert attempted.is_set()
                assert draft.lock.acquire(blocking=False), "draft→scenario inversion"
                try:
                    draft.create_target(TargetInput(name="manual", address="192.0.2.2", kind="DUT"))
                finally:
                    draft.lock.release()
            finally:
                native.release()
            with pytest.raises(DraftError) as exc:
                await task
            assert exc.value.code == "CHAT_TOOL_CONFLICT"
            assert not store.path.exists() and not store.coordinator.blocked
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
