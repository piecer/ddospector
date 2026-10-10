"""Offline CLI subprocesses on owned fixtures; never live .local state."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_scenario_retention import REAL_POPEN, paths
from test_scenario_storage import saved

ROOT = Path(__file__).resolve().parents[2]


def child(monkeypatch, args, *, data=None, ticket=None):
    env = {
        "PATH": os.defpath,
        "HOME": str(ROOT / "implementation-evidence"),
        "TMPDIR": "/home/piecer/.hermes/cache/scratch",
        "PYTHONPATH": str(ROOT / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if ticket is not None:
        env["AIDDOS_SCENARIO_RECOVERY_TICKET"] = ticket
    with monkeypatch.context() as scope:
        # Only this finite, explicit CLI child is exempt from API process denial.
        scope.setattr(subprocess, "Popen", REAL_POPEN)
        return subprocess.run(
            [sys.executable, *args], input=data, capture_output=True, timeout=30, cwd=ROOT, env=env
        )


def cli(monkeypatch, state_path, command="inspect", *args):
    return child(
        monkeypatch,
        [
            "-m",
            "aiddos.api.scenario_recovery",
            command,
            "--draft-path",
            str(state_path),
            *map(str, args),
        ],
    )


def test_accept_current_cannot_fork_intact_plan_but_can_abandon_lost_material(
    client, state_path, monkeypatch
):
    value, _ = failed_attempt(client, state_path, monkeypatch)
    registry, _, _ = paths(state_path)
    before = registry.read_bytes()
    observation = json.loads(cli(monkeypatch, state_path).stdout)
    archive = state_path.parent / "original-archive"
    result = cli(
        monkeypatch, state_path, "recover", "--review", observation["review"], "--archive", archive
    )
    assert result.returncode == 0
    old_ticket = json.loads(result.stdout)["ticket"]
    inspection = json.loads(cli(monkeypatch, state_path).stdout)
    new_archive = state_path.parent / "explicit-abandonment"
    refused = cli(
        monkeypatch,
        state_path,
        "recover",
        "--review",
        inspection["review"],
        "--archive",
        new_archive,
        "--accept-current",
    )
    assert refused.returncode == 2 and not new_archive.exists()
    lost = archive / "pending" / "candidate"
    preserved = state_path.parent / "operator-moved-candidate"
    lost.rename(preserved)
    preserved_bytes = preserved.read_bytes()
    former = {
        p: p.read_bytes()
        for p in (
            archive / "receipt.bin",
            archive / "decision.json",
            archive / "pending" / "publish",
        )
    }
    assert api_child(monkeypatch, state_path, value, 1, ticket=old_ticket)["status"] == 503
    denied = cli(
        monkeypatch, state_path, "recover", "--review", inspection["review"], "--archive", archive
    )
    assert denied.returncode == 2 and b"ticket" not in denied.stdout
    accepted = cli(
        monkeypatch,
        state_path,
        "recover",
        "--review",
        inspection["review"],
        "--archive",
        new_archive,
        "--accept-current",
    )
    assert accepted.returncode == 0, accepted.stderr.decode()
    decision = json.loads((new_archive / "decision.json").read_bytes())
    assert decision["incomplete_attempt_abandoned"] is True
    assert registry.read_bytes() == before and preserved.read_bytes() == preserved_bytes
    assert all(p.read_bytes() == raw for p, raw in former.items())
    assert (
        api_child(monkeypatch, state_path, value, 1, ticket=json.loads(accepted.stdout)["ticket"])[
            "status"
        ]
        == 201
    )


RECOVERY_FAULTS = (
    [
        (role, op)
        for role in ("archive-receipt.bin", "archive-decision.json")
        for op in (
            "open",
            "fstat",
            "fdopen",
            "write",
            "zero-write",
            "flush",
            "fsync",
            "stream-close",
            "close",
        )
    ]
    + [
        (role, op)
        for role in ("RECOVERING", "READY")
        for op in ("open", "fstat", "write", "zero-write", "fsync", "close")
    ]
    + [
        (role, op)
        for role in ("archive-dir", "archive-payload-dir", "parent-before", "slot-before")
        for op in ("open", "fsync", "close")
    ]
    + [("archived-payload", op) for op in ("open", "fsync", "close")]
)


@pytest.mark.parametrize("role,operation", RECOVERY_FAULTS)
def test_recovery_actual_io_failures_emit_no_ticket_and_preserve_current(
    client, state_path, monkeypatch, capfd, role, operation
):
    from test_scenario_retention import IOFault

    from aiddos.api import scenario_recovery as recovery

    failed_attempt(client, state_path, monkeypatch)
    registry, receipt, pending = paths(state_path)
    before, draft = registry.read_bytes(), state_path.read_bytes()
    observation = recovery.inspect_storage(state_path)[0]
    archive = state_path.parent / "fault-archive"
    with monkeypatch.context() as scope:
        fault = IOFault(scope, registry, role, operation)
        code = recovery.main(
            [
                "recover",
                "--draft-path",
                str(state_path),
                "--review",
                observation["review"],
                "--archive",
                str(archive),
            ]
        )
    output = capfd.readouterr()
    assert fault.fired == [(role, operation)] and not fault.fds
    assert code == 2 and output.out == "" and "ticket" not in output.err
    assert registry.read_bytes() == before and state_path.read_bytes() == draft
    # Every observed payload remains at one of its names; recovery never deletes it.
    for name in ("candidate", "publish"):
        assert (pending / name).is_file() or (archive / "pending" / name).is_file()
    assert receipt.stat().st_size <= 4096
    if archive.exists():
        files = [p for p in archive.rglob("*") if p.is_file()]
        assert len(files) <= 4 and sum(p.stat().st_size for p in files) <= 33562624


@pytest.mark.parametrize("role", ["read-registry", "read-receipt"])
@pytest.mark.parametrize("operation", ["open", "fstat", "fdopen", "read", "stream-close", "close"])
def test_inspect_real_io_failures_remain_effect_free(
    client, state_path, monkeypatch, capfd, role, operation
):
    from test_scenario_retention import IOFault

    from aiddos.api import scenario_recovery as recovery

    saved(client, state_path)
    registry, receipt, pending = paths(state_path)
    before = {p: p.read_bytes() for p in (registry, receipt, state_path)}
    with monkeypatch.context() as scope:
        fault = IOFault(scope, registry, role, operation)
        code = recovery.main(["inspect", "--draft-path", str(state_path)])
    output = capfd.readouterr()
    assert fault.fired == [(role, operation)] and not fault.fds
    assert code == 2 and output.out == ""
    assert all(p.read_bytes() == raw for p, raw in before.items()) and not list(pending.iterdir())


@pytest.mark.parametrize("damage", ["registry", "receipt", "candidate", "publish"])
def test_size_plus_one_is_rejected_even_by_accept_current(client, state_path, monkeypatch, damage):
    failed_attempt(client, state_path, monkeypatch)
    registry, receipt, pending = paths(state_path)
    observation = json.loads(cli(monkeypatch, state_path).stdout)
    path = {"registry": registry, "receipt": receipt}.get(damage, pending / damage)
    limit = 4096 if damage == "receipt" else 16777216
    with path.open("ab") as stream:
        stream.truncate(limit + 1)
    before = path.stat()
    archive = state_path.parent / "size-denied"
    assert cli(monkeypatch, state_path).returncode == 2
    result = cli(
        monkeypatch,
        state_path,
        "recover",
        "--review",
        observation["review"],
        "--archive",
        archive,
        "--accept-current",
        "--confirm-empty-registry",
    )
    assert result.returncode == 2 and not archive.exists()
    after = path.stat()
    assert (before.st_ino, before.st_size, before.st_mtime_ns) == (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )


def test_exact_two_payload_archive_budget_is_supported(client, state_path, monkeypatch):
    failed_attempt(client, state_path, monkeypatch)
    registry, receipt, pending = paths(state_path)
    before = registry.read_bytes()
    for name in ("candidate", "publish"):
        (pending / name).write_bytes(name[:1].encode() * 16777216)
    original = receipt.read_bytes()
    inspection = json.loads(cli(monkeypatch, state_path).stdout)
    archive = state_path.parent / "bounded-full-archive"
    result = cli(
        monkeypatch, state_path, "recover", "--review", inspection["review"], "--archive", archive
    )
    assert result.returncode == 0, result.stderr.decode()
    assert (archive / "receipt.bin").read_bytes() == original
    files = [p for p in archive.rglob("*") if p.is_file()]
    assert len(files) == 4 and sum(p.stat().st_size for p in files) <= 33562624
    assert all(
        (archive / "pending" / n).stat().st_size == 16777216 for n in ("candidate", "publish")
    )
    assert registry.read_bytes() == before


@pytest.mark.parametrize("kind", ["symlink", "fifo", "directory"])
@pytest.mark.parametrize("slot", ["receipt", "candidate", "publish"])
def test_nofollow_nonregular_control_and_payloads_are_never_adopted(
    client, state_path, monkeypatch, kind, slot
):
    failed_attempt(client, state_path, monkeypatch)
    _, receipt, pending = paths(state_path)
    path = receipt if slot == "receipt" else pending / slot
    path.rename(state_path.parent / "retained-original")
    caller = state_path.parent / "caller-data"
    caller.write_bytes(b"not adopted")
    if kind == "symlink":
        path.symlink_to(caller)
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        path.mkdir()
    info = path.lstat()
    assert cli(monkeypatch, state_path).returncode == 2
    assert path.lstat().st_ino == info.st_ino and caller.read_bytes() == b"not adopted"


def test_bounded_iteration_rejects_unknown_entry_without_listdir(client, state_path, monkeypatch):
    from aiddos.api import scenario_recovery as recovery

    failed_attempt(client, state_path, monkeypatch)
    _, _, pending = paths(state_path)
    for n in range(5):
        (pending / ("caller-" + str(n))).write_bytes(b"keep")
    real_scandir = os.scandir
    counts = []

    class Iterator:
        def __init__(self, inner):
            self.inner = inner

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def close(self):
            self.inner.close()

        def __iter__(self):
            return self

        def __next__(self):
            value = next(self.inner)
            counts.append(value.name)
            assert len(counts) <= 3
            return value

    with monkeypatch.context() as scope:
        scope.setattr(os, "listdir", lambda *a: pytest.fail("unbounded listdir"))
        scope.setattr(os, "scandir", lambda *a: Iterator(real_scandir(*a)))
        with pytest.raises(ValueError):
            recovery.inspect_storage(state_path)
    assert 1 <= len(counts) <= 3 and len(list(pending.iterdir())) == 7


@pytest.mark.parametrize(
    "placement",
    ["existing", "pending", "under-pending", "receipt", "registry", "symlink-parent", "cross-fs"],
)
def test_archive_placement_denies_before_effects(client, state_path, monkeypatch, placement):
    failed_attempt(client, state_path, monkeypatch)
    registry, receipt, pending = paths(state_path)
    observation = json.loads(cli(monkeypatch, state_path).stdout)
    existing = state_path.parent / "existing"
    existing.mkdir()
    (existing / "caller").write_bytes(b"preserve")
    alias = state_path.parent / "alias"
    alias.symlink_to(existing, target_is_directory=True)
    destination = {
        "existing": existing,
        "pending": pending,
        "under-pending": pending / "nested",
        "receipt": receipt,
        "registry": registry,
        "symlink-parent": alias / "new",
        "cross-fs": Path("/proc") / ("s01-no-create-" + observation["review"]),
    }[placement]
    # /proc is only a rejection target; no fixture or archive is created there.
    if placement == "cross-fs":
        assert os.stat("/proc").st_dev != state_path.parent.stat().st_dev
    before = {p: p.read_bytes() for p in (registry, receipt, *pending.iterdir())}
    result = cli(
        monkeypatch,
        state_path,
        "recover",
        "--review",
        observation["review"],
        "--archive",
        destination,
    )
    assert result.returncode == 2 and b"ticket" not in result.stdout
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert (existing / "caller").read_bytes() == b"preserve"


@pytest.mark.parametrize("operation", ["open", "fstat", "write", "zero-write", "fsync", "close"])
def test_actual_api_ticket_consume_faults_allocate_no_candidate(
    client, state_path, monkeypatch, operation
):
    value, _ = failed_attempt(client, state_path, monkeypatch)
    registry, receipt, pending = paths(state_path)
    before = registry.read_bytes()
    observation = json.loads(cli(monkeypatch, state_path).stdout)
    archive = state_path.parent / "consume-archive"
    result = cli(
        monkeypatch, state_path, "recover", "--review", observation["review"], "--archive", archive
    )
    assert result.returncode == 0
    ticket = json.loads(result.stdout)["ticket"]
    script = """import json,sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from aiddos.api.app import create_app
sys.path.insert(0,str(Path.cwd()/"tests"/"api"))
from test_scenario_retention import IOFault
request=json.load(sys.stdin)
state=Path(sys.argv[1]); operation=sys.argv[2]
registry=state.with_name(state.name+".scenarios.json")
with TestClient(create_app(state_path=state),base_url="http://localhost") as client:
 with pytest.MonkeyPatch.context() as scope:
  fault=IOFault(scope,registry,"ACTIVE",operation)
  response=client.post("/api/v1/scenarios",json=request)
 assert fault.fired==[("ACTIVE",operation)] and not fault.fds
 assert response.status_code==503
 assert client.get("/api/v1/scenarios").status_code==200
 assert client.post("/api/v1/scenarios",json=request).status_code==503
 print(json.dumps({"status":response.status_code,"fired":fault.fired}))
"""
    failed = child(
        monkeypatch,
        ["-c", script, str(state_path), operation],
        data=json.dumps({"revision": 1, "definition": value}).encode(),
        ticket=ticket,
    )
    assert failed.returncode == 0, failed.stderr.decode()
    assert json.loads(failed.stdout)["fired"] == [["ACTIVE", operation]]
    assert registry.read_bytes() == before and not list(pending.iterdir())
    if operation in {"fsync", "close"}:
        assert api_child(monkeypatch, state_path, value, 1, ticket=ticket)["status"] == 503


def test_invalid_save_does_not_consume_ticket_or_reinitialize_on_get(
    client, state_path, monkeypatch
):
    value, _ = failed_attempt(client, state_path, monkeypatch)
    _, receipt, pending = paths(state_path)
    observation = json.loads(cli(monkeypatch, state_path).stdout)
    archive = state_path.parent / "validated-handoff"
    result = cli(
        monkeypatch, state_path, "recover", "--review", observation["review"], "--archive", archive
    )
    ticket = json.loads(result.stdout)["ticket"]
    original = receipt.read_bytes()
    assert (
        api_child(monkeypatch, state_path, value, 0, ticket=ticket)["body"]["code"]
        == "SCENARIO_CONFLICT"
    )
    missing_reference = {**value, "target_id": "missing"}
    assert (
        api_child(monkeypatch, state_path, missing_reference, 1, ticket=ticket)["body"]["code"]
        == "INVALID_REFERENCE"
    )
    assert receipt.read_bytes() == original and not list(pending.iterdir())
    assert api_child(monkeypatch, state_path, value, 1, ticket=ticket)["status"] == 201


def test_changed_material_at_move_is_retained_and_refused_not_rolled_back(
    client, state_path, monkeypatch
):
    from aiddos.api import scenario_recovery as recovery

    failed_attempt(client, state_path, monkeypatch)
    registry, _, pending = paths(state_path)
    before = registry.read_bytes()
    observation = recovery.inspect_storage(state_path)[0]
    archive = state_path.parent / "move-change"
    real_move = recovery.rename_noreplace
    fired = []

    def move(source, destination):
        (source / "publish").write_bytes(b"late caller bytes")
        fired.append(True)
        return real_move(source, destination)

    with monkeypatch.context() as scope:
        scope.setattr(recovery, "rename_noreplace", move)
        with pytest.raises(ValueError):
            recovery.recover(state_path, observation["review"], archive)
    assert fired == [True] and registry.read_bytes() == before
    assert (archive / "pending" / "publish").read_bytes() == b"late caller bytes"
    assert not pending.exists()
    after = recovery.inspect_storage(state_path)[0]
    denied = cli(
        monkeypatch, state_path, "recover", "--review", after["review"], "--archive", archive
    )
    assert denied.returncode == 2


def test_atomic_no_replace_collision_retains_both_directories(client, state_path, monkeypatch):
    from aiddos.api import scenario_recovery as recovery

    failed_attempt(client, state_path, monkeypatch)
    registry, _, pending = paths(state_path)
    original = {p.name: p.read_bytes() for p in pending.iterdir()}
    observation = recovery.inspect_storage(state_path)[0]
    archive = state_path.parent / "move-collision"
    real_move = recovery.rename_noreplace
    fired = []

    def collide(source, destination):
        destination.mkdir(mode=0o700)
        (destination / "publish").write_bytes(b"caller collision")
        fired.append(True)
        return real_move(source, destination)

    with monkeypatch.context() as scope:
        scope.setattr(recovery, "rename_noreplace", collide)
        with pytest.raises(FileExistsError):
            recovery.recover(state_path, observation["review"], archive)
    assert fired == [True]
    assert {p.name: p.read_bytes() for p in pending.iterdir()} == original
    assert (archive / "pending" / "publish").read_bytes() == b"caller collision"
    assert json.loads(registry.read_bytes())["revision"] == 1


@pytest.mark.parametrize(
    "damage",
    [
        "extra",
        "format-bool",
        "action",
        "abandonment",
        "empty-int",
        "revision",
        "manifest",
        "missing-field",
    ],
)
def test_handoff_revalidates_closed_decision_even_with_matching_file_hash(
    client, state_path, monkeypatch, damage
):
    from test_scenario_retention import read_frame, wire_frame

    value, _ = failed_attempt(client, state_path, monkeypatch)
    registry, receipt, pending = paths(state_path)
    observation = json.loads(cli(monkeypatch, state_path).stdout)
    archive = state_path.parent / "decision-archive"
    result = cli(
        monkeypatch, state_path, "recover", "--review", observation["review"], "--archive", archive
    )
    ticket = json.loads(result.stdout)["ticket"]
    path = archive / "decision.json"
    decision = json.loads(path.read_bytes())
    if damage == "extra":
        decision["unknown"] = False
    elif damage == "format-bool":
        decision["format_version"] = True
    elif damage == "action":
        decision["action"] = "REPLAY"
    elif damage == "abandonment":
        decision["incomplete_attempt_abandoned"] = True
    elif damage == "empty-int":
        decision["empty_registry_confirmed"] = 0
    elif damage == "revision":
        decision["observation"]["registry_revision"] += 1
    elif damage == "manifest":
        decision["observation"]["entries"]["candidate"]["bytes"] = True
    else:
        del decision["observation"]["pending_present"]
    decision["review"] = hashlib.sha256(canonical(decision["observation"])).hexdigest()
    raw = canonical(decision) + b"\n"
    path.write_bytes(raw)
    frame = read_frame(receipt)
    frame["recovery"]["decision_hash"] = hashlib.sha256(raw).hexdigest()
    receipt.write_bytes(wire_frame(frame))
    before = registry.read_bytes()
    assert api_child(monkeypatch, state_path, value, 1, ticket=ticket)["status"] == 503
    assert registry.read_bytes() == before and not list(pending.iterdir())


def test_cli_output_failure_returns_refusal_not_a_successful_handoff(
    client, state_path, monkeypatch
):
    from aiddos.api import scenario_recovery as recovery

    saved(client, state_path)

    class BrokenOutput:
        @property
        def buffer(self):
            return self

        def write(self, data):
            raise OSError("output failure")

        def flush(self):
            raise OSError("flush failure")

    with monkeypatch.context() as scope:
        scope.setattr(sys, "stdout", BrokenOutput())
        scope.setattr(sys, "stderr", BrokenOutput())
        assert recovery.main(["inspect", "--draft-path", str(state_path)]) == 2


def test_inspect_absence_is_explicit_and_creates_nothing(state_path, monkeypatch):
    result = cli(monkeypatch, state_path)
    assert result.returncode == 0
    observed = json.loads(result.stdout)
    assert observed["phase"] == "MISSING" and not observed["receipt_present"]
    assert not observed["pending_present"] and observed["entries"] == {}
    assert observed["registry_hash"] == "ABSENT" and observed["registry_revision"] == 0
    assert observed["record_hash"] == hashlib.sha256(b"").hexdigest()
    assert observed["receipt_bytes"] == observed["registry_bytes"] == 0
    assert not list(state_path.parent.iterdir())


def test_empty_accept_current_resume_still_requires_explicit_confirmation(state_path, monkeypatch):
    observation = json.loads(cli(monkeypatch, state_path).stdout)
    archive = state_path.parent / "empty-archive"
    first = cli(
        monkeypatch,
        state_path,
        "recover",
        "--review",
        observation["review"],
        "--archive",
        archive,
        "--accept-current",
        "--confirm-empty-registry",
    )
    assert first.returncode == 0, first.stderr.decode()
    current = json.loads(cli(monkeypatch, state_path).stdout)
    _, receipt, pending = paths(state_path)
    before = receipt.read_bytes()
    denied = cli(
        monkeypatch,
        state_path,
        "recover",
        "--review",
        current["review"],
        "--archive",
        archive,
        "--accept-current",
    )
    assert denied.returncode == 2 and receipt.read_bytes() == before
    resumed = cli(
        monkeypatch,
        state_path,
        "recover",
        "--review",
        current["review"],
        "--archive",
        archive,
        "--accept-current",
        "--confirm-empty-registry",
    )
    assert resumed.returncode == 0 and not list(pending.iterdir())
    assert not (archive / "receipt.bin").read_bytes()
    assert not list((archive / "pending").iterdir())


@pytest.mark.parametrize("location", ["pending", "archive"])
def test_directory_iteration_primary_survives_secondary_iterator_close(
    client, state_path, monkeypatch, location
):
    from aiddos.api import scenario_recovery as recovery

    failed_attempt(client, state_path, monkeypatch)
    _, _, pending = paths(state_path)
    archive = state_path.parent / "iterator-archive"
    observation = recovery.inspect_storage(state_path)[0]
    if location == "archive":
        recovery.recover(state_path, observation["review"], archive)
        observation = recovery.inspect_storage(state_path)[0]
    target = pending if location == "pending" else archive
    identity = target.stat().st_ino
    original = os.scandir
    primary, secondary = OSError("iteration primary"), OSError("iterator close secondary")
    fired, closed = [], []

    class Iterator:
        def __init__(self, inner):
            self.inner = inner

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def __iter__(self):
            return self

        def __next__(self):
            next(self.inner)
            fired.append(True)
            raise primary

        def close(self):
            self.inner.close()
            closed.append(True)
            raise secondary

    def scan(fd):
        inner = original(fd)
        return Iterator(inner) if os.fstat(fd).st_ino == identity else inner

    with monkeypatch.context() as scope:
        scope.setattr(os, "scandir", scan)
        with pytest.raises(OSError) as error:
            if location == "pending":
                recovery.inspect_storage(state_path)
            else:
                recovery.recover(state_path, observation["review"], archive)
    assert fired == closed == [True]
    assert error.value is primary


@pytest.mark.parametrize(
    "role",
    [
        "archive-receipt.bin",
        "archive-decision.json",
        "RECOVERING",
        "READY",
        "archive-dir",
        "archived-payload",
    ],
)
def test_recovery_primary_fsync_survives_secondary_close_with_fd_reuse(
    client, state_path, monkeypatch, role
):
    from test_scenario_retention import IOFault

    from aiddos.api import scenario_recovery as recovery

    failed_attempt(client, state_path, monkeypatch)
    registry, _, _ = paths(state_path)
    observation = recovery.inspect_storage(state_path)[0]
    caller = state_path.parent / "caller-recovery-descriptor"
    caller.write_bytes(b"keep")
    archive = state_path.parent / "secondary-close-archive"
    real_open, real_close = os.open, os.close
    retained = []
    with monkeypatch.context() as scope:
        fault = IOFault(scope, registry, role, "fsync")
        close_instrumented = os.close

        def close(fd):
            selected = fault.fds.get(fd)
            close_instrumented(fd)
            if selected == role and fault.fired:
                replacement = real_open(caller, os.O_RDONLY)
                assert replacement == fd
                retained.append(replacement)
                raise OSError("secondary close")

        scope.setattr(os, "close", close)
        with pytest.raises(OSError) as error:
            recovery.recover(state_path, observation["review"], archive)
    assert error.value is fault.primary
    assert fault.fired == [(role, "fsync")] and not fault.fds and len(retained) == 1
    assert os.read(retained[0], 4) == b"keep"
    real_close(retained[0])
    assert caller.read_bytes() == b"keep"


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()


def test_inspect_executable_reports_exact_closed_observation_without_effects(
    client, state_path, monkeypatch
):
    saved(client, state_path)
    registry, receipt, pending = paths(state_path)
    original = {p: p.read_bytes() for p in (registry, receipt, state_path)}
    result = cli(monkeypatch, state_path)
    assert result.returncode == 0, result.stderr.decode()
    observation = json.loads(result.stdout)
    assert set(observation) == {
        "phase",
        "receipt_present",
        "receipt_bytes",
        "record_hash",
        "registry_hash",
        "registry_revision",
        "registry_bytes",
        "pending_present",
        "entries",
        "review",
    }
    assert observation["phase"] == "CLEAN" and observation["entries"] == {}
    assert observation["receipt_present"] and observation["pending_present"]
    assert observation["receipt_bytes"] == 4096
    assert observation["registry_revision"] == 1
    assert observation["registry_bytes"] == len(original[registry])
    assert observation["registry_hash"] == hashlib.sha256(original[registry]).hexdigest()
    assert observation["record_hash"] == hashlib.sha256(original[receipt]).hexdigest()
    review = observation.pop("review")
    assert review == hashlib.sha256(canonical(observation)).hexdigest()
    assert len(result.stdout) <= 4096 and result.stderr == b""
    assert all(p.read_bytes() == raw for p, raw in original.items())
    assert list(pending.iterdir()) == []


def api_child(monkeypatch, state_path, value, revision, *, ticket=None):
    script = """import json,socket,sys
from pathlib import Path
from fastapi.testclient import TestClient
from aiddos.api.app import create_app
import aiddos.api.scenario_store as store
assert Path(store.__file__).resolve().is_relative_to(Path.cwd())
def forbidden(*args, **kwargs): raise RuntimeError("network forbidden")
socket.socket.bind = socket.socket.listen = socket.socket.connect = forbidden
socket.getaddrinfo = forbidden
request=json.load(sys.stdin)
with TestClient(create_app(state_path=Path(sys.argv[1])),base_url="http://localhost") as client:
 response=client.post("/api/v1/scenarios",json=request)
 print(json.dumps({"status":response.status_code,"body":response.json()}))
"""
    result = child(
        monkeypatch,
        ["-c", script, str(state_path)],
        data=json.dumps({"revision": revision, "definition": value}).encode(),
        ticket=ticket,
    )
    assert result.returncode == 0, result.stderr.decode()
    return json.loads(result.stdout)


def failed_attempt(client, state_path, monkeypatch):
    value, first, _ = saved(client, state_path)
    fired = []

    def fail(source, destination):
        fired.append(str(source))
        Path(source).unlink()
        Path(source).write_bytes(b"caller replacement is retained")
        raise OSError("failed publication")

    with monkeypatch.context() as fault:
        fault.setattr(os, "replace", fail)
        response = client.post("/api/v1/scenarios", json={"revision": 1, "definition": value})
    assert response.status_code == 503 and len(fired) == 1
    return value, first


def test_normal_recovery_archives_then_one_use_handoff_to_real_api(client, state_path, monkeypatch):
    from test_scenario_retention import read_frame

    value, first = failed_attempt(client, state_path, monkeypatch)
    registry, receipt, pending = paths(state_path)
    before, draft, record = registry.read_bytes(), state_path.read_bytes(), receipt.read_bytes()
    payloads = {p.name: p.read_bytes() for p in pending.iterdir()}
    observation = json.loads(cli(monkeypatch, state_path).stdout)
    archive = state_path.parent / "reviewed-archive"
    denied = cli(monkeypatch, state_path, "recover", "--review", "0" * 64, "--archive", archive)
    assert denied.returncode == 2 and not archive.exists() and b"ticket" not in denied.stdout
    result = cli(
        monkeypatch, state_path, "recover", "--review", observation["review"], "--archive", archive
    )
    assert result.returncode == 0, result.stderr.decode()
    ready = json.loads(result.stdout)
    assert set(ready) == {"status", "action", "archive", "registry_hash", "ticket"}
    assert ready["status"] == "READY" and ready["action"] == "RECONCILE"
    assert (archive / "receipt.bin").read_bytes() == record
    assert {p.name: p.read_bytes() for p in (archive / "pending").iterdir()} == payloads
    decision = json.loads((archive / "decision.json").read_bytes())
    assert decision == {
        "format_version": 1,
        "action": "RECONCILE",
        "review": observation["review"],
        "observation": {k: v for k, v in observation.items() if k != "review"},
        "incomplete_attempt_abandoned": False,
        "empty_registry_confirmed": False,
    }
    frame = read_frame(receipt)
    assert frame["phase"] == "READY"
    assert (
        frame["recovery"]["decision_hash"]
        == hashlib.sha256((archive / "decision.json").read_bytes()).hexdigest()
    )
    assert ready["ticket"].encode() not in receipt.read_bytes()
    assert registry.read_bytes() == before and state_path.read_bytes() == draft
    assert list(pending.iterdir()) == []
    assert api_child(monkeypatch, state_path, value, 1)["status"] == 503
    assert api_child(monkeypatch, state_path, value, 1, ticket="0" * 64)["status"] == 503
    accepted = api_child(monkeypatch, state_path, value, 1, ticket=ready["ticket"])
    assert accepted["status"] == 201, accepted
    assert api_child(monkeypatch, state_path, value, 2, ticket=ready["ticket"])["status"] == 503
    # A real new process with CLEAN, no ticket, can perform the next save.
    assert api_child(monkeypatch, state_path, value, 2)["status"] == 201
    assert json.loads(registry.read_bytes())["scenarios"][0]["versions"] == [first]
    assert state_path.read_bytes() == draft
    assert {p.name: p.read_bytes() for p in (archive / "pending").iterdir()} == payloads


@pytest.mark.parametrize(
    "damage", ["missing-candidate", "torn", "missing-receipt", "missing-slot", "empty"]
)
def test_accept_current_preserves_observable_material_and_never_replays(
    client, state_path, monkeypatch, damage
):
    value, first = failed_attempt(client, state_path, monkeypatch)
    registry, receipt, pending = paths(state_path)
    moved = {}
    if damage == "missing-candidate":
        source = pending / "candidate"
    elif damage == "missing-receipt":
        source = receipt
    elif damage == "missing-slot":
        source = pending
    elif damage == "empty":
        source = registry
    else:
        source = None
        receipt.write_bytes(b"S01RR001 torn")
    if source is not None:
        destination = state_path.parent / "operator-moved"
        source.rename(destination)
        if destination.is_file():
            moved[destination] = destination.read_bytes()
        else:
            moved.update({p: p.read_bytes() for p in destination.iterdir()})
    current = registry.read_bytes() if registry.exists() else None
    original = receipt.read_bytes() if receipt.exists() else b""
    payloads = {p.name: p.read_bytes() for p in pending.iterdir()} if pending.exists() else {}
    observation = json.loads(cli(monkeypatch, state_path).stdout)
    archive = state_path.parent / "accepted-current"
    if damage != "empty":
        normal = cli(
            monkeypatch,
            state_path,
            "recover",
            "--review",
            observation["review"],
            "--archive",
            archive,
        )
        assert normal.returncode == 2 and not archive.exists()
    flags = ["--accept-current"]
    if damage == "empty":
        denied = cli(
            monkeypatch,
            state_path,
            "recover",
            "--review",
            observation["review"],
            "--archive",
            archive,
            *flags,
        )
        assert denied.returncode == 2 and not archive.exists()
        flags.append("--confirm-empty-registry")
    result = cli(
        monkeypatch,
        state_path,
        "recover",
        "--review",
        observation["review"],
        "--archive",
        archive,
        *flags,
    )
    assert result.returncode == 0, result.stderr.decode()
    ready = json.loads(result.stdout)
    decision = json.loads((archive / "decision.json").read_bytes())
    assert decision["action"] == ready["action"] == "ACCEPT_CURRENT"
    assert decision["incomplete_attempt_abandoned"] is True
    assert decision["empty_registry_confirmed"] is (damage == "empty")
    assert decision["observation"] == {k: v for k, v in observation.items() if k != "review"}
    assert (archive / "receipt.bin").read_bytes() == original
    assert {p.name: p.read_bytes() for p in (archive / "pending").iterdir()} == payloads
    assert (registry.read_bytes() if registry.exists() else None) == current
    assert all(p.read_bytes() == raw for p, raw in moved.items())
    revision = 0 if current is None else 1
    assert api_child(monkeypatch, state_path, value, revision)["status"] == 503
    assert (
        api_child(monkeypatch, state_path, value, revision, ticket=ready["ticket"])["status"] == 201
    )
    state = json.loads(registry.read_bytes())
    assert state["revision"] == revision + 1
    if current is not None:
        assert state["scenarios"][0]["versions"] == [first]


@pytest.mark.parametrize("point", ["before-move", "after-move", "after-mkdir", "ready-close"])
def test_interrupted_recovery_resumes_only_exact_archive_without_replay(
    client, state_path, monkeypatch, point
):
    value, first = failed_attempt(client, state_path, monkeypatch)
    registry, receipt, pending = paths(state_path)
    before = registry.read_bytes()
    observation = json.loads(cli(monkeypatch, state_path).stdout)
    archive = state_path.parent / "resume-archive"
    fired_path = state_path.parent / "resume-fault.json"
    script = """import json,os,sys
from pathlib import Path
from aiddos.api import scenario_recovery as recovery
assert "aiddos.api.app" not in sys.modules
point,draft,review,archive,report=sys.argv[1:]
archive=Path(archive)
registry,receipt,pending=recovery.storage_paths(draft)
real_sync=recovery.io.sync_directory
real_move=recovery.rename_noreplace
real_open,real_close,real_pwrite=os.open,os.close,os.pwrite
fds=set(); ready=set(); fired=[]
def fail():
 fired.append(point)
 Path(report).write_text(json.dumps(fired))
 raise OSError("recovery interrupted")
def sync(path):
 if not fired and ((point=="after-move" and path==archive/"pending") or
                  (point=="after-mkdir" and path==pending and (archive/"pending").exists())): fail()
 return real_sync(path)
def move(a,b):
 if point=="before-move" and not fired: fail()
 return real_move(a,b)
def opened(path,flags,*a,**kw):
 fd=real_open(path,flags,*a,**kw)
 if path==receipt and flags & os.O_WRONLY: fds.add(fd)
 return fd
def written(fd,data,offset):
 if (fd in fds and offset==0 and len(data)==4096 and
     recovery.io.decode_frame(data)["phase"]=="READY"):
  ready.add(fd)
 return real_pwrite(fd,data,offset)
def close(fd):
 should=fd in ready; fds.discard(fd); ready.discard(fd); real_close(fd)
 if point=="ready-close" and should and not fired: fail()
recovery.io.sync_directory=sync; recovery.rename_noreplace=move
os.open=opened; os.close=close; os.pwrite=written
args=["recover","--draft-path",draft,"--review",review,"--archive",str(archive)]
raise SystemExit(recovery.main(args))
"""
    result = child(
        monkeypatch,
        [
            "-c",
            script,
            point,
            str(state_path),
            observation["review"],
            str(archive),
            str(fired_path),
        ],
    )
    assert result.returncode == 2 and result.stdout == b"", result.stderr.decode()
    assert json.loads(fired_path.read_bytes()) == [point]
    preserved = {p: p.read_bytes() for p in (archive / "receipt.bin", archive / "decision.json")}
    inspection = json.loads(cli(monkeypatch, state_path).stdout)
    wrong = state_path.parent / "wrong-archive"
    denied = cli(
        monkeypatch, state_path, "recover", "--review", inspection["review"], "--archive", wrong
    )
    assert denied.returncode == 2 and not wrong.exists()
    denied_accept = cli(
        monkeypatch,
        state_path,
        "recover",
        "--review",
        inspection["review"],
        "--archive",
        wrong,
        "--accept-current",
    )
    assert denied_accept.returncode == 2 and not wrong.exists()
    assert all(p.read_bytes() == raw for p, raw in preserved.items())
    resumed = cli(
        monkeypatch, state_path, "recover", "--review", inspection["review"], "--archive", archive
    )
    assert resumed.returncode == 0, resumed.stderr.decode()
    assert all(p.read_bytes() == raw for p, raw in preserved.items())
    assert registry.read_bytes() == before
    ready = json.loads(resumed.stdout)
    assert api_child(monkeypatch, state_path, value, 1, ticket=ready["ticket"])["status"] == 201
    assert json.loads(registry.read_bytes())["scenarios"][0]["versions"] == [first]
