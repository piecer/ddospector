"""Real owned PostgreSQL application admission tests."""

import pytest
from offline_fixtures import application_probe


def test_offline_missing_schema_never_migrates(owned_pg):
    result = application_probe(owned_pg, "missing-schema")
    assert result["response"]["body"]["code"] == "RUN_DB_NOT_READY"


def test_offline_real_migration_repeat_and_runtime_privileges(owned_pg):
    result = application_probe(owned_pg, "migration")
    assert result["quota"] == [0, 0, 0, 0]


def test_offline_incompatible_migration_preserves_foreign_shape(owned_pg):
    assert application_probe(owned_pg, "migration-incompatible")["foreign_shape_preserved"]


def test_offline_four_retained_delayed_acquisitions(owned_pg):
    result = application_probe(owned_pg, "lifetime-acquire")
    assert result["drain"]["outcome"] == "CLEAN"


def test_offline_missing_driver_is_not_ready(owned_pg):
    assert (
        application_probe(owned_pg, "driver-missing")["response"]["body"]["code"]
        == "RUN_DB_NOT_READY"
    )


def test_offline_http_create_captures_real_s01_atomically(owned_pg):
    result = application_probe(owned_pg, "create")
    assert result["quota"] == [1, 1, 0, 65536]


def test_offline_idempotency_and_reads_never_reopen_source(owned_pg):
    result = application_probe(owned_pg, "idempotency")
    assert result["quota"] == [1, 1, 0, 65536]


def test_offline_real_lock_abort_is_bounded_and_atomic(owned_pg):
    result = application_probe(owned_pg, "lock")
    assert result["quota"] == [1, 1, 0, 65536]


def test_offline_terminal_fixture_replay_is_truthful(owned_pg):
    result = application_probe(owned_pg, "terminal-fixture")
    assert result["fixture_kind"] == "DB_ONLY_NOT_WORKER_REACHABLE"


def test_offline_disconnect_revokes_before_late_acquisition(owned_pg):
    result = application_probe(owned_pg, "disconnect")
    assert result["revoked_before_rescue"]


@pytest.mark.parametrize(
    "case",
    [
        "atomic",
        "uncertain",
        "quota",
        "retention",
        "corrupt",
        "snapshot",
        "source-timeout",
        "source-shutdown",
        "same-key-race",
        "close-delay",
        "close-unconfirmed",
        "close-after-error",
        "ddl-bounds",
        "corrupt-input",
        "source-lock",
    ],
)
def test_offline_storage_boundaries(owned_pg, case):
    result = application_probe(owned_pg, case)
    assert result["case"] == case


def test_offline_actual_http_process_and_same_volume_restart(owned_pg):
    first = application_probe(owned_pg, "durability-create")
    assert first["detail"]["run"]["state"] == "QUEUED"
    owned_pg.revalidate()
    owned_pg.call("stop", "--timeout", "2", owned_pg.cid, timeout=5)
    assert application_probe(owned_pg, "durability-outage")["readback"]
    owned_pg.restart()
    assert application_probe(owned_pg, "durability-read")["readback"]
