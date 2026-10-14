"""Readiness classifications; real owned-DB column faults live in evidence_probe."""

import asyncio
import time

import psycopg
import pytest

from aiddos.api.errors import DraftError
from aiddos.evidence import schema
from aiddos.runs.lifetime import Manager


@pytest.mark.parametrize("error,code", [
    (psycopg.errors.UndefinedTable, "EVIDENCE_NOT_READY"),
    (psycopg.errors.UndefinedColumn, "EVIDENCE_NOT_READY"),
    (psycopg.errors.InvalidSchemaName, "EVIDENCE_NOT_READY"),
    (psycopg.OperationalError, "RUN_DB_UNAVAILABLE"),
])
def test_marker_shape_is_not_unavailability(error, code):
    async def run():
        owner = Manager()
        async def execute(*args):
            raise error("private driver detail must not escape")
        async def work(op):
            await schema.ready(execute)
        try:
            with pytest.raises(DraftError, match=code) as raised:
                await owner.perform(time.monotonic() + 5, work)
            assert raised.value.code == code
        finally:
            await owner.shutdown()
        assert owner.drain_result["outcome"] == "CLEAN"
        assert not owner.operations
    asyncio.run(run())
