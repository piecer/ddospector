"""Public ASGI entry point sharing the legacy application object."""

from aiddos.api.app import app, create_app

__all__ = ["app", "create_app"]
