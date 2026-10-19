"""Real operator HTTP ingress; synthetic frozen targets_snapshot interface."""

import asyncio
import threading

from test_chat_tool_runtime_lifecycle import LiveProduct

from aiddos.api.chat_models import encoded


def test_targets_get_closed_fresh_bounded_and_no_model_authority(tmp_path, monkeypatch):
    product = LiveProduct(tmp_path)
    target = dict(
        id="legacy-target-id",
        name="literal 🌍",
        address="Example.COM.",
        kind="SINK",
        status="draft",
        created_at="2026-01-01T00:00:00+00:00",
    )
    value = dict(schema_version=1, draft_revision=4, targets=[target])
    observations = []

    async def snapshot(*, deadline=None, stop=None):
        observations.append(deadline)
        return value

    monkeypatch.setattr(product.runtime.worker, "targets_snapshot", snapshot, raising=False)
    try:
        assert product.request("/api/v1/chat/tools/targets") == (200, value)
        value["draft_revision"] = 5
        assert product.request("/api/v1/chat/tools/targets") == (200, value)
        assert len(observations) == 2 and all(d is not None for d in observations)
        assert (
            product.request("/api/v1/chat/tools/targets?offset=0")[1]["code"]
            == "CHAT_INVALID_REQUEST"
        )
        assert product.request("/api/v1/chat/tools/targets", "POST", {})[0] == 405
        assert len(observations) == 2
        value["targets"].append(dict(target))
        status, failure = product.request("/api/v1/chat/tools/targets")
        assert status != 200 and failure["code"] == "CHAT_STORAGE_ERROR"
        value["targets"] = [
            target
            | dict(
                id=f"t{i:063}",
                name="🌍" * 120,
                address="a" * 63 + "." + "b" * 63 + "." + "c" * 63 + "." + "d" * 61,
            )
            for i in range(100)
        ]
        status, found = product.request("/api/v1/chat/tools/targets")
        assert status == 200 and found == value
        assert len(encoded(found)) <= 128 * 1024
    finally:
        product.close()


def test_targets_inspection_has_no_queue_and_admission_owns_lease(tmp_path, monkeypatch):
    product = LiveProduct(tmp_path)
    entered, release = threading.Event(), threading.Event()

    async def snapshot(*, deadline=None, stop=None):
        entered.set()
        while not release.is_set():
            await asyncio.sleep(0.005)
        return dict(schema_version=1, draft_revision=0, targets=[])

    monkeypatch.setattr(product.runtime.worker, "targets_snapshot", snapshot, raising=False)
    import concurrent.futures

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(product.request, "/api/v1/chat/tools/targets")
            try:
                assert entered.wait(2)
                assert product.request("/api/v1/chat/tools/targets")[1]["code"] == "CHAT_BUSY"
                assert product.request("/api/v1/chat/tools/runtime")[1]["code"] == "CHAT_BUSY"
            finally:
                release.set()
            assert pending.result()[0] == 200
        assert not product.runtime.preparing
    finally:
        release.set()
        product.close()


def test_runtime_metadata_publishes_v2(tmp_path):
    product = LiveProduct(tmp_path)
    try:
        status, value = product.request("/api/v1/chat/tools/runtime")
        assert status == 200 and value["schema_version"] == 2
        assert value["tools"] == ["configuration_read", "agent_profile_update", "target_create"]
    finally:
        product.close()
