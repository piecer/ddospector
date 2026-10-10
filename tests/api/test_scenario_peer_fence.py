"""Public peer admission at the real final CLEAN write; no token remint."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from fastapi.testclient import TestClient
from scenario_producer import definition, register_targets
from test_scenario_recovery import api_child, child, cli, failed_attempt
from test_scenario_retention import paths
from test_scenario_storage import saved
from test_scenarios import assert_error

from aiddos.api import scenario_persistence as io
from aiddos.api.app import create_app
from aiddos.api.errors import DraftError
from aiddos.api.models import TargetInput
from aiddos.api.scenario_store import ScenarioStore
from aiddos.api.scenarios import ScenarioInput
from aiddos.api.store import DraftStore


def ready_ticket(client, state_path, monkeypatch):
    value, first = failed_attempt(client, state_path, monkeypatch)
    observed = cli(monkeypatch, state_path)
    assert observed.returncode == 0
    archive = state_path.parent / "peer-archive"
    recovered = cli(
        monkeypatch, state_path, "recover", "--review", json.loads(observed.stdout)["review"],
        "--archive", archive,
    )
    assert recovered.returncode == 0
    return value, first, json.loads(recovered.stdout)["ticket"]


CONSUMED_PEER = '''import json,sys,os
from pathlib import Path
from threading import Event
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from aiddos.api.app import create_app
from aiddos.api import scenario_persistence as io
from aiddos.api import scenario_store
from aiddos.api.errors import DraftError
from aiddos.api.scenarios import ScenarioInput
from aiddos.api.store import DraftStore
assert Path(scenario_store.__file__).resolve() == Path.cwd()/"src/aiddos/api/scenario_store.py"
path=Path(sys.argv[1]);overlap=sys.argv[2]=="True";value=json.load(sys.stdin)
interface=sys.argv[3]
original_env=os.environ["AIDDOS_SCENARIO_RECOVERY_TICKET"]
reached,release,started,done=Event(),Event(),Event(),Event()
real=io.write_frame
phases=[]
def frame(path,raw,**kw):
 real(path,raw,**kw);phase=io.decode_frame(raw)["phase"];phases.append(phase)
 if phase=="CLEAN":
  reached.set()
  if overlap: assert release.wait(5)
def peer_factory():
 started.set()
 peer=(create_app(state_path=path) if interface=="app" else
       scenario_store.ScenarioStore(DraftStore(path),ticket=original_env))
 done.set();return peer
with (TestClient(create_app(state_path=path),base_url="http://localhost") as c,
      ThreadPoolExecutor(max_workers=2) as pool):
 io.write_frame=frame
 future=pool.submit(c.post,"/api/v1/scenarios",json={"revision":1,"definition":value})
 try:
  assert reached.wait(5)
  if not overlap:assert future.result(timeout=5).status_code==201
  peer=pool.submit(peer_factory);assert started.wait(5)
  before_unlock=done.wait(0.5) if overlap else False
 finally:release.set()
 assert future.result(timeout=5).status_code==201
 peerapp=peer.result(timeout=5);io.write_frame=real
 request={"revision":2,"definition":value}
 if interface=="app":
  with TestClient(peerapp,base_url="http://localhost") as next_client:
   response=next_client.post("/api/v1/scenarios",json=request)
   status,body=response.status_code,response.json()
 else:
  try: body=peerapp.save(ScenarioInput.model_validate(request));status=201
  except DraftError as error: status,body=503,{"code":error.code}
 assert os.environ["AIDDOS_SCENARIO_RECOVERY_TICKET"]==original_env
 print(json.dumps({"status":status,"body":body,"peer_before_unlock":before_unlock,
                   "first_save_phases":phases,"environment_unchanged":True}))
'''


@pytest.mark.parametrize("overlap", [False, True])
@pytest.mark.parametrize("interface", ["app", "store"])
def test_consumed_startup_ticket_peer_unchanged_environment(
    client, state_path, monkeypatch, overlap, interface
):
    value, first, ticket = ready_ticket(client, state_path, monkeypatch)
    result = child(
        monkeypatch, ["-c", CONSUMED_PEER, str(state_path), str(overlap), interface],
        ticket=ticket, data=json.dumps(value).encode(),
    )
    assert result.returncode == 0, result.stderr.decode()
    observed = json.loads(result.stdout)
    assert observed["first_save_phases"] == ["ACTIVE", "PREPARED", "PUBLISHED", "CLEAN"]
    assert observed["environment_unchanged"]
    assert observed["status"] == 503, observed
    assert observed["body"]["code"] == "SCENARIO_STATE_UNAVAILABLE"
    assert not observed["peer_before_unlock"]
    registry, _, _ = paths(state_path)
    state = json.loads(registry.read_bytes())
    assert state["revision"] == 2
    assert state["scenarios"][0]["versions"] == [first]


@pytest.mark.parametrize("overlap", [False, True])
@pytest.mark.parametrize("interface", ["app", "store"])
def test_invalid_ticket_peer_preserves_fence(client, state_path, monkeypatch, overlap, interface):
    value, first, _ = saved(client, state_path)
    registry, receipt, pending = paths(state_path)
    reached, release, started, done = Event(), Event(), Event(), Event()
    real_write = io.write_frame

    def frame(path, raw, **kwargs):
        real_write(path, raw, **kwargs)
        if io.decode_frame(raw)["phase"] == "CLEAN":
            reached.set()
            if overlap:
                assert release.wait(5)

    def construct():
        started.set()
        peer = (
            create_app(state_path=state_path) if interface == "app"
            else ScenarioStore(DraftStore(state_path), ticket="0" * 64)
        )
        done.set()
        return peer

    with monkeypatch.context() as scope, ThreadPoolExecutor(max_workers=2) as pool:
        scope.setattr(io, "write_frame", frame)
        scope.setenv("AIDDOS_SCENARIO_RECOVERY_TICKET", "0" * 64)
        saving = pool.submit(
            client.post, "/api/v1/scenarios", json={"revision": 1, "definition": value}
        )
        try:
            assert reached.wait(5)
            if not overlap:
                assert saving.result(timeout=5).status_code == 201
            creating = pool.submit(construct)
            assert started.wait(5)
            before_unlock = done.wait(0.5) if overlap else False
        finally:
            release.set()
        assert saving.result(timeout=5).status_code == 201
        peer = creating.result(timeout=5)
    before = {p: p.read_bytes() for p in (registry, receipt, state_path)}
    request = {"revision": 2, "definition": value}
    if interface == "app":
        with TestClient(peer, base_url="http://localhost") as connection:
            assert connection.get("/api/v1/scenarios").json()["revision"] == 2
            assert_error(connection.post("/api/v1/scenarios", json=request),
                         503, "SCENARIO_STATE_UNAVAILABLE")
    else:
        assert peer.page()["revision"] == 2
        with pytest.raises(DraftError) as caught:
            peer.save(ScenarioInput.model_validate(request))
        assert caught.value.code == "SCENARIO_STATE_UNAVAILABLE"
    assert not before_unlock
    # Quarantine is shared, not just a private denial on the new peer.
    assert_error(client.post("/api/v1/scenarios", json=request),
                 503, "SCENARIO_STATE_UNAVAILABLE")
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert not list(pending.iterdir())
    assert json.loads(registry.read_bytes())["scenarios"][0]["versions"] == [first]


@pytest.mark.parametrize("invalid", [False, True])
def test_waiting_peer_constructors_do_not_hold_registry_guard(
    client, state_path, monkeypatch, invalid
):
    value, _, _ = saved(client, state_path)
    _, receipt, _ = paths(state_path)
    reached, release = Event(), Event()
    started, done = [Event(), Event()], [Event(), Event()]
    real_write = io.write_frame

    def frame(path, raw, **kwargs):
        real_write(path, raw, **kwargs)
        if path == receipt and io.decode_frame(raw)["phase"] == "CLEAN":
            reached.set()
            assert release.wait(5)

    def construct(n):
        started[n].set()
        peer = ScenarioStore(
            DraftStore(state_path), ticket="0" * 64 if invalid and n == 0 else None
        )
        done[n].set()
        return peer

    def unrelated():
        with TestClient(create_app(state_path=state_path.parent / "unrelated.json"),
                        base_url="http://localhost") as connection:
            other = definition(register_targets(connection))
            response = connection.post("/api/v1/scenarios", json={"revision": 0,
                                                                  "definition": other})
            assert response.status_code == 201
            return response.json()["revision"]

    with monkeypatch.context() as scope, ThreadPoolExecutor(max_workers=4) as pool:
        scope.setattr(io, "write_frame", frame)
        saving = pool.submit(client.post, "/api/v1/scenarios",
                             json={"revision": 1, "definition": value})
        try:
            assert reached.wait(5)
            peers = [pool.submit(construct, n) for n in range(2)]
            assert all(event.wait(5) for event in started)
            blocked = [not event.wait(0.25) for event in done]
            # This actual constructor and save must finish before releasing the owner.
            assert pool.submit(unrelated).result(timeout=2) == 1
        finally:
            release.set()
        assert saving.result(timeout=5).status_code == 201
        peers = [future.result(timeout=5) for future in peers]
    assert all(blocked)
    for n, peer in enumerate(peers):
        revision = 2 if invalid else 2 + n
        assert peer.page()["revision"] == revision
        request = ScenarioInput.model_validate({"revision": revision, "definition": value})
        if invalid:
            with pytest.raises(DraftError) as caught:
                peer.save(request)
            assert caught.value.code == "SCENARIO_STATE_UNAVAILABLE"
        else:
            assert peer.save(request)["revision"] == revision + 1


def test_competing_first_constructors_share_cas_without_deadlock(state_path):
    # Register only drafts: no scenario write before these constructors compete.
    drafts = DraftStore(state_path)
    value = definition([
        drafts.create_target(TargetInput(name=kind, kind=kind, address=address)).model_dump()
        for kind, address in (("DUT", "192.0.2.10"), ("SINK", "192.0.2.20"))
    ])
    start, constructed = Barrier(4), Barrier(4)

    def compete():
        start.wait(timeout=5)
        peer = ScenarioStore(DraftStore(state_path))
        constructed.wait(timeout=5)
        try:
            result = peer.save(ScenarioInput.model_validate({"revision": 0, "definition": value}))
            return peer, result["revision"]
        except DraftError as error:
            return peer, error.code

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(compete) for _ in range(4)]
        results = [future.result(timeout=5) for future in futures]
    assert len({id(peer.coordinator) for peer, _ in results}) == 1
    outcomes = [outcome for _, outcome in results]
    assert outcomes.count(1) == 1 and outcomes.count("SCENARIO_CONFLICT") == 3
    assert results[0][0].page()["revision"] == 1


LEGITIMATE_PEERS = '''import json,sys,os
from pathlib import Path
from fastapi.testclient import TestClient
from aiddos.api.app import create_app
from aiddos.api import scenario_store,scenario_persistence as io
from aiddos.api.errors import DraftError
from aiddos.api.scenarios import ScenarioInput
from aiddos.api.store import DraftStore
assert Path(scenario_store.__file__).resolve() == Path.cwd()/"src/aiddos/api/scenario_store.py"
path=Path(sys.argv[1]);consumer=sys.argv[2];value=json.load(sys.stdin)
ticket=os.environ["AIDDOS_SCENARIO_RECOVERY_TICKET"]
registry=path.with_name(path.name+".scenarios.json")
receipt=registry.with_name(registry.name+".s01-recovery")
pending=registry.with_name(registry.name+".s01-pending")
original={p:p.read_bytes() for p in (path,registry,receipt)}
owner=scenario_store.ScenarioStore(DraftStore(path),ticket=ticket)
matching=scenario_store.ScenarioStore(DraftStore(path),ticket=ticket)
plain=scenario_store.ScenarioStore(DraftStore(path))
assert owner.coordinator is matching.coordinator is plain.coordinator
app=create_app(state_path=path)
phases=[];real=io.write_frame
def frame(path,raw,**kw):
 real(path,raw,**kw);phases.append(io.decode_frame(raw)["phase"])
io.write_frame=frame
with TestClient(app,base_url="http://localhost") as client:
 assert client.get("/api/v1/scenarios").json()["revision"]==1
 assert matching.page()["revision"]==plain.page()["revision"]==1
 assert client.post("/api/v1/scenarios",json={"revision":0,"definition":value}).status_code==409
 assert all(p.read_bytes()==raw for p,raw in original.items())
 assert not list(pending.iterdir()) and not phases
 request={"revision":1,"definition":value}
 if consumer=="app":
  response=client.post("/api/v1/scenarios",json=request)
  assert response.status_code==201
  assert response.json()["revision"]==2
 else:
  peer=matching if consumer=="matching-store" else plain
  assert peer.save(ScenarioInput.model_validate(request))["revision"]==2
 assert phases==["ACTIVE","PREPARED","PUBLISHED","CLEAN"]
 assert owner.save(ScenarioInput.model_validate({"revision":2,"definition":value}))["revision"]==3
 later=scenario_store.ScenarioStore(DraftStore(path))
 assert later.save(ScenarioInput.model_validate({"revision":3,"definition":value}))["revision"]==4
 assert phases.count("ACTIVE")==1
 assert os.environ["AIDDOS_SCENARIO_RECOVERY_TICKET"]==ticket
 before={p:p.read_bytes() for p in (path,registry,receipt)}
 old=scenario_store.ScenarioStore(DraftStore(path),ticket=ticket)
 for peer in (old,owner,matching,plain,later):
  assert peer.page()["revision"]==4
  try:peer.save(ScenarioInput.model_validate({"revision":4,"definition":value}))
  except DraftError as error: assert error.code=="SCENARIO_STATE_UNAVAILABLE"
  else:raise AssertionError("consumed ticket was reminted")
 assert client.post("/api/v1/scenarios",json={"revision":4,"definition":value}).status_code==503
 assert all(p.read_bytes()==raw for p,raw in before.items())
 assert not list(pending.iterdir())
 print(json.dumps({"revision":4,"active_transitions":phases.count("ACTIVE"),
                   "environment_unchanged":True,"construction_and_get_effect_free":True}))
'''


@pytest.mark.parametrize("consumer", ["app", "matching-store", "no-ticket-store"])
def test_legitimate_peers_share_one_use_handoff_without_remint(
    client, state_path, monkeypatch, consumer
):
    value, first, ticket = ready_ticket(client, state_path, monkeypatch)
    result = child(
        monkeypatch, ["-c", LEGITIMATE_PEERS, str(state_path), consumer],
        ticket=ticket, data=json.dumps(value).encode(),
    )
    assert result.returncode == 0, result.stderr.decode()
    assert json.loads(result.stdout) == {
        "revision": 4, "active_transitions": 1, "environment_unchanged": True,
        "construction_and_get_effect_free": True,
    }
    registry, _, _ = paths(state_path)
    assert json.loads(registry.read_bytes())["scenarios"][0]["versions"] == [first]


@pytest.mark.parametrize("phase", ["PREPARED", "CLEAN"])
def test_error_fence_survives_peers_but_fresh_verified_clean_resumes(
    client, state_path, monkeypatch, phase
):
    value, first, _ = saved(client, state_path)
    registry, receipt, pending = paths(state_path)
    real_write, fired = io.write_frame, []

    def frame(path, raw, **kwargs):
        if io.decode_frame(raw)["phase"] == phase:
            if phase == "CLEAN":
                real_write(path, raw, **kwargs)
            fired.append(phase)
            raise OSError("synthetic CLEAN tail or effect-free PREPARED refusal")
        return real_write(path, raw, **kwargs)

    with monkeypatch.context() as scope:
        scope.setattr(io, "write_frame", frame)
        response = client.post("/api/v1/scenarios", json={"revision": 1, "definition": value})
    assert fired == [phase]
    assert_error(response, 503, "SCENARIO_COMMIT_UNCERTAIN" if phase == "CLEAN"
                 else "SCENARIO_STATE_UNAVAILABLE")
    revision = 2 if phase == "CLEAN" else 1
    before = {p: p.read_bytes() for p in (registry, receipt, state_path)}
    peer = ScenarioStore(DraftStore(state_path))
    assert peer.page()["revision"] == revision
    with pytest.raises(DraftError) as caught:
        peer.save(ScenarioInput.model_validate({"revision": revision, "definition": value}))
    assert caught.value.code == "SCENARIO_STATE_UNAVAILABLE"
    with TestClient(create_app(state_path=state_path), base_url="http://localhost") as connection:
        for current in (client, connection):
            assert current.get("/api/v1/scenarios").json()["revision"] == revision
            assert_error(current.post("/api/v1/scenarios",
                                      json={"revision": revision, "definition": value}),
                         503, "SCENARIO_STATE_UNAVAILABLE")
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert io.decode_frame(receipt.read_bytes())["phase"] == "CLEAN"
    assert not list(pending.iterdir())
    # Sequential new process, not a concurrent multiprocess writer or latch reset.
    assert api_child(monkeypatch, state_path, value, revision)["status"] == 201
    state = json.loads(registry.read_bytes())
    assert state["revision"] == revision + 1
    assert state["scenarios"][0]["versions"] == [first]
