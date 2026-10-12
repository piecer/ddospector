"""Runs-specific fixtures; the legacy tests/api guard is deliberately untouched."""

import socket
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools import s02_harness as h  # noqa: E402


@pytest.fixture(autouse=True)
def no_unowned_execution(monkeypatch):
    popen = subprocess.Popen
    socket_connect = socket.socket.connect
    pg_connect = psycopg.connect
    endpoints = {}

    def live_owner(endpoint, refusal):
        owner = endpoints.get(endpoint)
        if (
            owner is None
            or owner.state != "OWNED"
            or not owner.ready
            or owner.work_failed
            or owner.cleanup_deadline is not None
        ):
            raise AssertionError(refusal)
        try:
            owner.check_work()
        except h.Blocked:
            raise AssertionError(refusal) from None
        return owner

    def admit_local(owner, action, connector, refusal, *args, **kwargs):
        try:
            return owner._admit_connection(action, connector, *args, **kwargs)
        except h.Blocked:
            raise AssertionError(refusal) from None

    def guarded(argv, *args, **kwargs):
        if h.PROCESS_ARGV.get() != tuple(argv) or kwargs.get("shell", False):
            raise AssertionError("RUNS_PROCESS_REFUSED")
        return popen(argv, *args, **kwargs)

    def no_network(*args, **kwargs):
        raise AssertionError("RUNS_NETWORK_DNS_REFUSED")

    def unix_only(sock, address):
        if sock.family != socket.AF_UNIX or address not in {
            str(Path(endpoint) / ".s.PGSQL.5432") for endpoint in endpoints
        }:
            raise AssertionError("RUNS_NETWORK_DNS_REFUSED")
        refusal = "RUNS_NETWORK_DNS_REFUSED"
        owner = live_owner(str(Path(address).parent), refusal)
        return admit_local(owner, 7, socket_connect, refusal, sock, address)

    def validate(conninfo, kwargs):
        if conninfo or kwargs.get("host") not in endpoints:
            raise AssertionError("RUNS_DB_REFUSED")
        expected = h.connection_parameters(
            Path(kwargs["host"]), user=kwargs.get("user"), database=kwargs.get("dbname")
        )
        actual = {key: value for key, value in kwargs.items() if key != "autocommit"}
        if actual != expected:
            raise AssertionError("RUNS_DB_REFUSED")
        return live_owner(kwargs["host"], "RUNS_DB_REFUSED")

    def connect(conninfo="", **kwargs):
        owner = validate(conninfo, kwargs)
        return admit_local(owner, 5, pg_connect, "RUNS_DB_REFUSED", conninfo, **kwargs)

    def class_connect(cls, conninfo="", **kwargs):
        owner = validate(conninfo, kwargs)
        return admit_local(owner, 6, pg_connect, "RUNS_DB_REFUSED", conninfo, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", guarded)
    monkeypatch.setattr(socket.socket, "connect", unix_only)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.setattr(
        psycopg.Connection,
        "connect",
        classmethod(class_connect),
    )
    return {"validate": validate, "endpoints": endpoints}


@pytest.fixture
def owned_pg(tmp_path, no_unowned_execution):
    """Reusable owned socket/roles. App migration is deliberately a later gate."""
    with h.Harness(tmp_path) as owner:
        owner.bootstrap()
        no_unowned_execution["endpoints"][str(owner.socket)] = owner
        try:
            yield owner
        finally:
            del no_unowned_execution["endpoints"][str(owner.socket)]


@pytest.fixture
def tmp_path(request):
    """Unlike pytest basetemp, retain all I0 model journals across invocations."""
    path = ROOT / "implementation-evidence" / "cases" / (request.node.name + "-" + uuid.uuid4().hex)
    path.mkdir(parents=True)
    return path
