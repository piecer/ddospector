"""S01-only bounded persistence primitives. No failure-path pathname cleanup."""

import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path

from .encoding import strict_json
from .scenarios import ScenarioState

MAX_BYTES = 16777216
FRAME_BYTES = 4096
PHASES = {"ACTIVE", "PREPARED", "PUBLISHED", "CLEAN", "RECOVERING", "READY"}
HEX = re.compile(r"[0-9a-f]{64}\Z")


class InvalidStorage(ValueError):
    """Closed invalid-state result; never reflected by HTTP or CLI."""


def require(condition):
    if not condition:
        raise InvalidStorage("Invalid S01 storage")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("ascii")


@contextmanager
def descriptor(path, flags, mode=0o600, *, dir_fd=None, missing=False):
    try:
        fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, mode, dir_fd=dir_fd)
    except FileNotFoundError:
        if not missing:
            raise
        yield None
        return
    try:
        yield fd
    except BaseException:
        # The close attempt retires ownership, including real-close-then-EIO.
        try:  # noqa: SIM105 - do not allocate a cleanup manager after primary failure
            os.close(fd)
        except BaseException:
            pass
        raise
    else:
        os.close(fd)


@contextmanager
def stream_for(fd, mode):
    stream = os.fdopen(fd, mode, closefd=False)
    try:
        yield stream
    except BaseException:
        try:  # noqa: SIM105 - preserve the primary even on secondary close failure
            stream.close()
        except BaseException:
            pass
        raise
    else:
        stream.close()


def read_bytes(path, cap, *, missing=False, dir_fd=None, mode=None):
    with descriptor(path, os.O_RDONLY, dir_fd=dir_fd, missing=missing) as fd:
        if fd is None:
            return None
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_size <= cap)
        if mode is not None:
            require(stat.S_IMODE(info.st_mode) == mode)
        with stream_for(fd, "rb") as stream:
            raw = stream.read(cap + 1)
        require(len(raw) <= cap)
        return raw


def read_registry(path):
    raw = read_bytes(path, MAX_BYTES, missing=True)
    state = (
        {"format_version": 1, "revision": 0, "scenarios": []} if raw is None else strict_json(raw)
    )
    return raw, ScenarioState.model_validate(state).model_dump()


def sync_directory(path):
    with descriptor(path, os.O_RDONLY | os.O_DIRECTORY) as fd:
        os.fsync(fd)


def create_parents(path):
    """Synchronize every newly created directory through its existing parent."""
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    for current in reversed(missing):
        current.mkdir(mode=0o700)
        sync_directory(current)
        sync_directory(current.parent)


@contextmanager
def scan_directory(fd):
    iterator = os.scandir(fd)
    try:
        yield iterator
    except BaseException:
        try:  # noqa: SIM105 - secondary iterator close must not mask the primary
            iterator.close()
        except BaseException:
            pass
        raise
    else:
        iterator.close()


def pending_entries(path, *, missing=False):
    with descriptor(path, os.O_RDONLY | os.O_DIRECTORY, missing=missing) as fd:
        if fd is None:
            return None
        require(stat.S_IMODE(os.fstat(fd).st_mode) == 0o700)
        names = []
        with scan_directory(fd) as iterator:
            for entry in iterator:
                require(len(names) < 2 and entry.name in {"candidate", "publish"})
                names.append(entry.name)
        result = {}
        for name in sorted(names):
            raw = read_bytes(name, MAX_BYTES, dir_fd=fd)
            result[name] = {"bytes": len(raw), "sha256": digest(raw)}
        return result


def is_hash(value):
    return type(value) is str and HEX.fullmatch(value) is not None


def validate_entries(value):
    require(type(value) is dict and value.keys() <= {"candidate", "publish"})
    for entry in value.values():
        require(type(entry) is dict and set(entry) == {"bytes", "sha256"})
        require(type(entry["bytes"]) is int and 0 <= entry["bytes"] <= MAX_BYTES)
        require(is_hash(entry["sha256"]))


def validate_frame(value):
    require(
        type(value) is dict
        and set(value)
        == {"version", "phase", "generation", "pre", "post", "size", "recovery", "token_hash"}
    )
    require(type(value["version"]) is int and value["version"] == 1)
    require(type(value["phase"]) is str and value["phase"] in PHASES)
    require(
        type(value["generation"]) is str
        and re.fullmatch(r"[0-9a-f]{32}", value["generation"]) is not None
    )
    require(value["pre"] == "ABSENT" or is_hash(value["pre"]))
    require(value["post"] is None or is_hash(value["post"]))
    require(type(value["size"]) is int and 0 <= value["size"] <= MAX_BYTES)
    if value["phase"] == "ACTIVE":
        require(value["size"] == 0 and value["post"] is None)
    if value["phase"] in {"PREPARED", "PUBLISHED", "CLEAN"}:
        require(is_hash(value["post"]))
    recovery = value["recovery"]
    if value["phase"] in {"RECOVERING", "READY"}:
        require(
            type(recovery) is dict
            and set(recovery)
            == {"archive", "record_hash", "decision_hash", "registry_hash", "entries"}
        )
        archive = recovery["archive"]
        require(
            type(archive) is str
            and "\x00" not in archive
            and len(archive.encode("utf-8")) <= 1024
            and Path(archive).is_absolute()
        )
        require(is_hash(recovery["record_hash"]) and is_hash(recovery["decision_hash"]))
        require(recovery["registry_hash"] == "ABSENT" or is_hash(recovery["registry_hash"]))
        validate_entries(recovery["entries"])
    else:
        require(recovery is None)
    require(
        is_hash(value["token_hash"]) if value["phase"] == "READY" else value["token_hash"] is None
    )
    return value


def encode_frame(value):
    raw = canonical(validate_frame(value))
    require(len(raw) <= 4052)
    body = b"S01RR001" + len(raw).to_bytes(4, "big") + raw + bytes(4052 - len(raw))
    return body + hashlib.sha256(body).digest()


def decode_frame(raw):
    require(len(raw) == FRAME_BYTES and raw[:8] == b"S01RR001")
    require(hashlib.sha256(raw[:4064]).digest() == raw[4064:])
    length = int.from_bytes(raw[8:12], "big")
    require(length <= 4052 and raw[12 + length : 4064] == bytes(4052 - length))
    value = validate_frame(strict_json(raw[12 : 12 + length]))
    require(encode_frame(value) == raw)
    return value


def write_frame(path, raw, *, create=False):
    require(len(raw) == FRAME_BYTES)
    flags = os.O_WRONLY | (os.O_CREAT | os.O_EXCL if create else 0)
    with descriptor(path, flags) as fd:
        info = os.fstat(fd)
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_size <= FRAME_BYTES
            and stat.S_IMODE(info.st_mode) == 0o600
        )
        offset = 0
        while offset < len(raw):
            count = os.pwrite(fd, raw[offset:], offset)
            require(type(count) is int and 0 < count <= len(raw) - offset)
            offset += count
        os.fsync(fd)


def write_candidate(path, raw):
    require(len(raw) <= MAX_BYTES)
    with descriptor(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL) as fd:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode))
        with stream_for(fd, "wb") as stream:
            offset = 0
            while offset < len(raw):
                count = stream.write(raw[offset:])
                require(type(count) is int and 0 < count <= len(raw) - offset)
                offset += count
            stream.flush()
            os.fsync(fd)
        return info.st_dev, info.st_ino
