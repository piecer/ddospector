"""Companion ledger in the exclusively owned ChatStorage connection."""

from datetime import timedelta
from uuid import uuid4

from pydantic import Field, TypeAdapter

from .catalog import SAFETY_RULES
from .chat_models import SAFE_INT, ChatID, ChatTime, Counter, Session, Turn, TurnInput, encoded, now
from .chat_storage import storage_read
from .chat_tool_models import (
    CALL_BYTES,
    EXCHANGE_BYTES,
    PAYLOAD_BYTES,
    POOL_BYTES,
    RECONCILE_HOLD,
    RESULT_BYTES,
    TERMINAL,
    TURN_RESERVATION,
    WRITE_TOOLS,
    AssistantCall,
    Decision,
    DecisionInput,
    Fence,
    GrantRecord,
    GrantRequest,
    ProposalRecord,
    ReconcileInput,
    ReconcileReceipt,
    Result,
    ToolCall,
    ToolModel,
    ToolTranscript,
    allows_call,
    digest,
    instant,
    parse_arguments,
    validate_exchange,
    validate_result,
)
from .encoding import strict_json
from .errors import DraftError

TABLES = (
    "tool_grants",
    "tool_bindings",
    "tool_calls",
    "tool_decisions",
    "tool_exchanges",
    "tool_fence",
    "tool_reconciliations",
    "tool_reservations",
)
TOOL_SCHEMA = {
    name: f"CREATE TABLE {name} (key TEXT PRIMARY KEY, data TEXT NOT NULL)" for name in TABLES
}


def migrate(storage):
    """Caller validated the entire v1 image; DDL and version publish together."""
    with storage.transaction():
        for sql in TOOL_SCHEMA.values():
            storage.db.execute(sql)
        storage.db.execute("PRAGMA user_version=2")


CAPS = dict(zip(TABLES, (8192, 2048, 256 * 1024, 8192, 96 * 1024, 4096, 8192, 256), strict=True))


def charge(key, value):
    # Charge BOTH actual SQL columns, including repeated keys/linkage.
    return len(encoded({"key": key, "data": value}))


class Binding(ToolModel):
    turn_id: ChatID
    grant_id: ChatID
    deadline_at: ChatTime
    revision: Counter
    write_slot: bool


class StoredCall(ToolModel):
    turn_id: ChatID
    call: ToolCall


class DecisionReplay(ToolModel):
    call_id: ChatID
    input: DecisionInput
    receipt: Decision


class ReconcileReplay(ToolModel):
    input: ReconcileInput
    receipt: ReconcileReceipt


class Reservation(ToolModel):
    turn_id: ChatID
    remaining: int = Field(ge=0, le=TURN_RESERVATION)
    exchange_hold: int = Field(ge=0, le=EXCHANGE_BYTES)
    retired: bool


class ToolLedger:
    """Owner-thread facade; runtime owns clocks, Stop and worker admission.

    No method dispatches domain/model work. Boolean replay flags mean immutable
    historical replay and MUST NOT wake a producer. Transactions never span I/O
    outside SQLite. Public writes require an already-open ChatStorage.
    """

    def __init__(self, storage):
        self.storage = storage

    @property
    def db(self):
        return self.storage.db

    @property
    def fenced(self):
        return self.storage.fenced

    @fenced.setter
    def fenced(self, value):
        self.storage.fenced = value

    def _get(self, table, key):
        row = self.db.execute(f"SELECT data FROM {table} WHERE key=?", (key,)).fetchone()
        return None if row is None else strict_json(row[0].encode())

    def _rows(self, table):
        return [
            (key, strict_json(raw.encode()))
            for key, raw in self.db.execute(f"SELECT key, data FROM {table}")
        ]

    @storage_read
    def usage(self):
        if not self.storage.open():
            return {"actual": 0, "reserved": 0, "limit": POOL_BYTES}
        actual = sum(charge(k, v) for table in TABLES for k, v in self._rows(table))
        reserved = sum(v["remaining"] for _, v in self._rows("tool_reservations"))
        return {"actual": actual, "reserved": reserved, "limit": POOL_BYTES}

    def _raw_put(self, table, key, value):
        self.db.execute(
            f"INSERT INTO {table} VALUES (?,?) ON CONFLICT(key) DO UPDATE SET data=excluded.data",
            (key, encoded(value).decode()),
        )

    def _put(self, table, key, value, turn_id=None):
        if len(encoded(value)) > CAPS[table]:
            raise DraftError("CHAT_TOOL_LIMIT")
        old = self._get(table, key)
        delta = max(0, charge(key, value) - (charge(key, old) if old is not None else 0))
        if table == "tool_reservations" and old is not None:
            if value["remaining"] < delta:
                raise DraftError("CHAT_TOOL_LIMIT")
            value = value | {"remaining": value["remaining"] - delta}
        if turn_id is not None and table != "tool_reservations":
            reservation = self._get("tool_reservations", turn_id)
            if reservation is None or reservation["remaining"] < delta:
                raise DraftError("CHAT_TOOL_LIMIT")
            reservation["remaining"] -= delta
            self._raw_put("tool_reservations", turn_id, reservation)
        self._raw_put(table, key, value)
        usage = self.usage()
        if usage["actual"] + usage["reserved"] > POOL_BYTES:
            raise DraftError("CHAT_TOOL_LIMIT")

    @storage_read
    def grant(self, identifier, *, by_request=False):
        if not self.storage.open():
            raise DraftError("CHAT_NOT_FOUND")
        value = (
            next((v for _, v in self._rows("tool_grants") if v["request_id"] == identifier), None)
            if by_request
            else self._get("tool_grants", identifier)
        )
        if value is None:
            raise DraftError("CHAT_NOT_FOUND")
        return value

    @storage_read
    def reservation(self, turn_id):
        if not self.storage.open():
            return None
        return self._get("tool_reservations", turn_id)

    @staticmethod
    def _grant_commitment(body):
        return (
            {
                key: body[key]
                for key in ("request_id", "session_id", "turn_request_id", "expected_sequence")
            }
            | {"text_sha256": digest(body["text"]), "schema_version": body.get("schema_version", 1)}
            | ({"scope": body["scope"]} if "scope" in body else {})
        )

    def create_grant(self, body, *, timestamp=None):
        body = GrantRequest.model_validate(body).model_dump()
        timestamp = timestamp or now()
        with self.storage.transaction():
            commitment = self._grant_commitment(body)
            grants = self._rows("tool_grants")
            existing = next((g for _, g in grants if g["request_id"] == body["request_id"]), None)
            if existing is not None:
                if any(existing[key] != value for key, value in commitment.items()):
                    raise DraftError("CHAT_TOOL_GRANT_CONFLICT")
                return existing, True
            session, _ = self.storage.session(body["session_id"])
            if (
                session["sequence"] != body["expected_sequence"]
                or session["active_turn_id"] is not None
                or session["sequence"] >= 64
            ):
                raise DraftError("CHAT_TOOL_GRANT_INVALID")
            if len(grants) >= 2048:
                raise DraftError("CHAT_TOOL_LIMIT")
            for key, grant in grants:
                if grant["status"] == "pending" and instant(timestamp) >= instant(
                    grant["expires_at"]
                ):
                    self._put("tool_grants", key, grant | {"status": "expired"})
                elif grant["status"] == "pending" and grant["session_id"] == session["id"]:
                    raise DraftError("CHAT_TOOL_GRANT_CONFLICT")
            grant = (
                TypeAdapter(GrantRecord)
                .validate_python(
                    dict(
                        id=str(uuid4()),
                        **commitment,
                        settings_revision=session["settings_revision"],
                        profile_id=session["profile_id"],
                        created_at=timestamp,
                        expires_at=(instant(timestamp) + timedelta(seconds=300)).isoformat(),
                        status="pending",
                        **(
                            dict(read_scope=["targets", "target"], proposal_tools=["target_create"])
                            if commitment["schema_version"] == 2
                            else dict(
                                read_scope=["skills", "skill"], proposal_tools=["skill_create"]
                            )
                            if commitment["schema_version"] == 3
                            else dict(
                                read_scope=["agent_profile", "skills", "skill"],
                                proposal_fields=["name", "skill_ids"],
                            )
                        ),
                    )
                )
                .model_dump()
            )
            self._put("tool_grants", grant["id"], grant)
            return grant, False

    def revoke(self, grant_id):
        with self.storage.transaction():
            grant = self.grant(grant_id)
            if grant["status"] in {"pending", "consumed"}:
                grant["status"] = "revoked"
                binding = next(
                    (b for _, b in self._rows("tool_bindings") if b["grant_id"] == grant_id), None
                )
                self._put("tool_grants", grant_id, grant, binding["turn_id"] if binding else None)
            return grant

    def admit(self, grant_id, session, turn, commitment, *, timestamp=None, deadline_at=None):
        Session.model_validate(session)
        Turn.model_validate(turn)
        body = TurnInput.model_validate(
            {k: v for k, v in commitment.items() if k != "session_id"}
        ).model_dump()
        if set(commitment) != set(body) | {"session_id"}:
            raise ValueError("Invalid turn commitment")
        timestamp = timestamp or now()
        deadline_at = (
            deadline_at or (instant(turn["created_at"]) + timedelta(seconds=120)).isoformat()
        )
        with self.storage.transaction():
            existing = self.db.execute(
                "SELECT id, commitment, data FROM turns WHERE request_id=?", (body["request_id"],)
            ).fetchone()
            if existing is not None:
                binding = self._get("tool_bindings", existing[0])
                if (
                    binding is None
                    or binding["grant_id"] != grant_id
                    or strict_json(existing[1].encode()) != commitment
                ):
                    raise DraftError("CHAT_TOOL_GRANT_CONFLICT")
                return strict_json(existing[2].encode()), True
            grant = self.grant(grant_id)
            old_session, _ = self.storage.session(session["id"])
            if (
                grant["status"] != "pending"
                or instant(timestamp) >= instant(grant["expires_at"])
                or instant(timestamp) >= instant(deadline_at)
                or instant(deadline_at) > instant(turn["created_at"]) + timedelta(seconds=120)
                or grant["session_id"] != session["id"]
                or commitment["session_id"] != session["id"]
                or grant["turn_request_id"] != turn["request_id"]
                or body["request_id"] != turn["request_id"]
                or grant["text_sha256"] != digest(body["text"])
                or body["text"] != turn["user_text"]
                or grant["expected_sequence"] != body["expected_sequence"]
                or old_session["sequence"] != body["expected_sequence"]
                or session
                != old_session | {"sequence": turn["sequence"], "active_turn_id": turn["id"]}
                or turn["session_id"] != session["id"]
                or turn["sequence"] != old_session["sequence"] + 1
                or turn["status"] != "accepted"
                or turn["revision"] != 1
            ):
                raise DraftError("CHAT_TOOL_GRANT_INVALID")
            if any(s["active_turn_id"] is not None for s in self.storage.sessions()) or any(
                not r["retired"] for _, r in self._rows("tool_reservations")
            ):
                raise DraftError("CHAT_BUSY")
            usage = self.usage()
            if usage["actual"] + usage["reserved"] + TURN_RESERVATION > POOL_BYTES:
                raise DraftError("CHAT_TOOL_LIMIT")
            reservation = {
                "turn_id": turn["id"],
                "remaining": TURN_RESERVATION,
                "exchange_hold": 0,
                "retired": False,
            }
            # Reservation metadata is itself paid from this reservation.
            reservation["remaining"] -= charge(turn["id"], reservation)
            self._put("tool_reservations", turn["id"], reservation)
            self.storage._insert_turn(session, turn, commitment)
            self._put("tool_grants", grant_id, grant | {"status": "consumed"}, turn["id"])
            self._put(
                "tool_bindings",
                turn["id"],
                {
                    "turn_id": turn["id"],
                    "grant_id": grant_id,
                    "deadline_at": deadline_at,
                    "revision": 0,
                    "write_slot": False,
                },
                turn["id"],
            )
            self._put("tool_exchanges", turn["id"], [], turn["id"])
            return turn, False

    @storage_read
    def transcript(self, turn_id):
        self.storage.turn(turn_id)
        binding = self._get("tool_bindings", turn_id)
        calls = sorted(
            (v["call"] for _, v in self._rows("tool_calls") if v["turn_id"] == turn_id),
            key=lambda c: c["index"],
        )
        return {
            "schema_version": 1,
            "turn_id": turn_id,
            "revision": binding["revision"] if binding else 0,
            "calls": calls,
        }

    @storage_read
    def binding(self, turn_id):
        if not self.storage.open():
            raise DraftError("CHAT_NOT_FOUND")
        return self._get("tool_bindings", turn_id)

    @storage_read
    def call(self, call_id):
        if not self.storage.open():
            raise DraftError("CHAT_NOT_FOUND")
        row = self._get("tool_calls", call_id)
        if row is None:
            raise DraftError("CHAT_NOT_FOUND")
        return row["call"]

    @storage_read
    def exchanges(self, turn_id):
        self.storage.turn(turn_id)
        return self._get("tool_exchanges", turn_id) or []

    @storage_read
    def fence(self, current_draft_revision=None):
        value = None
        if self.storage.open():
            value = self._get("tool_fence", "singleton")
        value = value or {"schema_version": 1, "generation": 0, "fenced": False, "call_ids": []}
        return Fence.model_validate(
            value | {"current_draft_revision": current_draft_revision}
        ).model_dump()

    def _active(self, turn_id):
        turn = self.storage.turn(turn_id)
        session, _ = self.storage.session(turn["session_id"])
        reservation = self.reservation(turn_id)
        if (
            session["active_turn_id"] != turn_id
            or turn["status"] not in {"accepted", "running"}
            or reservation is None
            or reservation["retired"]
        ):
            raise DraftError("CHAT_TOOL_APPROVAL_CONFLICT")
        return turn

    def _save_call(self, turn_id, call):
        call = ToolCall.model_validate(call).model_dump()
        self._put("tool_calls", call["id"], {"turn_id": turn_id, "call": call}, turn_id)
        binding = self.binding(turn_id)
        if binding["revision"] >= SAFE_INT:
            raise DraftError("CHAT_TOOL_LIMIT")
        binding["revision"] += 1
        self._put("tool_bindings", turn_id, binding, turn_id)
        return call

    def _append(self, turn_id, message, *, settling=False):
        messages = self.exchanges(turn_id) + [message]
        try:
            validate_exchange(messages)
        except ValueError:
            raise DraftError("CHAT_TOOL_LIMIT") from None
        reservation = self.reservation(turn_id)
        hold = 0 if settling else reservation["exchange_hold"]
        if len(encoded(messages)) + hold > EXCHANGE_BYTES:
            raise DraftError("CHAT_TOOL_LIMIT")
        self._put("tool_exchanges", turn_id, messages, turn_id)

    def request_call(self, turn_id, native_message, *, timestamp=None):
        # Parsing precedes any durable Call. Original argument string is retained once.
        native = AssistantCall.model_validate(native_message).model_dump()
        function = native["tool_calls"][0]
        arguments = parse_arguments(function["function"]["name"], function["function"]["arguments"])
        with self.storage.transaction():
            self._active(turn_id)
            binding = self.binding(turn_id)
            grant = self.grant(binding["grant_id"])
            if not allows_call(grant, function["function"]["name"], arguments):
                raise DraftError("CHAT_TOOL_DENIED")
            timestamp = timestamp or now()
            if grant["status"] != "consumed":
                raise DraftError("CHAT_TOOL_GRANT_INVALID")
            if instant(timestamp) >= min(
                instant(grant["expires_at"]), instant(binding["deadline_at"])
            ):
                raise DraftError("CHAT_TIMEOUT")
            transcript = self.transcript(turn_id)
            calls = transcript["calls"]
            if any(c["provider_call_id"] == function["id"] for c in calls):
                raise DraftError("CHAT_TOOL_PROTOCOL")
            if (
                binding["write_slot"]
                or any(c["tool"] in WRITE_TOOLS for c in calls)
                or len(calls) >= 3
                or any(c["status"] not in TERMINAL for c in calls)
            ):
                raise DraftError("CHAT_TOOL_LIMIT")
            binding = self.binding(turn_id)
            call = dict(
                id=str(uuid4()),
                index=len(calls),
                provider_call_id=function["id"],
                tool=function["function"]["name"],
                arguments=arguments,
                args_digest=digest(arguments),
                grant_id=binding["grant_id"],
                actor="operator_authorized_model",
                status="requested",
                error_code=None,
                proposal=None,
                decision=None,
                result=None,
                started_at=timestamp or now(),
                finished_at=None,
            )
            self._append(turn_id, native)
            return self._save_call(turn_id, call)

    @staticmethod
    def projected_receipt(call):
        """Sizing witness only, never published as a saved fact."""
        if call["tool"] not in WRITE_TOOLS:
            raise ValueError("Not a write operation")
        proposal = call["proposal"]
        # 40-byte UTC time and 16-digit safe integer counters bound all receipts.
        stamp = "9999-12-31T23:59:59.99999999999999+00:00"
        receipt = dict(
            kind="agent_profile_updated",
            before_revision=SAFE_INT - 1,
            after_revision=SAFE_INT,
            agent_profile=proposal["after"],
            audit=dict(
                id="a" * 64,
                action="agent_profile.updated",
                entity_id="agent-profile",
                created_at=stamp,
                origin="local_operator",
            ),
        )
        if call["tool"] == "target_create":
            revision = proposal["expected_draft_revision"]
            if revision >= SAFE_INT:
                raise DraftError("CHAT_INVALID_REQUEST")
            receipt.update(
                kind="target_created",
                before_revision=revision,
                after_revision=revision + 1,
                target=dict(**proposal["after"], id="t" * 64, status="draft", created_at=stamp),
            )
            receipt.pop("agent_profile")
            receipt["audit"].update(action="target.created", entity_id="t" * 64)
        elif call["tool"] == "skill_create":
            revision = proposal["expected_draft_revision"]
            if revision >= SAFE_INT:
                raise DraftError("CHAT_INVALID_REQUEST")
            after = proposal["after"]
            receipt.update(
                kind="skill_created",
                before_revision=revision,
                after_revision=revision + 1,
                skill=dict(
                    id="s" * 64,
                    **{
                        key: dict(en=after[key], ko=after[key])
                        for key in ("name", "description", "instructions")
                    },
                    version="1.0.0",
                    category=after["category"],
                    status="draft",
                    allowed_operations=[],
                    required_capabilities=[],
                    safety_rules=SAFETY_RULES,
                ),
            )
            receipt.pop("agent_profile")
            receipt["audit"].update(action="skill.created", entity_id="s" * 64)
            # A valid manual input may expand beyond the chat receipt budget.
            # Size admission is a product refusal, not a malformed native call.
            if len(encoded(receipt)) > RESULT_BYTES:
                raise DraftError("CHAT_TOOL_LIMIT")
        return validate_result(receipt)

    @classmethod
    def projected_message(cls, call):
        return dict(
            role="tool",
            tool_call_id="\x00" * 128,
            content=encoded(
                dict(ok=True, result=cls.projected_receipt(call), error_code=None)
            ).decode(),
        )

    def _projection(self, turn_id, call):
        """Conservative actual-string receipt projection, including nested escaping."""
        proposal = call["proposal"]
        receipt = self.projected_receipt(call)
        stamp = "9999-12-31T23:59:59.99999999999999+00:00"
        decision_input = dict(
            request_id="f" * 36, proposal_digest=proposal["digest"], decision="approve"
        )
        decision = dict(schema_version=1, **decision_input, call_id=call["id"], accepted_at=stamp)
        projected = call | dict(
            status="succeeded",
            decision=decision,
            result=receipt,
            finished_at=stamp,
            started_at=stamp,
            provider_call_id="\x00" * 128,
        )
        tool_message = self.projected_message(call)
        messages = self.exchanges(turn_id)
        growth = len(encoded(messages + [tool_message])) - len(encoded(messages))
        replay = {"call_id": call["id"], "input": decision_input, "receipt": decision}
        record_sizes = (len(encoded({"turn_id": turn_id, "call": projected})), len(encoded(replay)))
        # Independent record envelope includes decision, fence, linkage and terminal error variants.
        required = sum(record_sizes) + growth + 4096 + 2048 + 256
        if (
            record_sizes[0] > CALL_BYTES
            or record_sizes[1] > 8192
            or len(encoded(messages)) + growth > EXCHANGE_BYTES
            or self.reservation(turn_id)["remaining"] < required
        ):
            raise DraftError("CHAT_TOOL_LIMIT")
        return growth

    def propose(self, call_id, proposal, *, timestamp=None, admission_guard=None):
        proposal = TypeAdapter(ProposalRecord).validate_python(proposal).model_dump()
        timestamp = timestamp or now()
        with self.storage.transaction():
            row = self._get("tool_calls", call_id)
            if row is None:
                raise DraftError("CHAT_NOT_FOUND")
            turn_id, call = row["turn_id"], row["call"]
            self._active(turn_id)
            if call["tool"] not in WRITE_TOOLS or call["status"] != "requested":
                raise DraftError("CHAT_TOOL_APPROVAL_CONFLICT")
            if self.fence()["fenced"]:
                raise DraftError("CHAT_TOOL_WRITE_FENCED")
            if any(c["proposal"] is not None for c in self.transcript(turn_id)["calls"]):
                raise DraftError("CHAT_TOOL_LIMIT")
            grant = self.grant(call["grant_id"])
            if (
                grant["status"] != "consumed"
                or instant(timestamp) >= instant(proposal["expires_at"])
                or instant(proposal["expires_at"])
                != min(instant(grant["expires_at"]), instant(self.binding(turn_id)["deadline_at"]))
            ):
                raise DraftError("CHAT_TOOL_GRANT_INVALID")
            prospective = ToolCall.model_validate(
                call | {"status": "awaiting_approval", "proposal": proposal}
            ).model_dump()
            growth = self._projection(turn_id, prospective)
            if admission_guard is not None:
                admission_guard()
            reservation = self.reservation(turn_id)
            reservation["exchange_hold"] = growth
            self._put("tool_reservations", turn_id, reservation)
            return self._save_call(turn_id, prospective)

    def decide(
        self, call_id, body, *, active_turn_id, timestamp=None, stopped=False, admission_guard=None
    ):
        body = DecisionInput.model_validate(body).model_dump()
        checked_at = timestamp or now()
        with self.storage.transaction():
            prior = self._get("tool_decisions", body["request_id"])
            if prior is not None:
                if prior["call_id"] != call_id or prior["input"] != body:
                    raise DraftError("CHAT_TOOL_APPROVAL_CONFLICT")
                return prior["receipt"], True
            if any(v["call_id"] == call_id for _, v in self._rows("tool_decisions")):
                raise DraftError("CHAT_TOOL_APPROVAL_CONFLICT")
            row = self._get("tool_calls", call_id)
            if row is None:
                raise DraftError("CHAT_NOT_FOUND")
            turn_id, call = row["turn_id"], row["call"]
            self._active(turn_id)
            grant = self.grant(call["grant_id"])
            proposal = call["proposal"]
            if (
                stopped
                or active_turn_id != turn_id
                or call["status"] != "awaiting_approval"
                or proposal is None
                or body["proposal_digest"] != proposal["digest"]
                or grant["status"] != "consumed"
                or instant(checked_at) >= instant(proposal["expires_at"])
                or instant(checked_at) >= instant(grant["expires_at"])
            ):
                raise DraftError("CHAT_TOOL_APPROVAL_CONFLICT")
            binding = self.binding(turn_id)
            if body["decision"] == "approve":
                if self.fence()["fenced"]:
                    raise DraftError("CHAT_TOOL_WRITE_FENCED")
                if binding["write_slot"]:
                    raise DraftError("CHAT_TOOL_APPROVAL_CONFLICT")
                self._projection(turn_id, call)
            # Preparation may outlive authority. Sample again before durable intent;
            # explicit timestamps retain deterministic component-call semantics.
            if admission_guard is not None:
                admission_guard(turn_id)
            timestamp = timestamp or now()
            if instant(timestamp) >= min(
                instant(proposal["expires_at"]), instant(grant["expires_at"])
            ):
                raise DraftError("CHAT_TOOL_APPROVAL_CONFLICT")
            receipt = Decision.model_validate(
                dict(schema_version=1, **body, call_id=call_id, accepted_at=timestamp)
            ).model_dump()
            if body["decision"] == "approve":
                call.update(status="executing", decision=receipt)
                binding["write_slot"] = True
            else:
                call.update(
                    status="denied",
                    decision=receipt,
                    finished_at=timestamp,
                    error_code="CHAT_TOOL_DENIED",
                )
            self._put(
                "tool_decisions",
                body["request_id"],
                {"call_id": call_id, "input": body, "receipt": receipt},
                turn_id,
            )
            self._put("tool_bindings", turn_id, binding, turn_id)
            self._save_call(turn_id, call)
            if body["decision"] == "deny":
                self._settle_message(turn_id, call)
            return receipt, False

    def start_read(self, call_id, *, timestamp=None):
        with self.storage.transaction():
            row = self._get("tool_calls", call_id)
            if row is None:
                raise DraftError("CHAT_NOT_FOUND")
            self._active(row["turn_id"])
            call = row["call"]
            grant = self.grant(call["grant_id"])
            if grant["status"] != "consumed":
                raise DraftError("CHAT_TOOL_GRANT_INVALID")
            if instant(timestamp or now()) >= min(
                instant(grant["expires_at"]), instant(self.binding(row["turn_id"])["deadline_at"])
            ):
                raise DraftError("CHAT_TIMEOUT")
            if call["tool"] != "configuration_read" or call["status"] != "requested":
                raise DraftError("CHAT_TOOL_CONFLICT")
            return self._save_call(row["turn_id"], call | {"status": "executing"})

    def _settle_message(self, turn_id, call):
        message = dict(
            role="tool",
            tool_call_id=call["provider_call_id"],
            content=encoded(
                dict(
                    ok=call["status"] == "succeeded",
                    result=call["result"],
                    error_code=call["error_code"],
                )
            ).decode(),
        )
        self._append(turn_id, message, settling=True)
        reservation = self.reservation(turn_id)
        reservation["exchange_hold"] = 0
        self._put("tool_reservations", turn_id, reservation)

    def _install_fence(self, turn_id, call_id):
        fence = self.fence()
        if fence["fenced"]:
            if fence["call_ids"] == [call_id]:
                return
            raise DraftError("CHAT_TOOL_WRITE_FENCED")
        if fence["generation"] >= SAFE_INT:
            raise DraftError("CHAT_TOOL_LIMIT")
        fence.pop("current_draft_revision")
        fence.update(generation=fence["generation"] + 1, fenced=True, call_ids=[call_id])
        self._put("tool_fence", "singleton", fence, turn_id)

    def finish_call(self, call_id, status, *, result=None, error_code=None, timestamp=None):
        """Persist authoritative fact first. Oversized exchange cannot erase the fact.

        Returns (call, exchange_retained). False requires conversation failure and
        no provider continuation; it never changes a known successful receipt.
        """
        with self.storage.transaction():
            row = self._get("tool_calls", call_id)
            if row is None:
                raise DraftError("CHAT_NOT_FOUND")
            turn_id, old = row["turn_id"], row["call"]
            if old["status"] in TERMINAL:
                raise DraftError("CHAT_TOOL_CONFLICT")
            if status not in TERMINAL:
                raise ValueError("Terminal outcome required")
            if status == "succeeded" and old["tool"] == "configuration_read":
                checked = TypeAdapter(Result).validate_python(result).model_dump()
                if len(encoded(checked)) > RESULT_BYTES:
                    status, result, error_code = "failed", None, "CHAT_TOOL_LIMIT"
            call = ToolCall.model_validate(
                old
                | dict(
                    status=status,
                    result=result,
                    error_code=error_code,
                    finished_at=timestamp or now(),
                )
            ).model_dump()
            if status == "succeeded" and old["status"] != "executing":
                raise DraftError("CHAT_TOOL_CONFLICT")
            self._save_call(turn_id, call)
            if status == "uncertain":
                self._install_fence(turn_id, call_id)
            # Use a savepoint: logical exchange refusal must not roll back known facts.
            self.db.execute("SAVEPOINT exchange_receipt")
            try:
                self._settle_message(turn_id, call)
            except DraftError as exc:
                if exc.code != "CHAT_TOOL_LIMIT":
                    raise
                self.db.execute("ROLLBACK TO exchange_receipt")
                self.db.execute("RELEASE exchange_receipt")
                reservation = self.reservation(turn_id)
                reservation["exchange_hold"] = 0
                self._put("tool_reservations", turn_id, reservation)
                return call, False
            self.db.execute("RELEASE exchange_receipt")
            return call, True

    def append_final(self, turn_id, content):
        with self.storage.transaction():
            self._active(turn_id)
            if any(c["status"] not in TERMINAL for c in self.transcript(turn_id)["calls"]):
                raise DraftError("CHAT_TOOL_CONFLICT")
            self._append(turn_id, {"role": "assistant", "content": content})

    @staticmethod
    def check_payload(payload):
        raw = encoded(payload)
        if len(raw) > PAYLOAD_BYTES:
            raise DraftError("CHAT_CONTEXT_LIMIT")
        return raw

    def _retire(self, turn_id):
        reservation = self.reservation(turn_id)
        fence = self.fence()
        held = any(c["id"] in fence["call_ids"] for c in self.transcript(turn_id)["calls"])
        if held and reservation["remaining"] < RECONCILE_HOLD:
            raise DraftError("CHAT_TOOL_LIMIT")
        reservation.update(remaining=RECONCILE_HOLD if held else 0, exchange_hold=0, retired=True)
        self._put("tool_reservations", turn_id, reservation)

    def retire(self, turn_id, *, owner_idle):
        with self.storage.transaction():
            if (
                not owner_idle
                or self.storage.turn(turn_id)["status"]
                in {"accepted", "running", "cancel_requested"}
                or any(c["status"] not in TERMINAL for c in self.transcript(turn_id)["calls"])
            ):
                raise DraftError("CHAT_BUSY")
            self._retire(turn_id)

    def reconcile(self, body, *, current_draft_revision, owner_idle):
        body = ReconcileInput.model_validate(body).model_dump()
        with self.storage.transaction():
            prior = self._get("tool_reconciliations", body["request_id"])
            if prior is not None:
                if prior["input"] != body:
                    raise DraftError("CHAT_TOOL_CONFLICT")
                return prior["receipt"], True
            fence = self.fence(current_draft_revision)
            if not owner_idle or any(s["active_turn_id"] for s in self.storage.sessions()):
                raise DraftError("CHAT_BUSY")
            if (
                not fence["fenced"]
                or fence["generation"] != body["expected_generation"]
                or current_draft_revision != body["expected_draft_revision"]
                or fence["generation"] >= SAFE_INT
            ):
                raise DraftError("CHAT_TOOL_CONFLICT")
            row = self._get("tool_calls", fence["call_ids"][0])
            turn_id = row["turn_id"]
            receipt = ReconcileReceipt.model_validate(
                dict(
                    schema_version=1,
                    request_id=body["request_id"],
                    acknowledged_call_ids=fence["call_ids"],
                    generation=fence["generation"] + 1,
                    write_fenced=False,
                    prior_outcomes="remain_uncertain",
                )
            ).model_dump()
            self._put(
                "tool_reconciliations",
                body["request_id"],
                {"input": body, "receipt": receipt},
                turn_id,
            )
            self._put(
                "tool_fence",
                "singleton",
                dict(schema_version=1, generation=receipt["generation"], fenced=False, call_ids=[]),
                turn_id,
            )
            self._retire(turn_id)
            return receipt, False

    def validate(self):
        """Validate the complete closed v2 graph before recovery changes any byte."""
        for table in TABLES:
            for (raw,) in self.db.execute(f"SELECT data FROM {table}"):
                if encoded(strict_json(raw.encode())).decode() != raw:
                    raise ValueError("Noncanonical retained JSON")
        tables = {name: dict(self._rows(name)) for name in TABLES}
        models = {
            "tool_grants": None,
            "tool_bindings": Binding,
            "tool_calls": StoredCall,
            "tool_decisions": DecisionReplay,
            "tool_reconciliations": ReconcileReplay,
            "tool_reservations": Reservation,
        }
        for table, rows in tables.items():
            for key, value in rows.items():
                if not isinstance(key, str) or len(encoded(value)) > CAPS[table]:
                    raise ValueError("Record cap")
                if table == "tool_grants":
                    TypeAdapter(GrantRecord).validate_python(value)
                elif table in models:
                    models[table].model_validate(value)
        usage = self.usage()
        if usage["actual"] + usage["reserved"] > POOL_BYTES:
            raise ValueError("Tool pool limit")
        sessions = {s["id"]: s for s in self.storage.sessions()}
        turns = {
            v["id"]: v
            for row in self.db.execute("SELECT data FROM turns")
            for v in [strict_json(row[0].encode())]
        }
        grants, bindings, calls = (
            tables[t] for t in ("tool_grants", "tool_bindings", "tool_calls")
        )
        if len(grants) > 2048:
            raise ValueError("Grant count")
        requests, pending, bound = set(), set(), set()
        for key, grant in grants.items():
            if (
                key != grant["id"]
                or grant["request_id"] in requests
                or grant["session_id"] not in sessions
            ):
                raise ValueError("Grant identity")
            requests.add(grant["request_id"])
            session = sessions[grant["session_id"]]
            if (
                grant["settings_revision"] != session["settings_revision"]
                or grant["profile_id"] != session["profile_id"]
            ):
                raise ValueError("Grant session binding")
            if grant["status"] == "pending":
                if grant["session_id"] in pending:
                    raise ValueError("Duplicate pending grant")
                pending.add(grant["session_id"])
        for key, binding in bindings.items():
            if (
                key != binding["turn_id"]
                or key not in turns
                or binding["grant_id"] not in grants
                or binding["grant_id"] in bound
            ):
                raise ValueError("Tool binding")
            bound.add(binding["grant_id"])
            grant, turn = grants[binding["grant_id"]], turns[key]
            if (
                grant["status"] not in {"consumed", "revoked"}
                or grant["session_id"] != turn["session_id"]
                or not instant(turn["created_at"])
                < instant(binding["deadline_at"])
                <= instant(turn["created_at"]) + timedelta(seconds=120)
                or grant["turn_request_id"] != turn["request_id"]
                or grant["expected_sequence"] + 1 != turn["sequence"]
                or grant["text_sha256"] != digest(turn["user_text"])
            ):
                raise ValueError("Grant turn commitment")
        if any(g["status"] == "consumed" and key not in bound for key, g in grants.items()):
            raise ValueError("Unbound consumed grant")
        for key, row in calls.items():
            call = row["call"]
            if (
                key != call["id"]
                or row["turn_id"] not in bindings
                or call["grant_id"] != bindings[row["turn_id"]]["grant_id"]
            ):
                raise ValueError("Call linkage")
            if not allows_call(grants[call["grant_id"]], call["tool"], call["arguments"]):
                raise ValueError("Call outside grant scope")
            if call["proposal"] is not None and instant(call["proposal"]["expires_at"]) != min(
                instant(grants[call["grant_id"]]["expires_at"]),
                instant(bindings[row["turn_id"]]["deadline_at"]),
            ):
                raise ValueError("Proposal outlives grant")
        decision_calls = set()
        for key, row in tables["tool_decisions"].items():
            if (
                key != row["input"]["request_id"]
                or row["call_id"] not in calls
                or row["call_id"] in decision_calls
            ):
                raise ValueError("Decision identity")
            decision_calls.add(row["call_id"])
            receipt = row["receipt"]
            if (
                receipt["request_id"] != key
                or receipt["call_id"] != row["call_id"]
                or any(receipt[k] != v for k, v in row["input"].items())
                or receipt != calls[row["call_id"]]["call"]["decision"]
            ):
                raise ValueError("Decision commitment")
        if {
            key for key, row in calls.items() if row["call"]["decision"] is not None
        } != decision_calls:
            raise ValueError("Missing decision replay")
        if set(tables["tool_exchanges"]) != set(bindings) or set(
            tables["tool_reservations"]
        ) != set(bindings):
            raise ValueError("Missing reservation/exchange")
        for key, binding in bindings.items():
            transcript = self.transcript(key)
            ToolTranscript.model_validate(transcript)
            ordered = transcript["calls"]
            if (
                grants[binding["grant_id"]]["schema_version"] in (2, 3)
                and sum(c["tool"] in WRITE_TOOLS for c in ordered) > 1
            ):
                raise ValueError("Scoped write attempt count")
            if binding["revision"] < len(ordered) or binding["write_slot"] != any(
                c["decision"] is not None and c["decision"]["decision"] == "approve"
                for c in ordered
            ):
                raise ValueError("Write slot or revision")
            messages = tables["tool_exchanges"][key]
            validate_exchange(messages)
            native = [m for m in messages if "tool_calls" in m]
            if len(native) != len(ordered):
                raise ValueError("Missing native exchange")
            for call, message in zip(ordered, native, strict=True):
                function = message["tool_calls"][0]
                if (
                    function["id"] != call["provider_call_id"]
                    or function["function"]["name"] != call["tool"]
                    or parse_arguments(call["tool"], function["function"]["arguments"])
                    != call["arguments"]
                ):
                    raise ValueError("Native call mismatch")
            for message in messages:
                if message["role"] == "tool":
                    call = next(
                        c for c in ordered if c["provider_call_id"] == message["tool_call_id"]
                    )
                    if call["status"] not in TERMINAL or strict_json(
                        message["content"].encode()
                    ) != dict(
                        ok=call["status"] == "succeeded",
                        result=call["result"],
                        error_code=call["error_code"],
                    ):
                        raise ValueError("Tool outcome mismatch")
            final = bool(
                messages
                and messages[-1]["role"] == "assistant"
                and "tool_calls" not in messages[-1]
            )
            if (final and any(c["status"] not in TERMINAL for c in ordered)) or (
                turns[key]["status"] == "succeeded" and not final
            ):
                raise ValueError("Missing terminal exchange")
            reservation = tables["tool_reservations"][key]
            if (
                reservation["turn_id"] != key
                or len(encoded(messages)) + reservation["exchange_hold"] > EXCHANGE_BYTES
                or reservation["remaining"] < reservation["exchange_hold"]
                or (
                    reservation["retired"]
                    and (
                        reservation["exchange_hold"]
                        or any(c["status"] not in TERMINAL for c in ordered)
                    )
                )
            ):
                raise ValueError("Reservation state")
        if set(tables["tool_fence"]) - {"singleton"}:
            raise ValueError("Multiple fences")
        fence = tables["tool_fence"].get("singleton") or dict(
            schema_version=1, generation=0, fenced=False, call_ids=[]
        )
        if set(fence) != {"schema_version", "generation", "fenced", "call_ids"}:
            raise ValueError("Fence shape")
        Fence.model_validate(fence | {"current_draft_revision": None})
        acknowledged, generations = set(), set()
        for key, row in tables["tool_reconciliations"].items():
            body, receipt = row["input"], row["receipt"]
            ids = receipt["acknowledged_call_ids"]
            if (
                key != body["request_id"]
                or key != receipt["request_id"]
                or receipt["generation"] != body["expected_generation"] + 1
                or receipt["generation"] in generations
                or acknowledged.intersection(ids)
                or any(i not in calls or calls[i]["call"]["status"] != "uncertain" for i in ids)
            ):
                raise ValueError("Reconciliation history")
            acknowledged.update(ids)
            generations.add(receipt["generation"])
        if generations != set(range(2, 2 * len(generations) + 1, 2)) or fence[
            "generation"
        ] != 2 * len(generations) + int(fence["fenced"]):
            raise ValueError("Fence generation history")
        uncertain = {key for key, row in calls.items() if row["call"]["status"] == "uncertain"}
        if uncertain - acknowledged != set(fence["call_ids"]):
            raise ValueError("Missing uncertainty fence")
        for key, reservation in tables["tool_reservations"].items():
            held = any(calls[i]["turn_id"] == key for i in fence["call_ids"])
            if reservation["retired"] and reservation["remaining"] != (
                RECONCILE_HOLD if held else 0
            ):
                raise ValueError("Retired reserve")

    def recover(self):
        """Startup only: never dispatch; a persisted executing write is uncertain."""
        with self.storage.transaction():
            for key, grant in self._rows("tool_grants"):
                if grant["status"] == "pending":
                    self._put("tool_grants", key, grant | {"status": "expired"})
            for _, row in self._rows("tool_calls"):
                call = row["call"]
                if call["status"] in TERMINAL:
                    continue
                uncertain = call["tool"] in WRITE_TOOLS and call["status"] == "executing"
                call.update(
                    status="uncertain" if uncertain else "cancelled",
                    finished_at=max(now(), call["started_at"], key=instant),
                    error_code="CHAT_TOOL_UNCERTAIN" if uncertain else "CHAT_CANCELLED",
                )
                self._save_call(row["turn_id"], call)
                if uncertain:
                    self._install_fence(row["turn_id"], call["id"])
            for key, reservation in self._rows("tool_reservations"):
                if not reservation["retired"]:
                    self._retire(key)
