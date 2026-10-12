"""Startup setting names shared by public and legacy entry points."""

import os


def startup_setting(suffix: str, default: str | None = None) -> str | None:
    """Prefer DDOSPECTOR even when empty; fall back only when absent."""
    preferred = f"DDOSPECTOR_{suffix}"
    if preferred in os.environ:
        return os.environ[preferred]
    return os.environ.get(f"AIDDOS_{suffix}", default)
