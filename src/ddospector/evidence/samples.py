"""File-only CLI: python -m ddospector.evidence.samples --output /new/directory.

Linux no-replace publication, with pinned private staging and bounded validation.
The random private creation namespace is trusted until its first handle is acquired;
this is not protection against a hostile same-UID actor during that acquisition.
Checks establish an observed completion snapshot, not an atomic snapshot against
arbitrary simultaneous writers or immutability after completion. Importers must
rehash original bytes; this manifest is not a real-DUT or ownership certificate.
"""
import argparse
import ctypes
import errno
import io
import json
import os
import secrets
import stat
import sys
from pathlib import Path

from aiddos.evidence.pcap import parse_capture
from aiddos.evidence.samples import SAMPLE_IDS, make_sample


def _rename_noreplace(parent_fd: int, source: str | Path, target: str | Path) -> None:
    """The only publication primitive. Never fall back to overwrite-capable rename."""
    if sys.platform != "linux":
        raise OSError(errno.ENOTSUP, "Linux renameat2(RENAME_NOREPLACE) required")
    try:
        rename = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError as exc:
        raise OSError(errno.ENOTSUP, "renameat2 is unavailable") from exc
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                       ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(parent_fd, os.fsencode(source), parent_fd, os.fsencode(target), 1):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), os.fspath(target))


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _metadata(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class _Stage:
    """Pins outlive every identity check; failures retain data, never clean paths."""

    def __init__(self, output: Path):
        self.output = output
        self.fds: list[int] = []
        self.files: dict[str, tuple[int, bytes, os.stat_result]] = {}
        self.private_name: str | None = None
        self.name = ""

    def acquire(self) -> None:
        # No parent creation, no following the final parent component.
        if sys.platform != "linux":
            raise OSError(errno.ENOTSUP, "Linux renameat2(RENAME_NOREPLACE) required")
        self.parent_fd = os.open(self.output.parent,
                                 os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        self.fds.append(self.parent_fd)
        try:
            os.stat(self.output.name, dir_fd=self.parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), str(self.output))
        # A same-path no-replace collision tests the actual kernel/filesystem
        # without creating output. Any result except EEXIST refuses admission.
        # Use the real parent pathname, not '.', which Linux rejects with EBUSY.
        try:
            _rename_noreplace(self.parent_fd, self.output.parent, self.output.parent)
        except FileExistsError:
            pass
        else:
            raise OSError(errno.ENOTSUP, "no-replace capability check did not refuse collision")
        name = ".pcap-stage-" + secrets.token_hex(16)
        os.mkdir(name, mode=0o700, dir_fd=self.parent_fd)
        self.private_name = self.name = name
        self.dir_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                              dir_fd=self.parent_fd)
        self.fds.append(self.dir_fd)
        os.fchmod(self.dir_fd, 0o700)
        self.root_info = os.fstat(self.dir_fd)
        self.check_root()

    def check_root(self) -> None:
        parent = os.stat(self.output.parent, follow_symlinks=False)
        if (_identity(parent) != _identity(os.fstat(self.parent_fd))
                or not stat.S_ISDIR(parent.st_mode)):
            raise OSError("output parent binding changed")
        root = os.fstat(self.dir_fd)
        named = os.stat(self.name, dir_fd=self.parent_fd, follow_symlinks=False)
        if (_identity(named) != _identity(root) or _identity(root) != _identity(self.root_info)
                or not stat.S_ISDIR(named.st_mode) or stat.S_IMODE(root.st_mode) != 0o700
                or root.st_uid != os.geteuid() or root.st_gid != self.root_info.st_gid
                or root.st_nlink != self.root_info.st_nlink):
            raise OSError("private output directory custody changed")

    def check_names(self) -> None:
        # Never materialize an unbounded foreign directory listing.
        entries = os.scandir(self.dir_fd)
        primary = None
        try:
            seen = set()
            for _ in range(len(self.files) + 1):
                entry = next(entries, None)
                if entry is None:
                    break
                if entry.name not in self.files or entry.name in seen:
                    raise OSError("unexpected output child name")
                seen.add(entry.name)
            if seen != self.files.keys():
                raise OSError("missing output child name")
        except BaseException as exc:
            primary = exc
            raise
        finally:
            try:
                entries.close()
            except OSError as exc:
                if primary is None:
                    raise
                primary.add_note(f"directory iterator close also failed: {exc}")

    def validate(self) -> None:
        self.check_root()
        self.check_names()
        for filename, (fd, expected, created) in self.files.items():
            before = os.fstat(fd)
            if (_identity(before) != _identity(created) or not stat.S_ISREG(before.st_mode)
                    or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1
                    or before.st_uid != os.geteuid() or before.st_gid != created.st_gid
                    or before.st_size != len(expected)):
                raise OSError(f"capture/manifest metadata changed: {filename}")
            # Bounded exact-byte comparison, including one byte beyond expected EOF.
            offset = 0
            while offset <= len(expected):
                chunk = os.pread(fd, min(65536, len(expected) + 1 - offset), offset)
                if not chunk:
                    if offset != len(expected):
                        raise OSError(f"capture/manifest truncated: {filename}")
                    break
                if chunk != expected[offset:offset + len(chunk)]:
                    raise OSError(f"capture/manifest content changed: {filename}")
                offset += len(chunk)
            after = os.fstat(fd)
            named = os.stat(filename, dir_fd=self.dir_fd, follow_symlinks=False)
            if _metadata(before) != _metadata(after) or _metadata(named) != _metadata(after):
                raise OSError(f"capture/manifest custody changed: {filename}")
        self.check_root()

    def retained_note(self) -> str:
        if self.private_name is None:
            return "no private output acquired; no cleanup attempted"
        return ("data retained without cleanup; private allocation: "
                f"{self.output.parent / self.private_name}; "
                f"last expected binding: {self.output.parent / self.name} "
                "(binding may have changed)")

    def close(self, primary: BaseException | None) -> None:
        first = primary
        while self.fds:
            fd = self.fds.pop()  # relinquish before close; never retry ambiguous close
            try:
                os.close(fd)
            except OSError as exc:
                if first is None:
                    first = exc
                else:
                    first.add_note(f"descriptor close also failed: {exc}")
        if primary is None and first is not None:
            first.add_note(self.retained_note())
            raise first


def _write_private(stage: _Stage, filename: str, data: bytes) -> None:
    # Only generated fixed basenames, never the requested public path as parent.
    fd = os.open(filename, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600, dir_fd=stage.dir_fd)
    stage.fds.append(fd)
    os.fchmod(fd, 0o600)
    stage.files[filename] = fd, data, os.fstat(fd)
    offset = 0
    while offset < len(data):
        written = os.write(fd, data[offset:])
        if written <= 0:
            raise OSError("short output write made no progress")
        offset += written


def _populate(stage: _Stage) -> None:
    manifest = {
        "source": "synthetic",
        "generator": "ddospector.evidence.samples/P2-00-v1",
        "packet_model": "TCP data segments; not full TCP/application sessions",
        "timestamps": "Fixed synthetic timestamps; not measured latency",
        "defense_verdict": None,
        "samples": [],
    }
    for sample_id in SAMPLE_IDS:
        pair = make_sample(sample_id)
        item = {"sample_id": sample_id, "coverage": pair.coverage}
        for side in ("ingress", "egress"):
            raw = getattr(pair, side)
            facts = parse_capture(io.BytesIO(raw))
            filename = f"{sample_id}-{side}.pcap"
            _write_private(stage, filename, raw)
            item[side] = {"filename": filename, "size_bytes": facts.size_bytes,
                          "sha256": facts.sha256, "packet_count": facts.packet_count}
        item["fixture_expectation"] = {
            "label": "Synthetic ground truth only; evaluator must compute from PCAP bytes",
            "criterion": "TCP packet-record multiset correspondence",
            "lower_bound_basis_points": 9500,
            "upper_bound_basis_points": 10000,
            "expected_outcome": {"complete": "SATISFIED", "violation": "VIOLATED",
                                 "unknown": "UNKNOWN"}[sample_id],
            "expected_matched_records": 10 if sample_id == "complete" else 9,
        }
        manifest["samples"].append(item)
    stage.validate()  # Do not certify memory-derived metadata without checking disk.
    _write_private(stage, "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())


def _generate(output: Path) -> None:
    stage = _Stage(output)
    primary = None
    try:
        stage.acquire()
        _populate(stage)
        stage.validate()
        _rename_noreplace(stage.parent_fd, stage.name, output.name)
        stage.name = output.name
        stage.validate()  # Final guarded observation; no further output writes.
    except BaseException as exc:
        primary = exc
        exc.add_note(stage.retained_note())
        raise
    finally:
        stage.close(primary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate synthetic files only; never send packets")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if not args.output.is_absolute():
        parser.error("--output must be an absolute new directory")
    try:
        _generate(args.output)
    except OSError as exc:
        print(f"sample generation failed: {exc}", file=sys.stderr)
        for note in getattr(exc, "__notes__", ()):
            print(note, file=sys.stderr)
        return 1
    print(f"Created six synthetic PCAPs and manifest.json in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
