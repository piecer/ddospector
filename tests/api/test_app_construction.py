"""Native construction races: scheduling hooks, never framework replacements."""

import ast
import inspect
import json
import sys
import threading
import warnings
from pathlib import Path

import pytest
from fastapi._compat.v2 import ModelField
from fastapi.testclient import TestClient
from scenario_producer import definition, register_targets

from aiddos.api.app import _compose_app, create_app
from aiddos.api.construction import serialized
from aiddos.api.runs import _compose_runs, runs_router
from aiddos.api.scenario_store import ScenarioStore
from aiddos.api.scenarios import _compose_scenarios, scenario_router
from aiddos.api.store import DraftStore


def test_native_warning_contexts_restore_under_competing_construction(tmp_path, record_property):
    """B can reach the guard OR native seam; GREEN never waits inside A for B's lock."""
    post = ModelField.__post_init__.__code__
    lines, first = inspect.getsourcelines(ModelField.__post_init__)
    tree = ast.parse(inspect.cleandoc("\n" + "".join(lines)))
    adapter_line = first + next(
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Attribute) and node.target.attr == "_type_adapter"
    ) - 1
    ready, admitted, restored, returned = (threading.Event() for _ in range(4))
    local = threading.local()
    events, failures, apps, phase = [], {}, {}, []
    before = list(warnings.filters)
    construction_file = Path(__file__).resolve().parents[2] / "src/aiddos/api/construction.py"

    def wait(event):
        assert event.wait(5), "construction schedule did not reach its actual seam"

    def is_append(frame):
        while frame is not None:
            endpoint = frame.f_locals.get("endpoint")
            if callable(endpoint) and getattr(endpoint, "__name__", None) == "append":
                return True
            frame = frame.f_back
        return False

    def trace(frame, event, arg):
        name = threading.current_thread().name
        if (name == "constructor-B" and event == "call"
                and frame.f_code.co_filename == str(construction_file)
                and frame.f_code.co_name == "guarded" and not admitted.is_set()):
            phase.append("guard")
            events.append("B_guard_admitted")
            admitted.set()
        if frame.f_code is not post:
            return trace
        if (event == "line" and frame.f_lineno == adapter_line
                and frame.f_locals["self"].name == "scenario_id"
                and not getattr(local, "selected", False) and is_append(frame)):
            local.selected = True
            local.target = id(frame)
            events.append(name + "_native_adapter")
            if name == "constructor-A":
                ready.set()
                wait(admitted)
            else:
                if not admitted.is_set():
                    phase.append("native")
                    admitted.set()
                wait(restored)
        if getattr(local, "target", None) == id(frame) and event == "return":
            events.append(name + "_native_restored")
            local.target = None
            if name == "constructor-A":
                restored.set()
                if phase == ["native"]:
                    wait(returned)
            else:
                returned.set()
        return trace

    def build(label):
        sys.settrace(trace)
        try:
            apps[label] = create_app(state_path=tmp_path / (label + ".json"))
        except BaseException as error:
            failures[label] = {"type": type(error).__name__, "message": str(error)}
        finally:
            sys.settrace(None)

    a = threading.Thread(target=build, args=("A",), name="constructor-A")
    b = threading.Thread(target=build, args=("B",), name="constructor-B")
    a.start()
    try:
        wait(ready)
        b.start()
        a.join(10)
        b.join(10)
    finally:
        admitted.set()
        restored.set()
        returned.set()
        a.join(6)
        if b.ident is not None:
            b.join(6)
    observation = {
        "events": events, "phase": phase, "failures": failures,
        "successes": sorted(apps), "filters_restored": warnings.filters == before,
        "alive": [t.name for t in (a, b) if t.is_alive()],
        "adapter_source": post.co_filename, "adapter_line": adapter_line,
    }
    record_property("native_construction", json.dumps(observation, sort_keys=True))
    assert not observation["alive"], observation
    assert all(name + "_native_adapter" in events for name in ("constructor-A", "constructor-B"))
    assert all(name + "_native_restored" in events for name in ("constructor-A", "constructor-B"))
    assert not failures and observation["filters_restored"], observation
    assert sorted(apps) == ["A", "B"]


@pytest.mark.parametrize("same_path", [False, True])
def test_concurrent_apps_keep_routes_filters_and_cas(tmp_path, same_path):
    from concurrent.futures import ThreadPoolExecutor

    start = threading.Barrier(2)
    constructed = threading.Barrier(2)
    before = list(warnings.filters)
    paths = [tmp_path / ("shared.json" if same_path else f"draft-{n}.json") for n in range(2)]
    # Prepared targets only; both actual app constructors still compete.
    targets = {}
    for path in set(paths):
        with TestClient(create_app(state_path=path), base_url="http://localhost") as client:
            targets[path] = register_targets(client)

    def worker(n):
        start.wait(5)
        app = create_app(state_path=paths[n])
        constructed.wait(5)
        with TestClient(app, base_url="http://localhost") as client:
            assert client.get("/api/v1/health").json()["mode"] == "OFFLINE"
            assert client.post("/api/v1/runs", content=b"not json",
                               headers={"Content-Type": "application/json"}).status_code == 409
            assert client.put("/api/v1/scenarios/not valid", json={}).status_code == 422
            assert client.get("/api/v1/offline-runs/not-valid").status_code == 422
            result = client.post("/api/v1/scenarios", json={
                "revision": 0, "definition": definition(targets[paths[n]])})
            return result.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, n) for n in range(2)]
        statuses = sorted(f.result(10) for f in futures)
    assert statuses == ([201, 409] if same_path else [201, 201])
    assert warnings.filters == before


@pytest.mark.parametrize("builder", ["scenario", "runs", "app"])
def test_native_exception_restores_filters_and_releases_builder(tmp_path, builder):
    from concurrent.futures import ThreadPoolExecutor

    def construct():
        if builder == "app":
            return create_app(state_path=tmp_path / "draft.json")
        drafts = DraftStore(tmp_path / "draft.json")
        return (scenario_router if builder == "scenario" else runs_router)(drafts)

    original = RuntimeError("construction-only native adapter entry fault")
    fired = []
    before = list(warnings.filters)
    from pydantic import TypeAdapter

    def inject(frame, event, arg):
        if (not fired and event == "call" and frame.f_code is TypeAdapter.__init__.__code__
                and frame.f_back.f_code is ModelField.__post_init__.__code__
                and any(f.function == {"scenario": "_compose_scenarios",
                                       "runs": "_compose_runs", "app": "_compose_app"}[builder]
                        for f in inspect.getouterframes(frame))):
            fired.append(True)
            raise original
        return inject

    sys.settrace(inject)
    try:
        with pytest.raises(RuntimeError) as caught:
            construct()
    finally:
        sys.settrace(None)
    assert caught.value is original and fired == [True]
    assert warnings.filters == before
    # Another thread, not same-thread RLock reacquisition, proves release.
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(construct).result(5).routes
    assert warnings.filters == before


def test_nested_prepared_builders_are_reentrant(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    peer = ScenarioStore(DraftStore(tmp_path / "draft.json"))
    before = list(warnings.filters)

    @serialized
    def nested():
        return _compose_scenarios(peer), _compose_runs(peer, None)

    with ThreadPoolExecutor(max_workers=1) as pool:
        routers = pool.submit(nested).result(5)
    assert [len(router.routes) for router in routers] == [4, 3]
    assert warnings.filters == before


@pytest.mark.parametrize("preparation", ["scenario_router", "runs_router"])
def test_actual_app_waiting_store_allows_unrelated_app_and_request(tmp_path, preparation):
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / "waiting.json"
    peer = ScenarioStore(DraftStore(path))
    selected, proceed, attempted = (threading.Event() for _ in range(3))
    completed = threading.Event()
    constructor = ScenarioStore.__init__.__code__
    source, first = inspect.getsourcelines(ScenarioStore.__init__)
    lock_line = first + next(n for n, line in enumerate(source) if "with self.lock:" in line)
    seen = []

    def trace(frame, event, arg):
        if frame.f_code is constructor and frame.f_back.f_code.co_name == preparation:
            if event == "call":
                selected.set()
                assert proceed.wait(5)
            if event == "line" and frame.f_lineno == lock_line and not attempted.is_set():
                seen.append(preparation)
                attempted.set()
        return trace

    def waiting():
        sys.settrace(trace)
        try:
            result = create_app(state_path=path)
            completed.set()
            return result
        finally:
            sys.settrace(None)

    def unrelated():
        with TestClient(create_app(state_path=tmp_path / "other.json"),
                        base_url="http://localhost") as client:
            value = definition(register_targets(client))
            response = client.post("/api/v1/scenarios", json={"revision": 0, "definition": value})
            assert response.status_code == 201
            return response.json()["revision"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(waiting)
        try:
            assert selected.wait(5)
            # For runs preparation the actual scenario router has already completed.
            with peer.lock:
                proceed.set()
                assert attempted.wait(5)
                assert not completed.is_set()
                assert pool.submit(unrelated).result(2) == 1
                assert not completed.is_set()
        finally:
            proceed.set()
        assert future.result(5).routes
    assert seen == [preparation]
    assert completed.is_set()


@pytest.mark.parametrize("left,right", [("scenario", "runs"), ("runs", "app"), ("app", "scenario")])
def test_sibling_builders_share_one_composition_boundary(tmp_path, left, right):
    from concurrent.futures import ThreadPoolExecutor

    peer = ScenarioStore(DraftStore(tmp_path / "draft.json"))
    scenario, runs = scenario_router(peer.drafts), runs_router(peer.drafts)
    builders = {
        "scenario": lambda: _compose_scenarios(peer),
        "runs": lambda: _compose_runs(peer, None),
        "app": lambda: _compose_app(peer.drafts, scenario, runs),
    }
    a_inside, b_admitted, b_inside, release = (threading.Event() for _ in range(4))
    construction_file = Path(__file__).resolve().parents[2] / "src/aiddos/api/construction.py"
    before = list(warnings.filters)

    def worker(kind, is_a):
        def trace(frame, event, arg):
            if event == "call":
                if (not is_a and frame.f_code.co_filename == str(construction_file)
                        and frame.f_code.co_name == "guarded"):
                    b_admitted.set()
                if frame.f_code is ModelField.__post_init__.__code__:
                    if is_a and not a_inside.is_set():
                        a_inside.set()
                        assert release.wait(5)
                    elif not is_a:
                        b_inside.set()
            return trace

        sys.settrace(trace)
        try:
            return builders[kind]()
        finally:
            sys.settrace(None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(worker, left, True)
        try:
            assert a_inside.wait(5)
            b = pool.submit(worker, right, False)
            assert b_admitted.wait(5)
            assert not b_inside.wait(0.1)
        finally:
            release.set()
        assert a.result(5).routes and b.result(5).routes
    assert b_inside.is_set()
    assert warnings.filters == before


def test_requests_progress_while_framework_composition_is_held(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    app = create_app(state_path=tmp_path / "served.json")
    entered, release = threading.Event(), threading.Event()

    def trace(frame, event, arg):
        if (frame.f_code is ModelField.__post_init__.__code__ and event == "call"
                and not entered.is_set()):
            entered.set()
            assert release.wait(5)
        return trace

    def build():
        sys.settrace(trace)
        try:
            return create_app(state_path=tmp_path / "building.json")
        finally:
            sys.settrace(None)

    with (TestClient(app, base_url="http://localhost") as client,
          ThreadPoolExecutor(max_workers=2) as pool):
        future = pool.submit(build)
        try:
            assert entered.wait(5)
            assert pool.submit(client.get, "/api/v1/health").result(2).status_code == 200
            value = definition(register_targets(client))
            response = pool.submit(client.post, "/api/v1/scenarios",
                                   json={"revision": 0, "definition": value}).result(2)
            assert response.status_code == 201
        finally:
            release.set()
        assert future.result(5).routes
