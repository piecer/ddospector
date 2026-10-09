"""Reproducible, live Python-3.12 differential expectations (not generated tables).

Exhaust all Unicode code points for fold/text/one-character IDNA. Also exercise
normalization/composition, bidi, IPv4/IPv6 and authority cross-products. No I/O
other than stdout and the importing of project/stdlib modules; no endpoints run.
"""

import hashlib
import json
import random
import sys
import unicodedata

from generate_unicode import require_runtime
from pydantic import TypeAdapter

from aiddos.api.ai_settings import AIBaseURL


def ascii_host(value):
    try:
        return value.encode("idna").decode("ascii")
    except UnicodeError:
        return None


def corpus():
    rng = random.Random(20261009)
    alphabet = list("aAZ09-._") + list(
        "\u00df\u0130\u0378\u1c89\u1c8a\ua7cb\u0264\u0345\u0340"
        "\u0300\u0301\u0308\u0323\u0327\u0334\u05b0\u05d0\u0627"
        "\u0903\u1100\u1161\u11a8\uac00\ud7a3\u2024\u3002\uff0e\uff61"
        "\ufdfa\u212b\u00c5"
    )
    # Normalization corrections and characters assigned after Unicode 3.2.
    alphabet += [
        chr(cp)
        for cp in (
            0x2F868,
            0x2F874,
            0x2F91F,
            0x2F95F,
            0x2F9BF,
            0x1D2C,
            0x1D6C1,
            0x1E030,
            0x1F9EA,
            0x10FFFF,
        )
    ]
    hosts = ["".join(rng.choices(alphabet, k=rng.randrange(1, 14))) for _ in range(4000)]
    hosts += [a + b for a in alphabet for b in alphabet]
    hosts += ["é" * n for n in (56, 57, 58, 59, 60, 63, 64)]
    hosts += ["a" * n for n in (62, 63, 64)]
    hosts += ["xn--a", "xn--invalid-", "xn--é", "\u0378", "model\u2024example"]
    hosts += [".".join(["a" * 63] * n) for n in (3, 4, 5)]
    hosts = list(dict.fromkeys(hosts))
    urls = ["https://" + host + "/v1" for host in hosts]
    addresses = [
        "1.2.3",
        "0127.0.0.1",
        "127.0.0.1",
        "127.0.0.1.",
        "0xabc",
        "model.123",
        "model.0xabc",
        "[::]",
        "[::1]",
        "[1:2:3:4:5:6:7:8]",
        "[::ffff:192.0.2.1]",
        "[1:2:3:4:5:6:7]",
        "[1:::2]",
        "[1::2::3]",
        "[1:2:3:4:5:6:192.0.2.1]",
        "[::ffff:0127.0.0.1]",
        "[::1%25eth0]",
        "[::1]extra",
        "[v1.a]",
        "[127.0.0.1]",
        "a@b",
        "@a",
        "%61.test",
        "a\\b",
    ]
    urls += [
        scheme + host + port + path
        for scheme in ("http://", "HTTPS://", "https:/", "file://")
        for host in addresses
        for port in ("", ":", ":0", ":1", ":00080", ":65535", ":65536", ":+80", ":١")
        for path in ("/v1", "/v1?", "/v1#")
    ]
    validator = TypeAdapter(AIBaseURL)
    results = []
    for value in urls:
        try:
            validator.validate_python(value, strict=True)
            accepted = True
        except ValueError:
            accepted = False
        results.append([value, accepted])
    return {"hosts": [[host, ascii_host(host)] for host in hosts], "urls": results}


def exhaustive():
    fold = hashlib.sha256()
    text = hashlib.sha256()
    idna = hashlib.sha256()
    for cp in range(0x110000):
        c = chr(cp)
        folded = ".".join(format(ord(ch), "x") for ch in c.casefold())
        fold.update(f"{cp}:{folded}\n".encode())
        text.update(bytes([int(unicodedata.category(c) in {"Cc", "Cf", "Cs"}), int(c.isspace())]))
        # Surrogates reject in IDNA, but are included in both exhaustive censuses.
        encoded = ascii_host(c)
        idna.update(f"{cp}:{encoded if encoded is not None else '<null>'}\n".encode())
    return {
        "count": 0x110000,
        "fold": fold.hexdigest(),
        "text": text.hexdigest(),
        "idna": idna.hexdigest(),
    }


if __name__ == "__main__":
    require_runtime()
    print(json.dumps(exhaustive() if sys.argv[1] == "exhaustive" else corpus(), ensure_ascii=True))
