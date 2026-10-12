"""F-01 native admission after real parameter preparation and original D."""

import hashlib
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from connection_deadline_probe import identity

from tools import s02_harness as h

CHILD = Path(__file__).with_name("connection_deadline_probe.py")


def save(directory, name, value):
    (directory / name).write_text(json.dumps(value, indent=2) + "\n")


@contextmanager
def launch(patch, owner, directory, mode):
    original_spawn, original_run = h.subprocess.Popen, h.run_child
    children, results = [], []
    source_sha = hashlib.sha256(Path(h.__file__).read_bytes()).hexdigest()
    output = directory / "connection-child.json"

    def spawn(argv, *args, **kwargs):
        if "--pg-child" not in argv:
            return original_spawn(argv, *args, **kwargs)
        assert owner.work_state == "PENDING"
        actual = [argv[0], str(CHILD), str(output), source_sha, mode, *argv[2:]]
        token = h.PROCESS_ARGV.set(tuple(actual))
        try:
            child = original_spawn(actual, *args, **kwargs)
        finally:
            h.PROCESS_ARGV.reset(token)
        children.append((child, identity(child.pid)))
        return child

    def run(*args, **kwargs):
        result = original_run(*args, **kwargs)
        if kwargs.get("_grant") is not None:
            results.append(result)
        return result

    patch.setattr(h.subprocess, "Popen", spawn)
    patch.setattr(h, "run_child", run)
    yield children, results, output


def exercise_boundary(owner, directory, monkeypatch, mode):
    control = mode.startswith("control")
    cap = mode.endswith("cap")
    action = "write" if cap else "read"
    with monkeypatch.context() as patch, launch(patch, owner, directory, mode) as observed:
        children, results, output = observed
        if control:
            proof = owner.probe(action)
            primary = None
        else:
            with pytest.raises(h.Blocked) as caught:
                owner.probe(action)
            primary = {"type": type(caught.value).__name__, "message": str(caught.value)}
            proof = None
        child, child_identity = children[0]
        row = json.loads(output.read_text())
        before = {
            "source": h.__file__,
            "source_sha256": hashlib.sha256(Path(h.__file__).read_bytes()).hexdigest(),
            "primary": primary,
            "child_identity": child_identity,
            "actual_exit": child.returncode,
            "pid_absent_before_rescue": not Path(f"/proc/{child.pid}").exists(),
            "pipes_closed_before_rescue": [
                stream.closed for stream in (child.stdin, child.stdout, child.stderr)
            ],
            "disposal_unconfirmed": owner.disposal_unconfirmed,
            "owner_state": owner.work_state,
            "child_observation": row,
            "real_results": [vars(result) for result in results],
            "actual_late_connect_entries": sum(e["after_original_D"] for e in row["connects"]),
            "proof": proof,
            "rescue_used": False,
        }
        if not control:
            count = len(children)
            with pytest.raises(h.Blocked, match="WORK_REVOKED"):
                owner.probe("write")
            before["next_operation_spawns"] = len(children) - count
            before["original_D"] = owner.attempt.deadline
        save(directory, "connection-before-rescue.json", before)
        assert len(children) == 1
        assert before["pid_absent_before_rescue"] and child.returncode is not None
        assert all(before["pipes_closed_before_rescue"]) and not owner.disposal_unconfirmed
        assert row["source"] == h.__file__ and row["source_sha256"] == before["source_sha256"]
        assert row["interpreter"] == sys.executable and row["prefix"] == sys.prefix
        assert row["TMPDIR"] == row["HOME"] == str(owner.socket.parent)
        assert all(e["closed_before_rescue"] for e in row["connections"])
        if control:
            assert proof["value"] == "i0-probe-not-application"
            assert row["connects"]
            if cap:
                refusals = [e for e in row["connects"] if not e["returned_real_connection"]]
                assert len(refusals) == 1 and refusals[0]["role_cap_refusal"]
                assert proof["connection_cap_enforced"] is True
                assert any(e["caller"] == "_pg_probe" for e in row["parameters"])
            else:
                assert all(e["returned_real_connection"] for e in row["connects"])
            assert row["sql"] and not any(e["after_original_D"] for e in row["sql"])
            assert child.returncode == 0 and owner.work_state == "ELIGIBLE"
        else:
            fired = [e for e in row["parameters"] if e.get("delay_fired")]
            assert len(fired) == 1
            assert fired[0]["entered_ns"] < row["original_deadline"] < fired[0]["return_ns"]
            assert row["original_deadline"] == before["original_D"]
            if cap:
                assert fired[0]["caller"] == "_pg_probe"
                assert row["sql"] and not any(e["after_original_D"] for e in row["sql"])
                assert any(e["returned_real_connection"] for e in row["connects"])
            else:
                assert not row["sql"]
            assert owner.work_state == "REVOKED" and before["next_operation_spawns"] == 0
            assert row["actual_main_exit"] == 78
        assert before["actual_late_connect_entries"] == 0, (
            "F01: native connector entered after parameter preparation returned beyond original D"
        )
    assert h.PROCESS_ARGV.get() is None


@pytest.mark.parametrize("mode", ["control", "late-parameters"])
def test_connection_parameters_original_deadline(owned_pg, tmp_path, monkeypatch, mode):
    owner = owned_pg
    owner.probe("write")
    exercise_boundary(owner, tmp_path, monkeypatch, mode)


@pytest.mark.parametrize("mode", ["control-cap", "late-cap"])
def test_cap_parameters_original_deadline(owned_pg, tmp_path, monkeypatch, mode):
    exercise_boundary(owned_pg, tmp_path, monkeypatch, mode)
