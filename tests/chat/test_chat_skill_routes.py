"""Real operator HTTP routes with explicit frozen-interface worker doubles.
No model/session/grant is configured and no actual Skill domain read is claimed.
"""

from copy import deepcopy

import pytest
from test_chat_tool_runtime_lifecycle import LiveProduct

from aiddos.api.catalog import SKILLS_V1
from aiddos.api.chat_models import SAFE_INT, encoded
from aiddos.api.errors import DraftError
from tests.chat.test_chat_skill_models import arguments, full_skill


def summaries(skills):
    return [{k: s[k] for k in ("id", "name", "category", "status", "version")} for s in skills]


def test_operator_detail_is_get_only_and_bounded(tmp_path, monkeypatch):
    product = LiveProduct(tmp_path)
    draft = full_skill(
        arguments(name="🌍" * 120, description="🌍" * 1000, instructions="🌍" * 8000),
        "legacy-domain-id",
    )
    records = deepcopy(SKILLS_V1) + [draft | dict(id=f"s{i:063}") for i in range(100)]
    inventory = dict(schema_version=1, draft_revision=SAFE_INT, skills=summaries(records))
    detail = dict(schema_version=1, draft_revision=SAFE_INT, skill=draft)
    observations = []

    async def listing(*, deadline=None, stop=None):
        observations.append(("list", deadline))
        return inventory

    async def selected(skill_id, *, deadline=None, stop=None):
        observations.append((skill_id, deadline))
        if skill_id == "absent":
            raise DraftError("CHAT_NOT_FOUND")
        return detail

    monkeypatch.setattr(product.runtime.worker, "skills_snapshot", listing, raising=False)
    monkeypatch.setattr(product.runtime.worker, "skill_snapshot", selected, raising=False)
    try:
        assert product.request("/api/v1/chat/tools/skills") == (200, inventory)
        assert len(encoded(inventory)) < 131072 and len(inventory["skills"]) == 103
        assert product.request("/api/v1/chat/tools/skills/legacy-domain-id") == (200, detail)
        assert 32768 < len(encoded(detail)) < 131072
        assert len(observations) == 2 and all(d is not None for _, d in observations)
        for path in (
            "/api/v1/chat/tools/skills?offset=0",
            "/api/v1/chat/tools/skills/legacy-domain-id?x=1",
            "/api/v1/chat/tools/skills/bad%20id",
            "/api/v1/chat/tools/skills/a%2Fb",
            "/api/v1/chat/tools/skills/",
            "/api/v1/chat/tools/skills/" + "x" * 65,
        ):
            assert product.request(path)[1]["code"] == "CHAT_INVALID_REQUEST"
        assert len(observations) == 2
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            assert (
                product.request("/api/v1/chat/tools/skills/legacy-domain-id", method, {})[0] == 405
            )
        assert product.request("/api/v1/chat/tools/skills/absent")[1]["code"] == "CHAT_NOT_FOUND"
        # Correct grammar but different returned identity fails closed.
        assert product.request("/api/v1/chat/tools/skills/other")[1]["code"] == "CHAT_STORAGE_ERROR"
        for template in SKILLS_V1:
            detail["skill"] = deepcopy(template)
            assert product.request("/api/v1/chat/tools/skills/" + template["id"]) == (200, detail)
            detail["skill"]["instructions"]["en"] += "forged"
            assert (
                product.request("/api/v1/chat/tools/skills/" + template["id"])[1]["code"]
                == "CHAT_STORAGE_ERROR"
            )
        inventory["skills"][-1] = inventory["skills"][-2]
        assert product.request("/api/v1/chat/tools/skills")[1]["code"] == "CHAT_STORAGE_ERROR"
    finally:
        product.close()


def test_inspection_no_queue_and_current_runtime_v3(tmp_path, monkeypatch):
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from aiddos.api import chat_tool_models as m

    product = LiveProduct(tmp_path)
    entered, release = threading.Event(), threading.Event()

    async def listing(*, deadline=None, stop=None):
        entered.set()
        while not release.is_set():
            await asyncio.sleep(0.005)
        return dict(schema_version=1, draft_revision=0, skills=summaries(SKILLS_V1))

    monkeypatch.setattr(product.runtime.worker, "skills_snapshot", listing, raising=False)
    try:
        status, value = product.request("/api/v1/chat/tools/runtime")
        assert status == 200 and value["schema_version"] == 3
        assert value["tools"] == [
            "configuration_read",
            "agent_profile_update",
            "target_create",
            "skill_create",
        ]
        assert m.ToolRuntimeV3.model_validate(value).model_dump() == value
        for old in (m.ToolRuntime, m.ToolRuntimeV2):
            with pytest.raises(ValueError):
                old.model_validate(value)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(product.request, "/api/v1/chat/tools/skills")
            try:
                assert entered.wait(2)
                assert product.request("/api/v1/chat/tools/skills")[1]["code"] == "CHAT_BUSY"
                assert (
                    product.request("/api/v1/chat/tools/skills/policy-validation")[1]["code"]
                    == "CHAT_BUSY"
                )
            finally:
                release.set()
            assert pending.result()[0] == 200
        assert not product.runtime.preparing
    finally:
        release.set()
        product.close()
