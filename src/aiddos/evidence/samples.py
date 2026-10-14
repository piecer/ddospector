"""Deterministic synthetic TCP data records, not TCP/application sessions.

Only bytes are constructed: no sockets, packet transmission or wall clock use.
Documentation addresses and explicitly synthetic fixed timestamps are used.
"""
import hashlib
import struct
from dataclasses import dataclass

SAMPLE_IDS = ("complete", "violation", "unknown")


@dataclass(frozen=True, slots=True)
class SamplePair:
    sample_id: str
    coverage: str
    ingress: bytes
    egress: bytes


def _checksum(data: bytes) -> int:
    padded = data + b"\0" if len(data) % 2 else data
    total = sum(struct.unpack(f"!{len(padded) // 2}H", padded))
    while total > 0xFFFF:
        total = (total & 0xFFFF) + (total >> 16)
    return total ^ 0xFFFF


def _frame(sample_id: str, identity: int, forwarded: bool) -> bytes:
    source, destination = b"\xc0\x00\x02\x0a", b"\xc6\x33\x64\x14"
    payload = f"SYNTHETIC-P2-00:{sample_id}:record-{identity:02d}".encode("ascii")
    tcp = struct.pack("!HHIIBBHHH", 41000, 42000, 1000 + identity * 128,
                      5000, 0x50, 0x18, 8192, 0, 0) + payload
    pseudo = source + destination + struct.pack("!BBH", 0, 6, len(tcp))
    tcp = tcp[:16] + struct.pack("!H", _checksum(pseudo + tcp)) + tcp[18:]
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp), identity,
                     0x4000, 63 if forwarded else 64, 6, 0, source, destination)
    ip = ip[:10] + struct.pack("!H", _checksum(ip)) + ip[12:]
    macs = bytes.fromhex("020000000004020000000003" if forwarded
                         else "020000000002020000000001")
    return macs + b"\x08\x00" + ip + tcp


def _capture(sample_id: str, forwarded: bool) -> bytes:
    # Identity zero occurs twice. Omitting only its second occurrence defeats
    # unique-set comparison while correctly changing multiset correspondence.
    identities = (*range(9), 0)
    if forwarded and sample_id != "complete":
        identities = identities[:-1]
    data = bytearray(struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))
    for index, identity in enumerate(identities):
        packet = _frame(sample_id, identity, forwarded)
        data.extend(struct.pack("<IIII", 1700000000, index * 1000 + (200 if forwarded else 0),
                                len(packet), len(packet)))
        data.extend(packet)
    return bytes(data)


def make_sample(sample_id: str) -> SamplePair:
    """Return a fresh immutable pair; unknown IDs cannot become filenames."""
    if sample_id not in SAMPLE_IDS:
        raise ValueError("unknown synthetic sample ID")
    coverage = "UNKNOWN" if sample_id == "unknown" else "COMPLETE_SYNTHETIC"
    return SamplePair(sample_id, coverage, _capture(sample_id, False), _capture(sample_id, True))


def recognize_pair(ingress_sha256: str, egress_sha256: str) -> SamplePair | None:
    """Recognize only the exact ordered pair of original byte digests.

    Regenerate this small bounded catalog rather than caching caller-visible
    objects. Names, paths and declared coverage are never identity evidence.
    """
    for sample_id in SAMPLE_IDS:
        pair = make_sample(sample_id)
        if (hashlib.sha256(pair.ingress).hexdigest() == ingress_sha256
                and hashlib.sha256(pair.egress).hexdigest() == egress_sha256):
            return pair
    return None
