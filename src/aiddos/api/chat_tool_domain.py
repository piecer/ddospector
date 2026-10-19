"""Native draft I/O for chat; never owns or uses a SQLite connection.

Use one instance from one event loop. All admission is no-queue. Read observer
cancellation is prompt, but native ownership remains until the worker retires.
Write cancellation is a Stop request, NOT abandonment: the await settles with
the real result/error so the producer can persist its receipt before retiring.
"""

import asyncio
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from time import monotonic

from pydantic import TypeAdapter, ValidationError

from .catalog import initial_workspace
from .chat_models import encoded
from .errors import DraftError
from .models import AgentProfileInput, SkillInput, TargetInput
from .validation import Identifier

_TARGET_ID = TypeAdapter(Identifier)
_SKILL_ID = TypeAdapter(Identifier)


def target_config(target):
    """Complete typed domain record, shared by model and operator inspection."""
    return target.model_dump()


def agent_config(profile):
    return {
        "resource_id": "agent-profile",
        "name": profile.name,
        "skill_ids": list(profile.skill_ids),
    }


class DomainWorker:
    """One lazy native worker. Keep the owning event loop alive through shutdown."""

    def __init__(self, draft):
        self.draft = draft
        self._executor = None
        self._active = None
        self._closed = False
        self._thread = None
        self._stop = None

    @property
    def busy(self):
        return self._active is not None

    async def _run(self, operation, *, deadline=None, stop=None, write=False):
        if self._closed or self.busy:
            raise DraftError("CHAT_BUSY")
        local_stop = threading.Event()

        def check():
            if local_stop.is_set() or (stop is not None and stop.is_set()):
                raise DraftError("CHAT_CANCELLED")
            if deadline is not None and monotonic() >= deadline:
                raise DraftError("CHAT_TIMEOUT")

        check()
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chat-domain")
        loop = asyncio.get_running_loop()

        def owned():
            self._thread = threading.current_thread()
            with self.draft.lock:
                check()
                result = operation(check)
                if not write:
                    check()
                return result

        future = loop.run_in_executor(self._executor, owned)
        self._active, self._stop = future, local_stop

        def retire(done):
            done.exception()  # Consume errors from abandoned read observers too.
            if self._active is done:
                self._active = self._stop = None

        future.add_done_callback(retire)
        while True:
            try:
                return await asyncio.shield(future)
            except asyncio.CancelledError:
                local_stop.set()
                if not write:
                    raise
                # fsync cannot be killed. Do not lose an applied write's receipt.
            except DraftError as exc:
                code = {
                    "STATE_UNAVAILABLE": "CHAT_STORAGE_ERROR",
                    "STATE_CORRUPT": "CHAT_STORAGE_ERROR",
                    "STATE_COMMIT_UNCERTAIN": "CHAT_TOOL_UNCERTAIN",
                    "AUDIT_LIMIT_REACHED": "CHAT_INVALID_REQUEST",
                    "DRAFT_LIMIT_REACHED": "CHAT_TOOL_LIMIT",
                    "INVALID_REFERENCE": "CHAT_INVALID_REQUEST",
                }.get(exc.code, exc.code)
                raise DraftError(code) from None

    def _prepare(self, expected_draft_revision, name, skill_ids, expected_settings_revision=None):
        state = self.draft._read()
        if state.audit_total != expected_draft_revision or (
            expected_settings_revision is not None
            and state.ai_settings.revision != expected_settings_revision
        ):
            raise DraftError("CHAT_TOOL_CONFLICT")
        try:
            value = AgentProfileInput(
                name=name, skill_ids=skill_ids, mcp_server_ids=state.agent_profile.mcp_server_ids
            )
            profile = self.draft.validate_agent_profile(state, value)
        except ValidationError:
            raise DraftError("CHAT_INVALID_REQUEST") from None
        except DraftError as exc:
            if exc.code == "INVALID_REFERENCE":
                raise DraftError("CHAT_INVALID_REQUEST") from None
            raise
        return state, value, profile

    async def ai_snapshot(self, *, deadline=None, stop=None):
        """Internal settings snapshot, never a model-visible projection."""
        return await self._run(lambda check: self.draft.ai_snapshot(), deadline=deadline, stop=stop)

    async def snapshot(self, *, deadline=None, stop=None):
        """Internal workspace snapshot, never a model-visible projection."""
        return await self._run(lambda check: self.draft.snapshot(), deadline=deadline, stop=stop)

    async def targets_snapshot(self, *, deadline=None, stop=None):
        """Bounded, fresh operator inspection; not model authorization or cached receipt."""
        def operation(check):
            state = self.draft._read()
            result = {
                "schema_version": 1,
                "draft_revision": state.audit_total,
                "targets": [target_config(target) for target in state.targets],
            }
            if len(encoded(result)) > 131072:
                raise DraftError("CHAT_TOOL_LIMIT")
            return result

        return await self._run(operation, deadline=deadline, stop=stop)

    async def skills_snapshot(self, *, deadline=None, stop=None):
        """Operator summaries only: finite catalog first, then stored custom order."""
        def operation(check):
            state = self.draft._read()
            fields = {"id", "name", "category", "status", "version"}
            skills = [
                {key: value for key, value in skill.items() if key in fields}
                for skill in initial_workspace()["skills"]
            ]
            skills.extend(skill.model_dump(include=fields) for skill in state.skills)
            result = {"schema_version": 1, "draft_revision": state.audit_total, "skills": skills}
            if len(encoded(result)) > 131072:
                raise DraftError("CHAT_TOOL_LIMIT")
            return result

        return await self._run(operation, deadline=deadline, stop=stop)

    async def skill_snapshot(self, skill_id, *, deadline=None, stop=None):
        """One full actual record, never a retained receipt or inferred ownership."""
        def operation(check):
            try:
                identifier = _SKILL_ID.validate_python(skill_id, strict=True)
            except ValidationError:
                raise DraftError("CHAT_INVALID_REQUEST") from None
            state = self.draft._read()
            # Templates come only from the exact finite catalog. _read validates
            # every custom draft's literal text, policy and noncatalog identity.
            skill = next((s for s in initial_workspace()["skills"] if s["id"] == identifier), None)
            if skill is None:
                custom = next((s for s in state.skills if s.id == identifier), None)
                if custom is None:
                    raise DraftError("CHAT_NOT_FOUND")
                skill = custom.model_dump()
            result = {"schema_version": 1, "draft_revision": state.audit_total, "skill": skill}
            if len(encoded(result)) > 131072:
                raise DraftError("CHAT_TOOL_LIMIT")
            return result

        return await self._run(operation, deadline=deadline, stop=stop)

    async def read_configuration(self, arguments, locale, *, deadline=None, stop=None):
        """Project validated native arguments; reject oversize results, never truncate."""

        def operation(check):
            state = self.draft._read()
            kind = arguments["kind"]
            result = {"kind": kind, "draft_revision": state.audit_total}
            if kind == "agent_profile":
                result["agent_profile"] = agent_config(state.agent_profile)
            elif kind == "targets":
                if set(arguments) != {"kind", "offset", "limit"}:
                    raise DraftError("CHAT_INVALID_REQUEST")
                offset, limit = arguments["offset"], arguments["limit"]
                if (
                    type(offset) is not int
                    or type(limit) is not int
                    or not (0 <= offset <= 100 and 1 <= limit <= 10)
                ):
                    raise DraftError("CHAT_INVALID_REQUEST")
                result["items"] = [
                    target_config(target) for target in state.targets[offset : offset + limit]
                ]
                end = offset + len(result["items"])
                result["next_offset"] = end if end < len(state.targets) else None
            elif kind == "target":
                if set(arguments) != {"kind", "id"}:
                    raise DraftError("CHAT_INVALID_REQUEST")
                try:
                    identifier = _TARGET_ID.validate_python(arguments["id"], strict=True)
                except ValidationError:
                    raise DraftError("CHAT_INVALID_REQUEST") from None
                target = next((t for t in state.targets if t.id == identifier), None)
                if target is None:
                    raise DraftError("CHAT_NOT_FOUND")
                result["target"] = target_config(target)
            else:
                skills = initial_workspace()["skills"] + [s.model_dump() for s in state.skills]

                def project(skill, detail=False):
                    item = {k: skill[k] for k in ("id", "category", "status", "version")}
                    item["name"] = skill["name"][locale]
                    if detail:
                        item.update({k: skill[k][locale] for k in ("description", "instructions")})
                    return item

                if kind == "skills":
                    offset, limit = arguments["offset"], arguments["limit"]
                    if (
                        type(offset) is not int
                        or type(limit) is not int
                        or not (0 <= offset <= 103 and 1 <= limit <= 10)
                    ):
                        raise DraftError("CHAT_INVALID_REQUEST")
                    result["items"] = [project(s) for s in skills[offset : offset + limit]]
                    end = offset + len(result["items"])
                    result["next_offset"] = end if end < len(skills) else None
                elif kind == "skill":
                    skill = next((s for s in skills if s["id"] == arguments["id"]), None)
                    if skill is None:
                        raise DraftError("CHAT_NOT_FOUND")
                    result["skill"] = project(skill, True)
                else:
                    raise DraftError("CHAT_INVALID_REQUEST")
            if len(encoded(result)) > 32768:
                raise DraftError("CHAT_TOOL_LIMIT")
            return result

        return await self._run(operation, deadline=deadline, stop=stop)

    async def prepare_update(
        self, expected_draft_revision, name, skill_ids, *, deadline=None, stop=None
    ):
        def operation(check):
            state, _, profile = self._prepare(expected_draft_revision, name, skill_ids)
            return {
                "before_revision": state.audit_total,
                "before": agent_config(state.agent_profile),
                "after": agent_config(profile),
            }

        return await self._run(operation, deadline=deadline, stop=stop)

    async def update_agent_profile(
        self,
        expected_draft_revision,
        name,
        skill_ids,
        publication_guard,
        expected_settings_revision=None,
        *,
        deadline=None,
        stop=None,
    ):
        """Gate is synchronous: verify immutable approval/UTC expiry or raise DraftError.

        It must not use SQLite, an async round-trip, another lock, or mutate drafts.
        The worker adds original monotonic-deadline and thread-safe Stop checks.
        Stop after the final gate cannot roll publication back.
        """
        skill_ids = skill_ids.copy() if isinstance(skill_ids, list) else skill_ids

        def operation(check):
            before, value, _ = self._prepare(
                expected_draft_revision, name, skill_ids, expected_settings_revision
            )

            def guard():
                check()
                publication_guard()
                check()

            try:
                profile, audit = self.draft.save_agent_profile_receipt(
                    value, expected_draft_revision=expected_draft_revision, publication_guard=guard
                )
            except DraftError:
                raise
            except Exception:
                # An unclassified fault after entering mutation cannot prove nonapplication.
                raise DraftError("CHAT_TOOL_UNCERTAIN") from None
            return {
                "kind": "agent_profile_updated",
                "before_revision": before.audit_total,
                "after_revision": before.audit_total + 1,
                "agent_profile": agent_config(profile),
                "audit": audit.model_dump(),
            }

        return await self._run(operation, deadline=deadline, stop=stop, write=True)

    def _prepare_target(
        self, expected_draft_revision, name, address, kind, expected_settings_revision=None
    ):
        state = self.draft._read()
        if state.audit_total != expected_draft_revision or (
            expected_settings_revision is not None
            and state.ai_settings.revision != expected_settings_revision
        ):
            raise DraftError("CHAT_TOOL_CONFLICT")
        try:
            value = TargetInput(name=name, address=address, kind=kind)
            value = self.draft.validate_target_creation(state, value)
        except ValidationError:
            raise DraftError("CHAT_INVALID_REQUEST") from None
        return state, value

    async def prepare_target_create(
        self,
        expected_draft_revision,
        name,
        address,
        kind,
        expected_settings_revision=None,
        *,
        deadline=None,
        stop=None,
    ):
        """Validate the literal proposed image without allocating any domain fields."""
        def operation(check):
            state, value = self._prepare_target(
                expected_draft_revision, name, address, kind, expected_settings_revision
            )
            return {
                "before_revision": state.audit_total,
                "before": None,
                "after": value.model_dump(),
            }

        return await self._run(operation, deadline=deadline, stop=stop)

    async def create_target(
        self,
        expected_draft_revision,
        name,
        address,
        kind,
        publication_guard,
        expected_settings_revision=None,
        *,
        deadline=None,
        stop=None,
    ):
        """Own the native lease through publication/readback, even on cancellation."""
        def operation(check):
            before, value = self._prepare_target(
                expected_draft_revision, name, address, kind, expected_settings_revision
            )

            def guard():
                check()
                publication_guard()
                check()

            try:
                target, audit = self.draft.create_target_receipt(
                    value, expected_draft_revision=expected_draft_revision, publication_guard=guard
                )
            except DraftError:
                raise
            except Exception:
                raise DraftError("CHAT_TOOL_UNCERTAIN") from None
            return {
                "kind": "target_created",
                "before_revision": before.audit_total,
                "after_revision": before.audit_total + 1,
                "target": target.model_dump(),
                "audit": audit.model_dump(),
            }

        return await self._run(operation, deadline=deadline, stop=stop, write=True)

    def _prepare_skill(
        self, expected_draft_revision, name, description, instructions, category,
        expected_settings_revision=None,
    ):
        state = self.draft._read()
        if state.audit_total != expected_draft_revision or (
            expected_settings_revision is not None
            and state.ai_settings.revision != expected_settings_revision
        ):
            raise DraftError("CHAT_TOOL_CONFLICT")
        try:
            value = SkillInput(
                name=name, description=description, instructions=instructions, category=category
            )
            value = self.draft.validate_skill_creation(state, value)
        except ValidationError:
            raise DraftError("CHAT_INVALID_REQUEST") from None
        return state, value

    async def prepare_skill_create(
        self,
        expected_draft_revision,
        name,
        description,
        instructions,
        category,
        expected_settings_revision=None,
        *,
        deadline=None,
        stop=None,
    ):
        """Validate literal proposed Skill data without allocating domain fields."""
        def operation(check):
            state, value = self._prepare_skill(
                expected_draft_revision, name, description, instructions, category,
                expected_settings_revision,
            )
            return {
                "before_revision": state.audit_total,
                "before": None,
                "after": value.model_dump(),
            }

        return await self._run(operation, deadline=deadline, stop=stop)

    async def create_skill(
        self,
        expected_draft_revision,
        name,
        description,
        instructions,
        category,
        publication_guard,
        expected_settings_revision=None,
        *,
        deadline=None,
        stop=None,
    ):
        """Own the native lease through publication/readback, even on cancellation."""
        def operation(check):
            before, value = self._prepare_skill(
                expected_draft_revision, name, description, instructions, category,
                expected_settings_revision,
            )

            def guard():
                check()
                publication_guard()
                check()

            try:
                skill, audit = self.draft.create_skill_receipt(
                    value, expected_draft_revision=expected_draft_revision, publication_guard=guard
                )
            except DraftError:
                raise
            except Exception:
                # Mutation entry alone cannot prove an unexpected fault was prepublication.
                raise DraftError("CHAT_TOOL_UNCERTAIN") from None
            return {
                "kind": "skill_created",
                "before_revision": before.audit_total,
                "after_revision": before.audit_total + 1,
                "skill": skill.model_dump(),
                "audit": audit.model_dump(),
            }

        return await self._run(operation, deadline=deadline, stop=stop, write=True)

    async def locked_revision(self, callback):
        """Run a synchronous owner-loop decision while this native lease holds RLock.

        The caller must admit this inspection exclusively from idle. The callback
        may use owner-thread SQLite, never await or acquire the draft lock. Native
        cancellation drains the lease and propagates the actual callback outcome.
        """
        loop = asyncio.get_running_loop()

        def operation(check):
            revision = self.draft._read().audit_total
            reply = Future()

            def decide():
                try:
                    check()
                    reply.set_result(callback(revision))
                except BaseException as exc:
                    reply.set_exception(exc)

            loop.call_soon_threadsafe(decide)
            return reply.result()

        return await self._run(operation, write=True)

    async def settle(self):
        """Drain the operation owned at entry, never later work; do not close capacity.

        A cancelled read observer can use this before retiring its owning turn.
        Repeated cancellation cannot abandon the native operation. Its error has
        already been consumed by the completion callback; this is a drain only.
        """
        future = self._active
        while future is not None and not future.done():
            try:
                await asyncio.shield(future)
            except asyncio.CancelledError:
                continue
            except Exception:
                break

    async def shutdown(self):
        """Close admission, signal Stop, drain native work, and retire the thread.

        Cancellation of shutdown cannot reopen admission or detach native work.
        This can wait for blocked OS I/O; it never blocks the event loop.
        """
        self._closed = True
        if self._stop is not None:
            self._stop.set()
        future = self._active
        while future is not None and not future.done():
            try:
                await asyncio.shield(future)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if self._executor is not None:
            self._executor.shutdown(wait=False)
        while self._thread is not None and self._thread.is_alive():
            try:
                await asyncio.sleep(0.001)
            except asyncio.CancelledError:
                continue
