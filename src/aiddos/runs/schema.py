"""Schema identity and logged/role/durability validation, shared read-only."""

import hashlib
import json
from pathlib import Path

from aiddos.api.errors import DraftError

SQL = Path(__file__).with_name("migrations") / "001_offline_runs.sql"


def checksum():
    return hashlib.sha256(SQL.read_bytes()).hexdigest()


# Stable catalog projections: no object OIDs, physical files, or current data.
SHAPE = """
SELECT 'column', c.relname, a.attname, pg_catalog.format_type(a.atttypid,a.atttypmod),
       a.attnotnull::text, ''
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
JOIN pg_attribute a ON a.attrelid=c.oid
WHERE n.nspname='aiddos_runs_v1' AND a.attnum>0 AND NOT a.attisdropped
UNION ALL
SELECT 'constraint', c.relname, x.conname, pg_get_constraintdef(x.oid), '', ''
FROM pg_constraint x JOIN pg_class c ON c.oid=x.conrelid
JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='aiddos_runs_v1'
UNION ALL
SELECT 'trigger', c.relname, t.tgname, pg_get_triggerdef(t.oid),t.tgenabled::text,''
FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='aiddos_runs_v1' AND NOT t.tgisinternal
UNION ALL
SELECT 'relation',c.relname,c.relkind::text,c.relpersistence::text,r.rolname,
       coalesce(c.relacl::text,'')
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
JOIN pg_roles r ON r.oid=c.relowner WHERE n.nspname='aiddos_runs_v1'
UNION ALL
SELECT 'function',p.proname,'',pg_get_functiondef(p.oid),'',''
FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
WHERE n.nspname='aiddos_runs_v1'
ORDER BY 1,2,3,4,5,6
"""


async def shape(execute):
    return hashlib.sha256(
        json.dumps(await execute(SHAPE), separators=(",", ":")).encode()
    ).hexdigest()


async def settings(execute, *, owner=False):
    rows = await execute(
        "SELECT current_database(),current_user,current_setting('server_version_num'),"
        "current_setting('fsync'),current_setting('full_page_writes'),"
        "current_setting('synchronous_commit')"
    )
    role = "aiddos_s02_owner" if owner else "aiddos_s02"
    row = rows[0]
    if row[:2] != ("aiddos_s02", role) or int(row[2]) // 10000 != 16 or row[3:] != ("on",) * 3:
        raise DraftError("RUN_DB_NOT_READY")
    flags = await execute(
        "SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolreplication,"
        "rolbypassrls,rolconnlimit FROM pg_roles WHERE rolname IN "
        "('aiddos_s02','aiddos_s02_owner') ORDER BY rolname"
    )
    if (
        len(flags) != 2
        or flags[0] != ("aiddos_s02", False, False, False, False, False, 8)
        or flags[1][:-1] != ("aiddos_s02_owner", False, False, False, False, False)
    ):
        raise DraftError("RUN_DB_NOT_READY")


async def ready(execute):
    rows = await execute("SELECT version,checksum,shape FROM aiddos_runs_v1.schema_version")
    if len(rows) != 1 or rows[0][:2] != (1, checksum()) or rows[0][2] != await shape(execute):
        raise DraftError("RUN_DB_NOT_READY")
