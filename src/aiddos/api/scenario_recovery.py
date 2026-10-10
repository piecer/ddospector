"""Offline S01 inspection/recovery. Stop cooperating writers before invocation.

No global application import, server, replay, rollback, or failure cleanup.
"""

import argparse
import ctypes
import os
import secrets
import sys
from contextlib import suppress
from pathlib import Path

from . import scenario_persistence as io
from .store import DraftStore


def storage_paths(draft_path):
    path = Path(draft_path)
    io.require(path.is_absolute() and "\x00" not in str(path))
    registry = DraftStore(path).path.with_name(path.name + ".scenarios.json")
    return (
        registry,
        registry.with_name(registry.name + ".s01-recovery"),
        registry.with_name(registry.name + ".s01-pending"),
    )


def bounded_json(value):
    raw = io.canonical(value) + b"\n"
    io.require(len(raw) <= 4096)
    return raw


def inspect_storage(draft_path):
    registry, receipt, pending = storage_paths(draft_path)
    current, state = io.read_registry(registry)
    raw = io.read_bytes(receipt, 4096, missing=True, mode=0o600)
    entries = io.pending_entries(pending, missing=True)
    frame = None
    phase = "MISSING" if raw is None else "MALFORMED"
    if raw is not None:
        try:
            frame = io.decode_frame(raw)
            phase = frame["phase"]
        except (ValueError, RecursionError):
            pass
    observation = {
        "phase": phase,
        "receipt_present": raw is not None,
        "receipt_bytes": len(raw) if raw is not None else 0,
        "record_hash": io.digest(raw or b""),
        "registry_hash": "ABSENT" if current is None else io.digest(current),
        "registry_revision": state["revision"],
        "registry_bytes": len(current) if current is not None else 0,
        "pending_present": entries is not None,
        "entries": entries or {},
    }
    observation["review"] = io.digest(io.canonical(observation))
    bounded_json(observation)
    return observation, raw, frame


OBSERVATION_KEYS = {
    "phase",
    "receipt_present",
    "receipt_bytes",
    "record_hash",
    "registry_hash",
    "registry_revision",
    "registry_bytes",
    "pending_present",
    "entries",
}


def validate_observation(value):
    io.require(type(value) is dict and set(value) == OBSERVATION_KEYS)
    io.require(
        type(value["phase"]) is str and value["phase"] in io.PHASES | {"MISSING", "MALFORMED"}
    )
    for name in ("receipt_present", "pending_present"):
        io.require(type(value[name]) is bool)
    for name, cap in (
        ("receipt_bytes", 4096),
        ("registry_bytes", io.MAX_BYTES),
        ("registry_revision", 1000),
    ):
        io.require(type(value[name]) is int and 0 <= value[name] <= cap)
    io.require(io.is_hash(value["record_hash"]))
    io.require(value["registry_hash"] == "ABSENT" or io.is_hash(value["registry_hash"]))
    io.validate_entries(value["entries"])
    if not value["receipt_present"]:
        io.require(
            value["phase"] == "MISSING"
            and value["receipt_bytes"] == 0
            and value["record_hash"] == io.digest(b"")
        )
    if not value["pending_present"]:
        io.require(value["entries"] == {})
    if value["registry_hash"] == "ABSENT":
        io.require(value["registry_bytes"] == value["registry_revision"] == 0)
    return value


def validate_decision(raw):
    from .encoding import strict_json

    value = strict_json(raw)
    io.require(
        type(value) is dict
        and set(value)
        == {
            "format_version",
            "action",
            "review",
            "observation",
            "incomplete_attempt_abandoned",
            "empty_registry_confirmed",
        }
    )
    io.require(type(value["format_version"]) is int and value["format_version"] == 1)
    io.require(type(value["action"]) is str and value["action"] in {"RECONCILE", "ACCEPT_CURRENT"})
    observation = validate_observation(value["observation"])
    io.require(
        io.is_hash(value["review"]) and value["review"] == io.digest(io.canonical(observation))
    )
    accepted = value["action"] == "ACCEPT_CURRENT"
    io.require(
        type(value["incomplete_attempt_abandoned"]) is bool
        and value["incomplete_attempt_abandoned"] == accepted
    )
    io.require(
        type(value["empty_registry_confirmed"]) is bool
        and value["empty_registry_confirmed"]
        == (accepted and observation["registry_hash"] == "ABSENT")
    )
    io.require(bounded_json(value) == raw)
    return value


def checked_archive_path(archive, registry, receipt, pending, *, fresh):
    io.require(type(archive) is str and "\x00" not in archive and len(archive.encode()) <= 1024)
    path = Path(archive)
    io.require(path.is_absolute() and str(path) == archive and ".." not in path.parts)
    # Refuse symlink traversal rather than normalizing an operator's authority token.
    io.require(path.parent.resolve(strict=True) == path.parent)
    for protected in (registry, receipt, pending):
        io.require(path != protected and not path.is_relative_to(protected))
    with (
        io.descriptor(path.parent, os.O_RDONLY | os.O_DIRECTORY) as dest,
        io.descriptor(registry.parent, os.O_RDONLY | os.O_DIRECTORY) as source,
    ):
        io.require(os.fstat(dest).st_dev == os.fstat(source).st_dev)
    if fresh:
        try:
            path.lstat()
        except FileNotFoundError:
            pass
        else:
            raise io.InvalidStorage("Archive already exists")
    return path


def rename_noreplace(source, destination):
    library = ctypes.CDLL(None, use_errno=True)
    function = getattr(library, "renameat2", None)
    io.require(function is not None)
    function.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    function.restype = ctypes.c_int
    if function(-100, os.fsencode(source), -100, os.fsencode(destination), 1) != 0:
        error = ctypes.get_errno()
        raise OSError(error, "Atomic no-replace archive move failed")


def current_matches(registry, expected):
    raw, state = io.read_registry(registry)
    actual = "ABSENT" if raw is None else io.digest(raw)
    io.require(actual == expected)
    return raw, state


def verify_archive(frame, registry, receipt, pending, *, complete=True):
    io.validate_frame(frame)
    recovery = frame["recovery"]
    io.require(type(recovery) is dict)
    archive = checked_archive_path(recovery["archive"], registry, receipt, pending, fresh=False)
    with io.descriptor(archive, os.O_RDONLY | os.O_DIRECTORY) as fd:
        names = set()
        with io.scan_directory(fd) as entries:
            for entry in entries:
                io.require(
                    len(names) < 3 and entry.name in {"receipt.bin", "decision.json", "pending"}
                )
                names.add(entry.name)
        io.require({"receipt.bin", "decision.json"} <= names)
        if complete:
            io.require("pending" in names)
        raw = io.read_bytes("receipt.bin", 4096, dir_fd=fd)
        decision_raw = io.read_bytes("decision.json", 4096, dir_fd=fd)
    io.require(
        io.digest(raw) == recovery["record_hash"]
        and io.digest(decision_raw) == recovery["decision_hash"]
    )
    decision = validate_decision(decision_raw)
    observation = decision["observation"]
    io.require(
        observation["record_hash"] == recovery["record_hash"]
        and observation["receipt_bytes"] == len(raw)
        and observation["entries"] == recovery["entries"]
        and observation["registry_hash"] == recovery["registry_hash"]
    )
    actual_phase = "MISSING" if not observation["receipt_present"] else "MALFORMED"
    if observation["receipt_present"]:
        with suppress(ValueError, RecursionError):
            actual_phase = io.decode_frame(raw)["phase"]
    io.require(actual_phase == observation["phase"])
    current, state = current_matches(registry, recovery["registry_hash"])
    io.require(
        state["revision"] == observation["registry_revision"]
        and (len(current) if current is not None else 0) == observation["registry_bytes"]
    )
    if complete:
        io.require(io.pending_entries(archive / "pending") == recovery["entries"])
    return decision


def resume_witnesses(frame, registry, receipt, pending):
    """An unmoved reviewed slot is preserved material, not a lost archive."""
    decision = verify_archive(frame, registry, receipt, pending, complete=False)
    archive = Path(frame["recovery"]["archive"])
    expected = frame["recovery"]["entries"]
    archived = io.pending_entries(archive / "pending", missing=True)
    live = io.pending_entries(pending, missing=True)
    if archived is None:
        io.require(frame["phase"] == "RECOVERING")
        if decision["observation"]["pending_present"]:
            io.require(live == expected)
        else:
            io.require(live is None)
    else:
        io.require(archived == expected and live in (None, {}))
    return decision, archived


def resume_recovery(draft_path, observation, original, frame, archive, accept_current):
    registry, receipt, pending = storage_paths(draft_path)
    io.require(str(archive) == frame["recovery"]["archive"])
    archive = checked_archive_path(str(archive), registry, receipt, pending, fresh=False)
    decision, archived = resume_witnesses(frame, registry, receipt, pending)
    action = "ACCEPT_CURRENT" if accept_current else "RECONCILE"
    io.require(decision["action"] == action)
    expected = frame["recovery"]["entries"]
    plan = {**frame, "phase": "RECOVERING", "token_hash": None}
    recovering_raw = io.encode_frame(plan)
    ticket = secrets.token_hex(32)
    ready_raw = io.encode_frame(
        {**plan, "phase": "READY", "token_hash": io.digest(ticket.encode())}
    )
    result = {
        "status": "READY",
        "action": action,
        "archive": str(archive),
        "registry_hash": frame["recovery"]["registry_hash"],
        "ticket": ticket,
    }
    bounded_json(result)
    io.require(
        inspect_storage(draft_path)[0] == observation
        and io.read_bytes(receipt, 4096, mode=0o600) == original
    )
    io.write_frame(receipt, recovering_raw)
    if archived is None:
        if decision["observation"]["pending_present"]:
            rename_noreplace(pending, archive / "pending")
        else:
            (archive / "pending").mkdir(mode=0o700)
    verify_archive(plan, registry, receipt, pending)
    for name in expected:
        with io.descriptor(archive / "pending" / name, os.O_RDONLY) as fd:
            os.fsync(fd)
    io.sync_directory(archive / "pending")
    io.sync_directory(archive)
    io.sync_directory(pending.parent)
    verify_archive(plan, registry, receipt, pending)
    io.require(io.read_bytes(receipt, 4096, mode=0o600) == recovering_raw)
    live = io.pending_entries(pending, missing=True)
    if live is None:
        pending.mkdir(mode=0o700)
    else:
        io.require(live == {})
    io.sync_directory(pending)
    io.sync_directory(pending.parent)
    io.write_frame(receipt, ready_raw)
    return result


def recover(draft_path, review, archive, *, accept_current=False, confirm_empty_registry=False):
    registry, receipt, pending = storage_paths(draft_path)
    observation, original, frame = inspect_storage(draft_path)
    io.require(io.is_hash(review) and observation["review"] == review)
    empty = observation["registry_hash"] == "ABSENT"
    io.require(not confirm_empty_registry or (accept_current and empty))
    io.require(not (accept_current and empty) or confirm_empty_registry)
    if frame is not None and frame["phase"] in {"RECOVERING", "READY"}:
        if not accept_current or str(archive) == frame["recovery"]["archive"]:
            return resume_recovery(
                draft_path, observation, original, frame, archive, accept_current
            )
        try:
            resume_witnesses(frame, registry, receipt, pending)
        except (FileNotFoundError, ValueError, RecursionError):
            # Explicit new review may abandon missing/invalid preservation material.
            # Permission/device I/O errors are not evidence of loss: those still deny.
            pass
        else:
            raise io.InvalidStorage("Intact recovery plan must use its original archive")
    if accept_current:
        if frame is None:
            frame = {
                "version": 1,
                "phase": "ACTIVE",
                "generation": secrets.token_hex(16),
                "pre": observation["registry_hash"],
                "post": None,
                "size": 0,
                "recovery": None,
                "token_hash": None,
            }
    else:
        io.require(frame is not None and observation["pending_present"])
    phase = frame["phase"]
    if accept_current:
        pass
    elif phase == "PREPARED":
        io.require("candidate" in observation["entries"])
    elif phase in {"PUBLISHED", "CLEAN"}:
        io.require(
            observation["registry_hash"] == frame["post"]
            and observation["registry_bytes"] == frame["size"]
        )
    elif phase == "ACTIVE":
        io.require(not observation["entries"] and observation["registry_hash"] == frame["pre"])
    else:
        raise io.InvalidStorage("Recovery plan requires explicit resume")
    action = "ACCEPT_CURRENT" if accept_current else "RECONCILE"
    archive = checked_archive_path(str(archive), registry, receipt, pending, fresh=True)
    decision = {
        "format_version": 1,
        "action": action,
        "review": review,
        "observation": {k: v for k, v in observation.items() if k != "review"},
        "incomplete_attempt_abandoned": accept_current,
        "empty_registry_confirmed": accept_current and empty,
    }
    decision_raw = bounded_json(decision)
    validate_decision(decision_raw)
    plan = {
        **frame,
        "phase": "RECOVERING",
        "token_hash": None,
        "recovery": {
            "archive": str(archive),
            "record_hash": io.digest(original or b""),
            "decision_hash": io.digest(decision_raw),
            "registry_hash": observation["registry_hash"],
            "entries": observation["entries"],
        },
    }
    recovering_raw = io.encode_frame(plan)
    ticket = secrets.token_hex(32)
    ready = {**plan, "phase": "READY", "token_hash": io.digest(ticket.encode("ascii"))}
    ready_raw = io.encode_frame(ready)
    result = {
        "status": "READY",
        "action": action,
        "archive": str(archive),
        "registry_hash": observation["registry_hash"],
        "ticket": ticket,
    }
    bounded_json(result)
    archive.mkdir(mode=0o700)
    io.write_candidate(archive / "receipt.bin", original or b"")
    io.write_candidate(archive / "decision.json", decision_raw)
    io.sync_directory(archive)
    io.sync_directory(archive.parent)
    # Review again before establishing authority to move; never restore changed data.
    io.require(inspect_storage(draft_path)[0] == observation)
    io.write_frame(receipt, recovering_raw, create=original is None)
    io.sync_directory(receipt.parent)
    if observation["pending_present"]:
        rename_noreplace(pending, archive / "pending")
    else:
        (archive / "pending").mkdir(mode=0o700)
    verify_archive(plan, registry, receipt, pending)
    for name in plan["recovery"]["entries"]:
        with io.descriptor(archive / "pending" / name, os.O_RDONLY) as fd:
            os.fsync(fd)
    io.sync_directory(archive / "pending")
    io.sync_directory(archive)
    io.sync_directory(pending.parent)
    verify_archive(plan, registry, receipt, pending)
    io.require(io.read_bytes(receipt, 4096, mode=0o600) == recovering_raw)
    pending.mkdir(mode=0o700)
    io.sync_directory(pending)
    io.sync_directory(pending.parent)
    io.write_frame(receipt, ready_raw)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    inspect_parser = sub.add_parser("inspect")
    inspect_parser.add_argument("--draft-path", required=True)
    recovery_parser = sub.add_parser("recover")
    recovery_parser.add_argument("--draft-path", required=True)
    recovery_parser.add_argument("--review", required=True)
    recovery_parser.add_argument("--archive", required=True)
    recovery_parser.add_argument("--accept-current", action="store_true")
    recovery_parser.add_argument("--confirm-empty-registry", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = (
            inspect_storage(args.draft_path)[0]
            if args.command == "inspect"
            else recover(
                args.draft_path,
                args.review,
                args.archive,
                accept_current=args.accept_current,
                confirm_empty_registry=args.confirm_empty_registry,
            )
        )
        raw = bounded_json(result)
        io.require(sys.stdout.buffer.write(raw) == len(raw))
        sys.stdout.buffer.flush()
        return 0
    except (OSError, ValueError, RecursionError):
        with suppress(OSError):
            print(
                "S01 recovery refused; stop writers and review bounded storage material.",
                file=sys.stderr,
            )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
