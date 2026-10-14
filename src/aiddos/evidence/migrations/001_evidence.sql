CREATE SCHEMA ddospector_evidence_v1 AUTHORIZATION aiddos_s02_owner;
REVOKE ALL ON SCHEMA ddospector_evidence_v1 FROM PUBLIC;
CREATE TABLE ddospector_evidence_v1.schema_version (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 version integer NOT NULL CHECK(version=1),
 checksum text NOT NULL CHECK(checksum ~ '^[0-9a-f]{64}$'),
 shape text NOT NULL CHECK(shape ~ '^[0-9a-f]{64}$')
);
CREATE TABLE ddospector_evidence_v1.quota (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 retained_count integer NOT NULL CHECK(retained_count BETWEEN 0 AND 16),
 raw_bytes integer NOT NULL CHECK(raw_bytes BETWEEN retained_count*2 AND retained_count*131072)
);
INSERT INTO ddospector_evidence_v1.quota VALUES(true,0,0);
CREATE TABLE ddospector_evidence_v1.bundles (
 id uuid PRIMARY KEY,
 request_id uuid NOT NULL UNIQUE,
 ordinal integer NOT NULL UNIQUE CHECK(ordinal BETWEEN 1 AND 16),
 run_id uuid NOT NULL REFERENCES aiddos_runs_v1.inputs(run_id),
 run_snapshot_digest text NOT NULL CHECK(run_snapshot_digest ~ '^[0-9a-f]{64}$'),
 request_digest text NOT NULL CHECK(request_digest ~ '^[0-9a-f]{64}$'),
 created_at timestamptz NOT NULL,
 metadata bytea NOT NULL CHECK(octet_length(metadata) BETWEEN 1 AND 4096),
 ingress bytea NOT NULL CHECK(octet_length(ingress) BETWEEN 1 AND 65536),
 egress bytea NOT NULL CHECK(octet_length(egress) BETWEEN 1 AND 65536)
);
CREATE TABLE ddospector_evidence_v1.reports (
 bundle_id uuid PRIMARY KEY REFERENCES ddospector_evidence_v1.bundles(id),
 body bytea NOT NULL CHECK(octet_length(body) BETWEEN 1 AND 32768),
 sha256 text NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$')
);
CREATE FUNCTION ddospector_evidence_v1.immutable_record() RETURNS trigger LANGUAGE plpgsql
AS $$ BEGIN RAISE EXCEPTION 'immutable evidence record' USING ERRCODE='23514'; END $$;
CREATE TRIGGER bundles_immutable BEFORE UPDATE OR DELETE ON ddospector_evidence_v1.bundles
FOR EACH ROW EXECUTE FUNCTION ddospector_evidence_v1.immutable_record();
CREATE TRIGGER reports_immutable BEFORE UPDATE OR DELETE ON ddospector_evidence_v1.reports
FOR EACH ROW EXECUTE FUNCTION ddospector_evidence_v1.immutable_record();
GRANT USAGE ON SCHEMA ddospector_evidence_v1 TO aiddos_s02;
GRANT SELECT ON ALL TABLES IN SCHEMA ddospector_evidence_v1 TO aiddos_s02;
GRANT INSERT ON ddospector_evidence_v1.bundles,ddospector_evidence_v1.reports TO aiddos_s02;
GRANT UPDATE(retained_count,raw_bytes) ON ddospector_evidence_v1.quota TO aiddos_s02;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA ddospector_evidence_v1 FROM PUBLIC;
