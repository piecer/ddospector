"""One real local normal execution, not the deferred W2 fault campaign."""

import hashlib
import json
import sys
from pathlib import Path

from tools import s02_harness as h

ROOT = Path(__file__).resolve().parents[2]


def test_selected_run_real_postgresql_and_separate_process(owned_pg):
    owned_pg.revalidate()
    output = owned_pg.directory / "phase1-normal"
    output.mkdir()
    handoff = {
        "root": str(ROOT), "socket": str(owned_pg.socket), "output": str(output),
        "owner": owned_pg.owner_process,
        "source": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "src").rglob("*.py"))
        },
    }
    config = output / "handoff.json"
    config.write_text(json.dumps(handoff, indent=2) + "\n")
    events = []
    result = h.run_child(
        [sys.executable, str(ROOT / "tests/runs/phase1_probe.py"), str(config)],
        output, 60, events.append,
    )
    (output / "launch.json").write_text(json.dumps({
        "code": result.code, "timed_out": result.timed_out, "events": events,
        "stdout": result.stdout, "stderr": result.stderr,
    }, indent=2) + "\n")
    assert not result.timed_out and result.code == 0, str(output)
    value = json.loads((output / "result.json").read_text())
    assert value["state"] == "SUCCEEDED" and value["attempt"] == 1
    assert value["other_run_untouched"] and value["repeat_refused"]
    assert value["stored_result_matches_http"]
