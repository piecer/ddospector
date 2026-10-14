"""Paired evidence transport. No parsing, evaluation or migration on request paths."""

from fastapi import APIRouter, Request
from starlette.responses import Response

from aiddos.evidence.contracts import request_value
from aiddos.evidence.queries import get, list_evidence
from aiddos.evidence.repository import create
from aiddos.runs.contracts import identifier, require
from aiddos.runs.lifetime import manager
from aiddos.startup import startup_setting

from .construction import serialized
from .runs import disconnected


def evidence_router():
    return _compose_evidence(startup_setting("RUN_DB_SOCKET"))


@serialized
def _compose_evidence(socket):
    router = APIRouter(prefix="/api/v1/evidence")

    async def perform(request, work):
        return await manager().perform(request.scope["s02_deadline"], work,
                                       lambda: disconnected(request))

    @router.post("")
    async def register(request: Request):
        require(not request.scope.get("query_string"))
        value = request_value(await request.body())
        status, body = await perform(request, lambda op: create(op, socket, value))
        return Response(body, status_code=status, media_type="application/json")

    @router.get("")
    async def listing(request: Request):
        require(not request.scope.get("query_string"))
        status, body = await perform(request, lambda op: list_evidence(op, socket))
        return Response(body, status_code=status, media_type="application/json")

    @router.get("/by-request/{request_id}")
    async def by_request(request_id: str, request: Request):
        identifier(request_id)
        require(not request.scope.get("query_string"))
        status, body = await perform(
            request, lambda op: get(op, socket, request_id, by_request=True)
        )
        return Response(body, status_code=status, media_type="application/json")

    @router.get("/{bundle_id}")
    async def detail(bundle_id: str, request: Request):
        identifier(bundle_id)
        require(not request.scope.get("query_string"))
        status, body = await perform(request, lambda op: get(op, socket, bundle_id))
        return Response(body, status_code=status, media_type="application/json")

    @router.get("/{bundle_id}/raw/{side}")
    async def raw(bundle_id: str, side: str, request: Request):
        identifier(bundle_id)
        require(side in {"ingress", "egress"} and not request.scope.get("query_string"))
        status, body = await perform(request, lambda op: get(op, socket, bundle_id, side=side))
        return Response(body, status_code=status, media_type="application/octet-stream",
                        headers={"Content-Disposition":
                                 f'attachment; filename="{bundle_id}-{side}.pcap"',
                                 "X-Content-Type-Options": "nosniff"})

    return router
