"""New HTTP families distinguish absent identity from broken retained linkage."""

from .contracts import require
from .repository import lookup


async def retained_detail(op, run_id):
    exists = await op.execute("SELECT run_id FROM aiddos_runs_v1.inputs WHERE run_id=%s", (run_id,))
    require(bool(exists), "RUN_NOT_FOUND")
    found = await lookup(op, run_id)
    require(found is not None, "RUN_STATE_CORRUPT")
    return found
