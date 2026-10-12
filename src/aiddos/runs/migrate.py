"""Explicit atomic schema install; never imported by application wiring."""

import asyncio
import os

from aiddos.api.errors import DraftError

from . import schema
from .config import driver, parameters


async def migrate(socket):
    pg = driver()
    kwargs = parameters(socket, owner=True)
    connection = await pg.AsyncConnection.connect(**kwargs, autocommit=True)
    try:

        async def execute(sql, args=None):
            cursor = await connection.execute(sql, args)
            return await cursor.fetchall() if cursor.description else []

        await schema.settings(execute, owner=True)
        # Migration serialization does not leave a durable lock or modify matching installs.
        async with connection.transaction():
            await execute("SELECT pg_advisory_xact_lock(19302302)")
            exists = await execute("SELECT 1 FROM pg_namespace WHERE nspname='aiddos_runs_v1'")
            if exists:
                await schema.ready(execute)
                return "MATCHING"
            await execute(schema.SQL.read_text())
            await execute(
                "INSERT INTO aiddos_runs_v1.schema_version VALUES(true,1,%s,%s)",
                (schema.checksum(), await schema.shape(execute)),
            )
        return "INSTALLED"
    finally:
        await connection.close()


def main():
    try:
        outcome = asyncio.run(migrate(os.environ.get("AIDDOS_RUN_DB_SOCKET")))
    except (DraftError, OSError, RuntimeError):
        print('{"schema_version":1,"status":"REFUSED"}')
        return 78
    except Exception:
        # CLI has no raw SQL, driver, path, or credential diagnostics.
        print('{"schema_version":1,"status":"REFUSED"}')
        return 78
    print('{"schema_version":1,"status":"' + outcome + '"}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
