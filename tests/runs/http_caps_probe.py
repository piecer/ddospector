"""Real HTTP lifetime caps, with naturally queued/cancelled records only."""

from uuid import uuid4

from http_state_probe import connect


def execute(request, value, queued, data):
    base = "/api/v1/offline-runs"
    ids = [queued["run"]["id"]]
    for _ in range(15):
        code, detail = request("POST", base, {**value, "request_id": str(uuid4())})
        assert code == 202
        ids.append(detail["run"]["id"])
    code, error = request("POST", base, {**value, "request_id": str(uuid4())})
    assert code == 429 and error["code"] == "RUN_QUEUE_FULL"
    assert request("POST", base, value) == (200, queued)
    for run_id in ids:
        code, terminal = request("POST", base + "/" + run_id + "/cancel", {})
        assert code == 200 and terminal["run"]["state"] == "CANCELLED"
    for ordinal in range(17, 129):
        code, detail = request("POST", base, {**value, "request_id": str(uuid4())})
        assert code == 202 and detail["run"]["ordinal"] == ordinal
        ids.append(detail["run"]["id"])
        code, terminal = request("POST", base + "/" + detail["run"]["id"] + "/cancel", {})
        assert code == 200 and terminal["run"]["state"] == "CANCELLED"
    code, error = request("POST", base, {**value, "request_id": str(uuid4())})
    assert code == 409 and error["code"] == "RUN_RETENTION_FULL"
    collected = []
    after = 0
    while after is not None:
        code, page = request("GET", base + f"?after={after}&through=128&limit=20")
        assert code == 200 and page["total"] == page["through"] == 128
        assert 1 <= len(page["items"]) <= 20
        collected.extend(row["id"] for row in page["items"])
        after = page["next_after"]
    assert ids == collected and len(set(collected)) == 128
    with connect(data) as db:
        assert db.execute(
            "SELECT retained_count,unfinished_count,leased_count,reserved_bytes FROM "
            "aiddos_runs_v1.quota"
        ).fetchone() == (128, 0, 0, 8388608)
        assert db.execute("SELECT count(*) FROM aiddos_runs_v1.events").fetchone() == (256,)
