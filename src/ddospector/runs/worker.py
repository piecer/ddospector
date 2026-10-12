"""Public CLI entry point delegating to aiddos.runs.worker."""

from aiddos.runs.worker import main

__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
