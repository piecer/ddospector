"""Bounded, single-process immutable scenario history, independent of draft replay."""

import os
import stat
from copy import deepcopy
from threading import RLock
from uuid import uuid4
from weakref import WeakValueDictionary

from . import scenario_persistence as persistence
from . import scenarios
from .catalog import CATALOG_VERSION, PROFILES_V1
from .errors import DraftError
from .scenarios import MAX_RECORD_BYTES, ScenarioInput, ScenarioState, canonical, record_digest
from .store import DraftStore, timestamp

MAX_STATE_BYTES = 16 * 1024 * 1024
PROTECTED_FIELDS = {
    "target_id",
    "sink_id",
    "dut_version",
    "policy_version",
    "pcap_asset",
    "traffic_budget",
    "stop_conditions",
}
_LOCKS = WeakValueDictionary()
_LOCKS_GUARD = RLock()


class ScenarioAdmissionRefused(DraftError):
    """Known S01 eligibility refusal, not a new public domain error code."""

    def __init__(self):
        super().__init__("SCENARIO_STATE_UNAVAILABLE")


class Coordinator:
    def __init__(self, ticket):
        self.lock = RLock()
        self.blocked = False
        self.ticket = ticket
        self.known = False


class ScenarioStore:
    def __init__(self, drafts: DraftStore, *, ticket=None):
        self.drafts = drafts
        self.path = drafts.path.with_name(drafts.path.name + ".scenarios.json")
        self.receipt_path = self.path.with_name(self.path.name + ".s01-recovery")
        self.pending_path = self.path.with_name(self.path.name + ".s01-pending")
        with _LOCKS_GUARD:
            coordinator = _LOCKS.get(str(self.path))
            if coordinator is None:
                coordinator = Coordinator(ticket)
                _LOCKS[str(self.path)] = coordinator
        self.coordinator = coordinator
        self.lock = coordinator.lock
        # Never wait for a path lock while holding the global registry guard.
        # Serialize peer fencing with saves so completion cannot erase a denial.
        with self.lock:
            if ticket is not None and ticket != coordinator.ticket:
                coordinator.blocked = True

    def _read(self) -> dict:
        try:
            return persistence.read_registry(self.path)[1]
        except (ValueError, RecursionError) as exc:
            raise DraftError("SCENARIO_STATE_CORRUPT") from exc
        except OSError as exc:
            raise DraftError("SCENARIO_STATE_UNAVAILABLE") from exc

    def _admission(self, *, observe=False):
        try:
            persistence.require(not self.coordinator.blocked)
            raw, _ = persistence.read_registry(self.path)
            pre = "ABSENT" if raw is None else persistence.digest(raw)
            record = persistence.read_bytes(self.receipt_path, 4096, missing=True, mode=0o600)
            entries = persistence.pending_entries(self.pending_path, missing=True)
            if record is None and entries is None:
                persistence.require(not self.coordinator.known and self.coordinator.ticket is None)
                return pre, "INITIALIZE"
            frame = persistence.decode_frame(record or b"")
            if self.coordinator.ticket is not None:
                from .scenario_recovery import verify_archive

                persistence.require(
                    persistence.is_hash(self.coordinator.ticket)
                    and frame["phase"] == "READY"
                    and entries == {}
                    and frame["token_hash"]
                    == persistence.digest(self.coordinator.ticket.encode("ascii"))
                )
                verify_archive(frame, self.path, self.receipt_path, self.pending_path)
                return pre, "CONSUME"
            persistence.require(
                frame["phase"] == "CLEAN"
                and raw is not None
                and frame["post"] == pre
                and frame["size"] == len(raw)
                and entries == {}
            )
            return pre, "CLEAN"
        except (OSError, ValueError, RecursionError) as exc:
            if not observe:
                self.coordinator.blocked = True
            if isinstance(exc, OSError):
                raise DraftError("SCENARIO_STATE_UNAVAILABLE") from exc
            raise ScenarioAdmissionRefused() from exc

    def _write(self, state: dict, *, publication_guard=None, readback=None):
        with self.lock:
            return self._write_locked(state, publication_guard=publication_guard, readback=readback)

    def _write_locked(self, state: dict, *, publication_guard=None, readback=None):
        # Complete closed candidate validation precedes initialization or acquisition.
        try:
            ScenarioState.model_validate(state)
            raw = scenarios.bounded_output(state, MAX_STATE_BYTES, "VALIDATION_ERROR")
        except (ValueError, RecursionError) as exc:
            raise DraftError("VALIDATION_ERROR") from exc
        pre, admission = self._admission()
        base = {
            "version": 1,
            "generation": uuid4().hex,
            "pre": pre,
            "post": persistence.digest(raw),
            "size": len(raw),
            "recovery": None,
            "token_hash": None,
        }
        frames = {
            phase: persistence.encode_frame({**base, "phase": phase})
            for phase in ("PREPARED", "PUBLISHED", "CLEAN")
        }
        active = persistence.encode_frame({**base, "phase": "ACTIVE", "post": None, "size": 0})
        candidate, publish = self.pending_path / "candidate", self.pending_path / "publish"
        published = False
        observed = None
        if publication_guard is not None:
            publication_guard()
        self.coordinator.blocked = True
        self.coordinator.known = True
        self.coordinator.ticket = None
        try:
            if admission == "INITIALIZE":
                persistence.create_parents(self.path.parent)
                self.pending_path.mkdir(mode=0o700)
                persistence.write_frame(self.receipt_path, active, create=True)
                persistence.sync_directory(self.pending_path)
                persistence.sync_directory(self.path.parent)
            elif admission == "CONSUME":
                persistence.write_frame(self.receipt_path, active)
            persistence.write_frame(self.receipt_path, frames["PREPARED"])
            identity = persistence.write_candidate(candidate, raw)
            os.link(candidate, publish, follow_symlinks=False)
            persistence.sync_directory(self.pending_path)
            info = publish.lstat()
            persistence.require(
                stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == identity
            )
            if publication_guard is not None:
                publication_guard()
            os.replace(publish, self.path)
            published = True
            persistence.sync_directory(self.pending_path)
            persistence.sync_directory(self.path.parent)
            persistence.write_frame(self.receipt_path, frames["PUBLISHED"])
            if readback is not None:
                observed = readback()
            # Only normal committed-link retirement. Never cleanup an exposed name.
            candidate.unlink()
            persistence.sync_directory(self.pending_path)
            persistence.write_frame(self.receipt_path, frames["CLEAN"])
        except DraftError as exc:
            if published and readback is not None:
                raise DraftError("SCENARIO_COMMIT_UNCERTAIN") from exc
            raise
        except (OSError, ValueError, RecursionError) as exc:
            code = "SCENARIO_COMMIT_UNCERTAIN" if published else "SCENARIO_STATE_UNAVAILABLE"
            raise DraftError(code) from exc
        self.coordinator.blocked = False
        return observed

    def page(self, offset: int = 0, limit: int = 50) -> dict:
        with self.lock:
            state = self._read()
            return {
                "revision": state["revision"],
                "total": len(state["scenarios"]),
                "offset": offset,
                "limit": limit,
                "items": [s["versions"][-1] for s in state["scenarios"][offset : offset + limit]],
                "execution_enabled": False,
            }

    def history(self, scenario_id: str) -> dict:
        with self.lock:
            state = self._read()
            identity = next((s for s in state["scenarios"] if s["id"] == scenario_id), None)
            if identity is None:
                raise DraftError("SCENARIO_NOT_FOUND")
            return {
                "revision": state["revision"],
                "scenario_id": scenario_id,
                "versions": identity["versions"],
                "execution_enabled": False,
            }

    def _prepare_definition(self, state, source, definition, scenario_id):
        target = next((t for t in source.targets if t.id == definition["target_id"]), None)
        sink = next((t for t in source.targets if t.id == definition["sink_id"]), None)
        if target is None or sink is None or target.kind != "DUT" or sink.kind != "SINK":
            raise DraftError("INVALID_REFERENCE")
        identity = next((s for s in state["scenarios"] if s["id"] == scenario_id), None)
        if scenario_id is not None and identity is None:
            raise DraftError("SCENARIO_NOT_FOUND")
        if (identity is None and len(state["scenarios"]) >= 100) or (
            identity is not None and len(identity["versions"]) >= 10
        ):
            raise DraftError("SCENARIO_LIMIT_REACHED")
        snapshots = {
            "target_snapshot": target.model_dump(),
            "sink_snapshot": sink.model_dump(),
            "profile_snapshot": deepcopy(
                next(p for p in PROFILES_V1 if p["id"] == definition["profile_id"])
            ),
            "catalog_version": CATALOG_VERSION,
        }
        return identity, snapshots

    def _candidate(self, state, identity, definition, snapshots):
        if identity is None:
            identity = {"id": str(uuid4()), "versions": []}
            state["scenarios"].append(identity)
        record = {
            "id": identity["id"],
            "version": len(identity["versions"]) + 1,
            "created_at": timestamp(),
            "status": "definition",
            "execution_enabled": False,
            "definition": definition,
            **snapshots,
        }
        record["digest"] = record_digest(record)
        if len(canonical(record)) > MAX_RECORD_BYTES:
            raise DraftError("VALIDATION_ERROR")
        identity["versions"].append(record)
        state["revision"] += 1
        return record

    def resolve_intent(self, intent, expected_settings_revision):
        with self.lock, self.drafts.lock:
            _, _, resolved, _ = self._resolve(intent, expected_settings_revision)
            return resolved

    def inspect_state(self):
        with self.lock:
            state = self._read()
            status = "available"
            try:
                self._admission(observe=True)
            except ScenarioAdmissionRefused:
                status = "quarantined"
            return {
                "schema_version": 4,
                "scenario_revision": state["revision"],
                "registry_write_status": status,
            }

    def read_configuration(self, grant, arguments):
        with self.lock:
            kind = arguments["kind"]
            if kind == "scenario_context":
                if set(arguments) != {"kind"}:
                    raise DraftError("CHAT_INVALID_REQUEST")
                with self.drafts.lock:
                    state, source, resolved, before = self._resolve(
                        grant["intent"], grant["settings_revision"]
                    )
                    if any(canonical(grant[k]) != canonical(v) for k, v in resolved.items()):
                        raise DraftError("CHAT_TOOL_CONFLICT")
                    target, sink = self._references(source, resolved["resolved_inputs"])
                    result = {
                        "kind": kind,
                        "scenario_revision": state["revision"],
                        "draft_revision": source.audit_total,
                        "operation": grant["intent"]["operation"],
                        **resolved,
                        "target_snapshot": target.model_dump(),
                        "sink_snapshot": sink.model_dump(),
                        "profiles": [
                            deepcopy(next(p for p in PROFILES_V1 if p["id"] == id_))
                            for id_ in ("tcpreplay-policy", "k6-http")
                        ],
                        "base": before,
                    }
            elif kind == "scenarios":
                if set(arguments) != {"kind", "offset", "limit"}:
                    raise DraftError("CHAT_INVALID_REQUEST")
                offset, limit = arguments["offset"], arguments["limit"]
                if (
                    type(offset) is not int
                    or type(limit) is not int
                    or not (0 <= offset <= 100 and 1 <= limit <= 10)
                ):
                    raise DraftError("CHAT_INVALID_REQUEST")
                state = self._read()
                total = len(state["scenarios"])
                items = []
                for identity in state["scenarios"][offset : offset + limit]:
                    record = identity["versions"][-1]
                    items.append(
                        {
                            **{k: record[k] for k in ("id", "version", "digest")},
                            **{
                                k: record["definition"][k]
                                for k in ("name", "profile_id", "target_id", "sink_id")
                            },
                        }
                    )
                end = offset + len(items)
                result = {
                    "kind": kind,
                    "scenario_revision": state["revision"],
                    "total": total,
                    "offset": offset,
                    "limit": limit,
                    "items": items,
                    "next_offset": end if end < total else None,
                }
            elif kind == "scenario":
                if set(arguments) != {"kind", "id", "version", "digest"}:
                    raise DraftError("CHAT_INVALID_REQUEST")
                state = self._read()
                result = {
                    "kind": kind,
                    "scenario_revision": state["revision"],
                    "scenario": self._select(
                        state, {k: arguments[k] for k in ("id", "version", "digest")}
                    ),
                }
            else:
                raise DraftError("CHAT_INVALID_REQUEST")
            scenarios.bounded_output(result, 32768, "CHAT_TOOL_LIMIT")
            return result

    def _resolve(self, intent, expected_settings_revision):
        if type(intent) is not dict or set(intent) != {
            "operation",
            "expected_scenario_revision",
            "expected_draft_revision",
            "base",
            "input_source",
        }:
            raise DraftError("CHAT_INVALID_REQUEST")
        for key, cap in (
            ("expected_scenario_revision", 1000),
            ("expected_draft_revision", 9007199254740991),
        ):
            if type(intent[key]) is not int or not 0 <= intent[key] <= cap:
                raise DraftError("CHAT_INVALID_REQUEST")
        if (
            type(expected_settings_revision) is not int
            or not 0 <= expected_settings_revision <= 9007199254740991
        ):
            raise DraftError("CHAT_INVALID_REQUEST")
        input_source = intent["input_source"]
        if (
            type(input_source) is not dict
            or (
                input_source.get("source") == "operator"
                and set(input_source) != {"source", "inputs"}
            )
            or (
                input_source.get("source") == "scenario_version"
                and set(input_source) != {"source", "reference"}
            )
        ):
            raise DraftError("CHAT_INVALID_REQUEST")
        state, source = self._read(), self.drafts._read()
        self._admission()
        if (
            intent["expected_scenario_revision"] != state["revision"]
            or intent["expected_draft_revision"] != source.audit_total
            or expected_settings_revision != source.ai_settings.revision
        ):
            raise DraftError("CHAT_TOOL_CONFLICT")
        before = None
        if intent["operation"] == "scenario_create":
            if intent["base"] is not None:
                raise DraftError("CHAT_INVALID_REQUEST")
        elif intent["operation"] == "scenario_append":
            before = self._select(state, intent["base"])
            identity = next(s for s in state["scenarios"] if s["id"] == before["id"])
            if before != identity["versions"][-1]:
                raise DraftError("CHAT_TOOL_CONFLICT")
        else:
            raise DraftError("CHAT_INVALID_REQUEST")
        input_source = intent["input_source"]
        if input_source["source"] == "operator":
            inputs = deepcopy(input_source["inputs"])
        elif input_source["source"] == "scenario_version":
            selected = self._select(state, input_source["reference"])
            inputs = {k: deepcopy(selected["definition"][k]) for k in PROTECTED_FIELDS}
        else:
            raise DraftError("CHAT_INVALID_REQUEST")
        self._protected(inputs)
        self._references(source, inputs)
        if (before is None and len(state["scenarios"]) >= 100) or (
            before is not None and before["version"] >= 10
        ):
            raise DraftError("SCENARIO_LIMIT_REACHED")
        resolved = {
            "resolved_inputs": inputs,
            "inputs_digest": persistence.digest(
                canonical({"input_source": intent["input_source"], "resolved_inputs": inputs})
            ),
        }
        return state, source, resolved, before

    @staticmethod
    def _select(state, reference):
        from pydantic import TypeAdapter

        from .validation import Identifier

        if type(reference) is not dict or set(reference) != {"id", "version", "digest"}:
            raise DraftError("CHAT_INVALID_REQUEST")
        TypeAdapter(Identifier).validate_python(reference["id"], strict=True)
        if type(reference["version"]) is not int or not 1 <= reference["version"] <= 10:
            raise DraftError("CHAT_INVALID_REQUEST")
        if not persistence.is_hash(reference["digest"]):
            raise DraftError("CHAT_INVALID_REQUEST")
        identity = next((s for s in state["scenarios"] if s["id"] == reference["id"]), None)
        if identity is None or reference["version"] > len(identity["versions"]):
            raise DraftError("SCENARIO_NOT_FOUND")
        record = identity["versions"][reference["version"] - 1]
        if record["digest"] != reference["digest"]:
            raise DraftError("CHAT_TOOL_CONFLICT")
        return record

    @staticmethod
    def _protected(inputs):
        from pydantic import TypeAdapter

        from .validation import Identifier, Name

        if type(inputs) is not dict or set(inputs) != PROTECTED_FIELDS:
            raise DraftError("CHAT_INVALID_REQUEST")
        for key in ("target_id", "sink_id"):
            TypeAdapter(Identifier).validate_python(inputs[key], strict=True)
        for key in ("dut_version", "policy_version"):
            TypeAdapter(Name).validate_python(inputs[key], strict=True)
        scenarios.TrafficBudget.model_validate(inputs["traffic_budget"])
        scenarios.StopConditions.model_validate(inputs["stop_conditions"])
        if inputs["pcap_asset"] is not None:
            scenarios.PcapAsset.model_validate(inputs["pcap_asset"])

    @staticmethod
    def _references(source, inputs):
        target = next((t for t in source.targets if t.id == inputs["target_id"]), None)
        sink = next((t for t in source.targets if t.id == inputs["sink_id"]), None)
        if target is None or sink is None or target.kind != "DUT" or sink.kind != "SINK":
            raise DraftError("INVALID_REFERENCE")
        return target, sink

    def _prepare_chat(self, grant, arguments, expected_settings_revision):
        intent = grant["intent"]
        state, source, resolved, before = self._resolve(intent, expected_settings_revision)
        if (
            type(grant["settings_revision"]) is not int
            or grant["settings_revision"] != expected_settings_revision
            or any(canonical(grant[k]) != canonical(v) for k, v in resolved.items())
        ):
            raise DraftError("CHAT_TOOL_CONFLICT")
        keys = {"expected_scenario_revision", "expected_draft_revision", "definition"}
        if before is not None:
            keys.add("base")
        if set(arguments) != keys:
            raise DraftError("CHAT_INVALID_REQUEST")
        if before is not None and canonical(arguments["base"]) != canonical(intent["base"]):
            raise DraftError("CHAT_TOOL_CONFLICT")
        for key in ("expected_scenario_revision", "expected_draft_revision"):
            if type(arguments[key]) is not int or arguments[key] != intent[key]:
                raise DraftError("CHAT_TOOL_CONFLICT")
        proposed = arguments["definition"]
        if (
            type(proposed) is not dict
            or set(proposed) != set(scenarios.ScenarioDefinition.model_fields) - PROTECTED_FIELDS
        ):
            raise DraftError("CHAT_INVALID_REQUEST")
        definition = scenarios.ScenarioDefinition.model_validate(
            {**proposed, **resolved["resolved_inputs"]}
        ).model_dump()
        identity, snapshots = self._prepare_definition(
            state, source, definition, None if before is None else before["id"]
        )
        self._size_preparation(state, identity, definition, snapshots)
        prepared = {
            "expected_scenario_revision": state["revision"],
            "expected_draft_revision": source.audit_total,
            "before": before,
            "after": definition,
            "snapshots": snapshots,
            "input_source": deepcopy(intent["input_source"]),
            "inputs_digest": resolved["inputs_digest"],
        }
        return state, identity, prepared

    @staticmethod
    def _size_preparation(state, identity, definition, snapshots):
        # Sizing-only strings, never generated fields or semantically validated
        # saved records. datetime.isoformat's maximal UTC representation is 32.
        witness = {
            "id": "0" * 36 if identity is None else identity["id"],
            "version": 1 if identity is None else len(identity["versions"]) + 1,
            "created_at": "0" * 32,
            "status": "definition",
            "execution_enabled": False,
            "definition": definition,
            **snapshots,
            "digest": "0" * 64,
        }
        scenarios.bounded_output(witness, MAX_RECORD_BYTES, "VALIDATION_ERROR")
        candidate = deepcopy(state)
        if identity is None:
            candidate["scenarios"].append({"id": witness["id"], "versions": [witness]})
        else:
            selected = next(s for s in candidate["scenarios"] if s["id"] == identity["id"])
            selected["versions"].append(witness)
        candidate["revision"] += 1
        scenarios.bounded_output(candidate, MAX_STATE_BYTES, "VALIDATION_ERROR")

    def prepare_scenario(self, grant, arguments, expected_settings_revision):
        with self.lock, self.drafts.lock:
            return self._prepare_chat(grant, arguments, expected_settings_revision)[2]

    def save_receipt(
        self, grant, arguments, proposal, publication_guard, expected_settings_revision
    ):
        with self.lock, self.drafts.lock:
            try:
                state, identity, prepared = self._prepare_chat(
                    grant, arguments, expected_settings_revision
                )
            except (ValueError, TypeError, KeyError):
                raise DraftError("CHAT_INVALID_REQUEST") from None
            extras = {"schema_version", "operation", "digest", "expires_at"}
            if (
                type(proposal) is not dict
                or set(proposal) not in (set(prepared), set(prepared) | extras)
                or any(canonical(proposal.get(k)) != canonical(v) for k, v in prepared.items())
                or (
                    "schema_version" in proposal
                    and (
                        type(proposal["schema_version"]) is not int
                        or proposal["schema_version"] != 4
                        or proposal["operation"] != grant["intent"]["operation"]
                    )
                )
            ):
                raise DraftError("CHAT_TOOL_CONFLICT")
            record = self._candidate(state, identity, prepared["after"], prepared["snapshots"])
            result = {
                "kind": "scenario_created" if prepared["before"] is None else "scenario_appended",
                "before_scenario_revision": state["revision"] - 1,
                "after_scenario_revision": state["revision"],
                "source_draft_revision": prepared["expected_draft_revision"],
                "scenario": record,
                "execution_enabled": False,
            }
            scenarios.bounded_output(result, 32768, "CHAT_TOOL_LIMIT")

            def readback():
                actual = persistence.read_registry(self.path)[1]
                persistence.require(canonical(actual) == canonical(state))
                selected = next(s for s in actual["scenarios"] if s["id"] == record["id"])
                return {**result, "scenario": selected["versions"][record["version"] - 1]}

            return self._write(state, publication_guard=publication_guard, readback=readback)

    def save(self, value: ScenarioInput, scenario_id: str | None = None) -> dict:
        # Scenario -> draft is the only lock order. Keep the selected source stable
        # through publication; historical readers deliberately never acquire it.
        with self.lock, self.drafts.lock:
            state = self._read()
            source = self.drafts._read()
            self._admission()
            if value.revision != state["revision"]:
                raise DraftError("SCENARIO_CONFLICT")
            definition = value.definition.model_dump()
            identity, snapshots = self._prepare_definition(state, source, definition, scenario_id)
            record = self._candidate(state, identity, definition, snapshots)
            receipt = {
                "revision": state["revision"],
                "scenario": record,
                "execution_enabled": False,
            }
            scenarios.bounded_output(receipt, scenarios.MAX_RESPONSE_BYTES, "VALIDATION_ERROR")
            self._write(state)
            return receipt
