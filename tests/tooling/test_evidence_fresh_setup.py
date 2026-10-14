"""Phase-2 provisioning is opt-in, fresh-only and before serving."""

import json
from types import SimpleNamespace

import pytest
from test_phase1_local import ROOT, local


def test_create_only_evidence_option():
    parser = local().parser()
    assert parser.parse_args(["create", "--workspace", "/new", "--evidence"]).evidence is True
    assert parser.parse_args(["create", "--workspace", "/new"]).evidence is False
    for verb in ("open", "worker"):
        with pytest.raises(SystemExit):
            parser.parse_args([verb, "--workspace", "/old", "--evidence"])


@pytest.mark.parametrize("failure", [False, True])
def test_fresh_provisioning_order_and_failure_preservation(tmp_path, monkeypatch, failure):
    module = local()
    workspace = tmp_path / "new"
    module.new_workspace(workspace)
    for name in ("session.lock", "activity.lock"):
        (workspace / name).touch(mode=0o600)
    module.save_state(workspace, {"format": 1, "root": str(ROOT), "phase": "NEW"})
    owner = module.PersistentPG(workspace)
    calls = []
    monkeypatch.setattr(owner, "create", lambda: calls.append("create"))
    monkeypatch.setattr(owner, "bootstrap", lambda: calls.append("bootstrap"))
    monkeypatch.setattr(module, "PersistentPG", lambda w: owner)
    monkeypatch.setattr(module, "retained_pg", lambda *a: owner)
    monkeypatch.setattr(module, "stop_pg", lambda o: calls.append("stop"))

    class Native:
        def __init__(self, *args):
            pass

        def launch(self, name, argv, extra=None):
            calls.append(argv[-1])
            code = 78 if failure and argv[-1] == "ddospector.evidence.migrate" else 0
            return SimpleNamespace(wait=lambda timeout: code)

        def retire_all(self):
            calls.append("retire")

    monkeypatch.setattr(module, "NativeChildren", Native)
    def servers(*args):
        calls.append("serve")
        return [], "http://127.0.0.1:5175"
    monkeypatch.setattr(module, "launch_servers", servers)
    args = SimpleNamespace(workspace=workspace, command="create", web_port=0, evidence=True)
    if failure:
        with pytest.raises(module.h.Blocked, match="EVIDENCE_MIGRATION_FAILED_DATA_RETAINED"):
            module.serve(args, lambda: True)
    else:
        assert module.serve(args, lambda: True) == 0
    assert calls[:4] == ["create", "bootstrap", "ddospector.runs.migrate",
                         "ddospector.evidence.migrate"]
    assert ("serve" in calls) is not failure
    assert calls[-2:] == ["retire", "stop"]
    assert json.loads((workspace / "workspace.json").read_text())["phase"] == (
        "BLOCKED" if failure else "STOPPED")
    assert owner.socket.is_dir() and owner.journal.is_file()
