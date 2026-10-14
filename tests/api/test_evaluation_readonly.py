"""Evaluation is explicit one-shot only; HTTP cannot accept or produce a report."""
from uuid import uuid4

import pytest

from aiddos.runs.lifetime import Manager


@pytest.mark.parametrize("suffix", ["/evaluate", "/report", "/analysis"])
def test_no_http_evaluation_admission(client, monkeypatch, suffix):
    calls = []
    async def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("HTTP evaluation admitted")
    monkeypatch.setattr(Manager, "perform", forbidden)
    response = client.post("/api/v1/evidence/" + str(uuid4()) + suffix, json={})
    assert response.status_code == 404
    assert calls == []
