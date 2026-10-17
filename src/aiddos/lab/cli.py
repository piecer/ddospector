"""Zero-network deployment configuration CLI."""

import argparse
import os
import stat
import sys
from os import close as _close
from os import fstat as _fstat
from os import open as _open
from os import read as _read

from aiddos.lab import profile


def _preflight(path: str) -> dict:
    """Read one local regular file; publish only after retiring its read-only FD.

    Parent directories are an operator-trusted namespace, not a filesystem sandbox.
    A late close error cannot replace an already determined refusal.
    """
    result = profile.refused("PROFILE_IO_ERROR")
    if not os.path.isabs(path):
        return result
    fd = None
    try:
        fd = _open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
        if stat.S_ISREG(_fstat(fd).st_mode):
            raw = bytearray()
            while len(raw) <= profile.MAX_PROFILE_BYTES:
                chunk = _read(fd, min(4096, profile.MAX_PROFILE_BYTES + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
            result = profile.evaluate(bytes(raw))
    except (OSError, ValueError, UnicodeError):
        result = profile.refused("PROFILE_IO_ERROR")
    finally:
        if fd is not None:
            retiring, fd = fd, None
            try:
                _close(retiring)
            except OSError:
                if result["status"] != "REFUSED":
                    result = profile.refused("PROFILE_IO_ERROR")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m ddospector.lab", allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("template", allow_abbrev=False)
    preflight = commands.add_parser("preflight", allow_abbrev=False)
    preflight.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    if args.command == "template":
        sys.stdout.write(profile.canonical(profile.template()).decode("utf-8") + "\n")
        return 0
    result = _preflight(args.config)
    sys.stdout.write(profile.canonical(result).decode("utf-8") + "\n")
    return 2 if result["status"] == "REFUSED" else 0
