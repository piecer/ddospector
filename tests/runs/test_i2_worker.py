"""I2 vertical acceptance through separately launched HTTP/worker processes."""
import hashlib
import json
import sys
from pathlib import Path

from tools import s02_harness as h

ROOT = Path(__file__).resolve().parents[2]


def probe(owner, case, timeout=60):
    owner.check_work()
    owner.revalidate()
    output = owner.directory / ('i2-' + case)
    output.mkdir()
    handoff = {
        'root': str(ROOT), 'prefix': str(ROOT / '.venv'),
        'python': str(ROOT / '.venv/bin/python'), 'owner': owner.owner_process,
        'socket': str(owner.socket), 'output': str(output), 'case': case,
        'source': {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ('src', 'tests/runs')
            for p in sorted((ROOT / folder).rglob('*.py'))
        },
    }
    path = output / 'handoff.json'
    path.write_text(json.dumps(handoff, indent=2) + '\n')
    assert Path(sys.prefix) == ROOT / '.venv'
    events = []
    result = h.run_child(
        [str(ROOT / '.venv/bin/python'), str(ROOT / 'tests/runs/i2_probe.py'), str(path)],
        output, timeout, events.append,
    )
    (output / 'launch.json').write_text(json.dumps({
        'actual_exit': result.code, 'timed_out': result.timed_out,
        'events': events, 'stderr': result.stderr, 'stdout': result.stdout,
    }, indent=2) + '\n')
    assert not result.timed_out, str(output)
    assert result.code == 0, str(output)
    return json.loads((output / 'result.json').read_text())


def test_i2_01_captured_http_run_completes_without_s01(owned_pg):
    result = probe(owned_pg, 'captured-success')
    assert result['detail']['run']['state'] == 'SUCCEEDED'
    assert result['detail']['result']['evaluation'] == 'NOT_EVALUATED'
