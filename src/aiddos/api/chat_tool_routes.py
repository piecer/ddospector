"""Closed native-tool HTTP companions; no model-accessible authority routes."""

from fastapi import APIRouter, Request
from pydantic import TypeAdapter

from .chat import body, identifier, query, response
from .chat_models import EmptyInput
from .chat_tool_models import DecisionInput, GrantRequest, ReconcileInput, ToolTurnInput
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
        result, status = await runtime.create_grant((await body(request, GrantRequest)).root)
        return response(result, status)

    @router.post("/sessions/{session_id}/tool-turns")
    async def accept(session_id: str, request: Request):
        identifier(session_id)
        result, status = await runtime.accept_tool(session_id, await body(request, ToolTurnInput))
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
        result, status = await runtime.reconcile_tools(await body(request, ReconcileInput))
        return response(result, status)

    return router
