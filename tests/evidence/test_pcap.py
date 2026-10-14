"""Frozen P2-00 bounded classic-PCAP contracts."""
import hashlib
import importlib
import io
import struct
from dataclasses import FrozenInstanceError

import pytest


def parser():
    try:
        return importlib.import_module("aiddos.evidence.pcap")
    except ImportError:
        pytest.fail("P2-00 parser is not implemented")


@pytest.mark.parametrize("endian,nano", [("<", False), (">", False), ("<", True), (">", True)])
def test_empty_capture_all_header_variants(wire, endian, nano):
    make, _ = wire
    raw = make(endian=endian, nano=nano, unused=(0xFFFFFFFF, 1234))
    stream = io.BytesIO(raw)
    result = parser().parse_capture(stream)
    assert result.size_bytes == len(raw)
    assert result.sha256 == hashlib.sha256(raw).hexdigest()
    assert (result.packet_count, result.wire_bytes, result.payload_bytes) == (0, 0, 0)
    assert (result.first_timestamp_ns, result.last_timestamp_ns) == (None, None)
    assert result.timestamps_ordered is True
    assert result.fingerprints == ()
    assert stream.closed is False
    with pytest.raises(FrozenInstanceError):
        result.packet_count = 1


@pytest.mark.parametrize("endian,nano", [("<", False), (">", False), ("<", True), (">", True)])
def test_tcp_records_identity_counts_and_integer_timestamps(wire, endian, nano):
    make, frame = wire
    first = frame(b"odd")
    forwarded = frame(b"odd", ttl=63, mac=b"\x02" * 12) + b"padding"
    other = frame(b"different")
    divisor = 1_000_000_000 if nano else 1_000_000
    stamps = [(0xFFFFFFFF, divisor - 1), (0xFFFFFFFF, 0), (0xFFFFFFFF, 1)]
    raw = make([first, forwarded, other], endian=endian, nano=nano, timestamps=stamps)
    result = parser().parse_capture(io.BytesIO(raw))
    assert result.size_bytes == len(raw)
    assert result.sha256 == hashlib.sha256(raw).hexdigest()
    assert result.packet_count == 3
    assert result.wire_bytes == len(first) + len(forwarded) + len(other)
    assert result.payload_bytes == 15
    assert result.first_timestamp_ns == 0xFFFFFFFF * 1_000_000_000 + (
        divisor - 1) * (1 if nano else 1000)
    assert result.last_timestamp_ns == 0xFFFFFFFF * 1_000_000_000 + (1 if nano else 1000)
    assert result.timestamps_ordered is False
    identity = hashlib.sha256(first[26:34] + first[34:]).hexdigest()
    other_identity = hashlib.sha256(other[26:34] + other[34:]).hexdigest()
    assert result.fingerprints == tuple(sorted(((identity, 2), (other_identity, 1))))
    assert not hasattr(result, "payload")


def test_ip_endpoints_and_tcp_bytes_are_identity(wire):
    make, frame = wire
    frames = [frame(), frame(src=b"\xc0\x00\x02\x03"), frame(b"tesT")]
    result = parser().parse_capture(io.BytesIO(make(frames)))
    assert len(result.fingerprints) == 3
    assert result.timestamps_ordered is True


def error(raw, code):
    module = parser()
    with pytest.raises(module.PcapError) as caught:
        module.parse_capture(io.BytesIO(raw))
    assert isinstance(caught.value, ValueError)
    assert caught.value.code == code


class BorrowedReader:
    def __init__(self, raw, chunk=65535):
        self.raw = raw
        self.position = 0
        self.chunk = chunk
        self.requests = []

    def read(self, size):
        assert 0 < size <= 65535
        self.requests.append(size)
        end = self.position + min(size, self.chunk)
        data = self.raw[self.position:end]
        self.position += len(data)
        return data

    def close(self):
        pytest.fail("borrowed reader was closed")

    def seek(self, *_):
        pytest.fail("forward-only reader was sought")


def test_short_reads_borrowed_reader_and_checkpoints(wire):
    make, frame = wire
    raw = make([frame()])
    reader = BorrowedReader(raw, chunk=1)
    calls = []
    result = parser().parse_capture(reader, check=lambda: calls.append(reader.position))
    assert result.sha256 == hashlib.sha256(raw).hexdigest()
    assert reader.position == len(raw)
    assert len(calls) >= len(raw)
    assert max(reader.requests) <= 65535


@pytest.mark.parametrize("stop", [1, 25, 50])
def test_checkpoint_exception_propagates_unchanged(wire, stop):
    make, frame = wire
    reader = BorrowedReader(make([frame()]), chunk=1)
    sentinel = RuntimeError("caller cancelled")
    count = 0

    def check():
        nonlocal count
        count += 1
        if count == stop:
            raise sentinel

    with pytest.raises(RuntimeError) as caught:
        parser().parse_capture(reader, check=check)
    assert caught.value is sentinel
    assert reader.position <= stop


def test_every_header_and_record_truncation_boundary(wire):
    make, frame = wire
    raw = make([frame()])
    for cut in range(len(raw)):
        if cut != 24:  # a complete empty PCAP is valid
            error(raw[:cut], "PCAP_MALFORMED")
    error(raw + b"\0", "PCAP_MALFORMED")


@pytest.mark.parametrize("kwargs,code", [
    ({"version": (2, 3)}, "PCAP_UNSUPPORTED"),
    ({"link": 101}, "PCAP_UNSUPPORTED"),
    ({"link": 0x04000001}, "PCAP_UNSUPPORTED"),
    ({"snaplen": 0}, "PCAP_MALFORMED"),
])
def test_global_header_policy(wire, kwargs, code):
    make, _ = wire
    error(make(**kwargs), code)


def test_magic_recognition(wire):
    make, _ = wire
    raw = make()
    error(b"\x0a\x0d\x0d\x0a" + raw[4:], "PCAP_UNSUPPORTED")
    error(b"nope" + raw[4:], "PCAP_UNSUPPORTED")


@pytest.mark.parametrize("nano,limit", [(False, 1_000_000), (True, 1_000_000_000)])
def test_timestamp_fraction_bound(wire, nano, limit):
    make, frame = wire
    error(make([frame()], nano=nano, timestamps=[(1, limit)]), "PCAP_MALFORMED")


def test_record_lengths_and_truncation_distinction(wire):
    make, frame = wire
    packet = frame()
    raw = make([packet])
    error(make([packet], snaplen=len(packet) - 1), "PCAP_MALFORMED")
    smaller_original = raw[:36] + struct.pack("<I", len(packet) - 1) + raw[40:]
    error(smaller_original, "PCAP_MALFORMED")
    truncated = raw[:36] + struct.pack("<I", len(packet) + 1) + raw[40:]
    error(truncated, "PCAP_TRUNCATED")
    error(truncated[:-1], "PCAP_MALFORMED")
    error(make() + struct.pack("<IIII", 1, 0, 0, 0), "PCAP_MALFORMED")


def test_exact_and_excess_frame_limit(wire):
    make, frame = wire
    module = parser()
    assert module.MAX_FRAME_BYTES == 65535
    packet = frame()
    full = packet + b"\0" * (65535 - len(packet))
    assert module.parse_capture(io.BytesIO(make([full]))).wire_bytes == 65535
    error(make([full + b"\0"], snaplen=65536), "PCAP_TOO_LARGE")
    raw = make([packet])
    error(raw[:36] + struct.pack("<I", 65536) + raw[40:], "PCAP_TOO_LARGE")


def test_exact_and_excess_record_limit_stops_before_body(wire):
    make, frame = wire
    module = parser()
    assert module.MAX_PACKETS == 4096
    raw = make([frame()] * 4096)
    assert module.parse_capture(io.BytesIO(raw)).packet_count == 4096
    reader = BorrowedReader(raw + make([frame()])[24:])
    with pytest.raises(module.PcapError) as caught:
        module.parse_capture(reader)
    assert caught.value.code == "PCAP_TOO_MANY_PACKETS"
    assert reader.position <= len(raw) + 16


def test_exact_and_excess_capture_limit_bounds_consumption(wire):
    make, frame = wire
    module = parser()
    assert module.MAX_CAPTURE_BYTES == 1_048_576
    budget = module.MAX_CAPTURE_BYTES - 24 - 16 * 16
    length, rest = divmod(budget, 16)
    packet = frame()
    frames = [packet + b"\0" * (length + (i < rest) - len(packet)) for i in range(16)]
    raw = make(frames)
    assert len(raw) == module.MAX_CAPTURE_BYTES
    assert module.parse_capture(io.BytesIO(raw)).size_bytes == module.MAX_CAPTURE_BYTES
    for excess in (raw + b"\0", make([*frames[:-1], frames[-1] + b"\0"])):
        reader = BorrowedReader(excess)
        with pytest.raises(module.PcapError) as caught:
            module.parse_capture(reader)
        assert caught.value.code == "PCAP_TOO_LARGE"
        assert reader.position <= module.MAX_CAPTURE_BYTES + 1


@pytest.mark.parametrize("offset,value,code", [
    (12, b"\x86\xdd", "PCAP_UNSUPPORTED"),  # IPv6
    (12, b"\x81\x00", "PCAP_UNSUPPORTED"),  # VLAN
    (12, b"\x08\x06", "PCAP_UNSUPPORTED"),  # ARP
    (14, b"\x65", "PCAP_UNSUPPORTED"),
    (14, b"\x46", "PCAP_UNSUPPORTED"),  # IP options
    (14, b"\x44", "PCAP_MALFORMED"),
    (23, b"\x11", "PCAP_UNSUPPORTED"),  # UDP
    (20, b"\x20\x00", "PCAP_UNSUPPORTED"),  # more fragments
    (20, b"\x00\x01", "PCAP_UNSUPPORTED"),  # fragment offset
    (20, b"\x80\x00", "PCAP_MALFORMED"),  # reserved flag
    (46, b"\x60", "PCAP_UNSUPPORTED"),  # TCP options
    (46, b"\x40", "PCAP_MALFORMED"),
    (16, b"\x00\x27", "PCAP_MALFORMED"),  # no complete TCP header
    (16, b"\xff\xff", "PCAP_MALFORMED"),  # IP length outside frame
    (22, b"\x3f", "PCAP_CHECKSUM_UNVERIFIED"),  # corrupted IPv4 checksum
    (54, b"X", "PCAP_CHECKSUM_UNVERIFIED"),  # corrupted TCP checksum
    (24, b"\x00\x00", "PCAP_CHECKSUM_UNVERIFIED"),
    (50, b"\x00\x00", "PCAP_CHECKSUM_UNVERIFIED"),
])
def test_packet_validation_never_skips_unsupported_or_corrupt_record(wire, offset, value, code):
    make, frame = wire
    packet = frame()
    changed = packet[:offset] + value + packet[offset + len(value):]
    error(make([packet, changed, packet]), code)


@pytest.mark.parametrize("length", [1, 13, 14, 33, 34, 53])
def test_incomplete_network_headers_are_malformed(wire, length):
    make, frame = wire
    error(make([frame()[:length]]), "PCAP_MALFORMED")


def test_reader_failure_not_misreported_as_data_quality(wire):
    make, frame = wire
    sentinel = OSError("read failed")

    class FailingReader(BorrowedReader):
        def read(self, size):
            if self.position >= 40:
                raise sentinel
            return super().read(size)

    with pytest.raises(OSError) as caught:
        parser().parse_capture(FailingReader(make([frame()])))
    assert caught.value is sentinel
