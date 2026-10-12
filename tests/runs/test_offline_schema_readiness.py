"""I1-RV-01 persistent real-PG, actual-ASGI required-marker regression."""

import pytest
from offline_fixtures import application_probe


def test_missing_checksum_is_not_ready(owned_pg):
    result = application_probe(owned_pg, "schema-readiness-checksum-run")
    assert result["schema_readiness"]["fault_fired"]
    assert result["schema_readiness"]["denied"][0]["body"]["code"] == "RUN_DB_NOT_READY"


@pytest.mark.parametrize(
    "fault,route",
    [
        (fault, route)
        for fault in ("checksum", "version", "shape", "checksum-value", "shape-value", "empty")
        for route in ("run", "request", "post")
        if (fault, route) != ("checksum", "run")
    ],
)
def test_shared_marker_guard_siblings(owned_pg, fault, route):
    proof = application_probe(owned_pg, f"schema-readiness-{fault}-{route}")["schema_readiness"]
    assert proof["fault_fired"] and proof["quota_fault_fired"]
    assert proof["source_calls"] == proof["dml_calls"] == 0
    assert len(proof["denied"]) == 4
    assert proof["unchanged"] and proof["repeat_unchanged"] and proof["refused_unchanged"]
    assert proof["retained_before_rescue"] == 0


@pytest.mark.parametrize("route", ["run", "request", "post"])
@pytest.mark.parametrize("configured", [False, True])
def test_configuration_error_is_distinct_without_driver_io(owned_pg, route, configured):
    kind = "invalid" if configured else "unconfigured"
    result = application_probe(owned_pg, f"schema-configuration-{kind}-{route}")
    assert result["configuration"]["status"] == 503
    assert result["configuration"]["driver_calls"] == 0
