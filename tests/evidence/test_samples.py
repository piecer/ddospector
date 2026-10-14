"""Synthetic fixtures must describe facts, never substitute for an evaluator."""
import hashlib
import importlib
import io
import json
import os
import stat
import subprocess
import sys
from collections import Counter
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from aiddos.evidence.pcap import parse_capture


def samples():
    try:
        return importlib.import_module("aiddos.evidence.samples")
    except ImportError:
        pytest.fail("P2-00 generator is not implemented")


@pytest.mark.parametrize("sample_id,coverage,egress_count", [
    ("complete", "COMPLETE_SYNTHETIC", 10),
    ("violation", "COMPLETE_SYNTHETIC", 9),
    ("unknown", "UNKNOWN", 9),
])
def test_pure_deterministic_sample_pairs(sample_id, coverage, egress_count, monkeypatch):
    module = samples()
    assert module.SAMPLE_IDS == ("complete", "violation", "unknown")

    def no_io(*args, **kwargs):
        pytest.fail("pure generation performed file I/O")

    with monkeypatch.context() as patch:
        patch.setattr("builtins.open", no_io)
        pair = module.make_sample(sample_id)
        again = module.make_sample(sample_id)
    assert pair == again
    assert pair is not again
    assert pair.sample_id == sample_id
    assert pair.coverage == coverage
    assert isinstance(pair.ingress, bytes)
    assert isinstance(pair.egress, bytes)
    assert pair.ingress != pair.egress
    assert b"SYNTHETIC-P2-00:" + sample_id.encode() in pair.ingress
    ingress = parse_capture(io.BytesIO(pair.ingress))
    egress = parse_capture(io.BytesIO(pair.egress))
    assert ingress.packet_count == 10
    assert egress.packet_count == egress_count
    assert ingress.timestamps_ordered and egress.timestamps_ordered
    assert len(ingress.fingerprints) == 9
    assert sorted(count for _, count in ingress.fingerprints) == [1] * 8 + [2]
    left, right = Counter(dict(ingress.fingerprints)), Counter(dict(egress.fingerprints))
    assert set(left) == set(right)  # sets alone must miss the omitted duplicate
    assert sum((left & right).values()) == egress_count
    assert (left == right) == (sample_id == "complete")
    # The first frame is at 24-byte global + 16-byte record header.
    assert pair.ingress[40:52] != pair.egress[40:52]
    assert pair.ingress[62] == 64 and pair.egress[62] == 63
    with pytest.raises(FrozenInstanceError):
        pair.coverage = "poison"
    with pytest.raises(FrozenInstanceError):
        pair.ingress = b"poison"


def test_invalid_sample_id_rejected():
    with pytest.raises(ValueError):
        samples().make_sample("../complete")


def test_recognition_requires_exact_ordered_digest_pair_and_is_unpoisonable():
    module = samples()
    pairs = [module.make_sample(name) for name in module.SAMPLE_IDS]
    hashes = [(hashlib.sha256(p.ingress).hexdigest(), hashlib.sha256(p.egress).hexdigest())
              for p in pairs]
    for pair, (left, right) in zip(pairs, hashes, strict=True):
        found = module.recognize_pair(left, right)
        assert found == pair
        assert module.recognize_pair(right, left) is None
        assert module.recognize_pair(left.upper(), right) is None
        assert module.recognize_pair(left, "0" * 64) is None
        assert module.recognize_pair(left, right + " ") is None
        # Even bypassing frozen setattr cannot poison a later returned object.
        object.__setattr__(found, "coverage", "poison")
        assert module.recognize_pair(left, right) == pair
    for i, (left, _) in enumerate(hashes):
        for j, (_, right) in enumerate(hashes):
            if i != j:
                assert module.recognize_pair(left, right) is None


def run_cli(output, tmp_path):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
           "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
           "PYTHONDONTWRITEBYTECODE": "1", "LC_ALL": "C"}
    return subprocess.run([sys.executable, "-m", "ddospector.evidence.samples",
                           "--output", str(output)], env=env, cwd=tmp_path,
                          capture_output=True, text=True, timeout=10)


def test_public_cli_writes_exactly_six_private_pcaps_and_honest_manifest(tmp_path):
    output = tmp_path / "new-samples"
    result = run_cli(output, tmp_path)
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    files = {path.name for path in output.iterdir()}
    assert files == {f"{name}-{side}.pcap" for name in samples().SAMPLE_IDS
                     for side in ("ingress", "egress")} | {"manifest.json"}
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["source"] == "synthetic"
    assert manifest["generator"] == "ddospector.evidence.samples/P2-00-v1"
    assert manifest["packet_model"] == "TCP data segments; not full TCP/application sessions"
    assert manifest["timestamps"] == "Fixed synthetic timestamps; not measured latency"
    assert manifest["defense_verdict"] is None
    assert len(manifest["samples"]) == 3
    for item in manifest["samples"]:
        pair = samples().make_sample(item["sample_id"])
        assert item["coverage"] == pair.coverage
        expected = {"complete": "SATISFIED", "violation": "VIOLATED", "unknown": "UNKNOWN"}
        assert item["fixture_expectation"] == {
            "label": "Synthetic ground truth only; evaluator must compute from PCAP bytes",
            "criterion": "TCP packet-record multiset correspondence",
            "lower_bound_basis_points": 9500, "upper_bound_basis_points": 10000,
            "expected_outcome": expected[pair.sample_id],
            "expected_matched_records": 10 if pair.sample_id == "complete" else 9,
        }
        for side in ("ingress", "egress"):
            meta = item[side]
            path = output / meta["filename"]
            raw = path.read_bytes()
            assert raw == getattr(pair, side)
            assert meta["size_bytes"] == len(raw)
            assert meta["sha256"] == hashlib.sha256(raw).hexdigest()
            assert meta["packet_count"] == parse_capture(io.BytesIO(raw)).packet_count
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in output.iterdir())
    refused = run_cli(output, tmp_path)
    assert refused.returncode != 0
    assert before == {path.name: path.read_bytes() for path in output.iterdir()}


@pytest.mark.parametrize("kind", ["directory", "file", "symlink", "relative"])
def test_cli_refuses_existing_or_relative_destination_without_writes(tmp_path, kind):
    output = tmp_path / "destination"
    if kind == "directory":
        output.mkdir()
        (output / "caller.txt").write_bytes(b"preserve")
    elif kind == "file":
        output.write_bytes(b"preserve")
    elif kind == "symlink":
        target = tmp_path / "target"
        target.mkdir()
        (target / "caller.txt").write_bytes(b"preserve")
        output.symlink_to(target)
    else:
        output = Path("relative")
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = run_cli(output, tmp_path)
    assert result.returncode != 0
    assert ("absolute" if kind == "relative" else "File exists") in result.stderr
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert not (tmp_path / "relative").exists()


def test_partial_write_failure_keeps_owned_files_without_publishing_manifest(
        tmp_path, monkeypatch, capsys, record_property):
    try:
        cli = importlib.import_module("ddospector.evidence.samples")
    except ImportError:
        pytest.fail("P2-00 CLI is not implemented")
    output = tmp_path / "partial"
    original = os.open
    fault_fired = []

    def fail_second(path, flags, mode=0o777, **kwargs):
        if str(path).endswith("complete-egress.pcap"):
            fault_fired.append(True)
            raise OSError("injected disk failure")
        return original(path, flags, mode, **kwargs)

    caller = tmp_path / "caller.txt"
    caller.write_bytes(b"caller sentinel")
    monkeypatch.setattr(os, "open", fail_second)
    code = cli.main(["--output", str(output)])
    assert code != 0
    assert fault_fired == [True]
    record_property("fault_fired", True)
    record_property("cli_exit", code)
    record_property("retained_root", str(tmp_path))
    # Semantic rebind: failure data now stays in the private sibling, not public
    # output. Original review REDs and the old test are archived unchanged.
    stages = list(tmp_path.glob(".pcap-stage-*"))
    assert len(stages) == 1
    retained = (stages[0] / "complete-ingress.pcap").read_bytes()
    assert retained == samples().make_sample("complete").ingress
    assert not (stages[0] / "manifest.json").exists()
    assert not output.exists()
    assert caller.read_bytes() == b"caller sentinel"
    captured = capsys.readouterr()
    assert not captured.out
    assert "injected disk failure" in captured.err
    assert str(stages[0]) in captured.err


@pytest.mark.parametrize("same_bytes", [False, True], ids=["different-bytes", "same-bytes"])
def test_cli_refuses_completed_capture_substitution(
        tmp_path, monkeypatch, capsys, record_property, same_bytes):
    cli = importlib.import_module("ddospector.evidence.samples")
    output = tmp_path / "output"
    held = tmp_path / "held-original"
    original = cli._write_private
    fired = []

    def replace_completed(*args, **kwargs):
        result = original(*args, **kwargs)
        paths = list(tmp_path.rglob("complete-ingress.pcap"))
        if paths and not fired:
            path = paths[0]
            path.rename(held)
            replacement = held.read_bytes() if same_bytes else b"foreign non-PCAP"
            path.write_bytes(replacement)
            path.chmod(0o600)
            fired.append((path, replacement, held.stat().st_ino, path.stat().st_ino))
        return result

    monkeypatch.setattr(cli, "_write_private", replace_completed)
    code = cli.main(["--output", str(output)])
    assert len(fired) == 1
    path, replacement, old_inode, new_inode = fired[0]
    record_property("fault_fired", True)
    record_property("retained_root", str(tmp_path))
    record_property("cli_exit", code)
    assert old_inode != new_inode
    assert held.read_bytes() == samples().make_sample("complete").ingress
    assert path.read_bytes() == replacement
    assert code != 0
    assert not output.exists()
    assert not (path.parent / "manifest.json").exists()
    captured = capsys.readouterr()
    assert not captured.out
    assert str(path.parent) in captured.err


def test_cli_refuses_public_collision_during_generation(
        tmp_path, monkeypatch, capsys, record_property):
    cli = importlib.import_module("ddospector.evidence.samples")
    output = tmp_path / "output"
    original = cli.make_sample
    fired = []

    def collide(sample_id):
        if not fired:
            # Old CLI created the public root; new CLI must never create it here.
            if output.exists():
                output.rename(tmp_path / "held-original")
            output.mkdir(mode=0o755)
            output.chmod(0o755)
            (output / "caller.txt").write_bytes(b"caller sentinel")
            fired.append(True)
        return original(sample_id)

    monkeypatch.setattr(cli, "make_sample", collide)
    code = cli.main(["--output", str(output)])
    assert fired == [True]
    record_property("fault_fired", True)
    record_property("retained_root", str(tmp_path))
    record_property("cli_exit", code)
    assert code != 0
    assert {p.name for p in output.iterdir()} == {"caller.txt"}
    assert (output / "caller.txt").read_bytes() == b"caller sentinel"
    assert stat.S_IMODE(output.stat().st_mode) == 0o755
    stages = list(tmp_path.glob(".pcap-stage-*"))
    assert len(stages) == 1
    retained = (stages[0] / "complete-ingress.pcap").read_bytes()
    assert retained == samples().make_sample("complete").ingress
    captured = capsys.readouterr()
    assert not captured.out
    assert str(stages[0]) in captured.err
