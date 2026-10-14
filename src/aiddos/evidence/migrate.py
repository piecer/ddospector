"""Explicit owner-only atomic install during fresh workspace bootstrap."""

import asyncio

from aiddos.api.errors import DraftError
from aiddos.runs import schema as core
from aiddos.runs.config import driver, parameters
from aiddos.startup import startup_setting

from . import schema


async def migrate(socket):
    connection = await driver().AsyncConnection.connect(**parameters(socket, owner=True),
                                                        autocommit=True)
    try:
        async def execute(sql, args=None):
            cursor = await connection.execute(sql, args)
            return await cursor.fetchall() if cursor.description else []

        await core.settings(execute, owner=True)
        await core.ready(execute)
        async with connection.transaction():
            await execute("SELECT pg_advisory_xact_lock(19302303)")
            exists = await execute(
                "SELECT 1 FROM pg_namespace WHERE nspname='ddospector_evidence_v1'"
            )
            if exists:
                await schema.ready(execute)
                return "MATCHING"
            await execute(schema.SQL.read_text())
            await execute("INSERT INTO ddospector_evidence_v1.schema_version VALUES(true,1,%s,%s)",
                          (schema.checksum(), await schema.shape(execute)))
            await schema.ready(execute)
        return "INSTALLED"
    finally:
        await connection.close()


def main():
    try:
        outcome = asyncio.run(migrate(startup_setting("RUN_DB_SOCKET")))
    except (DraftError, OSError, RuntimeError):
        print('{"schema_version":1,"status":"REFUSED"}')
        return 78
    except Exception:
        print('{"schema_version":1,"status":"REFUSED"}')
        return 78
    print('{"schema_version":1,"status":"' + outcome + '"}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
