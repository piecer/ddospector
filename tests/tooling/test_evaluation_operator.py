"""Explicit operator wrapper and scoped gate wiring, without external provisioning."""
import json
from types import SimpleNamespace

from test_phase1_local import ROOT, local
from test_phase2_storage_targets import dry_run


def test_evaluate_parser_and_make_targets():
    module = local()
    args = module.parser().parse_args(["evaluate", "--workspace", "/owned",
                                      "--evidence-id", "00000000-0000-4000-8000-000000000001"])
    assert args.evidence_id == "00000000-0000-4000-8000-000000000001"
    command = dry_run("phase2-evaluate")
    assert 'tools/phase1_local.py evaluate --workspace "$PHASE1_WORKSPACE"' in command
    assert '--evidence-id "$PHASE2_EVIDENCE_ID"' in command
    gate = dry_run("test-phase2-evaluation")
    for part in ("test_evidence_postgres.py", "test_evaluation_postgres.py",
                 "tests/evidence", "test_evaluation_operator.py", "junit_family=legacy"):
        assert part in gate
    assert "pytest tests/runs -q" not in gate


def test_operator_uses_retained_custody_and_retires_child(tmp_path, monkeypatch):
    module = local()
    workspace = tmp_path / "owned"
    module.new_workspace(workspace)
    (workspace / "activity.lock").touch(mode=0o600)
    identity = module.h.process_identity()
    module.save_state(workspace, {"phase": "RUNNING", "supervisor": identity})
    calls = []
    owner = SimpleNamespace(socket=workspace / "d/s", metadata=lambda: {"Status": "running"})
    def retained(w, state):
        calls.append("retained")
        assert w == workspace and state["supervisor"] == identity
        return owner
    monkeypatch.setattr(module, "retained_pg", retained)
    class Native:
        def __init__(self, *args):
            pass
        def launch(self, label, argv, env):
            calls.append((label, argv, env))
            return SimpleNamespace(poll=lambda: 0, wait=lambda: 0)
        def retire_all(self):
            calls.append("retired")
    monkeypatch.setattr(module, "NativeChildren", Native)
    args = SimpleNamespace(command="evaluate", workspace=workspace,
                           evidence_id="00000000-0000-4000-8000-000000000001")
    assert module.worker(args, lambda: False) == 0
    assert calls == ["retained", ("evaluate", [str(ROOT / ".venv/bin/python"), "-m",
        "ddospector.evidence.evaluate", "--evidence-id", args.evidence_id],
        {"DDOSPECTOR_RUN_DB_SOCKET": str(owner.socket)}), "retired"]
    assert json.loads((workspace / "workspace.json").read_text())["phase"] == "RUNNING"
