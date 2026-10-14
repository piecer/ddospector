"""Forward-only classic-PCAP evidence parsing (Ethernet/IPv4/TCP only)."""
import hashlib
import struct
from collections import Counter
from dataclasses import dataclass

MAX_CAPTURE_BYTES = 1_048_576
MAX_PACKETS = 4096
MAX_FRAME_BYTES = 65535


class PcapError(ValueError):
    """Stable data-quality error; caller cancellation/I/O errors are not wrapped."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class _Reader:
    def __init__(self, stream, check):
        self.stream = stream
        self.check = check
        self.size = 0
        self.digest = hashlib.sha256()

    def exact(self, length: int, *, eof_ok=False) -> bytes:
        data = bytearray()
        while len(data) < length:
            if self.check is not None:
                self.check()
            # At the cap, a single byte probes EOF without an unbounded drain.
            request = min(length - len(data), MAX_FRAME_BYTES,
                          MAX_CAPTURE_BYTES + 1 - self.size)
            chunk = self.stream.read(request)
            if not isinstance(chunk, bytes) or len(chunk) > request:
                raise TypeError("binary reader must return at most the requested bytes")
            self.size += len(chunk)
            if self.size > MAX_CAPTURE_BYTES:
                raise PcapError("PCAP_TOO_LARGE")
            if not chunk:
                if eof_ok and not data:
                    return b""
                raise PcapError("PCAP_MALFORMED")
            self.digest.update(chunk)
            data.extend(chunk)
        return bytes(data)


@dataclass(frozen=True, slots=True)
class Capture:
    size_bytes: int
    sha256: str
    packet_count: int
    wire_bytes: int
    payload_bytes: int
    first_timestamp_ns: int | None
    last_timestamp_ns: int | None
    timestamps_ordered: bool
    fingerprints: tuple[tuple[str, int], ...]


def _checksum(data: bytes) -> int:
    """Internet one's-complement checksum; odd tails are zero-padded."""
    if len(data) % 2:
        data += b"\0"
    total = sum(int.from_bytes(data[i:i + 2], "big") for i in range(0, len(data), 2))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def _fingerprint(packet: bytes) -> tuple[str, int]:
    if len(packet) < 14:
        raise PcapError("PCAP_MALFORMED")
    if packet[12:14] != b"\x08\x00":
        raise PcapError("PCAP_UNSUPPORTED")
    if len(packet) < 34:
        raise PcapError("PCAP_MALFORMED")
    if packet[14] >> 4 != 4:
        raise PcapError("PCAP_UNSUPPORTED")
    ihl = packet[14] & 15
    if ihl < 5:
        raise PcapError("PCAP_MALFORMED")
    if ihl != 5 or packet[23] != 6:
        raise PcapError("PCAP_UNSUPPORTED")
    flags_offset = int.from_bytes(packet[20:22], "big")
    if flags_offset & 0x8000:
        raise PcapError("PCAP_MALFORMED")
    if flags_offset & 0x3FFF:
        raise PcapError("PCAP_UNSUPPORTED")
    ip_length = int.from_bytes(packet[16:18], "big")
    if ip_length < 40 or 14 + ip_length > len(packet):
        raise PcapError("PCAP_MALFORMED")
    segment = packet[34:14 + ip_length]
    offset = segment[12] >> 4
    if offset < 5:
        raise PcapError("PCAP_MALFORMED")
    if offset != 5:
        raise PcapError("PCAP_UNSUPPORTED")
    endpoints = packet[26:34]
    pseudo = endpoints + b"\0\x06" + len(segment).to_bytes(2, "big")
    if _checksum(packet[14:34]) != 0 or _checksum(pseudo + segment) != 0:
        raise PcapError("PCAP_CHECKSUM_UNVERIFIED")
    return hashlib.sha256(endpoints + segment).hexdigest(), len(segment) - 20


def parse_capture(stream, *, check=None) -> Capture:
    """Parse the entire bounded stream, or fail without returning partial facts.

    First/last timestamps follow physical record order, not min/max. A failed
    parse leaves the borrowed reader at its last consumed position. Frame-size
    excess uses PCAP_TOO_LARGE. At most cap+1 bytes are consumed (EOF probe).
    """
    reader = _Reader(stream, check)
    header = reader.exact(24)
    variants = {
        b"\xd4\xc3\xb2\xa1": ("<", 1000), b"\xa1\xb2\xc3\xd4": (">", 1000),
        b"\x4d\x3c\xb2\xa1": ("<", 1), b"\xa1\xb2\x3c\x4d": (">", 1),
    }
    if header[:4] not in variants:
        raise PcapError("PCAP_UNSUPPORTED")
    endian, scale = variants[header[:4]]
    major, minor, _, _, snaplen, link = struct.unpack(endian + "HHIIII", header[4:])
    if (major, minor) != (2, 4) or link != 1:
        raise PcapError("PCAP_UNSUPPORTED")
    if snaplen == 0:
        raise PcapError("PCAP_MALFORMED")
    count = wire_bytes = payload_bytes = 0
    first = last = None
    ordered = True
    fingerprints = Counter()
    while record := reader.exact(16, eof_ok=True):
        if count == MAX_PACKETS:
            raise PcapError("PCAP_TOO_MANY_PACKETS")
        sec, frac, included, original = struct.unpack(endian + "IIII", record)
        if included > MAX_FRAME_BYTES or original > MAX_FRAME_BYTES:
            raise PcapError("PCAP_TOO_LARGE")
        if included == 0 or included > snaplen or included > original:
            raise PcapError("PCAP_MALFORMED")
        if frac >= 1_000_000_000 // scale:
            raise PcapError("PCAP_MALFORMED")
        packet = reader.exact(included)
        if included < original:
            raise PcapError("PCAP_TRUNCATED")
        fingerprint, payload_length = _fingerprint(packet)
        fingerprints[fingerprint] += 1
        count += 1
        wire_bytes += original
        payload_bytes += payload_length
        timestamp = sec * 1_000_000_000 + frac * scale
        if first is None:
            first = timestamp
        if last is not None and timestamp < last:
            ordered = False
        last = timestamp
    return Capture(reader.size, reader.digest.hexdigest(), count, wire_bytes, payload_bytes,
                   first, last, ordered, tuple(sorted(fingerprints.items())))
