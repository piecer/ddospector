"""FastAPI application wiring."""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from .boundary import DevelopmentBoundary
from .errors import DraftError, error_response
from .models import (
    AgentProfile,
    AgentProfileInput,
    AISettingsInput,
    AISettingsSnapshot,
    Campaign,
    CampaignInput,
    ContextPreview,
    McpServer,
    McpServerInput,
    PreviewInput,
    Skill,
    SkillInput,
    Target,
    TargetInput,
)
from .preview import preview_context
from .store import DraftStore


def create_app(*, state_path: str | Path | None = None) -> FastAPI:
    application = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)
    application.add_middleware(DevelopmentBoundary)
    store = DraftStore(
        Path(
            state_path
            or os.environ.get(
                "AIDDOS_UI_STATE_PATH",
                ".local/ui-drafts.json",
            )
        )
    )

    @application.exception_handler(Exception)
    async def unexpected_error(request, exc):
        return error_response("INTERNAL_ERROR")

    @application.exception_handler(HTTPException)
    async def http_error(request, exc):
        codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
        return error_response(codes.get(exc.status_code, "VALIDATION_ERROR"))

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error_response("VALIDATION_ERROR")

    @application.exception_handler(DraftError)
    async def domain_error(request, exc):
        return error_response(exc.code)

    @application.get("/api/v1/health")
    def health():
        return {"status": "ok", "version": "0.1.0-ui", "mode": "OFFLINE"}

    @application.get("/api/v1/ai-settings", response_model=AISettingsSnapshot)
    def ai_settings():
        return store.ai_snapshot()

    @application.put("/api/v1/ai-settings", response_model=AISettingsSnapshot)
    def save_ai_settings(value: AISettingsInput):
        return store.save_ai_settings(value)

    @application.get("/api/v1/workspace")
    def workspace():
        return store.snapshot()

    @application.post("/api/v1/targets", status_code=201, response_model=Target)
    def create_target(value: TargetInput):
        return store.create_target(value)

    @application.post("/api/v1/mcp-servers", status_code=201, response_model=McpServer)
    def create_mcp_server(value: McpServerInput):
        return store.create_mcp_server(value)

    @application.post("/api/v1/skills", status_code=201, response_model=Skill)
    def create_skill(value: SkillInput):
        return store.create_skill(value)

    @application.put("/api/v1/agent-profile", response_model=AgentProfile)
    def save_agent_profile(value: AgentProfileInput):
        return store.save_agent_profile(value)

    @application.post("/api/v1/agent/preview", response_model=ContextPreview)
    def preview(value: PreviewInput):
        return preview_context(store.snapshot(), value)

    @application.post("/api/v1/campaigns", status_code=201, response_model=Campaign)
    def create_campaign(value: CampaignInput):
        return store.create_campaign(value)

    @application.post("/api/v1/ai-settings/test")
    @application.post("/api/v1/ai-settings/models")
    def deny_ai_connection():
        return error_response("AI_CONNECTION_NOT_AVAILABLE")

    @application.post("/api/v1/runs")
    def deny_run():
        return error_response("LIVE_NOT_AVAILABLE")

    @application.post("/api/v1/agent/execute")
    def deny_agent_execution():
        return error_response("AGENT_EXECUTION_NOT_AVAILABLE")

    return application


app = create_app()
