"""Closed native-tool HTTP companions; no model-accessible authority routes."""

from fastapi import APIRouter, Request
from pydantic import TypeAdapter

from . import chat_scenario_models as scenario
from .chat import body, identifier, query, response
from .chat_models import EmptyInput
from .chat_tool_models import DecisionInput, GrantRequest, ReconcileInput, ToolTurnInput
from .encoding import strict_json
from .errors import DraftError
from .validation import Identifier


def tool_router(runtime):
    router = APIRouter(prefix="/api/v1/chat")

    @router.get("/tools/runtime")
    async def metadata(request: Request):
        query(request)
        return response(await runtime.tools_runtime())

    @router.get("/tools/targets")
    async def targets(request: Request):
        query(request)
        return response(await runtime.tools_targets())

    @router.get("/tools/scenarios/state")
    async def scenario_state(request: Request):
        query(request)
        return response(await runtime.tools_scenario_state())

    @router.get("/tools/skills")
    async def skills(request: Request):
        query(request)
        return response(await runtime.tools_skills())

    @router.get("/tools/skills/{skill_id:path}")
    async def skill(skill_id: str, request: Request):
        query(request)
        try:
            TypeAdapter(Identifier).validate_python(skill_id)
        except ValueError:
            raise DraftError("CHAT_INVALID_REQUEST") from None
        return response(await runtime.tools_skills(skill_id))

    @router.post("/tool-grants")
    async def grant(request: Request):
        query(request)
        raw = await request.body()
        try:
            value = strict_json(raw)
            if isinstance(value, dict) and value.get("schema_version") == 4:
                checked = scenario.GrantInputV4.model_validate(
                    scenario.decode_raw("GrantInputV4", raw)
                )
            else:
                checked = GrantRequest.model_validate(value).root
        except ValueError:
            raise DraftError("CHAT_INVALID_REQUEST") from None
        result, status = await runtime.create_grant(checked)
        return response(result, status)

    @router.post("/sessions/{session_id}/tool-turns")
    async def accept(session_id: str, request: Request):
        identifier(session_id)
        value = await body(request, ToolTurnInput)
        async with runtime.lock:
            is_scenario = runtime.ledger.grant(value.grant_id)["schema_version"] == 4
        accept = runtime._accept_scenario_tool if is_scenario else runtime.accept_tool
        result, status = await accept(session_id, value)
        return response(result, status)

    @router.get("/turns/{turn_id}/tools")
    async def transcript(turn_id: str, request: Request):
        identifier(turn_id)
        query(request)
        async with runtime.lock:
            return response(runtime.ledger.transcript(turn_id))

    @router.post("/tool-calls/{call_id}/decision")
    async def decide(call_id: str, request: Request):
        identifier(call_id)
        query(request)
        async with runtime.lock:
            call = runtime.ledger.call(call_id)
            is_scenario = runtime.ledger.grant(call["grant_id"])["schema_version"] == 4
        if is_scenario:
            try:
                value = scenario.DecisionInput.model_validate(
                    scenario.decode_raw("DecisionInput", await request.body())
                )
            except ValueError:
                raise DraftError("CHAT_INVALID_REQUEST") from None
            result, status = await runtime._decide_scenario_tool(call_id, value)
        else:
            result, status = await runtime.decide_tool(call_id, await body(request, DecisionInput))
        return response(result, status)

    @router.get("/tool-grants/by-request/{request_id}")
    async def grant_request(request_id: str, request: Request):
        identifier(request_id)
        query(request)
        async with runtime.lock:
            return response(runtime.ledger.grant(request_id, by_request=True))

    @router.post("/tool-grants/{grant_id}/revoke")
    async def revoke(grant_id: str, request: Request):
        identifier(grant_id)
        await body(request, EmptyInput)
        return response(await runtime.revoke_grant(grant_id))

    @router.get("/tools/fence")
    async def fence(request: Request):
        query(request)
        return response(await runtime.tool_fence())

    @router.post("/tools/reconcile")
    async def reconcile(request: Request):
        query(request)
        raw = await request.body()
        try:
            value = strict_json(raw)
            if isinstance(value, dict) and value.get("schema_version") == 4:
                checked = scenario.ReconcileInputV4.model_validate(
                    scenario.decode_raw("ReconcileInputV4", raw)
                )
                reconcile = runtime._reconcile_scenario_tools
            else:
                checked = ReconcileInput.model_validate(value)
                reconcile = runtime.reconcile_tools
        except ValueError:
            raise DraftError("CHAT_INVALID_REQUEST") from None
        result, status = await reconcile(checked)
        return response(result, status)

    return router
