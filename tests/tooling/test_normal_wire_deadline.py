"""Deterministic effect-free R1 schedules through the real capture supervisor."""

import json
from types import SimpleNamespace

import pytest

from tools import normal_wire as wire
from tools import s02_harness, s02_web_probe


@pytest.mark.parametrize("completion", [59, 61])
def test_completion_observation_respects_original_probe_deadline(tmp_path, monkeypatch, completion):
    output = tmp_path / "capture"
    clock = {"now": 0}
    events = []

    class Process:
        returncode = None
        polls = 0

        def poll(self):
            self.polls += 1
            if self.polls == 1:
                clock["now"] = 59
                return None
            self.returncode = 0
            return 0

    class Native:
        closed = False
        clean = False

        def __init__(self, *_):
            pass

        def launch(self, *_):
            work = output / "pg/phase1-normal"
            for name in ("result.json", "captured-wire.json"):
                (work / name).write_text("{}")
            for role in wire.WORKERS:
                for suffix in ("exit", "origins", "started"):
                    (work / f"{role}-{suffix}.json").write_text("{}")
            for name in ("probe-origins.json", "probe.native-end.json"):
                (output / name).write_text("{}")
            return Process()

        def discover(self):
            pass

        def retire_all(self):
            events.append("native-retired")
            self.closed = self.clean = True
            (output / "native-retirement.json").write_text("{}")

    class PG:
        state = "NEW"
        owner_process = {}

        def __init__(self, path):
            self.directory = path / "pg"
            self.directory.mkdir()
            self.socket = path / "socket"
            self.journal = path / "journal.jsonl"
            self.journal.write_text(json.dumps({"synthetic": True}) + "\n")

        def __enter__(self):
            return self

        def bootstrap(self):
            pass

        def __exit__(self, *_):
            events.append("pg-retired")
            self.state = "CLEAN"

    def sleep(_):
        clock["now"] = completion

    monkeypatch.setattr(s02_harness, "Harness", PG)
    monkeypatch.setattr(s02_web_probe, "NativeChildren", Native)
    monkeypatch.setattr(wire, "time", SimpleNamespace(monotonic=lambda: clock["now"], sleep=sleep))
    # Isolate supervisor admission; this synthetic object is never product evidence.
    monkeypatch.setattr(wire, "assemble", lambda *_: {"synthetic_test_only": True})
    if completion < 60:
        wire.capture(output)
        assert (output / "normal-wire-current.json").exists()
    else:
        with pytest.raises(RuntimeError, match="EXPIRED"):
            wire.capture(output)
        assert not (output / "normal-wire-current.json").exists()
    assert events == ["native-retired", "pg-retired"]
