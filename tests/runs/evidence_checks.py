"""Bounded controls inside the one normal owned-PG fixture; no outage or restart."""

import base64
import copy
import hashlib
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
from phase1_probe import h, save

from aiddos.api.errors import ERRORS
from aiddos.api.scenarios import canonical
from aiddos.evidence.samples import make_sample


def connect(data, *, owner=False):
    return psycopg.connect(**h.connection_parameters(
        Path(data["socket"]), user="aiddos_s02_owner" if owner else "aiddos_s02"))


def core_bytes(data, run_id):
    with connect(data) as db:
        inputs = db.execute("SELECT request,snapshot FROM aiddos_runs_v1.inputs WHERE run_id=%s",
                            (run_id,)).fetchone()
        result = db.execute("SELECT result FROM aiddos_runs_v1.results WHERE run_id=%s",
                            (run_id,)).fetchone()[0]
        events = db.execute("SELECT event FROM aiddos_runs_v1.events WHERE run_id=%s ORDER BY seq",
                            (run_id,)).fetchall()
        return {"request": inputs[0], "snapshot": inputs[1], "result": result,
                **{f"event-{index}": row[0] for index, row in enumerate(events, 1)}}


def check_timestamps(client, data, capture, payload, detail):
    """Real retained scalar faults, restored before the aggregate contract assertion."""
    from aiddos.evidence.repository import PROJECTION
    from aiddos.evidence.validation import metadata

    output = Path(data["output"])
    item = detail["evidence"]
    root = "/api/v1/evidence"
    selected = root + "/" + item["id"]
    paths = {"list": root, "detail": selected,
             "by-request": root + "/by-request/" + payload["request_id"],
             **{side: selected + "/raw/" + side for side in ("ingress", "egress")}}
    original_core = core_bytes(data, payload["run_id"])
    before = {label: capture("timestamp-before-" + label, client.get(path), 200).content
              for label, path in paths.items()}
    before["replay"] = capture("timestamp-before-replay", client.post(root, json=payload),
                               200).content
    assert before["detail"] == before["by-request"] == before["replay"] == canonical(detail)

    def stored():
        with connect(data) as db:
            row = db.execute(
                "SELECT id,request_id,ordinal,run_id,run_snapshot_digest,request_digest,"
                "created_at::text,metadata,ingress,egress FROM ddospector_evidence_v1.bundles "
                "WHERE id=%s", (item["id"],),
            ).fetchone()
            quota = db.execute("SELECT * FROM ddospector_evidence_v1.quota").fetchall()
            trigger = db.execute(
                "SELECT tgenabled FROM pg_trigger WHERE tgrelid="
                "'ddospector_evidence_v1.bundles'::regclass AND tgname='bundles_immutable'",
            ).fetchone()
        assert trigger == ("O",)
        return row, quota

    original, counters = stored()

    def replace_timestamp(raw):
        with connect(data, owner=True) as db:
            db.execute("ALTER TABLE ddospector_evidence_v1.bundles "
                       "DISABLE TRIGGER bundles_immutable")
            db.execute("UPDATE ddospector_evidence_v1.bundles SET created_at=%s WHERE id=%s",
                       (raw, item["id"]))
            db.execute("ALTER TABLE ddospector_evidence_v1.bundles "
                       "ENABLE TRIGGER bundles_immutable")

    # No stored metadata changes: positive boundary rows are read-only SQL projections.
    positives = []
    for at in ("0001-01-01T00:00:00.000000Z", "9999-12-31T23:59:59.999999Z",
               "2000-02-29T12:34:56.123456Z"):
        value = copy.deepcopy(item)
        value["created_at"] = at
        with connect(data) as db:
            row = db.execute(
                "SELECT " + PROJECTION + " FROM (SELECT id,request_id,ordinal,run_id,"
                "run_snapshot_digest,request_digest,%s::timestamptz AS created_at,"
                "%s::bytea AS metadata,ingress,egress FROM ddospector_evidence_v1.bundles "
                "WHERE id=%s) AS boundary", (at, canonical(value), item["id"]),
            ).fetchone()
        assert metadata(row) == value
        positives.append(at)

    expected = {"code": "EVIDENCE_STATE_CORRUPT", "message": ERRORS["EVIDENCE_STATE_CORRUPT"][1]}
    faults = []
    for label, raw, readback in (
        ("infinity", "infinity", "infinity"),
        ("minus-infinity", "-infinity", "-infinity"),
        ("year-10000", "10000-01-01 00:00:00+00", "10000-01-01 00:00:00+00"),
        ("bc", "0001-12-31 23:59:59.999999+00 BC", "0001-12-31 23:59:59.999999+00 BC"),
    ):
        replace_timestamp(raw)
        try:
            changed, quota = stored()
            assert changed[6] == readback
            assert changed[:6] + changed[7:] == original[:6] + original[7:]
            assert quota == counters
            fault = {"case": label, "stored_text": changed[6], "fault_fired": True,
                     "only_created_at_changed": True, "immutable_trigger": "O"}
            try:
                with connect(data) as db:
                    db.execute("SELECT created_at FROM ddospector_evidence_v1.bundles WHERE id=%s",
                               (item["id"],)).fetchone()
            except psycopg.DataError as exc:
                fault["native_hydration"] = {"type": type(exc).__name__, "message": str(exc),
                                             "sqlstate": exc.sqlstate}
            else:
                raise AssertionError("unrepresentable native timestamp did not fire")
            responses = []
            for route, path in paths.items():
                response = capture("timestamp-" + label + "-" + route, client.get(path), 503)
                responses.append({"route": route, "status": response.status_code,
                                  "body": response.json()})
            response = capture("timestamp-" + label + "-replay",
                               client.post(root, json=payload), 503)
            responses.append({"route": "replay", "status": response.status_code,
                              "body": response.json()})
            assert stored() == (changed, counters)  # Reads/replay never repair the scalar.
            fault["responses"] = responses
            faults.append(fault)
        finally:
            replace_timestamp(original[6])
        assert stored() == (original, counters)
        for route, path in paths.items():
            assert capture("timestamp-restored-" + label + "-" + route,
                           client.get(path), 200).content == before[route]
        assert capture("timestamp-restored-" + label + "-replay",
                       client.post(root, json=payload), 200).content == before["replay"]
        assert core_bytes(data, payload["run_id"]) == original_core
        fault["restored_exact_bytes"] = True
        fault["core_unchanged"] = True
        save(output / "timestamp-faults.json", {"faults": faults, "positive_timestamps": positives,
                                               "expected": expected, "source": data["source"]})

    origins = {}
    for name, module in tuple(sys.modules.items()):
        if name.startswith(("aiddos.", "ddospector.")) and getattr(module, "__file__", None):
            path = Path(module.__file__).resolve()
            assert path.is_relative_to(Path(data["root"]) / "src")
            origins[name] = {"path": str(path),
                             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    save(output / "timestamp-source-origins.json", origins)
    wrong = [(fault["case"], response) for fault in faults for response in fault["responses"]
             if response["body"] != expected]
    assert not wrong, ("retained timestamp corruption misclassified", wrong)


def check_controls(client, data, capture, payload, detail):
    check_timestamps(client, data, capture, payload, detail)
    root = "/api/v1/evidence"
    selected = root + "/" + detail["evidence"]["id"]
    bundle_id = detail["evidence"]["id"]
    output = Path(data["output"])
    controls = []

    def error(label, response, code):
        capture(label, response, ERRORS[code][0])
        assert response.json() == {"code": code, "message": ERRORS[code][1]}
        controls.append(label)

    with connect(data) as db:
        counters = db.execute("SELECT * FROM ddospector_evidence_v1.quota").fetchall()
    oversized = copy.deepcopy(payload)
    oversized["request_id"] = str(uuid4())
    oversized["ingress"]["base64"] = base64.b64encode(b"x" * 65537).decode("ascii")
    error("oversized", client.post(root, json=oversized), "EVIDENCE_CAPTURE_TOO_LARGE")
    with connect(data) as db:
        assert db.execute("SELECT * FROM ddospector_evidence_v1.quota").fetchall() == counters
        assert db.execute("SELECT count(*) FROM ddospector_evidence_v1.bundles").fetchone() == (1,)
    conflict = copy.deepcopy(payload)
    conflict["egress"]["name"] += "changed"
    error("conflict", client.post(root, json=conflict), "EVIDENCE_IDEMPOTENCY_CONFLICT")
    missing = copy.deepcopy(payload)
    missing.update(request_id=str(uuid4()), run_id=str(uuid4()))
    error("missing-run", client.post(root, json=missing), "EVIDENCE_RUN_NOT_READY")
    error("not-found", client.get(root + "/" + str(uuid4())), "EVIDENCE_NOT_FOUND")

    # Bounded read observer: list transfers metadata bytes only, selected detail one pair.
    from aiddos.runs.lifetime import Operation
    original = Operation.execute
    queries = []
    async def observed(self, sql, args=None):
        rows = await original(self, sql, args)
        queries.append({"sql": sql, "rows": len(rows),
                        "byte_columns": [[len(v) for v in row if isinstance(v, bytes)]
                                         for row in rows]})
        return rows
    Operation.execute = observed
    try:
        capture("observed-list", client.get(root), 200)
        list_queries = queries[:]
        queries.clear()
        capture("observed-detail", client.get(selected), 200)
        selected_queries = queries[:]
    finally:
        Operation.execute = original
    assert not any(",ingress,egress FROM" in q["sql"] for q in list_queries)
    raw_queries = [q for q in selected_queries if ",ingress,egress FROM" in q["sql"]]
    assert len(raw_queries) == 1 and raw_queries[0]["rows"] == 1
    assert len(raw_queries[0]["byte_columns"][0]) == 3
    save(output / "query-census.json", {"list": list_queries, "selected": selected_queries})

    # One local transaction-failure injection after the actual INSERT; no DB/worker fault.
    from aiddos.api.errors import DraftError
    attempted = copy.deepcopy(payload)
    attempted["request_id"] = str(uuid4())
    inserted = []
    async def fail_after_insert(self, sql, args=None):
        rows = await original(self, sql, args)
        if sql.startswith("INSERT INTO ddospector_evidence_v1.bundles"):
            inserted.append(True)
            raise DraftError("RUN_DB_UNAVAILABLE")
        return rows
    Operation.execute = fail_after_insert
    try:
        error("atomic-rollback", client.post(root, json=attempted), "RUN_DB_UNAVAILABLE")
    finally:
        Operation.execute = original
    assert inserted == [True]
    with connect(data) as db:
        assert db.execute("SELECT * FROM ddospector_evidence_v1.quota").fetchall() == counters
        assert db.execute("SELECT count(*) FROM ddospector_evidence_v1.bundles").fetchone() == (1,)
    error("rollback-absent", client.get(root + "/by-request/" + attempted["request_id"]),
          "EVIDENCE_NOT_FOUND")

    # Runtime ACLs and actual forbidden statements, not only schema declarations.
    denied = []
    for table in ("bundles", "reports"):
        with connect(data) as db:
            assert db.execute(
                "SELECT has_table_privilege(current_user,%s,'SELECT'),"
                "has_table_privilege(current_user,%s,'INSERT'),"
                "has_table_privilege(current_user,%s,'UPDATE'),"
                "has_table_privilege(current_user,%s,'DELETE')",
                ("ddospector_evidence_v1." + table,) * 4,
            ).fetchone() == (True, True, False, False)
        for sql in (f"DELETE FROM ddospector_evidence_v1.{table}",
                    "UPDATE ddospector_evidence_v1." + table +
                    (" SET metadata=metadata" if table == "bundles" else " SET body=body")):
            try:
                with connect(data) as db:
                    db.execute(sql)
            except psycopg.errors.InsufficientPrivilege:
                denied.append(sql)
            else:
                raise AssertionError("runtime mutation was allowed")
    save(output / "immutability.json", {"denied": denied})

    # Reserved report storage limit: real SQL exact/+1 with every transaction rolled back.
    for size in (32768, 32769):
        with connect(data) as db:
            try:
                db.execute("INSERT INTO ddospector_evidence_v1.reports VALUES(%s,%s,%s)",
                           (bundle_id, b"x" * size, hashlib.sha256(b"x" * size).hexdigest()))
                assert size == 32768
                assert db.execute("SELECT octet_length(body) FROM ddospector_evidence_v1.reports"
                                  ).fetchone() == (32768,)
            except psycopg.errors.CheckViolation:
                assert size == 32769
            finally:
                db.rollback()

    # SQL envelope limits are not claims that arbitrary 4096-byte metadata is valid JSON.
    for column, exact in (("metadata", 4096), ("ingress", 65536), ("egress", 65536)):
        for size in (exact, exact + 1):
            with connect(data) as db:
                try:
                    fields = {"metadata": "metadata", "ingress": "ingress", "egress": "egress"}
                    fields[column] = "%s"
                    db.execute(
                        "INSERT INTO ddospector_evidence_v1.bundles "
                        "SELECT %s,%s,2,run_id,run_snapshot_digest,request_digest,created_at,"
                        + fields["metadata"] + "," + fields["ingress"] + "," + fields["egress"]
                        + " FROM ddospector_evidence_v1.bundles WHERE id=%s",
                        (str(uuid4()), str(uuid4()), b"x" * size, bundle_id),
                    )
                    assert size == exact
                except psycopg.errors.CheckViolation:
                    assert size == exact + 1
                finally:
                    db.rollback()
    try:
        with connect(data) as db:
            db.execute("UPDATE ddospector_evidence_v1.quota SET singleton=true")
    except psycopg.errors.InsufficientPrivilege:
        pass
    else:
        raise AssertionError("quota identity update allowed")

    # A malformed readiness-marker column is NOT a database-connectivity error.
    with connect(data, owner=True) as db:
        db.execute("ALTER TABLE ddospector_evidence_v1.schema_version RENAME shape TO broken_shape")
    try:
        for label, response in (("marker-list", client.get(root)),
                                ("marker-post", client.post(root, json=payload)),
                                ("marker-detail", client.get(selected))):
            error(label, response, "EVIDENCE_NOT_READY")
    finally:
        with connect(data, owner=True) as db:
            db.execute("ALTER TABLE ddospector_evidence_v1.schema_version "
                       "RENAME broken_shape TO shape")
    assert capture("marker-restored", client.get(selected), 200).json() == detail

    # Counter corruption is surfaced, never an empty list or implicit repair.
    with connect(data) as db:
        db.execute("UPDATE ddospector_evidence_v1.quota SET retained_count=2")
    try:
        error("counter-list", client.get(root), "EVIDENCE_STATE_CORRUPT")
        error("counter-post", client.post(root, json=payload), "EVIDENCE_STATE_CORRUPT")
        with connect(data) as db:
            assert db.execute("SELECT retained_count FROM ddospector_evidence_v1.quota"
                              ).fetchone() == (2,)
    finally:
        with connect(data) as db:
            db.execute("UPDATE ddospector_evidence_v1.quota SET retained_count=1")

    # Privileged isolated corruption fixtures restore trigger shape BEFORE HTTP observation.
    def replace(column, raw):
        assert column in {"metadata", "ingress"}
        with connect(data, owner=True) as db:
            db.execute("ALTER TABLE ddospector_evidence_v1.bundles "
                       "DISABLE TRIGGER bundles_immutable")
            db.execute("UPDATE ddospector_evidence_v1.bundles SET " + column + "=%s WHERE id=%s",
                       (raw, bundle_id))
            db.execute("ALTER TABLE ddospector_evidence_v1.bundles "
                       "ENABLE TRIGGER bundles_immutable")
            assert db.execute("SELECT " + column + " FROM ddospector_evidence_v1.bundles "
                              "WHERE id=%s", (bundle_id,)).fetchone()[0] == raw

    bad = copy.deepcopy(detail["evidence"])
    bad["ingress"]["size_bytes"] = True
    for label, raw in (("metadata-array", b"[]"), ("metadata-bool", canonical(bad))):
        replace("metadata", raw)
        try:
            error(label + "-list", client.get(root), "EVIDENCE_STATE_CORRUPT")
            error(label + "-detail", client.get(selected), "EVIDENCE_STATE_CORRUPT")
            error(label + "-raw", client.get(selected + "/raw/ingress"), "EVIDENCE_STATE_CORRUPT")
        finally:
            replace("metadata", canonical(detail["evidence"]))
    ingress = base64.b64decode(payload["ingress"]["base64"])
    replace("ingress", bytes([ingress[0] ^ 1]) + ingress[1:])
    try:
        # List explicitly does not claim raw verification.
        capture("raw-corrupt-metadata-list", client.get(root), 200)
        error("raw-corrupt-detail", client.get(selected), "EVIDENCE_STATE_CORRUPT")
        error("raw-corrupt-download", client.get(selected + "/raw/ingress"),
              "EVIDENCE_STATE_CORRUPT")
    finally:
        replace("ingress", ingress)

    # Both other generated pairs are recognized from actual original digests.
    for sample_id in ("violation", "unknown"):
        pair = make_sample(sample_id)
        body = {"request_id": str(uuid4()), "run_id": payload["run_id"],
                **{side: {"name": "untrusted-name", "base64": base64.b64encode(
                    getattr(pair, side)).decode("ascii")} for side in ("ingress", "egress")}}
        item = capture(sample_id, client.post(root, json=body), 201).json()["evidence"]
        assert item["sample_id"] == sample_id and item["coverage"] == pair.coverage
        assert item["analysis_state"] == "REGISTERED"
        for side in ("ingress", "egress"):
            downloaded = capture(sample_id + "-" + side,
                                 client.get(root + "/" + item["id"] + "/raw/" + side), 200)
            assert downloaded.content == getattr(pair, side)

    # Maximal inputs are intentionally malformed PCAP: registration is not parsing.
    maximal = {"request_id": str(uuid4()), "run_id": payload["run_id"],
               **{side: {"name": "é" * 128,
                         "base64": base64.b64encode(bytes(range(256)) * 256).decode("ascii")}
                  for side in ("ingress", "egress")}}
    for ordinal in range(4, 17):
        maximal["request_id"] = str(uuid4())
        response = capture(f"capacity-{ordinal}", client.post(root, json=maximal), 201)
        item = response.json()["evidence"]
        assert item["ordinal"] == ordinal and item["provenance"] == "UNVERIFIED"
        assert item["sample_id"] is None and item["coverage"] == "UNKNOWN"
    for side in ("ingress", "egress"):
        raw = capture("maximal-" + side, client.get(root + "/" + item["id"] + "/raw/" + side), 200)
        assert raw.content == bytes(range(256)) * 256 and len(raw.content) == 65536
    listing = capture("full-list", client.get(root), 200)
    assert listing.json()["total"] == 16
    assert [item["ordinal"] for item in listing.json()["items"]] == list(range(1, 17))
    assert len(listing.content) <= 65536
    assert capture("full-replay", client.post(root, json=payload), 200).json() == detail
    error("full-conflict", client.post(root, json=conflict), "EVIDENCE_IDEMPOTENCY_CONFLICT")
    maximal["request_id"] = str(uuid4())
    error("capacity-17", client.post(root, json=maximal), "EVIDENCE_RETENTION_FULL")
    assert client.get(root).content == listing.content
    with connect(data) as db:
        retained, total = db.execute("SELECT retained_count,raw_bytes FROM "
                                     "ddospector_evidence_v1.quota").fetchone()
        assert retained == 16
        assert db.execute("SELECT count(*),sum(octet_length(ingress)+octet_length(egress)) "
                          "FROM ddospector_evidence_v1.bundles").fetchone() == (16, total)

    # P2-01 must refuse even a bounded stored report; no implicit future-schema trust.
    with connect(data) as db:
        db.execute("INSERT INTO ddospector_evidence_v1.reports VALUES(%s,%s,%s)",
                   (bundle_id, b"{}", hashlib.sha256(b"{}").hexdigest()))
        assert db.execute("SELECT count(*) FROM ddospector_evidence_v1.reports"
                          ).fetchone() == (1,)
    error("unexpected-report-list", client.get(root), "EVIDENCE_STATE_CORRUPT")
    error("unexpected-report-detail", client.get(selected), "EVIDENCE_STATE_CORRUPT")
    error("unexpected-report-raw", client.get(selected + "/raw/egress"), "EVIDENCE_STATE_CORRUPT")
    save(output / "controls.json", {"public_failures": controls, "retained_count": retained,
                                    "raw_bytes": total, "report_fixture_retained": True,
                                    "corruption_fixture":
                                    "ISOLATED_OWNER_SQL_NOT_RUNTIME_AUTHORITY"})
