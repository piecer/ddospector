"""Real public CLI, bounded local FD lifetime, and child audit regressions."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from aiddos.lab import cli, profile

ROOT = Path(__file__).resolve().parents[2]
SENTINEL = "PRIVATE_SENTINEL_DO_NOT_DISCLOSE"
TEMPLATE_SHA = "7c3c1e45082eb3870ccda5bb10566645da712a2fae31f6985202b3d7bd776b57"
FILLED_SHA = "02517fd83b442469510ac46fe420329e9e8e4db6c8b7e6a479bc82888f01ca0d"


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def valid_bytes():
    value = profile.template()
    value["target"].update(connect_ipv4="127.0.0.1", port=8080, scheme="http",
                           http_host="Example.test", path="/health?check=1")
    value["source"].update(bind_ipv4="127.0.0.1", interface="lo")
    value["expected"]["http_status"] = 200
    return wire(value)


def refusal(code):
    return {"schema_version": 1, "status": "REFUSED", "code": code}


def accepted():
    return {"schema_version": 1, "status": "CONFIG_VALID_NO_NETWORK",
            "profile_sha256": FILLED_SHA, "network_io_performed": False,
            "site_verified": False, "baseline_execution_supported": False}


def child(tmp_path, arguments, *, audited=True):
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "TMPDIR": str(tmp_path),
           "PYTHONPATH": str(ROOT / "src"), "PYTHONNOUSERSITE": "1",
           "PYTHONDONTWRITEBYTECODE": "1"}
    receipt = tmp_path / "audit.json"
    command = ([str(ROOT / "tests/lab/cli_audit_child.py"), str(receipt), str(ROOT)]
               if audited else ["-m", "ddospector.lab"])
    result = subprocess.run([sys.executable, *command, *arguments], cwd=ROOT, env=env,
                            capture_output=True, timeout=5, check=False)
    observation = json.loads(receipt.read_text()) if audited else None
    return result, observation


def assert_zero_network(observation):
    assert observation["observer_installed_before_product_import"] is True
    assert observation["counts"] == {
        "socket_creation": 0, "resolver": 0, "connect": 0, "child_launch": 0,
    }
    assert observation["events"] == []
    assert len(observation["origins"]) == 5
    assert all(Path(p).is_relative_to(ROOT / "src") for p in observation["origins"].values())


@pytest.mark.parametrize("audited", [False, True])
def test_real_template_canonical_no_network(tmp_path, audited):
    result, observation = child(tmp_path, ["template"], audited=audited)
    assert result.returncode == 0
    assert result.stderr == b""
    assert result.stdout.endswith(b"\n") and result.stdout.count(b"\n") == 1
    assert len(result.stdout) == 383
    assert hashlib.sha256(result.stdout[:-1]).hexdigest() == TEMPLATE_SHA
    assert result.stdout == wire(json.loads(result.stdout)) + b"\n"
    if audited:
        assert_zero_network(observation)


@pytest.mark.parametrize("control,category,event", [
    ("@socket", "socket_creation", "socket.__new__"),
    ("@resolver", "resolver", "socket.getaddrinfo"),
    ("@connect", "connect", "socket.connect"),
    ("@child", "child_launch", "subprocess.Popen"),
])
def test_observer_positive_controls_veto_before_effect(tmp_path, control, category, event):
    result, observation = child(tmp_path, [control])
    assert result.returncode == 0 and result.stdout == result.stderr == b""
    assert observation["control_blocked"] is True
    assert observation["events"] == [event]
    assert observation["counts"][category] == 1
    assert sum(observation["counts"].values()) == 1
    assert observation["origins"] == {}


@pytest.mark.parametrize("args", [[], ["execute"], ["template", "--execute"],
                                  ["preflight"], ["preflight", "--config", "/x", "--execute"],
                                  ["preflight", "--conf", "/x"]])
def test_unknown_or_missing_arguments_are_usage_errors(tmp_path, args):
    result, observation = child(tmp_path, args)
    assert result.returncode == 2
    assert result.stdout == b""
    assert b"usage:" in result.stderr
    assert b"Traceback" not in result.stderr
    assert_zero_network(observation)


@pytest.mark.parametrize("case,code", [
    ("valid", None), ("invalid", "INVALID_PROFILE"),
    ("template", "SITE_CONFIGURATION_REQUIRED"), ("oversize", "PROFILE_TOO_LARGE"),
    ("missing", "PROFILE_IO_ERROR"), ("relative", "PROFILE_IO_ERROR"),
])
@pytest.mark.parametrize("audited", [False, True])
def test_real_preflight_exact_envelope_preserves_caller(tmp_path, case, code, audited):
    path = tmp_path / (SENTINEL + ".json")
    raw = {"valid": valid_bytes(), "invalid": b'{"' + SENTINEL.encode() + b'":0}',
           "template": wire(profile.template()), "oversize": b"x" * 16385}.get(case, b"")
    if case != "missing":
        path.write_bytes(raw)
    before = path.stat() if path.exists() else None
    config = "relative/" + SENTINEL if case == "relative" else str(path)
    result, observation = child(tmp_path, ["preflight", "--config", config], audited=audited)
    assert result.returncode == (2 if code else 0)
    assert result.stdout == wire(refusal(code) if code else accepted()) + b"\n"
    assert result.stderr == b""
    assert SENTINEL.encode() not in result.stdout + result.stderr
    if before:
        after = path.stat()
        assert (before.st_ino, before.st_mode, before.st_size, before.st_mtime_ns) == (
            after.st_ino, after.st_mode, after.st_size, after.st_mtime_ns)
        assert path.read_bytes() == raw
    else:
        assert not path.exists()
    if audited:
        assert_zero_network(observation)
        assert observation["exit"] == result.returncode


@pytest.mark.parametrize("size,code", [(16384, None), (16385, "PROFILE_TOO_LARGE"),
                                      (20000, "PROFILE_TOO_LARGE")])
def test_partial_reads_spend_one_cap_plus_one_budget(tmp_path, monkeypatch, capsys, size, code):
    path = tmp_path / "profile.json"
    raw = valid_bytes()
    path.write_bytes(raw + b" " * (size - len(raw)))
    real_read = os.read
    requests, received = [], []

    def partial(fd, count):
        requests.append(count)
        result = real_read(fd, min(count, 117))
        received.append(len(result))
        assert sum(received) <= 16385
        return result

    monkeypatch.setattr(cli, "_read", partial)
    assert cli.main(["preflight", "--config", str(path)]) == (2 if code else 0)
    capture = capsys.readouterr()
    assert capture.out.encode() == wire(refusal(code) if code else accepted()) + b"\n"
    assert capture.err == ""
    assert len(requests) > 1 and sum(received) == min(size, 16385)
    consumed = 0
    for count, amount in zip(requests, received, strict=True):
        assert 0 < count <= 16385 - consumed
        consumed += amount


@pytest.mark.parametrize("kind", ["fifo", "directory", "symlink", "device-mode"])
def test_nonregular_and_symlink_refused_before_read(tmp_path, monkeypatch, capsys, kind):
    import stat
    from types import SimpleNamespace

    target = tmp_path / "target"
    target.write_bytes(valid_bytes())
    path = tmp_path / "input"
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    elif kind == "symlink":
        path.symlink_to(target)
    else:
        # No device is opened: a real ordinary FD exercises the device-mode fstat branch.
        path.write_bytes(valid_bytes())
    opened, reads, stats, closed = [], [], [], []

    def checked_open(name, flags):
        assert flags & os.O_NONBLOCK and flags & os.O_NOFOLLOW
        assert flags & os.O_ACCMODE == os.O_RDONLY
        fd = os.open(name, flags)
        opened.append(fd)
        return fd

    def checked_stat(fd):
        stats.append(fd)
        value = os.fstat(fd)
        return SimpleNamespace(st_mode=stat.S_IFCHR) if kind == "device-mode" else value

    def no_read(fd, count):
        reads.append(fd)
        raise AssertionError("nonregular read")

    def close(fd):
        closed.append(fd)
        os.close(fd)

    monkeypatch.setattr(cli, "_open", checked_open)
    monkeypatch.setattr(cli, "_fstat", checked_stat)
    monkeypatch.setattr(cli, "_read", no_read)
    monkeypatch.setattr(cli, "_close", close)
    assert cli.main(["preflight", "--config", str(path)]) == 2
    capture = capsys.readouterr()
    assert capture.out.encode() == wire(refusal("PROFILE_IO_ERROR")) + b"\n"
    assert capture.err == ""
    assert reads == []
    assert len(opened) == (0 if kind == "symlink" else 1)
    assert closed == opened == stats
    assert target.read_bytes() == valid_bytes()
    assert path.is_symlink() if kind == "symlink" else path.exists()


@pytest.mark.parametrize("case,primary", [
    ("valid", None), ("oversize", "PROFILE_TOO_LARGE"), ("invalid", "INVALID_PROFILE"),
    ("template", "SITE_CONFIGURATION_REQUIRED"), ("fstat", "PROFILE_IO_ERROR"),
    ("read", "PROFILE_IO_ERROR"),
])
@pytest.mark.parametrize("close_fails", [False, True])
def test_close_matrix_retains_primary_until_one_final_envelope(
    tmp_path, monkeypatch, capsys, case, primary, close_fails,
):
    import fcntl

    path = tmp_path / (SENTINEL + ".json")
    raw = {"oversize": b"x" * 16385, "invalid": SENTINEL.encode(),
           "template": wire(profile.template())}.get(case, valid_bytes())
    path.write_bytes(raw)
    opened, closed, slots, prepublication, fired = [], [], [], [], []
    operations = []

    def failure(label):
        fired.append(label)
        error = OSError(SENTINEL + label)
        error.add_note(SENTINEL + "_NOTE")
        raise error

    def open_fd(name, flags):
        fd = os.open(name, flags)
        opened.append(fd)
        assert fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
        assert not os.get_inheritable(fd)
        return fd

    def fstat(fd):
        operations.append("fstat")
        if case == "fstat":
            failure("fstat")
        return os.fstat(fd)

    def read(fd, count):
        operations.append("read")
        if case == "read":
            failure("read")
        return os.read(fd, count)

    def close(fd):
        closed.append(fd)
        slots.append(sys._getframe(1).f_locals["fd"])
        prepublication.append(capsys.readouterr())
        os.close(fd)  # Ambiguous failure occurs after actual retirement; never retry it.
        if close_fails:
            failure("close")

    monkeypatch.setattr(cli, "_open", open_fd)
    monkeypatch.setattr(cli, "_fstat", fstat)
    monkeypatch.setattr(cli, "_read", read)
    monkeypatch.setattr(cli, "_close", close)
    exit_code = cli.main(["preflight", "--config", str(path)])
    capture = capsys.readouterr()
    assert len(opened) == 1 and closed == opened
    assert fired == ([case] if case in ("fstat", "read") else []) + (
        ["close"] if close_fails else [])
    assert operations[0] == "fstat"
    if case == "fstat":
        assert operations == ["fstat"]
    elif case == "read":
        assert operations == ["fstat", "read"]
    assert all(item.out == item.err == "" for item in prepublication)
    code = primary or ("PROFILE_IO_ERROR" if close_fails else None)
    assert exit_code == (2 if code else 0)
    assert capture.out.encode() == wire(refusal(code) if code else accepted()) + b"\n"
    assert capture.err == ""
    assert SENTINEL not in capture.out + capture.err
    assert slots == [None]
    with pytest.raises(OSError):
        os.fstat(opened[0])
    assert path.read_bytes() == raw


def test_open_failure_never_closes_and_hides_notes(tmp_path, monkeypatch, capsys):
    fired, closed = [], []

    def fail_open(*args):
        fired.append("open")
        error = OSError(SENTINEL)
        error.add_note(SENTINEL + "_NOTE")
        raise error

    monkeypatch.setattr(cli, "_open", fail_open)
    monkeypatch.setattr(cli, "_close", lambda fd: closed.append(fd))
    assert cli.main(["preflight", "--config", str(tmp_path / SENTINEL)]) == 2
    capture = capsys.readouterr()
    assert fired == ["open"] and closed == []
    assert capture.out.encode() == wire(refusal("PROFILE_IO_ERROR")) + b"\n"
    assert capture.err == "" and SENTINEL not in capture.out


def test_make_collects_lab_in_scoped_default_and_ruff_targets():
    def dry_run(*targets):
        result = subprocess.run(["make", "-n", *targets], cwd=ROOT, capture_output=True,
                                text=True, timeout=5, check=False)
        assert result.returncode == 0, result.stderr
        return result.stdout

    scoped = dry_run("test-phase3-config")
    assert "pytest tests/lab -q" in scoped
    assert "pytest tests/lab -q" in dry_run("test")
    lint = dry_run("lint")
    ruff = next(line for line in lint.splitlines() if "ruff check" in line)
    assert "tests/lab" in ruff.split()


@pytest.mark.parametrize("raw", [b'"\xff"', b'{"x":NaN}',
                                 b'[' * 1500 + b']' * 1500, b'{"x":"\\ud800"}'],
                         ids=["utf8", "nan", "recursion", "surrogate"])
def test_real_cli_decoder_failures_are_private_refusals(tmp_path, raw):
    path = tmp_path / SENTINEL
    path.write_bytes(raw)
    result, observation = child(tmp_path, ["preflight", "--config", str(path)])
    assert result.returncode == 2 and result.stderr == b""
    assert result.stdout == wire(refusal("INVALID_PROFILE")) + b"\n"
    assert_zero_network(observation)


@pytest.mark.parametrize("kind", ["fifo", "symlink", "directory"])
def test_real_cli_nonregular_returns_without_blocking(tmp_path, kind):
    path = tmp_path / SENTINEL
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    else:
        target = tmp_path / "regular"
        target.write_bytes(valid_bytes())
        path.symlink_to(target)
    result, observation = child(tmp_path, ["preflight", "--config", str(path)])
    assert result.returncode == 2 and result.stderr == b""
    assert result.stdout == wire(refusal("PROFILE_IO_ERROR")) + b"\n"
    assert_zero_network(observation)
