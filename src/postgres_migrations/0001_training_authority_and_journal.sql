DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dohalm_training_owner') THEN
        CREATE ROLE dohalm_training_owner NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dohalm_training_runtime') THEN
        CREATE ROLE dohalm_training_runtime LOGIN NOINHERIT;
    END IF;
END
$$;

ALTER ROLE dohalm_training_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE dohalm_training_runtime LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER SCHEMA dohalm_training_v1 OWNER TO dohalm_training_owner;
REVOKE ALL ON SCHEMA dohalm_training_v1 FROM PUBLIC;

CREATE TABLE dohalm_training_v1.training_authority_identity (
    authority_id uuid PRIMARY KEY,
    subject_family text NOT NULL CHECK (
        subject_family IN (
            'config', 'readiness', 'dataset_version', 'dataset_manifest',
            'dataset_pair', 'decision', 'issuer', 'approver'
        )
    ),
    domain_key varchar(256) NOT NULL CHECK (
        domain_key ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$'
    ),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    UNIQUE (subject_family, domain_key),
    UNIQUE (authority_id, subject_family)
);

CREATE TABLE dohalm_training_v1.training_config_authority (
    authority_id uuid PRIMARY KEY,
    subject_family text NOT NULL DEFAULT 'config' CHECK (subject_family = 'config'),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    payload_bytes bytea NOT NULL CHECK (octet_length(payload_bytes) > 0),
    payload_sha256 char(71) NOT NULL CHECK (payload_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    valid_from timestamptz NOT NULL CHECK (created_at <= valid_from),
    valid_until timestamptz NULL DEFAULT NULL CHECK (valid_until IS NULL OR valid_from < valid_until),
    source_commit char(40) NOT NULL CHECK (source_commit ~ '^[0-9a-f]{40}$'),
    config_kind text NOT NULL CHECK (config_kind = 'full_pretraining'),
    config_schema_version smallint NOT NULL CHECK (config_schema_version = 1),
    FOREIGN KEY (authority_id, subject_family)
        REFERENCES dohalm_training_v1.training_authority_identity (authority_id, subject_family)
        ON DELETE RESTRICT
);

CREATE TABLE dohalm_training_v1.training_readiness_authority (
    authority_id uuid PRIMARY KEY,
    subject_family text NOT NULL DEFAULT 'readiness' CHECK (subject_family = 'readiness'),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    payload_bytes bytea NOT NULL CHECK (octet_length(payload_bytes) > 0),
    payload_sha256 char(71) NOT NULL CHECK (payload_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    valid_from timestamptz NOT NULL CHECK (created_at <= valid_from),
    valid_until timestamptz NULL DEFAULT NULL CHECK (
        valid_until IS NOT NULL AND valid_from < valid_until
    ),
    source_commit char(40) NOT NULL CHECK (source_commit ~ '^[0-9a-f]{40}$'),
    dataset_pair_fingerprint char(71) NOT NULL CHECK (dataset_pair_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    config_fingerprint char(71) NOT NULL CHECK (config_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    evaluated_at timestamptz NOT NULL CHECK (evaluated_at < valid_until),
    readiness_result text NOT NULL CHECK (readiness_result = 'READY'),
    FOREIGN KEY (authority_id, subject_family)
        REFERENCES dohalm_training_v1.training_authority_identity (authority_id, subject_family)
        ON DELETE RESTRICT
);

CREATE TABLE dohalm_training_v1.dataset_version_authority (
    authority_id uuid PRIMARY KEY,
    subject_family text NOT NULL DEFAULT 'dataset_version' CHECK (subject_family = 'dataset_version'),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    payload_bytes bytea NOT NULL CHECK (octet_length(payload_bytes) > 0),
    payload_sha256 char(71) NOT NULL CHECK (payload_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    valid_from timestamptz NOT NULL CHECK (created_at <= valid_from),
    valid_until timestamptz NULL DEFAULT NULL CHECK (valid_until IS NULL OR valid_from < valid_until),
    source_commit char(40) NOT NULL CHECK (source_commit ~ '^[0-9a-f]{40}$'),
    common_object_id varchar(256) NOT NULL UNIQUE,
    FOREIGN KEY (authority_id, subject_family)
        REFERENCES dohalm_training_v1.training_authority_identity (authority_id, subject_family)
        ON DELETE RESTRICT
);

CREATE TABLE dohalm_training_v1.dataset_manifest_authority (
    authority_id uuid PRIMARY KEY,
    subject_family text NOT NULL DEFAULT 'dataset_manifest' CHECK (subject_family = 'dataset_manifest'),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    payload_bytes bytea NOT NULL CHECK (octet_length(payload_bytes) > 0),
    payload_sha256 char(71) NOT NULL CHECK (payload_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    valid_from timestamptz NOT NULL CHECK (created_at <= valid_from),
    valid_until timestamptz NULL DEFAULT NULL CHECK (valid_until IS NULL OR valid_from < valid_until),
    source_commit char(40) NOT NULL CHECK (source_commit ~ '^[0-9a-f]{40}$'),
    common_object_id varchar(256) NOT NULL UNIQUE,
    FOREIGN KEY (authority_id, subject_family)
        REFERENCES dohalm_training_v1.training_authority_identity (authority_id, subject_family)
        ON DELETE RESTRICT
);

CREATE TABLE dohalm_training_v1.dataset_pair_authority (
    authority_id uuid PRIMARY KEY,
    subject_family text NOT NULL DEFAULT 'dataset_pair' CHECK (subject_family = 'dataset_pair'),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    payload_bytes bytea NOT NULL CHECK (octet_length(payload_bytes) > 0),
    payload_sha256 char(71) NOT NULL CHECK (payload_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    valid_from timestamptz NOT NULL CHECK (created_at <= valid_from),
    valid_until timestamptz NULL DEFAULT NULL CHECK (valid_until IS NULL OR valid_from < valid_until),
    source_commit char(40) NOT NULL CHECK (source_commit ~ '^[0-9a-f]{40}$'),
    dataset_version_authority_id uuid NOT NULL REFERENCES dohalm_training_v1.dataset_version_authority (authority_id) ON DELETE RESTRICT,
    dataset_manifest_authority_id uuid NOT NULL REFERENCES dohalm_training_v1.dataset_manifest_authority (authority_id) ON DELETE RESTRICT,
    pair_fingerprint char(71) NOT NULL CHECK (pair_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    publication_scenario text NOT NULL CHECK (publication_scenario <> ''),
    UNIQUE (
        dataset_version_authority_id, dataset_manifest_authority_id,
        pair_fingerprint, publication_scenario
    ),
    FOREIGN KEY (authority_id, subject_family)
        REFERENCES dohalm_training_v1.training_authority_identity (authority_id, subject_family)
        ON DELETE RESTRICT
);

CREATE TABLE dohalm_training_v1.training_issuer_registry (
    authority_id uuid PRIMARY KEY,
    subject_family text NOT NULL DEFAULT 'issuer' CHECK (subject_family = 'issuer'),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    payload_bytes bytea NOT NULL CHECK (octet_length(payload_bytes) > 0),
    payload_sha256 char(71) NOT NULL CHECK (payload_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    valid_from timestamptz NOT NULL CHECK (created_at <= valid_from),
    valid_until timestamptz NULL DEFAULT NULL CHECK (valid_until IS NULL OR valid_from < valid_until),
    source_commit char(40) NOT NULL CHECK (source_commit ~ '^[0-9a-f]{40}$'),
    issuer_id varchar(256) NOT NULL UNIQUE,
    adapter_kind text NOT NULL CHECK (adapter_kind = 'same_process_training_execution_issuer'),
    active_from timestamptz NOT NULL,
    active_until timestamptz NULL CHECK (active_until IS NULL OR active_from < active_until),
    UNIQUE (authority_id, issuer_id),
    FOREIGN KEY (authority_id, subject_family)
        REFERENCES dohalm_training_v1.training_authority_identity (authority_id, subject_family)
        ON DELETE RESTRICT
);

CREATE TABLE dohalm_training_v1.training_approver_registry (
    authority_id uuid PRIMARY KEY,
    subject_family text NOT NULL DEFAULT 'approver' CHECK (subject_family = 'approver'),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    payload_bytes bytea NOT NULL CHECK (octet_length(payload_bytes) > 0),
    payload_sha256 char(71) NOT NULL CHECK (payload_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    valid_from timestamptz NOT NULL CHECK (created_at <= valid_from),
    valid_until timestamptz NULL DEFAULT NULL CHECK (valid_until IS NULL OR valid_from < valid_until),
    source_commit char(40) NOT NULL CHECK (source_commit ~ '^[0-9a-f]{40}$'),
    approver_reference varchar(256) NOT NULL UNIQUE,
    active_from timestamptz NOT NULL,
    active_until timestamptz NULL CHECK (active_until IS NULL OR active_from < active_until),
    UNIQUE (authority_id, approver_reference),
    FOREIGN KEY (authority_id, subject_family)
        REFERENCES dohalm_training_v1.training_authority_identity (authority_id, subject_family)
        ON DELETE RESTRICT
);

CREATE TABLE dohalm_training_v1.training_execution_decision_authority (
    authority_id uuid PRIMARY KEY,
    subject_family text NOT NULL DEFAULT 'decision' CHECK (subject_family = 'decision'),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    payload_bytes bytea NOT NULL CHECK (octet_length(payload_bytes) > 0),
    payload_sha256 char(71) NOT NULL CHECK (payload_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    valid_from timestamptz NOT NULL CHECK (created_at <= valid_from),
    valid_until timestamptz NULL DEFAULT NULL CHECK (
        valid_until IS NOT NULL AND valid_from < valid_until
    ),
    source_commit char(40) NOT NULL CHECK (source_commit ~ '^[0-9a-f]{40}$'),
    decision text NOT NULL CHECK (decision IN ('approved', 'denied')),
    authorization_id varchar(256) NOT NULL UNIQUE,
    issuer_authority_id uuid NOT NULL,
    issuer_id varchar(256) NOT NULL,
    approver_authority_id uuid NOT NULL,
    approver_reference varchar(256) NOT NULL,
    evidence_reference varchar(256) NOT NULL CHECK (evidence_reference ~ '^decision:[0-9a-f-]{36}$'),
    request_fingerprint char(71) NOT NULL CHECK (request_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    issued_at timestamptz NOT NULL CHECK (valid_from <= issued_at AND issued_at < valid_until),
    FOREIGN KEY (issuer_authority_id, issuer_id)
        REFERENCES dohalm_training_v1.training_issuer_registry (authority_id, issuer_id) ON DELETE RESTRICT,
    FOREIGN KEY (approver_authority_id, approver_reference)
        REFERENCES dohalm_training_v1.training_approver_registry (authority_id, approver_reference) ON DELETE RESTRICT,
    FOREIGN KEY (authority_id, subject_family)
        REFERENCES dohalm_training_v1.training_authority_identity (authority_id, subject_family)
        ON DELETE RESTRICT
);

CREATE TABLE dohalm_training_v1.training_authority_event (
    event_id uuid PRIMARY KEY,
    authority_id uuid NOT NULL,
    subject_family text NOT NULL CHECK (
        subject_family IN (
            'config', 'readiness', 'dataset_version', 'dataset_manifest',
            'dataset_pair', 'decision', 'issuer', 'approver'
        )
    ),
    subject_version bigint NOT NULL CHECK (subject_version >= 1),
    event_kind text NOT NULL CHECK (event_kind IN ('published', 'activated', 'revoked', 'superseded')),
    superseded_by_authority_id uuid NULL,
    effective_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    producer_role varchar(128) NOT NULL CHECK (producer_role = 'training_authority_producer'),
    correlation_reference varchar(256) NOT NULL CHECK (correlation_reference ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$'),
    evidence_reference varchar(256) NOT NULL CHECK (evidence_reference ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$'),
    event_fingerprint char(71) NOT NULL CHECK (event_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    CHECK ((event_kind = 'superseded') = (superseded_by_authority_id IS NOT NULL)),
    CHECK (superseded_by_authority_id IS NULL OR superseded_by_authority_id <> authority_id),
    UNIQUE (authority_id, subject_version),
    FOREIGN KEY (authority_id, subject_family)
        REFERENCES dohalm_training_v1.training_authority_identity (authority_id, subject_family) ON DELETE RESTRICT,
    FOREIGN KEY (superseded_by_authority_id, subject_family)
        REFERENCES dohalm_training_v1.training_authority_identity (authority_id, subject_family) ON DELETE RESTRICT
);

CREATE TABLE dohalm_training_v1.training_authority_current (
    authority_id uuid PRIMARY KEY REFERENCES dohalm_training_v1.training_authority_identity (authority_id) ON DELETE RESTRICT,
    subject_family text NOT NULL,
    stream_head_event_id uuid NOT NULL REFERENCES dohalm_training_v1.training_authority_event (event_id) ON DELETE RESTRICT,
    current_event_id uuid NULL REFERENCES dohalm_training_v1.training_authority_event (event_id) ON DELETE RESTRICT,
    current_subject_version bigint NOT NULL CHECK (current_subject_version >= 1),
    state text NOT NULL CHECK (state IN ('scheduled', 'current', 'expired', 'revoked', 'superseded')),
    state_effective_at timestamptz NOT NULL,
    superseded_by_authority_id uuid NULL,
    valid_from timestamptz NOT NULL,
    valid_until timestamptz NULL CHECK (valid_until IS NULL OR valid_from < valid_until),
    projection_version bigint NOT NULL CHECK (projection_version >= 1),
    projected_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    CHECK ((state = 'scheduled') = (current_event_id IS NULL)),
    CHECK ((state = 'superseded') = (superseded_by_authority_id IS NOT NULL)),
    CHECK (projection_version = current_subject_version),
    FOREIGN KEY (authority_id, subject_family)
        REFERENCES dohalm_training_v1.training_authority_identity (authority_id, subject_family) ON DELETE RESTRICT,
    FOREIGN KEY (superseded_by_authority_id, subject_family)
        REFERENCES dohalm_training_v1.training_authority_identity (authority_id, subject_family) ON DELETE RESTRICT
);

CREATE TABLE dohalm_training_v1.training_execution_journal (
    run_id varchar(256) PRIMARY KEY CHECK (run_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$'),
    request_fingerprint char(71) NOT NULL CHECK (request_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    intent_fingerprint char(71) NOT NULL CHECK (intent_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    host_schema_version smallint NOT NULL DEFAULT 1 CHECK (host_schema_version = 1),
    host_lifecycle_version smallint NOT NULL DEFAULT 1 CHECK (host_lifecycle_version = 1),
    orchestration_correlation_id varchar(256) NOT NULL UNIQUE,
    dataset_version_id varchar(256) NOT NULL,
    dataset_manifest_id varchar(256) NOT NULL,
    dataset_pair_fingerprint char(71) NOT NULL CHECK (dataset_pair_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    config_fingerprint char(71) NOT NULL CHECK (config_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    readiness_fingerprint char(71) NOT NULL CHECK (readiness_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    source_commit char(40) NOT NULL CHECK (source_commit ~ '^[0-9a-f]{40}$'),
    prerequisite_resolution_policy_reference varchar(256) NOT NULL,
    authorization_id varchar(256) NULL,
    issuer_id varchar(256) NULL,
    approver_reference varchar(256) NULL,
    evidence_reference varchar(256) NULL,
    authorization_fingerprint char(71) NULL CHECK (authorization_fingerprint IS NULL OR authorization_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    decision_evidence_fingerprint char(71) NULL CHECK (decision_evidence_fingerprint IS NULL OR decision_evidence_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    decision_policy_reference varchar(256) NULL,
    phase text NOT NULL DEFAULT 'claimed' CHECK (
        phase IN (
            'claimed', 'resolved', 'validated', 'decision_submitted',
            'approval_consumed', 'backend_entered', 'completed', 'failed',
            'manual_reconciliation_required'
        )
    ),
    journal_version bigint NOT NULL DEFAULT 1 CHECK (journal_version >= 1),
    backend_entered boolean NOT NULL DEFAULT false,
    reconciliation_required boolean NOT NULL DEFAULT false,
    reconciliation_reason_code varchar(128) NULL CHECK (
        reconciliation_reason_code IS NULL OR reconciliation_reason_code ~ '^[A-Z][A-Z0-9_]{0,127}$'
    ),
    process_boundary_id varchar(256) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    UNIQUE (run_id, request_fingerprint),
    CHECK (
        (authorization_id IS NULL AND issuer_id IS NULL AND approver_reference IS NULL AND
         evidence_reference IS NULL AND authorization_fingerprint IS NULL AND
         decision_evidence_fingerprint IS NULL AND decision_policy_reference IS NULL)
        OR
        (authorization_id IS NOT NULL AND issuer_id IS NOT NULL AND approver_reference IS NOT NULL AND
         evidence_reference IS NOT NULL AND authorization_fingerprint IS NOT NULL AND
         decision_evidence_fingerprint IS NOT NULL AND decision_policy_reference IS NOT NULL)
    ),
    CHECK (reconciliation_required = (phase = 'manual_reconciliation_required')),
    CHECK ((reconciliation_reason_code IS NOT NULL) = (phase = 'manual_reconciliation_required')),
    CHECK (NOT backend_entered OR phase IN ('backend_entered', 'completed', 'failed', 'manual_reconciliation_required'))
);

CREATE TABLE dohalm_training_v1.training_execution_phase_event (
    event_id uuid PRIMARY KEY,
    run_id varchar(256) NOT NULL,
    request_fingerprint char(71) NOT NULL CHECK (request_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    journal_version bigint NOT NULL CHECK (journal_version >= 1),
    from_phase text NULL,
    to_phase text NOT NULL CHECK (
        to_phase IN (
            'claimed', 'resolved', 'validated', 'decision_submitted',
            'approval_consumed', 'backend_entered', 'completed', 'failed',
            'manual_reconciliation_required'
        )
    ),
    process_boundary_id varchar(256) NOT NULL,
    reason_code varchar(128) NULL CHECK (reason_code IS NULL OR reason_code ~ '^[A-Z][A-Z0-9_]{0,127}$'),
    event_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    recorded_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    UNIQUE (run_id, journal_version),
    CHECK (event_at = recorded_at),
    CHECK (
        (journal_version = 1 AND from_phase IS NULL AND to_phase = 'claimed' AND reason_code IS NULL)
        OR (journal_version > 1 AND from_phase IS NOT NULL)
    ),
    CHECK ((to_phase IN ('failed', 'manual_reconciliation_required')) = (reason_code IS NOT NULL)),
    FOREIGN KEY (run_id, request_fingerprint)
        REFERENCES dohalm_training_v1.training_execution_journal (run_id, request_fingerprint) ON DELETE RESTRICT
);

CREATE FUNCTION dohalm_training_v1.reject_immutable_mutation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'immutable C1 authority row';
END
$$;

CREATE FUNCTION dohalm_training_v1.read_authority_state(requested_authority_id uuid)
RETURNS text
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT state
    FROM dohalm_training_v1.training_authority_current
    WHERE authority_id = requested_authority_id
$$;

CREATE TRIGGER training_authority_identity_immutable
BEFORE UPDATE OR DELETE ON dohalm_training_v1.training_authority_identity
FOR EACH ROW EXECUTE FUNCTION dohalm_training_v1.reject_immutable_mutation();
CREATE TRIGGER training_config_authority_immutable
BEFORE UPDATE OR DELETE ON dohalm_training_v1.training_config_authority
FOR EACH ROW EXECUTE FUNCTION dohalm_training_v1.reject_immutable_mutation();
CREATE TRIGGER training_readiness_authority_immutable
BEFORE UPDATE OR DELETE ON dohalm_training_v1.training_readiness_authority
FOR EACH ROW EXECUTE FUNCTION dohalm_training_v1.reject_immutable_mutation();
CREATE TRIGGER dataset_version_authority_immutable
BEFORE UPDATE OR DELETE ON dohalm_training_v1.dataset_version_authority
FOR EACH ROW EXECUTE FUNCTION dohalm_training_v1.reject_immutable_mutation();
CREATE TRIGGER dataset_manifest_authority_immutable
BEFORE UPDATE OR DELETE ON dohalm_training_v1.dataset_manifest_authority
FOR EACH ROW EXECUTE FUNCTION dohalm_training_v1.reject_immutable_mutation();
CREATE TRIGGER dataset_pair_authority_immutable
BEFORE UPDATE OR DELETE ON dohalm_training_v1.dataset_pair_authority
FOR EACH ROW EXECUTE FUNCTION dohalm_training_v1.reject_immutable_mutation();
CREATE TRIGGER training_execution_decision_authority_immutable
BEFORE UPDATE OR DELETE ON dohalm_training_v1.training_execution_decision_authority
FOR EACH ROW EXECUTE FUNCTION dohalm_training_v1.reject_immutable_mutation();
CREATE TRIGGER training_issuer_registry_immutable
BEFORE UPDATE OR DELETE ON dohalm_training_v1.training_issuer_registry
FOR EACH ROW EXECUTE FUNCTION dohalm_training_v1.reject_immutable_mutation();
CREATE TRIGGER training_approver_registry_immutable
BEFORE UPDATE OR DELETE ON dohalm_training_v1.training_approver_registry
FOR EACH ROW EXECUTE FUNCTION dohalm_training_v1.reject_immutable_mutation();
CREATE TRIGGER training_authority_event_immutable
BEFORE UPDATE OR DELETE ON dohalm_training_v1.training_authority_event
FOR EACH ROW EXECUTE FUNCTION dohalm_training_v1.reject_immutable_mutation();
CREATE TRIGGER training_execution_phase_event_immutable
BEFORE UPDATE OR DELETE ON dohalm_training_v1.training_execution_phase_event
FOR EACH ROW EXECUTE FUNCTION dohalm_training_v1.reject_immutable_mutation();

ALTER TABLE dohalm_training_v1.schema_migration OWNER TO dohalm_training_owner;
ALTER TABLE dohalm_training_v1.training_authority_identity OWNER TO dohalm_training_owner;
ALTER TABLE dohalm_training_v1.training_config_authority OWNER TO dohalm_training_owner;
ALTER TABLE dohalm_training_v1.training_readiness_authority OWNER TO dohalm_training_owner;
ALTER TABLE dohalm_training_v1.dataset_version_authority OWNER TO dohalm_training_owner;
ALTER TABLE dohalm_training_v1.dataset_manifest_authority OWNER TO dohalm_training_owner;
ALTER TABLE dohalm_training_v1.dataset_pair_authority OWNER TO dohalm_training_owner;
ALTER TABLE dohalm_training_v1.training_execution_decision_authority OWNER TO dohalm_training_owner;
ALTER TABLE dohalm_training_v1.training_issuer_registry OWNER TO dohalm_training_owner;
ALTER TABLE dohalm_training_v1.training_approver_registry OWNER TO dohalm_training_owner;
ALTER TABLE dohalm_training_v1.training_authority_event OWNER TO dohalm_training_owner;
ALTER TABLE dohalm_training_v1.training_authority_current OWNER TO dohalm_training_owner;
ALTER TABLE dohalm_training_v1.training_execution_journal OWNER TO dohalm_training_owner;
ALTER TABLE dohalm_training_v1.training_execution_phase_event OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.reject_immutable_mutation() OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.read_authority_state(uuid) OWNER TO dohalm_training_owner;

REVOKE ALL ON ALL TABLES IN SCHEMA dohalm_training_v1 FROM PUBLIC, dohalm_training_runtime;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA dohalm_training_v1 FROM PUBLIC;
GRANT USAGE ON SCHEMA dohalm_training_v1 TO dohalm_training_runtime;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.read_authority_state(uuid) TO dohalm_training_runtime;
