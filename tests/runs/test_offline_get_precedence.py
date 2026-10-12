"""Both public GET routes preserve missing-row error precedence on real PG."""

import pytest
from offline_fixtures import application_probe


@pytest.mark.parametrize("route", ["run", "request"])
def test_missing_get_precedes_corrupt_quota(owned_pg, route):
    result = application_probe(owned_pg, "get-precedence-" + route)
    assert result["precedence"]["fault_fired"]
    assert result["precedence"]["missing_corrupt"]["status"] == 404
    assert result["precedence"]["unchanged"]
    assert result["precedence"]["source_calls"] == 0


@pytest.mark.parametrize("route", ["run", "request"])
@pytest.mark.parametrize(
    "readiness", ["unconfigured", "missing-schema", "invalid-schema", "outage"]
)
def test_get_readiness_precedes_missing_row(owned_pg, route, readiness):
    if readiness == "outage":
        owned_pg.revalidate()
        owned_pg.call("stop", "--timeout", "2", owned_pg.cid, timeout=5)
    result = application_probe(owned_pg, "get-readiness-" + readiness + "-" + route)
    assert result["readiness"]["status"] == 503
    assert result["readiness"]["control_fired"]
