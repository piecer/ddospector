"""Independent, deterministic wire constructors for parser contract tests."""
import struct

import pytest


def checksum(data):
    if len(data) % 2:
        data += b"\0"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    while total > 65535:
        total = (total & 65535) + (total >> 16)
    return total ^ 65535


def frame(payload=b"test", *, ttl=64, mac=b"\x01" * 12, src=b"\xc0\x00\x02\x01"):
    dst = b"\xc6\x33\x64\x02"
    tcp = struct.pack("!HHIIBBHHH", 12345, 443, 100, 200, 0x50, 0x18, 4096, 0, 0)
    segment = tcp + payload
    pseudo = src + dst + struct.pack("!BBH", 0, 6, len(segment))
    segment = segment[:16] + struct.pack("!H", checksum(pseudo + segment)) + segment[18:]
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(segment), 7, 0x4000, ttl,
                     6, 0, src, dst)
    ip = ip[:10] + struct.pack("!H", checksum(ip)) + ip[12:]
    return mac + b"\x08\x00" + ip + segment


def capture(frames=(), *, endian="<", nano=False, snaplen=65535, link=1,
            timestamps=None, unused=(0, 0), version=(2, 4)):
    magic = 0xA1B23C4D if nano else 0xA1B2C3D4
    data = struct.pack(endian + "IHHIIII", magic, *version, *unused, snaplen, link)
    for index, packet in enumerate(frames):
        sec, frac = timestamps[index] if timestamps else (1700000000, index)
        data += struct.pack(endian + "IIII", sec, frac, len(packet), len(packet)) + packet
    return data


@pytest.fixture
def wire():
    return capture, frame
