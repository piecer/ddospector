"""B2: inclusive raw payload cap, independent of delimiter/network segmentation."""

import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from provider_fixture import ProviderFixture, Scenario, sse

from aiddos.api.chat_transport import SSEParser
from aiddos.api.errors import DraftError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from chat_acceptance import OwnedProcess, bootstrap, healthy, http, reserved_port  # noqa: E402


def raw_frame(size):
    prefix = sse("valid")[:-2]
    return prefix + b" " * (size - len(prefix))


def partitions(raw):
    for mask in range(1 << (len(raw) - 1)):
        cuts = [0] + [i for i in range(1, len(raw)) if mask & (1 << (i - 1))] + [len(raw)]
        yield tuple(raw[a:b] for a, b in zip(cuts, cuts[1:], strict=False))


SEPARATORS = [b"\n\n", b"\r\n\n", b"\n\r\n", b"\r\n\r\n"]
SPLITS = [split for separator in SEPARATORS for split in partitions(separator)]


@pytest.mark.parametrize("split", SPLITS)
@pytest.mark.parametrize("joined", [False, True])
@pytest.mark.parametrize("size", [65536, 65537])
def test_frame_cap_for_every_separator_partition(split, joined, size):
    parser = SSEParser()
    raw = raw_frame(size)
    pieces = (raw + split[0], *split[1:]) if joined else (raw, *split)
    output = []

    def parse():
        for piece in pieces:
            for offset in range(0, len(piece), 4096):
                output.extend(parser.feed(piece[offset : offset + 4096]))
                assert len(parser.buffer) <= 65536 + 3
        output.extend(parser.feed(sse(finish="stop") + b"data: [DONE]\n\n"))
        parser.end()

    if size > 65536:
        with pytest.raises(DraftError) as error:
            parse()
        assert error.value.code == "CHAT_OUTPUT_LIMIT"
    else:
        parse()
        assert output == ["valid"]


@pytest.mark.parametrize("prefix", [b"\r", b"\n", b"\r\n", b"\n\r", b"\r\n\r"])
@pytest.mark.parametrize("ending", [b"x", b""])
def test_pending_delimiter_allowance_cannot_be_used_for_payload(prefix, ending):
    parser = SSEParser()
    # Pending delimiter bytes have their own bound; EOF or a nonmatching byte
    # resolves ambiguity and must not increase the raw-payload allowance.
    list(parser.feed(raw_frame(65536)))
    list(parser.feed(prefix))
    assert len(parser.buffer) == 65536 + len(prefix)
    with pytest.raises(DraftError) as error:
        if ending:
            list(parser.feed(ending))
        else:
            parser.end()
    assert error.value.code == "CHAT_OUTPUT_LIMIT"


@contextmanager
def wire_product(directory):
    env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG") if key in os.environ}
    env.update(PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
    env["DDOSPECTOR_UI_STATE_PATH"] = str(directory / "draft.json")
    with reserved_port() as sock:
        port = sock.getsockname()[1]
        assert port not in (5173, 5180, 5175, 5182, 11434)
        base = f"http://127.0.0.1:{port}"
        child = OwnedProcess(
            [
                sys.executable,
                "-B",
                "-m",
                "uvicorn",
                "aiddos.api.app:app",
                "--fd",
                str(sock.fileno()),
                "--no-access-log",
                "--log-level",
                "error",
            ],
            env=env,
            log=directory / "api.log",
            cwd=directory,
            pass_fds=(sock.fileno(),),
        )
    try:
        healthy(child, base)
        yield base
    finally:
        child.stop()
        (directory / "process-receipt.json").write_text(json.dumps(child.receipt()) + "\n")
        assert child.cleaned


@pytest.mark.parametrize("split", [False, True], ids=["whole-delimiter", "split-delimiter"])
def test_exact_frame_default_http_adapter(tmp_path, split):
    raw = raw_frame(65536)
    end = sse(finish="stop") + b"data: [DONE]\n\n"
    chunks = (raw, b"\n", b"\n" + end) if split else (raw, b"\n\n" + end)
    scenario = Scenario(chunks, (0, 0.03, 0.03) if split else (0, 0.03))
    with wire_product(tmp_path) as base, ProviderFixture([scenario]) as provider:
        bootstrap(base, provider.base_url, "SYNTHETIC-fixture-only")
        status, runtime = http(base, "/api/v1/chat/runtime")
        assert status == 200 and runtime["supported"]
        status, session = http(
            base,
            "/api/v1/chat/sessions",
            "POST",
            {
                "request_id": str(uuid4()),
                "settings_revision": runtime["settings_revision"],
                "profile_id": runtime["profile"]["id"],
                "approved_endpoint": runtime["profile"]["endpoint"],
                "locale": "ko",
            },
        )
        assert status == 201
        status, turn = http(
            base,
            f"/api/v1/chat/sessions/{session['id']}/turns",
            "POST",
            {"request_id": str(uuid4()), "expected_sequence": 0, "text": "SYNTHETIC user"},
        )
        assert status == 202
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            status, final = http(base, f"/api/v1/chat/turns/{turn['id']}")
            assert status == 200
            if final["status"] in {"succeeded", "failed", "interrupted", "cancelled"}:
                break
            time.sleep(0.03)
        else:
            pytest.fail("terminal deadline")
        provider.wait_closed()
        assert len(provider.requests) == 1 and provider.opened == provider.closed
        assert final["status"] == "succeeded" and final["assistant_text"] == "valid", final
        assert final["error_code"] is None
        assert final["transport"] == "closed" and final["provider_stop"] == "unknown"
