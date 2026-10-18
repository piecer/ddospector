"""Single-process draft store. No execution store or multiprocess guarantee."""

import json
import os
import stat
import tempfile
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4
from weakref import WeakValueDictionary

from .catalog import SAFETY_RULES, initial_workspace, localized
from .encoding import strict_json
from .errors import DraftError
from .models import (
    AgentProfile,
    AgentProfileInput,
    AISettingsInput,
    AISettingsSnapshot,
    AuditEvent,
    Campaign,
    CampaignInput,
    DraftState,
    LegacyDraftState,
    McpServer,
    McpServerInput,
    Skill,
    SkillInput,
    Target,
    TargetInput,
)

MAX_STATE_BYTES = 16 * 1024 * 1024
_LOCKS = WeakValueDictionary()
_LOCKS_GUARD = RLock()


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


class DraftStore:
    def __init__(self, path: Path):
        self.path = path.parent.resolve() / path.name
        with _LOCKS_GUARD:
            lock = _LOCKS.get(str(self.path))
            if lock is None:
                lock = RLock()
                _LOCKS[str(self.path)] = lock
            self.lock = lock

    def _read(self) -> DraftState:
        try:
            descriptor = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return DraftState()
        except OSError:
            raise DraftError("STATE_UNAVAILABLE") from None
        try:
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_STATE_BYTES:
                    raise DraftError("STATE_CORRUPT")
                raw = stream.read(MAX_STATE_BYTES + 1)
            if len(raw) > MAX_STATE_BYTES:
                raise DraftError("STATE_CORRUPT")
            payload = strict_json(raw)
            if (
                isinstance(payload, dict)
                and type(payload.get("format_version")) is int
                and payload["format_version"] == 1
            ):
                legacy = LegacyDraftState.model_validate(payload)
                if json.dumps(legacy.model_dump(), sort_keys=True) != json.dumps(
                    payload, sort_keys=True
                ):
                    raise DraftError("STATE_CORRUPT")
                # No write here: only the next authorized mutation publishes v2.
                payload = {
                    **legacy.model_dump(),
                    "format_version": 2,
                    "ai_settings": AISettingsSnapshot.empty().model_dump(),
                }
            state = DraftState.model_validate(payload)
            # Require every persisted field and exact primitive types. In-memory
            # defaults must not silently repair an incomplete/corrupt stored image.
            if json.dumps(state.model_dump(), sort_keys=True) != json.dumps(
                payload, sort_keys=True
            ):
                raise DraftError("STATE_CORRUPT")
            return state
        except (ValueError, RecursionError):
            raise DraftError("STATE_CORRUPT") from None
        except OSError:
            raise DraftError("STATE_UNAVAILABLE") from None

    def _write(
        self, state: DraftState, *, publication_guard: Callable[[], None] | None = None
    ) -> None:
        if state.audit_total > 9007199254740991:
            raise DraftError("AUDIT_LIMIT_REACHED")
        state.audit = state.audit[-500:]
        temporary = None
        published = False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, name = tempfile.mkstemp(prefix=".ui-drafts-", dir=self.path.parent)
            temporary = Path(name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(state.model_dump_json())
                stream.flush()
                os.fsync(stream.fileno())
            if publication_guard is not None:
                publication_guard()
            os.replace(temporary, self.path)
            published = True
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            code = "STATE_COMMIT_UNCERTAIN" if published else "STATE_UNAVAILABLE"
            raise DraftError(code) from None
        finally:
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink(missing_ok=True)

    def ai_snapshot(self) -> dict:
        with self.lock:
            return self._read().ai_settings.model_dump()

    def save_ai_settings(self, value: AISettingsInput) -> dict:
        with self.lock:
            state = self._read()
            if value.revision != state.ai_settings.revision:
                raise DraftError("AI_SETTINGS_CONFLICT")
            data = value.model_dump()
            data["revision"] += 1
            updated_at = timestamp()
            settings = AISettingsSnapshot(
                **data,
                updated_at=updated_at,
                execution_enabled=False,
                connection_status="not_tested",
            )
            state.ai_settings = settings
            state.audit.append(
                AuditEvent(
                    id=str(uuid4()),
                    action="ai_settings.updated",
                    entity_id="ai-settings",
                    created_at=updated_at,
                )
            )
            state.audit_total += 1
            self._write(state)
            return settings.model_dump()

    def snapshot(self) -> dict:
        with self.lock:
            state = self._read()
            data = initial_workspace()
            data["targets"] = [target.model_dump() for target in state.targets]
            data["mcp_servers"] = [server.model_dump() for server in state.mcp_servers]
            data["skills"].extend(skill.model_dump() for skill in state.skills)
            data["agent_profile"] = state.agent_profile.model_dump()
            data["campaigns"] = [campaign.model_dump() for campaign in state.campaigns]
            data["audit"] = [event.model_dump() for event in state.audit]
            data["meta"]["audit_retention"].update(
                retained=len(state.audit),
                total_recorded=state.audit_total,
                dropped=state.audit_total - len(state.audit),
            )
            return data

    def _create(self, collection: str, model, value, action: str):
        with self.lock:
            state = self._read()
            if len(getattr(state, collection)) >= 100:
                raise DraftError("DRAFT_LIMIT_REACHED")
            entity = model(**value.model_dump(), id=str(uuid4()), created_at=timestamp())
            getattr(state, collection).append(entity)
            state.audit.append(
                AuditEvent(
                    id=str(uuid4()),
                    action=action,
                    entity_id=entity.id,
                    created_at=entity.created_at,
                )
            )
            state.audit_total += 1
            self._write(state)
            return entity

    def validate_agent_profile(self, state: DraftState, value: AgentProfileInput) -> AgentProfile:
        """Shared business validation; caller holds the draft lock for this state."""
        catalog = initial_workspace()
        skill_ids = {item["id"] for item in catalog["skills"]} | {s.id for s in state.skills}
        mcp_ids = {server.id for server in state.mcp_servers}
        if not set(value.skill_ids) <= skill_ids or not set(value.mcp_server_ids) <= mcp_ids:
            raise DraftError("INVALID_REFERENCE")
        return AgentProfile(
            **value.model_dump(),
            autonomy=state.agent_profile.autonomy,
            execution_enabled=state.agent_profile.execution_enabled,
        )

    def save_agent_profile(
        self,
        value: AgentProfileInput,
        *,
        expected_draft_revision: int | None = None,
        publication_guard: Callable[[], None] | None = None,
    ) -> AgentProfile:
        with self.lock:
            state = self._read()
            if expected_draft_revision is not None and state.audit_total != expected_draft_revision:
                raise DraftError("CHAT_TOOL_CONFLICT")
            return self._save_agent_profile(state, value, publication_guard)

    def _save_agent_profile(self, state, value, publication_guard):
        profile = self.validate_agent_profile(state, value)
        state.agent_profile = profile
        state.audit.append(
            AuditEvent(
                id=str(uuid4()),
                action="agent_profile.updated",
                entity_id="agent-profile",
                created_at=timestamp(),
            )
        )
        state.audit_total += 1
        if publication_guard is None:
            self._write(state)
        else:
            self._write(state, publication_guard=publication_guard)
        return profile

    def save_agent_profile_receipt(
        self,
        value: AgentProfileInput,
        *,
        expected_draft_revision: int,
        publication_guard: Callable[[], None],
    ) -> tuple[AgentProfile, AuditEvent]:
        """Publish once and verify the exact image/audit before releasing the lock."""
        with self.lock:
            state = self._read()
            if state.audit_total != expected_draft_revision:
                raise DraftError("CHAT_TOOL_CONFLICT")
            self._save_agent_profile(state, value, publication_guard)
            try:
                actual = self._read()
                if actual.model_dump() != state.model_dump():
                    raise DraftError("STATE_COMMIT_UNCERTAIN")
            except Exception:
                raise DraftError("STATE_COMMIT_UNCERTAIN") from None
            return actual.agent_profile, actual.audit[-1]

    def create_skill(self, value: SkillInput) -> Skill:
        with self.lock:
            state = self._read()
            if len(state.skills) >= 100:
                raise DraftError("DRAFT_LIMIT_REACHED")
            skill = Skill(
                id=str(uuid4()),
                status="draft",
                category=value.category,
                **{
                    field: localized(getattr(value, field), getattr(value, field))
                    for field in ("name", "description", "instructions")
                },
                allowed_operations=[],
                required_capabilities=[],
                safety_rules=SAFETY_RULES,
            )
            state.skills.append(skill)
            state.audit.append(
                AuditEvent(
                    id=str(uuid4()),
                    action="skill.created",
                    entity_id=skill.id,
                    created_at=timestamp(),
                )
            )
            state.audit_total += 1
            self._write(state)
            return skill

    def create_campaign(self, value: CampaignInput) -> Campaign:
        with self.lock:
            state = self._read()
            profile_ids = {p["id"] for p in initial_workspace()["profiles"]}
            if (
                value.target_id not in {t.id for t in state.targets}
                or value.profile_id not in profile_ids
            ):
                raise DraftError("INVALID_REFERENCE")
            return self._create("campaigns", Campaign, value, "campaign.created")

    def create_target(self, value: TargetInput) -> Target:
        return self._create("targets", Target, value, "target.created")

    def create_mcp_server(self, value: McpServerInput) -> McpServer:
        return self._create("mcp_servers", McpServer, value, "mcp_server.created")
