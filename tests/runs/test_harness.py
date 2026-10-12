"""I0 harness behavior; models are explicitly separate from Docker witnesses."""

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest

from tools import s02_harness as h


class ModelDocker:
    """Stateful daemon model; never a real PG witness."""

    def __init__(self):
        self.calls = []
        self.cid = "a" * 64
        self.volume = "b" * 64
        self.container_present = False
        self.volume_present = False
        self.metadata = None
        self.created = "2099-01-01T00:00:00Z"

    def call(self, *args, timeout=10):
        self.calls.append(args)
        if args[:1] == ("version",):
            return h.Result(0, '"29.1.3"\n', "")
        if args[:1] == ("info",):
            return h.Result(0, json.dumps(tempfile.gettempdir()), "")
        if args[:2] == ("image", "inspect"):
            return h.Result(0, json.dumps(h.IMAGE_ID), "")
        if args[:1] == ("ps",):
            return h.Result(0, self.cid + "\n" if self.container_present else "", "")
        if args[:1] == ("create",):
            assert not self.container_present
            self.created = datetime.now(UTC).isoformat()
            self.container_present = self.volume_present = True
            Path(args[args.index("--cidfile") + 1]).write_text(self.cid)
            labels = dict(args[i + 1].split("=", 1) for i, a in enumerate(args) if a == "--label")
            socket_mount = args[args.index("--mount") + 1]
            source = socket_mount.split("src=", 1)[1].split(",", 1)[0]
            self.metadata = {
                "Id": self.cid,
                "Name": "/" + args[args.index("--name") + 1],
                "Image": h.IMAGE_ID,
                "Created": self.created,
                "Labels": labels,
                "NetworkMode": "none",
                "PortBindings": {},
                "Memory": 512 * 1024**2,
                "PidsLimit": 128,
                "NanoCpus": 2_000_000_000,
                "LogConfig": {"Type": "json-file", "Config": {"max-size": "10m", "max-file": "2"}},
                "Cmd": list(args[args.index(h.IMAGE) + 1 :]),
                "Status": "created",
                "Entrypoint": [args[args.index("--entrypoint") + 1]],
                "Mounts": [
                    {"Type": "bind", "Source": source, "Destination": "/socket", "RW": True},
                    {
                        "Type": "volume",
                        "Name": self.volume,
                        "Destination": "/var/lib/postgresql/data",
                        "RW": True,
                    },
                ],
            }
            return h.Result(0, self.cid + "\n", "")
        if args[:2] == ("container", "inspect"):
            return h.Result(0, json.dumps(self.metadata), "")
        if args[:2] == ("volume", "inspect"):
            if self.volume_present:
                return h.Result(0, json.dumps({"Name": self.volume, "CreatedAt": self.created}), "")
            return h.Result(
                1, "", f"Error response from daemon: get {self.volume}: no such volume\n"
            )
        if args[:1] == ("stop",):
            self.metadata["Status"] = "exited"
            return h.Result(0, self.cid, "")
        if args[:1] == ("rm",):
            self.container_present = False
            return h.Result(0, self.cid, "")
        if args[:2] == ("volume", "rm"):
            self.volume_present = False
            return h.Result(0, self.volume, "")
        raise AssertionError(args)


def test_model_create_receipt_precedes_metadata_and_cleanup(tmp_path):
    backend = ModelDocker()
    owner = h.Harness(tmp_path, backend=backend)
    owner.create()
    assert owner.state == "OWNED"
    events = [json.loads(line) for line in owner.journal.read_text().splitlines()]
    assert [x["event"] for x in events].index("create_result") < [x["event"] for x in events].index(
        "registered"
    )
    assert owner.cidfile.read_text().strip() == backend.cid
    assert owner.volume == {"Name": backend.volume, "CreatedAt": backend.created}
    assert owner.name.split("-")[-1] not in owner.labels.values()
    assert owner.socket.parent.stat().st_mode & 0o777 == 0o700
    assert owner.socket.stat().st_mode & 0o777 == 0o777
    owner.close()
    assert owner.state == "CLEAN"
    assert not backend.container_present and not backend.volume_present
    assert json.loads(owner.journal.read_text().splitlines()[-1])["event"] == "clean"


@pytest.mark.parametrize("timestamp", ["2000-01-01T00:00:00Z", "2099-01-01T00:00:00Z"])
def test_model_refuses_nonfresh_anonymous_volume_before_workload(tmp_path, timestamp):
    backend = ModelDocker()
    original = backend.call

    def fault(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[:2] == ("volume", "inspect"):
            row = json.loads(result.stdout)
            row["CreatedAt"] = timestamp
            return h.Result(0, json.dumps(row), "")
        return result

    backend.call = fault
    owner = h.Harness(tmp_path, backend=backend)
    with pytest.raises(h.Blocked):
        owner.create()
    assert owner.state == "BLOCKED"
    assert not any(a[0] in {"start", "stop", "rm"} for a in backend.calls)


@pytest.mark.parametrize("failure", ["conflict", "lost_ack", "empty_ack", "inspect"])
def test_model_unknown_create_custody_stops_without_adoption(tmp_path, failure):
    backend = ModelDocker()
    original = backend.call
    fired = []

    def fault(*args, **kwargs):
        if args[0] == "create":
            result = original(*args, **kwargs)
            if failure != "inspect":
                fired.append(failure)
                return {
                    "conflict": h.Result(125, "", "Conflict"),
                    "lost_ack": h.Result(-9, "", "", True),
                    "empty_ack": h.Result(0, "", ""),
                }[failure]
            return result
        if args[:2] == ("container", "inspect") and failure == "inspect":
            fired.append(failure)
            return h.Result(1, "", "unavailable")
        return original(*args, **kwargs)

    backend.call = fault
    owner = h.Harness(tmp_path, backend=backend)
    with pytest.raises(h.Blocked):
        owner.create()
    assert fired == [failure]
    before = list(backend.calls)
    with pytest.raises(h.Blocked):
        owner.create()
    with pytest.raises(h.Blocked):
        owner.close()
    assert backend.calls == before
    assert backend.container_present and backend.volume_present
    assert len([a for a in backend.calls if a[0] == "create"]) == 1
    assert not any(a[0] in {"start", "stop", "rm"} for a in backend.calls)


@pytest.mark.parametrize(
    "changed",
    [
        "Id",
        "Name",
        "Labels",
        "Image",
        "NetworkMode",
        "PortBindings",
        "Memory",
        "PidsLimit",
        "NanoCpus",
        "LogConfig",
        "Cmd",
        "Mounts",
        "CreatedAt",
        "attachments",
        "receipt",
        "Created",
    ],
)
def test_model_cleanup_refuses_changed_custody(tmp_path, changed):
    backend = ModelDocker()
    owner = h.Harness(tmp_path, backend=backend).create()
    if changed == "CreatedAt":
        backend.created = "2000-01-01T00:00:00Z"
    elif changed == "attachments":
        original = backend.call

        def attached(*args, **kwargs):
            if args[0] == "ps" and any(a.startswith("volume=") for a in args):
                backend.calls.append(args)
                return h.Result(0, backend.cid + "\n" + "c" * 64 + "\n", "")
            return original(*args, **kwargs)

        backend.call = attached
    elif changed == "receipt":
        owner.receipt = owner.receipt | {"stdout": "c" * 64}
    else:
        backend.metadata[changed] = [] if changed == "Mounts" else "foreign-or-unknown"
    cut = len(backend.calls)
    with pytest.raises(h.Blocked):
        owner.close()
    assert owner.state == "BLOCKED"
    assert not any(a[0] in {"stop", "rm"} or a[:2] == ("volume", "rm") for a in backend.calls[cut:])
    assert backend.container_present and backend.volume_present
    with pytest.raises(h.Blocked):
        owner.close()


def test_real_collision_is_preserved_for_its_separate_fixture_owner(tmp_path):
    sentinel = h.Harness(tmp_path / "sentinel-owner").create()
    try:
        before = sentinel.metadata()
        contender = h.Harness(tmp_path / "contender")
        contender.name = sentinel.name
        contender.labels = dict(sentinel.labels)  # Even all matching labels confer no ownership.
        with pytest.raises(h.Blocked, match="NAME_COLLISION"):
            contender.create()
        contender.close()
        assert contender.cid is None
        after = sentinel.metadata()
        # Docker's Mounts is an unordered metadata collection; compare full rows.
        before["Mounts"].sort(key=lambda row: row["Destination"])
        after["Mounts"].sort(key=lambda row: row["Destination"])
        assert after == before
        assert sentinel.attachments() == [sentinel.cid]
    finally:
        sentinel.close()
    assert sentinel.state == "CLEAN"


def test_context_cleanup_preserves_primary_on_secondary_failure(tmp_path):
    backend = ModelDocker()
    owner = h.Harness(tmp_path, backend=backend)
    primary = ValueError("primary-owned-test-failure")
    with pytest.raises(ValueError) as caught, owner:
        backend.created = "2000-01-01T00:00:00Z"
        raise primary
    assert caught.value is primary
    assert owner.state == "BLOCKED"
    assert backend.container_present and backend.volume_present
    assert any(
        json.loads(x)["event"] == "cleanup_secondary"
        for x in owner.journal.read_text().splitlines()
    )


def test_context_body_failure_cleans_registered_resources(tmp_path):
    backend = ModelDocker()
    owner = h.Harness(tmp_path, backend=backend)
    with pytest.raises(ValueError), owner:
        raise ValueError("primary-owned-test-failure")
    assert owner.state == "CLEAN"
    assert not backend.container_present and not backend.volume_present


def test_real_pg_private_socket_roles_and_restart(owned_pg):
    owner = owned_pg
    try:
        assert owner.ready is True
        with psycopg.connect(**h.connection_parameters(owner.socket)) as connection:
            assert connection.execute("SELECT current_user").fetchone() == ("aiddos_s02",)
        proof = owner.probe("write")
        assert proof["server_major"] == 16
        assert proof["durability"] == ["on", "on", "on"]
        assert proof["identity"] == ["aiddos_s02", "aiddos_s02", None]
        assert proof["runtime"] == [False, False, False, False, 8]
        assert proof.get("owner") == ["aiddos_s02_owner", False, False, False, False]
        assert proof.get("socket_settings") == ["", "/socket", "0777"]
        assert proof.get("connection_cap_enforced") is True
        assert proof["ddl_denied"] is True
        volume = dict(owner.volume)
        owner.restart()
        after = owner.probe("read")
        assert after["value"] == proof["value"] == "i0-probe-not-application"
        assert owner.volume == volume
    except Exception:
        if owner.state == "OWNED":
            owner.call("logs", "--tail", "80", owner.cid)
        raise
    finally:
        owner.close()
    assert owner.state == "CLEAN"


def test_real_subprocess_sanitized_and_reaped_on_timeout(tmp_path, monkeypatch):
    # Marker values are test-owned; do not inspect caller credential values.
    monkeypatch.setenv("PGSERVICE", "test-marker-never-propagate")
    monkeypatch.setenv("PYTHONPATH", "test-marker-never-propagate")
    notices = []
    code = "import os; print('PGSERVICE' in os.environ, 'PYTHONPATH' in os.environ)"
    result = h.run_child([sys.executable, "-c", code], tmp_path, 2, notices.append)
    assert result.stdout.strip() == "False False"
    start = time.monotonic()
    result = h.run_child(
        [sys.executable, "-c", "import time; time.sleep(60)"], tmp_path, 0.1, notices.append
    )
    assert result.timed_out and result.code != 0
    assert time.monotonic() - start < 3
    assert notices[-1]["reaped"] is True
    assert not Path(f"/proc/{notices[-1]['pid']}").exists()


@pytest.mark.parametrize("signum", [signal.SIGHUP, signal.SIGINT, signal.SIGTERM])
def test_real_cli_signal_reaps_process_and_owned_database(tmp_path, signum):
    notices = []
    short = Path(tempfile.mkdtemp(prefix="i0p-"))
    argv = [
        sys.executable,
        str(Path(h.__file__).resolve()),
        "--evidence",
        str(tmp_path),
        "--mode",
        "wait",
    ]
    sent = False
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(h.run_child, argv, short, 45, notices.append)
        while not future.done() and time.monotonic() - started < 30:
            journals = list(tmp_path.glob("*/journal.jsonl"))
            if journals and any('"event": "signal_ready"' in p.read_text() for p in journals):
                receipt = notices[0]
                live = Path(f"/proc/{receipt['pid']}/stat").read_text().rsplit(")", 1)[1]
                assert live.split()[19] == receipt["start_ticks"]
                os.kill(receipt["pid"], signum)
                sent = True
                break
            time.sleep(0.02)
        result = future.result(timeout=45)
    assert sent is True
    assert result.code == 128 + signum and not result.timed_out
    assert time.monotonic() - started < 40
    assert json.loads(result.stdout)["cleanup"] == "CLEAN"
    events = [json.loads(line) for line in journals[0].read_text().splitlines()]
    assert events[-1]["event"] == "clean"
    assert any(e["event"] == "interrupted" and e["signal"] == signum for e in events)
    assert notices[-1]["reaped"]
    assert not Path(f"/proc/{notices[-1]['pid']}").exists()


def test_real_cli_failure_preserves_primary_and_proves_cleanup(tmp_path):
    notices = []
    short = Path(tempfile.mkdtemp(prefix="i0p-"))
    result = h.run_child(
        [
            sys.executable,
            str(Path(h.__file__).resolve()),
            "--evidence",
            str(tmp_path),
            "--mode",
            "fail",
        ],
        short,
        40,
        notices.append,
    )
    assert result.code == 1 and not result.timed_out
    assert json.loads(result.stdout)["primary"] == "I0_EXPECTED_FAILURE"
    journals = list(tmp_path.glob("*/journal.jsonl"))
    assert len(journals) == 1
    events = [json.loads(line) for line in journals[0].read_text().splitlines()]
    assert any(e["event"] == "pg_proof" and e["action"] == "write" for e in events)
    assert any(e["event"] == "container_absent" for e in events)
    assert any(e["event"] == "volume_absence_readback" and e["code"] == 1 for e in events)
    assert events[-1]["event"] == "clean"
    assert notices[-1]["reaped"]
    assert not Path(f"/proc/{notices[-1]['pid']}").exists()


def test_model_cleanup_shared_deadline_stops_new_commands(tmp_path, monkeypatch):
    backend = ModelDocker()
    owner = h.Harness(tmp_path, backend=backend).create()
    ticks = [100.0]
    monkeypatch.setattr(h.time, "monotonic", lambda: ticks[0])
    original = backend.call
    issued = []

    def slow(*args, **kwargs):
        issued.append((ticks[0], kwargs["timeout"]))
        ticks[0] += 4
        return original(*args, **kwargs)

    backend.call = slow
    with pytest.raises(h.Blocked):
        owner.close()
    assert owner.state == "BLOCKED"
    assert all(at < 130 and timeout <= 130 - at for at, timeout in issued)


def test_model_revalidation_latches_custody_loss(tmp_path):
    backend = ModelDocker()
    owner = h.Harness(tmp_path, backend=backend).create()
    backend.metadata["Name"] = "/foreign"
    with pytest.raises(h.Blocked):
        owner.revalidate()
    backend.metadata["Name"] = "/" + owner.name
    before = list(backend.calls)
    with pytest.raises(h.Blocked):
        owner.revalidate()
    with pytest.raises(h.Blocked):
        owner.close()
    assert backend.calls == before


@pytest.mark.parametrize("phase", ["stop", "rm", "volume_rm", "absence"])
def test_model_cleanup_errors_never_retry_or_infer_absence(tmp_path, phase):
    backend = ModelDocker()
    owner = h.Harness(tmp_path, backend=backend).create()
    original = backend.call
    fired = []

    def fault(*args, **kwargs):
        is_target = (
            args[0] == phase
            or (phase == "volume_rm" and args[:2] == ("volume", "rm"))
            or (
                phase == "absence"
                and args[:2] == ("volume", "inspect")
                and not backend.volume_present
            )
        )
        if is_target:
            fired.append(phase)
            backend.calls.append(args)
            return h.Result(1, "", "daemon unavailable")
        return original(*args, **kwargs)

    backend.call = fault
    with pytest.raises(h.Blocked):
        owner.close()
    assert fired == [phase]
    count = len(backend.calls)
    with pytest.raises(h.Blocked):
        owner.close()
    assert len(backend.calls) == count
    assert not any(
        json.loads(x)["event"] == "clean" for x in owner.journal.read_text().splitlines()
    )


def test_runs_fixture_denies_unowned_process_commands():
    with (
        pytest.raises(AssertionError, match="RUNS_PROCESS_REFUSED"),
        subprocess.Popen(["/usr/bin/true"]) as process,
    ):
        process.wait(timeout=2)


def test_db_fixture_refuses_unregistered_endpoint_before_driver(no_unowned_execution):
    with pytest.raises(AssertionError, match="RUNS_DB_REFUSED"):
        no_unowned_execution["validate"]("", h.connection_parameters(Path("/foreign")))
    with pytest.raises(AssertionError, match="RUNS_DB_REFUSED"):
        psycopg.connect(host="/foreign")
    with pytest.raises(AssertionError, match="RUNS_NETWORK_DNS_REFUSED"):
        socket.getaddrinfo("forbidden.invalid", 5432)
    with (
        socket.socket(socket.AF_INET) as connection,
        pytest.raises(AssertionError, match="RUNS_NETWORK_DNS_REFUSED"),
    ):
        connection.connect(("127.0.0.1", 5432))


def test_model_failed_probe_blocks_later_work_but_allows_proven_cleanup(tmp_path, monkeypatch):
    backend = ModelDocker()
    owner = h.Harness(tmp_path, backend=backend).create()
    fired = []

    def failed(*args, **kwargs):
        fired.append(True)
        return h.Result(78, "", '{"blocked":"probe failure"}')

    monkeypatch.setattr(h, "run_child", failed)
    with pytest.raises(h.Blocked):
        owner.probe("write")
    before = list(backend.calls)
    with pytest.raises(h.Blocked):
        owner.probe("write")
    assert fired == [True]
    assert backend.calls == before
    owner.close()
    assert owner.state == "CLEAN"


def test_model_primary_create_error_survives_failed_block_journal(tmp_path, monkeypatch):
    backend = ModelDocker()
    owner = h.Harness(tmp_path, backend=backend)
    original_call = backend.call
    primary = OSError("test create transport failure")

    def fault(*args, **kwargs):
        if args[0] == "create":
            raise primary
        return original_call(*args, **kwargs)

    original_note = owner.note

    def note(event, **data):
        if event == "blocked":
            raise OSError("test secondary journal failure")
        original_note(event, **data)

    backend.call = fault
    monkeypatch.setattr(owner, "note", note)
    with pytest.raises(OSError) as caught:
        owner.create()
    assert caught.value is primary
    assert owner.state == "BLOCKED"


def test_admission_refuses_missing_or_unsupported_prerequisites():
    good = {
        "image_id": h.IMAGE_ID,
        "free_bytes": 1024**3,
        "daemon_free_bytes": 1024**3,
        "docker_ready": True,
        "socket": "/private/socket",
    }
    assert h.admit(good) is None
    for key, bad in [
        ("image_id", "sha256:foreign"),
        ("free_bytes", 1024**3 - 1),
        ("daemon_free_bytes", 1024**3 - 1),
        ("docker_ready", False),
        ("socket", "relative"),
        ("socket", "/x,other"),
        ("socket", "/x y"),
        ("socket", "/x\x00"),
        ("socket", "/" + "é" * 40),
    ]:
        with pytest.raises(h.Blocked):
            h.admit(good | {key: bad})
