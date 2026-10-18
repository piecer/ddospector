"""Explicit text-chat routes, independent of legacy draft execution."""

from fastapi import APIRouter, Request
from pydantic import ValidationError
from starlette.responses import Response

from .chat_events import EventResponse
from .chat_models import SAFE_INT, EmptyInput, SessionInput, TurnInput, encoded, runtime_view, uid
from .errors import DraftError


def response(value, status=200):
    raw = encoded(value)
    if len(raw) > 1024 * 1024:
        raise DraftError("CHAT_STORAGE_ERROR")
    return Response(raw, status_code=status, media_type="application/json")


def identifier(value):
    try:
        return uid(value)
    except ValueError:
        raise DraftError("CHAT_INVALID_REQUEST") from None


def query(request, key=None):
    items = list(request.query_params.multi_items())
    if not items:
        return None
    if len(items) != 1 or items[0][0] != key:
        raise DraftError("CHAT_INVALID_REQUEST")
    value = items[0][1]
    if not value.isascii() or not value.isdecimal() or len(value) > 16:
        raise DraftError("CHAT_INVALID_REQUEST")
    number = int(value)
    if number > SAFE_INT or (key == "before_sequence" and number < 1):
        raise DraftError("CHAT_INVALID_REQUEST")
    return number


async def body(request, model):
    query(request)
    try:
        return model.model_validate(await request.json())
    except (ValueError, ValidationError):
        raise DraftError("CHAT_INVALID_REQUEST") from None


def chat_router(runtime):
    router = APIRouter(prefix="/api/v1/chat")

    @router.get("/runtime")
    async def get_runtime(request: Request):
        query(request)
        return response(runtime_view(await runtime.metadata_snapshot()))

    @router.post("/sessions")
    async def create_session(request: Request):
        value = await body(request, SessionInput)
        result, status = await runtime.create_session(value)
        return response(result, status)

    @router.get("/sessions")
    async def sessions(request: Request):
        query(request)
        async with runtime.lock:
            return response({"schema_version": 1, "sessions": runtime.storage.sessions()})

    @router.get("/sessions/{session_id}")
    async def history(session_id: str, request: Request):
        identifier(session_id)
        before = query(request, "before_sequence")
        async with runtime.lock:
            session, _ = runtime.storage.session(session_id)
            turns = [
                t
                for t in runtime.storage.turns(session_id)
                if before is None or t["sequence"] < before
            ]
            page = turns[-2:]
            return response(
                {
                    "schema_version": 1,
                    "session": session,
                    "turns": page,
                    "next_before_sequence": page[0]["sequence"] if len(turns) > 2 else None,
                }
            )

    @router.post("/sessions/{session_id}/turns")
    async def accept_turn(session_id: str, request: Request):
        identifier(session_id)
        value = await body(request, TurnInput)
        result, status = await runtime.accept(session_id, value)
        return response(result, status)

    @router.get("/turns/by-request/{request_id}")
    async def turn_request(request_id: str, request: Request):
        query(request)
        identifier(request_id)
        async with runtime.lock:
            return response(runtime.storage.turn(request_id, by_request=True))

    @router.get("/turns/{turn_id}")
    async def turn(turn_id: str, request: Request):
        query(request)
        identifier(turn_id)
        async with runtime.lock:
            return response(runtime.storage.turn(turn_id))

    @router.post("/turns/{turn_id}/cancel")
    async def cancel(turn_id: str, request: Request):
        identifier(turn_id)
        await body(request, EmptyInput)
        return response(await runtime.cancel(turn_id))

    @router.get("/turns/{turn_id}/events")
    async def events(turn_id: str, request: Request):
        identifier(turn_id)
        after = query(request, "after") or 0
        return EventResponse(runtime, await runtime.subscribe(turn_id, after))

    return router
