"""Public independent Guardian process entry point."""

from aiddos.lab.guardian import GuardianError, main, run

__all__ = ["GuardianError", "run", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
