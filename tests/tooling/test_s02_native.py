"""Actual owned native processes; these controls import no product modules."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PYTHON = str(ROOT / ".venv/bin/python")


@pytest.mark.parametrize("kind", ["exit", "spawn-failure", "late-descendant", "diagnostic-log"])
def test_native_retirement(tmp_path, kind):
    child = (
        r"""
import json, os, sys, time
from pathlib import Path
from tools.s02_web_probe import NativeChildren
out=Path(sys.argv[1]); kind=sys.argv[2]
env={"PATH":"/usr/bin:/bin","HOME":str(out),"TMPDIR":str(out),"PYTHONDONTWRITEBYTECODE":"1"}
owner=NativeChildren(out,env)
try:
    if kind=="spawn-failure":
        try: owner.launch("broken",["/no-such-owned-executable"])
        except FileNotFoundError: pass
        else: raise AssertionError("missing spawn error")
    else:
        code="print('finished')" if kind=="exit" else """
        + '"""'
        + r"""
import os,signal,time
from pathlib import Path
def stop(sig, frame):
    if os.fork()==0:
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        time.sleep(20)
    else:
        raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
print('armed',flush=True)
time.sleep(20)
"""
        + '"""'
        + r"""
        if kind=="diagnostic-log":
            code=("import os; os.write(2,b'first\\n'); "
                  "f=os.open('/proc/self/fd/2',os.O_WRONLY|os.O_NONBLOCK); "
                  "os.write(f,b'diagnostic\\n'); os.close(f); os.write(2,b'last\\n')")
        p=owner.launch("child",[sys.executable,"-c",code])
        if kind in ("exit","diagnostic-log"): assert p.wait(timeout=2)==0
        else:
            end=time.monotonic()+2
            while "armed" not in (out/"child.stdout").read_text():
                assert time.monotonic()<end
                time.sleep(.01)
finally:
    owner.retire_all()
assert owner.clean
assert not owner.children(os.getpid())
"""
    )
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
    with subprocess.Popen(
        [PYTHON, "-c", child, str(tmp_path), kind],
        cwd=ROOT,
        env=env,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as p:
        stdout, stderr = p.communicate(timeout=10)
    assert p.returncode == 0, stdout + stderr
    receipt = json.loads((tmp_path / "native-retirement.json").read_text())
    assert receipt["clean"] and receipt["remaining"] == []
    assert receipt["pidfds_closed"]
    if kind == "diagnostic-log":
        assert (tmp_path / "child.stderr").read_bytes() == b"first\ndiagnostic\nlast\n"
    if kind == "late-descendant":
        assert len(receipt["identities"]) >= 2
        assert any(item["signal"] == 9 for item in receipt["signals"])
