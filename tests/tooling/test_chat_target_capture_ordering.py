"""Deterministic capture orchestration controls; no product success is synthesized."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/chat"))
import chat_target_capture as capture  # noqa: E402
import test_chat_target_integration as integration  # noqa: E402


def test_runtime_capture_follows_bootstrap_but_precedes_native_admission(tmp_path, monkeypatch):
    events = []

    class Child:
        def stop(self):
            events.append("cleanup")

        def receipt(self):
            return {"cleanup_verified": True}

    class Product:
        captures = []
        child = Child()

        def request(self, path):
            assert path == "/api/v1/chat/tools/runtime"
            events.append("runtime")
            assert "bootstrap" in events, "metadata requires completed bootstrap"
            assert "admit" not in events, "metadata must precede native admission"
            return 200, {"schema_version": 2}

    class Provider:
        requests = []
        opened = closed = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    def bootstrap(_app, _provider):
        events.append("bootstrap")
        return {"HARNESS_ONLY": "session"}

    def grant(_app, _session):
        events.append("grant")
        return {}, {}

    def admit(*_args):
        events.append("admit")
        return {}

    def stop_before_proposal(*_args):
        events.append("proposal-boundary")
        raise AssertionError("HARNESS_ONLY stop before proposal; not producer success")

    monkeypatch.setattr(capture, "CaptureProduct", lambda _: Product())
    monkeypatch.setattr(capture, "ProviderFixture", lambda *a, **k: Provider())
    # Exercise the real setup_plan, including its default grant/admit orchestration.
    monkeypatch.setattr(integration, "session", bootstrap)
    monkeypatch.setattr(integration, "workspace", lambda _: {})
    monkeypatch.setattr(integration.harness, "plan", lambda *a, **k: ())
    monkeypatch.setattr(integration, "target_grant", grant)
    monkeypatch.setattr(integration, "admit", admit)
    monkeypatch.setattr(capture, "proposal", stop_before_proposal)
    output = tmp_path / "capture"
    assert capture.main(["--output", str(output)]) == 1
    result = json.loads((output / "capture-result.json").read_text())
    assert events == ["bootstrap", "runtime", "grant", "admit", "proposal-boundary", "cleanup"]
    assert "HARNESS_ONLY stop before proposal" in result["error"]
    assert result["verdict"] == "HOLD"
    assert result["synthetic_provider_requests"] == result["real_model_requests"] == 0
    assert result["cleanup"]["cleanup_verified"] is True


def test_browser_target_setup_reads_availability_before_selecting_or_consent():
    # Execute the actual fixture setup block, not a duplicate sequence. This is
    # a deterministic harness control; the component and Chromium gates are separate.
    source = (ROOT / "web/e2e/chat-tools.case.ts").read_text()
    start = source.index("      if (targetCase) {", source.index("const prompt ="))
    end = source.index('      await page.getByTestId("chat-tools-toggle").check();', start)
    block = source[start:end]
    script = r'''
const assert = require('node:assert/strict');
const events = [];
let available = false, selected = 'agent_v1';
const targetCase = true;
const targetLabel = '정확히 다음 메시지만: 대상 읽기와 대상 생성 제안 1건에 동의합니다. '
  + '저장 권한이 아니며 정확한 제안에 별도 승인이 필요합니다.';
const scope = {
  kind: 'scope',
  async selectOption(value) {
    events.push('select');
    // The shipped change handler rejects target before availability.
    if (available) selected = value;
  },
};
const toggle = {kind: 'toggle'};
const page = {
  getByTestId(id) {
    assert.ok(['chat-tool-scope', 'chat-tools-toggle'].includes(id));
    return id === 'chat-tool-scope' ? scope : toggle;
  },
  getByRole(role, {name}) {
    if (role === 'button') {
      assert.equal(name, '도구 사용 가능 여부 / 차단 읽기');
      return {async click() { events.push('availability'); available = true; }};
    }
    assert.equal(role, 'option'); assert.equal(name, '대상 생성');
    return {kind: 'target-option'};
  },
};
const requests = [];
function expect(actual) {
  return {
    async toHaveValue(value) {
      assert.equal(selected, value);
      if (value === 'target_create_v2') events.push('target-value');
    },
    async toHaveAccessibleName(value) {
      assert.equal(value, actual === scope ? '도구 허용 범위' : targetLabel);
      if (actual === toggle) {
        assert.equal(selected, 'target_create_v2'); events.push('target-label');
      }
    },
    async toBeEnabled() {
      assert.equal(actual.kind, 'target-option');
      assert.equal(available, true); events.push('enabled');
    },
    toEqual(value) { assert.deepEqual(actual, value); },
    not: {async toBeChecked() { assert.equal(actual, toggle); events.push('unchecked'); }},
  };
}
(async () => {
BLOCK
assert.equal(selected, 'target_create_v2', 'target setup must not silently retain Agent scope');
assert.deepEqual(events, [
  'availability', 'enabled', 'select', 'target-value', 'target-label', 'unchecked',
]);
})().catch(error => {console.error(error); process.exitCode = 1;});
'''.replace("BLOCK", block)
    result = subprocess.run(
        ["/usr/bin/node", "-e", script], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stdout + result.stderr
