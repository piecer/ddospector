"""Producer fixture capture and callable/JSONL oracle checks (no browser)."""

import hashlib
import io
import json
from copy import deepcopy
from pathlib import Path

import pytest
from scenario_producer import canonical, generate_samples, main, producer_oracle

from aiddos.api.scenarios import ScenarioVersion


def test_samples_are_real_serialized_api_outputs_with_source_bound_receipts(tmp_path):
    output = tmp_path / "samples"
    receipt = generate_samples(output)
    assert json.loads((output / "receipt.json").read_bytes()) == receipt
    assert receipt["sample_count"] == len(receipt["samples"]) == 12
    assert len({s["file"] for s in receipt["samples"]}) == 12
    assert sorted(p.name for p in tmp_path.iterdir()) == ["samples"]
    for sample in receipt["samples"]:
        raw = (output / sample["file"]).read_bytes()
        assert len(raw) == sample["bytes"]
        assert hashlib.sha256(raw).hexdigest() == sample["sha256"]
        value = json.loads(raw)
        records = (
            [value["scenario"]]
            if sample["kind"] == "mutation"
            else value["versions"]
            if sample["kind"] == "history"
            else value["items"]
            if sample["kind"] == "page"
            else []
        )
        for record in records:
            assert ScenarioVersion.model_validate(record).model_dump() == record
            assert producer_oracle(canonical({"kind": "version", "value": record})) == {
                "accepted": True
            }
        if sample["kind"] == "mutation":
            assert value["scenario"]["definition"] == sample["request"]["definition"]
            assert value["revision"] == sample["request"]["revision"] + 1
    root = Path(__file__).resolve().parents[2]
    assert receipt["producer_origin"] == str(root / "src/aiddos/api/app.py")
    assert all(
        hashlib.sha256((root / p).read_bytes()).hexdigest() == h
        for p, h in receipt["source_manifest"].items()
    )
    ack = json.loads((output / "replay-update.json").read_bytes())
    history = json.loads((output / "history-after-concurrent.json").read_bytes())
    assert ack["scenario"] in history["versions"]
    assert ack["scenario"] != history["versions"][-1]
    assert history["revision"] >= ack["revision"]
    with pytest.raises(FileExistsError):
        generate_samples(output)


def test_oracle_accepts_exact_producer_model_and_rejects_raw_numeric_aliases():
    from scenario_producer import definition

    value = definition([{"id": "dut"}, {"id": "sink"}])
    valid = canonical({"kind": "definition", "value": value})
    assert producer_oracle(valid) == {"accepted": True}
    for raw in (
        valid.replace(b'"ip_version":4', b'"ip_version":4.0'),
        valid.replace(b'"ip_version":4', b'"ip_version":4e0'),
        valid.replace(b'"name":', b'"name":"duplicate","\\u006eame":'),
        b"{}",
        b"[]",
        b"\xff",
        b"NaN",
    ):
        assert producer_oracle(raw) == {"accepted": False}
    changed = deepcopy(value)
    changed["stop_conditions"]["management_loss"] = 1
    assert producer_oracle(canonical({"kind": "definition", "value": changed})) == {
        "accepted": False
    }


def test_oracle_cli_reads_one_result_per_jsonl_input(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["scenario_producer.py", "--oracle"])
    raw = b'{"kind":"state","value":{"format_version":1,"revision":0,"scenarios":[]}}\n{}\n'
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(raw)))
    main()
    assert [json.loads(line) for line in capsys.readouterr().out.splitlines()] == [
        {"accepted": True},
        {"accepted": False},
    ]
