"""Public CLI entry point delegating to aiddos.runs.migrate."""

from aiddos.runs.migrate import main

__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
