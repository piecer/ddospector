"""Worker-local queued cancellation fixture; not an HTTP cancellation witness."""

import json
import sys
from pathlib import Path

from tools import s02_harness as h

ROOT = Path(__file__).resolve().parents[2]


def test_worker_never_claims_withdrawn_queued_fixture(owned_pg):
    owned_pg.revalidate()
    output = owned_pg.directory / "queued-cancel"
    output.mkdir()
    data = {
        "root": str(ROOT),
        "socket": str(owned_pg.socket),
        "output": str(output),
        "owner": owned_pg.owner_process,
    }
    path = output / "handoff.json"
    path.write_text(json.dumps(data))
    events = []
    result = h.run_child(
        [sys.executable, str(ROOT / "tests/runs/worker_queued_probe.py"), str(path)],
        output,
        60,
        events.append,
    )
    (output / "launch.json").write_text(
        json.dumps(
            {
                "actual_exit": result.code,
                "timed_out": result.timed_out,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "events": events,
            },
            indent=2,
        )
    )
    assert not result.timed_out and result.code == 0, str(output)
    assert json.loads((output / "result.json").read_text())["unchanged"]
