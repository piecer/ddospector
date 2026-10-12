"""Scoped I1 application child launch; I0 guards and protocol are unchanged."""

import hashlib
import json
import sys
from pathlib import Path

from tools import s02_harness as h

ROOT = Path(__file__).resolve().parents[2]


def application_probe(owner, case):
    owner.check_work()
    owner.revalidate()
    assert owner.ready
    output = owner.directory / ("application-" + case)
    output.mkdir()
    handoff = {
        "root": str(ROOT),
        "prefix": str(ROOT / ".venv"),
        "python": str(ROOT / ".venv/bin/python"),
        "owner": owner.owner_process,
        "socket": str(owner.socket),
        "output": str(output),
        "case": case,
        "source": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "src").rglob("*.py"))
        },
    }
    receipt = output / "handoff.json"
    receipt.write_text(json.dumps(handoff, indent=2) + "\n")
    assert Path(sys.prefix) == ROOT / ".venv"
    observations = []
    result = h.run_child(
        [str(ROOT / ".venv/bin/python"), str(ROOT / "tests/runs/offline_probe.py"), str(receipt)],
        output,
        60,
        observations.append,
    )
    (output / "launch.json").write_text(
        json.dumps(
            {
                "observations": observations,
                "actual_exit": result.code,
                "timed_out": result.timed_out,
                "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(),
                "stderr_bytes": len(result.stderr.encode()),
                "stdout": result.stdout,
            },
            indent=2,
        )
        + "\n"
    )
    # Public diagnostics only. Driver messages stay out of pytest tracebacks.
    assert not result.timed_out, "APPLICATION_PROBE_TIMEOUT"
    assert result.code == 0, f"APPLICATION_PROBE_FAILED: {output}"
    return json.loads((output / "result.json").read_text())
