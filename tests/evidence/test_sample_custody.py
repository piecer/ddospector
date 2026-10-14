"""Bounded custody schedules for real CLI/real files, never arbitrary code faults."""
import importlib
import os
import stat
from collections import Counter

import pytest

from aiddos.evidence.samples import make_sample


@pytest.mark.parametrize("kind", ["in-place", "append", "truncate", "symlink",
                                  "mode", "link", "extra-name"])
def test_cli_refuses_changed_private_capture(tmp_path, monkeypatch, capsys, record_property, kind):
    cli = importlib.import_module("ddospector.evidence.samples")
    output = tmp_path / "output"
    caller = tmp_path / "caller.txt"
    caller.write_bytes(b"caller sentinel")
    original = cli._write_private
    fired = []

    def alter_completed(stage, filename, data):
        result = original(stage, filename, data)
        if not fired and filename == "complete-ingress.pcap":
            path = output.parent / stage.name / filename
            fd = stage.files[filename][0]
            assert os.pread(fd, len(data) + 1, 0) == data
            if kind == "symlink":
                path.rename(tmp_path / "held-original")
                path.symlink_to(caller)
            elif kind == "mode":
                path.chmod(0o644)
            elif kind == "link":
                os.link(path, tmp_path / "extra-link")
            elif kind == "extra-name":
                (path.parent / "foreign.txt").write_bytes(b"extra")
            else:
                altered = {"in-place": bytes([data[0] ^ 1]) + data[1:],
                           "append": data + b"extra", "truncate": data[:-1]}[kind]
                path.write_bytes(altered)
            fired.append(path)
        return result

    monkeypatch.setattr(cli, "_write_private", alter_completed)
    code = cli.main(["--output", str(output)])
    assert len(fired) == 1
    record_property("fault_fired", True)
    record_property("retained_root", str(tmp_path))
    record_property("cli_exit", code)
    assert code != 0
    assert not output.exists()
    assert not (fired[0].parent / "manifest.json").exists()
    assert caller.read_bytes() == b"caller sentinel"
    expected = make_sample("complete").ingress
    if kind == "symlink":
        assert fired[0].is_symlink()
        assert (tmp_path / "held-original").read_bytes() == expected
    elif kind == "mode":
        assert stat.S_IMODE(fired[0].stat().st_mode) == 0o644
    elif kind == "link":
        assert fired[0].stat().st_nlink == 2
        assert (tmp_path / "extra-link").read_bytes() == expected
    elif kind == "extra-name":
        assert (fired[0].parent / "foreign.txt").read_bytes() == b"extra"
    else:
        altered = {"in-place": bytes([expected[0] ^ 1]) + expected[1:],
                   "append": expected + b"extra", "truncate": expected[:-1]}[kind]
        assert fired[0].read_bytes() == altered
    captured = capsys.readouterr()
    assert not captured.out
    assert str(fired[0].parent) in captured.err


@pytest.mark.parametrize("kind", ["directory", "capture-replace", "manifest-replace",
                                  "capture-in-place", "manifest-in-place"])
def test_cli_final_checkpoint_refuses_postpublication_changes(
        tmp_path, monkeypatch, capsys, record_property, kind):
    cli = importlib.import_module("ddospector.evidence.samples")
    output = tmp_path / "output"
    held = tmp_path / "held-original"
    original = cli._rename_noreplace
    fired = []

    def after_publication(parent_fd, source, target):
        original(parent_fd, source, target)  # Actual Linux publication first.
        if target != output.name:
            return
        assert output.is_dir()
        if kind == "directory":
            before = {p.name: p.read_bytes() for p in output.iterdir()}
            output.rename(held)
            output.mkdir(mode=0o755)
            output.chmod(0o755)
            (output / "caller.txt").write_bytes(b"caller sentinel")
            fired.append((output, before))
        else:
            filename = "manifest.json" if kind.startswith("manifest") else "complete-ingress.pcap"
            path = output / filename
            before = path.read_bytes()
            if kind.endswith("replace"):
                path.rename(held)
                path.write_bytes(b"foreign replacement")
                path.chmod(0o644)
            else:
                path.write_bytes(bytes([before[0] ^ 1]) + before[1:])
            fired.append((path, before))

    monkeypatch.setattr(cli, "_rename_noreplace", after_publication)
    code = cli.main(["--output", str(output)])
    assert len(fired) == 1
    record_property("fault_fired", True)
    record_property("actual_publication", True)
    record_property("retained_root", str(tmp_path))
    record_property("cli_exit", code)
    assert code != 0
    path, before = fired[0]
    if kind == "directory":
        assert {p.name for p in output.iterdir()} == {"caller.txt"}
        assert (output / "caller.txt").read_bytes() == b"caller sentinel"
        assert stat.S_IMODE(output.stat().st_mode) == 0o755
        assert {p.name: p.read_bytes() for p in held.iterdir()} == before
    elif kind.endswith("replace"):
        assert held.read_bytes() == before
        assert path.read_bytes() == b"foreign replacement"
        assert stat.S_IMODE(path.stat().st_mode) == 0o644
    else:
        assert path.read_bytes() == bytes([before[0] ^ 1]) + before[1:]
    captured = capsys.readouterr()
    assert not captured.out
    assert str(output) in captured.err


@pytest.mark.parametrize("primary_io", [False, True], ids=["close-only", "primary-and-close"])
def test_cli_closes_pins_once_and_preserves_primary_failure(
        tmp_path, monkeypatch, capsys, record_property, primary_io):
    cli = importlib.import_module("ddospector.evidence.samples")
    output = tmp_path / "output"
    real_open, real_close, generate = os.open, os.close, cli._generate
    acquired, closes, caught, fired = [], [], [], []
    io_error, close_error = OSError("primary disk failure"), OSError("ambiguous close failure")

    def opened(path, flags, mode=0o777, **kwargs):
        if primary_io and str(path) == "complete-egress.pcap":
            fired.append("io")
            raise io_error
        fd = real_open(path, flags, mode, **kwargs)
        acquired.append(fd)
        return fd

    def closed(fd):
        closes.append(fd)
        real_close(fd)
        if "close" not in fired:
            fired.append("close")
            raise close_error

    def observed_generate(path):
        try:
            return generate(path)
        except OSError as exc:
            caught.append(exc)
            raise

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", opened)
        patch.setattr(os, "close", closed)
        patch.setattr(cli, "_generate", observed_generate)
        code = cli.main(["--output", str(output)])
    assert fired == (["io", "close"] if primary_io else ["close"])
    assert caught == [io_error if primary_io else close_error]
    assert len(acquired) == (3 if primary_io else 9)
    assert Counter(acquired) == Counter(closes)
    assert all(count == 1 for count in Counter(closes).values())
    for fd in acquired:
        with pytest.raises(OSError):
            os.fstat(fd)
    record_property("fault_fired", str(fired))
    record_property("retained_root", str(tmp_path))
    record_property("cli_exit", code)
    record_property("acquired_and_closed_once", len(acquired))
    assert code != 0
    if primary_io:
        assert not output.exists()
        stages = list(tmp_path.glob(".pcap-stage-*"))
        assert len(stages) == 1
        assert (stages[0] / "complete-ingress.pcap").read_bytes() == make_sample("complete").ingress
        assert not (stages[0] / "manifest.json").exists()
    else:
        assert len(list(output.iterdir())) == 7
    captured = capsys.readouterr()
    assert not captured.out
    assert "ambiguous close failure" in captured.err
    if primary_io:
        assert "sample generation failed: primary disk failure" in captured.err


@pytest.mark.parametrize("unsupported_kind", ["primitive", "platform"])
def test_cli_unsupported_primitive_refuses_before_writes(
        tmp_path, monkeypatch, capsys, record_property, unsupported_kind):
    cli = importlib.import_module("ddospector.evidence.samples")
    fired = []

    def unsupported(*args):
        fired.append(True)
        raise OSError("renameat2 unsupported")

    with monkeypatch.context() as patch:
        if unsupported_kind == "platform":
            patch.setattr(cli.sys, "platform", "unsupported-test-platform")
        patch.setattr(cli, "_rename_noreplace", unsupported)
        code = cli.main(["--output", str(tmp_path / "output")])
    assert fired == ([] if unsupported_kind == "platform" else [True])
    assert code != 0
    assert not list(tmp_path.iterdir())
    captured = capsys.readouterr()
    assert not captured.out
    message = "Linux renameat2" if unsupported_kind == "platform" else "renameat2 unsupported"
    assert message in captured.err
    record_property("unsupported_trigger", unsupported_kind)
    record_property("cli_exit", code)
    record_property("retained_root", str(tmp_path))


def test_actual_linux_noreplace_preserves_empty_destination(tmp_path, record_property):
    cli = importlib.import_module("ddospector.evidence.samples")
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir(mode=0o700)
    destination.mkdir(mode=0o755)
    (source / "sentinel").write_bytes(b"owned source")
    identity = destination.stat().st_ino
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(FileExistsError):
            cli._rename_noreplace(fd, "source", "destination")
        assert destination.stat().st_ino == identity
        assert list(destination.iterdir()) == []
        assert (source / "sentinel").read_bytes() == b"owned source"
        cli._rename_noreplace(fd, "source", "published")
        assert not source.exists()
        assert (tmp_path / "published/sentinel").read_bytes() == b"owned source"
    finally:
        os.close(fd)
    record_property("actual_primitive", "renameat2(RENAME_NOREPLACE)")
    record_property("retained_root", str(tmp_path))


def test_cli_pins_all_anchors_through_final_checkpoint(
        tmp_path, monkeypatch, record_property):
    cli = importlib.import_module("ddospector.evidence.samples")
    original = cli._Stage.validate
    observed = []

    def observe(stage):
        result = original(stage)
        if stage.name == stage.output.name:
            assert len(stage.fds) == 9
            assert len(stage.files) == 7
            for filename, (fd, expected, created) in stage.files.items():
                info = os.fstat(fd)
                assert (info.st_dev, info.st_ino) == (created.st_dev, created.st_ino)
                assert os.pread(fd, len(expected) + 1, 0) == expected
                assert os.stat(filename, dir_fd=stage.dir_fd).st_ino == info.st_ino
            observed.extend(stage.fds)
        return result

    monkeypatch.setattr(cli._Stage, "validate", observe)
    code = cli.main(["--output", str(tmp_path / "output")])
    assert code == 0
    assert len(observed) == 9
    for fd in observed:
        with pytest.raises(OSError):
            os.fstat(fd)
    record_property("final_checkpoint_fired", True)
    record_property("pinned_until_checkpoint", len(observed))
    record_property("retained_root", str(tmp_path))


def test_cli_refuses_replaced_private_root_without_redirecting_writes(
        tmp_path, monkeypatch, capsys, record_property):
    cli = importlib.import_module("ddospector.evidence.samples")
    original = cli.make_sample
    held = tmp_path / "held-original"
    output = tmp_path / "output"
    fired = []

    def replace_private(sample_id):
        if not fired:
            stages = list(tmp_path.glob(".pcap-stage-*"))
            assert len(stages) == 1
            stage = stages[0]
            stage.rename(held)
            stage.mkdir(mode=0o755)
            stage.chmod(0o755)
            (stage / "caller.txt").write_bytes(b"caller sentinel")
            fired.append(stage)
        return original(sample_id)

    monkeypatch.setattr(cli, "make_sample", replace_private)
    code = cli.main(["--output", str(output)])
    assert len(fired) == 1
    assert code != 0
    assert not output.exists()
    assert {p.name for p in fired[0].iterdir()} == {"caller.txt"}
    assert (fired[0] / "caller.txt").read_bytes() == b"caller sentinel"
    assert stat.S_IMODE(fired[0].stat().st_mode) == 0o755
    assert (held / "complete-ingress.pcap").read_bytes() == make_sample("complete").ingress
    assert not (held / "manifest.json").exists()
    assert not capsys.readouterr().out
    record_property("fault_fired", True)
    record_property("cli_exit", code)
    record_property("retained_root", str(tmp_path))
