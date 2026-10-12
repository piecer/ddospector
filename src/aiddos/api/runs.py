"""OFFLINE admission transport, separate from the legacy LIVE denial."""

from fastapi import APIRouter, Request
from starlette.responses import Response

from aiddos.runs.cancellation import cancel
from aiddos.runs.contracts import identifier, raw_json, request_value, require
from aiddos.runs.lifetime import manager
from aiddos.runs.queries import events, list_runs, page_query
from aiddos.runs.repository import create, get
from aiddos.startup import startup_setting

from .construction import serialized
from .errors import DraftError
from .scenario_store import ScenarioStore


async def disconnected(request):
    while True:
        if (await request.receive())["type"] == "http.disconnect":
            return


def runs_router(drafts) -> APIRouter:
    socket = startup_setting("RUN_DB_SOCKET")
    peer = ScenarioStore(drafts, ticket=None)
    return _compose_runs(peer, socket)


@serialized
def _compose_runs(peer, socket) -> APIRouter:
    router = APIRouter(prefix="/api/v1/offline-runs")

    @router.post("")
    async def create_run(request: Request):
        require(not request.scope.get("query_string"))
        value = request_value(await request.body())
        if value["mode"] == "LIVE":
            raise DraftError("LIVE_NOT_AVAILABLE")
        status, body = await manager().perform(
            request.scope["s02_deadline"],
            lambda op: create(op, socket, peer, value),
            lambda: disconnected(request),
        )
        return Response(body, status_code=status, media_type="application/json")

    @router.get("")
    async def listing(request: Request):
        query = page_query(request.scope.get("query_string", b""))
        status, body = await manager().perform(
            request.scope["s02_deadline"],
            lambda op: list_runs(op, socket, query),
            lambda: disconnected(request),
        )
        return Response(body, status_code=status, media_type="application/json")

    @router.get("/by-request/{request_id}")
    async def by_request(request_id: str, request: Request):
        identifier(request_id)
        require(not request.scope.get("query_string"))
        status, body = await manager().perform(
            request.scope["s02_deadline"],
            lambda op: get(op, socket, request_id, by_request=True),
            lambda: disconnected(request),
        )
        return Response(body, status_code=status, media_type="application/json")

    @router.get("/{run_id}")
    async def detail(run_id: str, request: Request):
        identifier(run_id)
        require(not request.scope.get("query_string"))
        status, body = await manager().perform(
            request.scope["s02_deadline"],
            lambda op: get(op, socket, run_id),
            lambda: disconnected(request),
        )
        return Response(body, status_code=status, media_type="application/json")

    @router.get("/{run_id}/events")
    async def event_page(run_id: str, request: Request):
        identifier(run_id)
        query = page_query(request.scope.get("query_string", b""), events=True)
        status, body = await manager().perform(
            request.scope["s02_deadline"],
            lambda op: events(op, socket, run_id, query),
            lambda: disconnected(request),
        )
        return Response(body, status_code=status, media_type="application/json")

    @router.post("/{run_id}/cancel")
    async def cancel_run(run_id: str, request: Request):
        identifier(run_id)
        require(not request.scope.get("query_string"))
        require(raw_json(await request.body()) == {})
        status, body = await manager().perform(
            request.scope["s02_deadline"],
            lambda op: cancel(op, socket, run_id),
            lambda: disconnected(request),
        )
        return Response(body, status_code=status, media_type="application/json")

    return router
