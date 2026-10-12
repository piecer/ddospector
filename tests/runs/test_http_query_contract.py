"""Raw-byte grammar negatives and new-route admission before any DB acquisition."""

import pytest


@pytest.mark.parametrize(
    "raw",
    [
        b"after=\xff",
        b"after=\xc0\xaf",
        "after=١".encode(),
        b"after=%31",
        b"%61fter=0",
        b"after=01",
        b"after=+1",
        b"after=-0",
        b"after=1e0",
        b"after=1.0",
        b"after",
        b"after=",
        b"after=0&after=0",
        b"after=0&",
        b"&after=0",
        b"limit=0",
        b"limit=21",
        b"x=0",
        b"after=0;limit=1",
        b"after=" + b"1" * 256,
    ],
)
@pytest.mark.parametrize("events", [False, True])
def test_http_raw_page_query_bytes_are_not_lossily_decoded(raw, events):
    from aiddos.api.errors import DraftError
    from aiddos.runs.queries import page_query

    with pytest.raises(DraftError) as error:
        page_query(raw, events=events)
    assert error.value.code == "VALIDATION_ERROR"


@pytest.mark.parametrize("family", ["list", "events", "cancel"])
def test_http_missing_configuration_and_transport_precedence(owned_pg, family):
    from test_http_producer import probe

    # A process-rooted manager cannot reopen after TestClient lifespan shutdown.
    # Keep all assertions in a fresh real HTTP process, not a private manager reset.
    assert probe(owned_pg, "configuration-" + family)["verified"]
