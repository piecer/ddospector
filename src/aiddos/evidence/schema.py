"""Separate versioned evidence schema; request readiness is strictly read-only."""

import hashlib
import json
from pathlib import Path

from aiddos.api.errors import DraftError
from aiddos.runs import schema as core
from aiddos.runs.config import driver

SQL = Path(__file__).with_name("migrations") / "001_evidence.sql"
SHAPE = core.SHAPE.replace("aiddos_runs_v1", "ddospector_evidence_v1")
# Include namespace and column grants, which table ACL alone does not describe.
EXTRA_SHAPE = """
SELECT 'namespace',n.nspname,r.rolname,coalesce(n.nspacl::text,'')
FROM pg_namespace n JOIN pg_roles r ON r.oid=n.nspowner
WHERE n.nspname='ddospector_evidence_v1'
UNION ALL
SELECT 'column_acl',c.relname,a.attname,coalesce(a.attacl::text,'')
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
JOIN pg_attribute a ON a.attrelid=c.oid
WHERE n.nspname='ddospector_evidence_v1' AND a.attnum>0 AND NOT a.attisdropped
ORDER BY 1,2,3,4
"""


def checksum():
    return hashlib.sha256(SQL.read_bytes()).hexdigest()


async def shape(execute):
    rows = await execute(SHAPE)
    extra = await execute(EXTRA_SHAPE)
    return hashlib.sha256(json.dumps([rows, extra], separators=(",", ":")).encode()).hexdigest()


async def ready(execute):
    pg = driver()
    try:
        rows = await execute(
            "SELECT singleton,version,checksum,shape FROM ddospector_evidence_v1.schema_version "
            "LIMIT 2"
        )
        if (len(rows) != 1 or rows[0][:3] != (True, 1, checksum())
                or rows[0][3] != await shape(execute)):
            raise DraftError("EVIDENCE_NOT_READY")
        flags = await execute(
            "SELECT pg_has_role('aiddos_s02','aiddos_s02_owner','MEMBER'),"
            "has_schema_privilege('aiddos_s02','ddospector_evidence_v1','CREATE')"
        )
        if flags != [(False, False)]:
            raise DraftError("EVIDENCE_NOT_READY")
    except (pg.errors.UndefinedTable, pg.errors.UndefinedColumn, pg.errors.InvalidSchemaName):
        raise DraftError("EVIDENCE_NOT_READY") from None
