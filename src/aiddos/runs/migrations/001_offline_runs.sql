CREATE SCHEMA aiddos_runs_v1 AUTHORIZATION aiddos_s02_owner;
REVOKE ALL ON SCHEMA aiddos_runs_v1 FROM PUBLIC;
CREATE TABLE aiddos_runs_v1.schema_version (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 version integer NOT NULL CHECK(version=1),
 checksum text NOT NULL CHECK(checksum ~ '^[0-9a-f]{64}$'),
 shape text NOT NULL
);
CREATE TABLE aiddos_runs_v1.quota (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 retained_count integer NOT NULL CHECK(retained_count BETWEEN 0 AND 128),
 unfinished_count integer NOT NULL CHECK(unfinished_count BETWEEN 0 AND 16),
 leased_count integer NOT NULL CHECK(leased_count BETWEEN 0 AND 2),
 reserved_bytes integer NOT NULL CHECK(reserved_bytes=retained_count*65536),
 CHECK(leased_count<=unfinished_count AND unfinished_count<=retained_count)
);
INSERT INTO aiddos_runs_v1.quota VALUES(true,0,0,0,0);
CREATE TABLE aiddos_runs_v1.inputs (
 run_id uuid PRIMARY KEY,
 request_id uuid NOT NULL UNIQUE,
 ordinal integer NOT NULL UNIQUE CHECK(ordinal BETWEEN 1 AND 128),
 request bytea NOT NULL CHECK(octet_length(request) BETWEEN 1 AND 1024),
 request_digest text NOT NULL CHECK(request_digest ~ '^[0-9a-f]{64}$'),
 snapshot bytea NOT NULL CHECK(octet_length(snapshot) BETWEEN 1 AND 12288),
 snapshot_digest text NOT NULL CHECK(snapshot_digest ~ '^[0-9a-f]{64}$')
);
CREATE TABLE aiddos_runs_v1.jobs (
 run_id uuid PRIMARY KEY REFERENCES aiddos_runs_v1.inputs(run_id),
 state text NOT NULL CHECK(state IN ('QUEUED','RUNNING','CANCEL_REQUESTED','SUCCEEDED','FAILED','CANCELLED','TIMED_OUT')),
 attempt integer NOT NULL CHECK(attempt BETWEEN 0 AND 3),
 generation integer NOT NULL CHECK(generation BETWEEN 0 AND 6),
 created_at timestamptz NOT NULL,
 started_at timestamptz,
 updated_at timestamptz NOT NULL,
 finished_at timestamptz,
 deadline_at timestamptz NOT NULL,
 cancel_requested_at timestamptz,
 event_count integer NOT NULL CHECK(event_count BETWEEN 1 AND 16),
 failure_code text,
 owner_token uuid,
 lease_until timestamptz,
 step integer NOT NULL CHECK(step BETWEEN 0 AND 2),
 CHECK(deadline_at=created_at+interval '300 seconds'),
 CHECK(updated_at>=created_at),
 CHECK((attempt=0)=(started_at IS NULL)),
 CHECK((state IN ('RUNNING','CANCEL_REQUESTED'))=(owner_token IS NOT NULL)),
 CHECK((owner_token IS NULL)=(lease_until IS NULL)),
 CHECK((state IN ('SUCCEEDED','FAILED','CANCELLED','TIMED_OUT'))=(finished_at IS NOT NULL)),
 CHECK(finished_at IS NULL OR finished_at=updated_at),
 CHECK((state IN ('CANCEL_REQUESTED','CANCELLED'))=(cancel_requested_at IS NOT NULL)),
 CHECK((state='FAILED' AND failure_code IN ('SNAPSHOT_INVALID','OFFLINE_PREPARATION_FAILED','RESULT_LIMIT_EXCEEDED','RETRY_EXHAUSTED'))
    OR (state='TIMED_OUT' AND failure_code='DEADLINE_EXCEEDED')
    OR (state NOT IN ('FAILED','TIMED_OUT') AND failure_code IS NULL)),
 CHECK(state NOT IN ('FAILED','TIMED_OUT') OR failure_code IS NOT NULL)
);
CREATE TABLE aiddos_runs_v1.results (
 run_id uuid PRIMARY KEY REFERENCES aiddos_runs_v1.jobs(run_id),
 result bytea NOT NULL CHECK(octet_length(result) BETWEEN 1 AND 8192)
);
CREATE TABLE aiddos_runs_v1.events (
 run_id uuid REFERENCES aiddos_runs_v1.jobs(run_id),
 seq integer CHECK(seq BETWEEN 1 AND 16),
 event bytea NOT NULL CHECK(octet_length(event) BETWEEN 1 AND 512),
 PRIMARY KEY(run_id,seq)
);
CREATE FUNCTION aiddos_runs_v1.immutable_record() RETURNS trigger LANGUAGE plpgsql
AS $$ BEGIN RAISE EXCEPTION 'immutable offline record' USING ERRCODE='23514'; END $$;
CREATE TRIGGER inputs_immutable BEFORE UPDATE OR DELETE ON aiddos_runs_v1.inputs
FOR EACH ROW EXECUTE FUNCTION aiddos_runs_v1.immutable_record();
CREATE TRIGGER results_immutable BEFORE UPDATE OR DELETE ON aiddos_runs_v1.results
FOR EACH ROW EXECUTE FUNCTION aiddos_runs_v1.immutable_record();
CREATE TRIGGER events_immutable BEFORE UPDATE OR DELETE ON aiddos_runs_v1.events
FOR EACH ROW EXECUTE FUNCTION aiddos_runs_v1.immutable_record();
CREATE FUNCTION aiddos_runs_v1.job_identity() RETURNS trigger LANGUAGE plpgsql
AS $$ BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'immutable offline identity' USING ERRCODE='23514'; END IF;
 IF OLD.state IN ('SUCCEEDED','FAILED','CANCELLED','TIMED_OUT')
 OR NEW.run_id IS DISTINCT FROM OLD.run_id
 OR NEW.created_at IS DISTINCT FROM OLD.created_at
 OR NEW.deadline_at IS DISTINCT FROM OLD.deadline_at
 OR (OLD.started_at IS NOT NULL AND NEW.started_at IS DISTINCT FROM OLD.started_at)
 OR (OLD.cancel_requested_at IS NOT NULL AND NEW.cancel_requested_at IS DISTINCT FROM OLD.cancel_requested_at)
 OR (OLD.finished_at IS NOT NULL AND NEW.finished_at IS DISTINCT FROM OLD.finished_at)
 THEN RAISE EXCEPTION 'immutable offline identity' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER jobs_identity BEFORE UPDATE OR DELETE ON aiddos_runs_v1.jobs
FOR EACH ROW EXECUTE FUNCTION aiddos_runs_v1.job_identity();
GRANT USAGE ON SCHEMA aiddos_runs_v1 TO aiddos_s02;
GRANT SELECT ON ALL TABLES IN SCHEMA aiddos_runs_v1 TO aiddos_s02;
GRANT INSERT ON aiddos_runs_v1.inputs,aiddos_runs_v1.jobs,aiddos_runs_v1.results,aiddos_runs_v1.events TO aiddos_s02;
GRANT UPDATE ON aiddos_runs_v1.jobs,aiddos_runs_v1.quota TO aiddos_s02;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA aiddos_runs_v1 FROM PUBLIC;
