import socket
import subprocess

import pytest
from fastapi.testclient import TestClient

from aiddos.api.app import create_app


@pytest.fixture(autouse=True)
def no_external_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Draft API attempted network/DNS/process execution")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


@pytest.fixture
def state_path(tmp_path):
    return tmp_path / "drafts.json"


@pytest.fixture
def client(state_path):
    with TestClient(
        create_app(state_path=state_path),
        base_url="http://localhost",
        raise_server_exceptions=False,
    ) as connection:
        yield connection
