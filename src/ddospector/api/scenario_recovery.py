"""Public CLI entry point delegating to aiddos.api.scenario_recovery."""

from aiddos.api.scenario_recovery import main

__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
