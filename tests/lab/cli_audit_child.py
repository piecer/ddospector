"""Harness only: install an audit veto before importing the public product CLI."""

import json
import runpy
import sys
from pathlib import Path


class ForbiddenEffect(BaseException):
    pass


def main():
    receipt, root, *arguments = sys.argv[1:]
    counts = dict.fromkeys(("socket_creation", "resolver", "connect", "child_launch"), 0)
    events = []

    def observe(event, args):
        category = None
        if event == "socket.__new__":
            category = "socket_creation"
        elif event.startswith("socket."):
            category = "connect" if event == "socket.connect" else "resolver"
        elif event in ("subprocess.Popen", "os.system", "os.fork", "os.forkpty",
                       "os.posix_spawn", "os.exec", "os.spawn"):
            category = "child_launch"
        if category is not None:
            counts[category] += 1
            events.append(event)
            raise ForbiddenEffect(event)

    sys.addaudithook(observe)
    exit_code = 0
    origins = {}
    control_blocked = False
    try:
        if arguments and arguments[0].startswith("@"):
            import socket
            import subprocess

            try:
                match arguments[0]:
                    case "@socket":
                        socket.socket()
                    case "@resolver":
                        socket.getaddrinfo("invalid.example", 80)
                    case "@connect":
                        # Synthetic audit-boundary control: no socket or dial is created.
                        sys.audit("socket.connect", None, ("127.0.0.1", 1))
                    case "@child":
                        subprocess.run([sys.executable, "-c", "raise SystemExit(99)"], check=True)
                    case _:
                        raise AssertionError("unknown harness control")
            except ForbiddenEffect:
                control_blocked = True
            assert control_blocked
        else:
            sys.argv = ["ddospector.lab", *arguments]
            try:
                runpy.run_module("ddospector.lab", run_name="__main__")
            except SystemExit as error:
                exit_code = error.code
            for name in ("aiddos", "ddospector", "aiddos.lab.profile", "aiddos.lab.cli",
                         "ddospector.lab"):
                origin = Path(sys.modules[name].__file__).resolve()
                assert origin.is_relative_to(Path(root) / "src"), str(origin)
                origins[name] = str(origin)
    finally:
        Path(receipt).write_text(json.dumps({"counts": counts, "events": events,
            "origins": origins, "control_blocked": control_blocked,
            "exit": exit_code, "observer_installed_before_product_import": True}) + "\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
