"""Opt-in, nonsecret source-origin receipt for normal-wire probe/worker exits."""

import atexit
import hashlib
import json
import os
import sys
from pathlib import Path


def record():
    root = Path(os.environ["NORMAL_WIRE_ROOT"]).resolve()
    modules = {}
    for name, module in list(sys.modules.items()):
        if not (name.startswith(("aiddos", "ddospector")) or name == "scenario_producer"):
            continue
        filename = getattr(module, "__file__", None)
        if filename is None:
            continue
        path = Path(filename).resolve()
        # A foreign origin causes a missing final receipt, never a successful fallback.
        relative = str(path.relative_to(root))
        modules[name] = {"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    identity = {"pid": os.getpid(),
                "start_ticks": Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19],
                "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}
    value = {"root": str(root), "pid": os.getpid(), "identity": identity, "modules": modules}
    with Path(os.environ["NORMAL_WIRE_ORIGIN"]).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write("\n")


if os.environ.get("NORMAL_WIRE_ORIGIN"):
    atexit.register(record)
