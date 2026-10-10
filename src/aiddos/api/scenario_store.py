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
_LOCKS = WeakValueDictionary()
_LOCKS_GUARD = RLock()


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

    def _admission(self):
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
            self.coordinator.blocked = True
            raise DraftError("SCENARIO_STATE_UNAVAILABLE") from exc

    def _write(self, state: dict) -> None:
        with self.lock:
            self._write_locked(state)

    def _write_locked(self, state: dict) -> None:
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
            os.replace(publish, self.path)
            published = True
            persistence.sync_directory(self.pending_path)
            persistence.sync_directory(self.path.parent)
            persistence.write_frame(self.receipt_path, frames["PUBLISHED"])
            # Only normal committed-link retirement. Never cleanup an exposed name.
            candidate.unlink()
            persistence.sync_directory(self.pending_path)
            persistence.write_frame(self.receipt_path, frames["CLEAN"])
        except (OSError, ValueError, RecursionError) as exc:
            code = "SCENARIO_COMMIT_UNCERTAIN" if published else "SCENARIO_STATE_UNAVAILABLE"
            raise DraftError(code) from exc
        self.coordinator.blocked = False

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
                "target_snapshot": target.model_dump(),
                "sink_snapshot": sink.model_dump(),
                "profile_snapshot": deepcopy(
                    next(p for p in PROFILES_V1 if p["id"] == definition["profile_id"])
                ),
                "catalog_version": CATALOG_VERSION,
            }
            record["digest"] = record_digest(record)
            if len(canonical(record)) > MAX_RECORD_BYTES:
                raise DraftError("VALIDATION_ERROR")
            identity["versions"].append(record)
            state["revision"] += 1
            receipt = {
                "revision": state["revision"],
                "scenario": record,
                "execution_enabled": False,
            }
            scenarios.bounded_output(receipt, scenarios.MAX_RESPONSE_BYTES, "VALIDATION_ERROR")
            self._write(state)
            return receipt
