"""Selected real P2-01 normal path, never the deferred fault campaign."""

import hashlib
import json
import sys
from pathlib import Path

from tools import s02_harness as h

ROOT = Path(__file__).resolve().parents[2]


def test_evidence_registration_real_owned_postgresql(owned_pg):
    owned_pg.revalidate()
    output = owned_pg.directory / "evidence-normal"
    output.mkdir()
    sources = [p for directory in ("src", "tools", "tests/runs")
               for p in (ROOT / directory).rglob("*")
               if p.is_file() and p.suffix in {".py", ".sql"}]
    handoff = {
        "root": str(ROOT), "socket": str(owned_pg.socket), "output": str(output),
        "owner": owned_pg.owner_process,
        "source": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(sources)},
    }
    config = output / "handoff.json"
    config.write_text(json.dumps(handoff, indent=2) + "\n")
    events = []
    result = h.run_child(
        [sys.executable, str(ROOT / "tests/runs/evidence_probe.py"), str(config)],
        output, 180, events.append,
    )
    (output / "launch.json").write_text(json.dumps({
        "code": result.code, "timed_out": result.timed_out, "events": events,
        "stdout": result.stdout, "stderr": result.stderr,
    }, indent=2) + "\n")
    assert not result.timed_out and result.code == 0, str(output)
    value = json.loads((output / "result.json").read_text())
    assert value["run_unchanged"] and value["registration_readback"]
