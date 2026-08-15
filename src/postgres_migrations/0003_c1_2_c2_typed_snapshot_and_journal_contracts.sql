CREATE FUNCTION dohalm_training_v1.read_c2_training_prerequisite_snapshot(
    requested_dataset_version_authority_id uuid,
    requested_dataset_manifest_authority_id uuid,
    requested_config_authority_id uuid,
    requested_readiness_authority_id uuid,
    requested_pair_fingerprint char(71),
    requested_config_fingerprint char(71),
    requested_readiness_fingerprint char(71)
)
RETURNS TABLE (
    snapshot_at timestamptz,
    dataset_version_authority_id uuid, dataset_version_reference varchar(256),
    dataset_version_payload bytea, dataset_version_payload_sha256 char(71), dataset_version_source_commit char(40),
    dataset_version_state text, dataset_version_state_effective_at timestamptz,
    dataset_manifest_authority_id uuid, dataset_manifest_reference varchar(256),
    dataset_manifest_payload bytea, dataset_manifest_payload_sha256 char(71), dataset_manifest_source_commit char(40),
    dataset_manifest_state text, dataset_manifest_state_effective_at timestamptz,
    dataset_pair_authority_id uuid, dataset_pair_reference varchar(256), dataset_pair_payload bytea,
    dataset_pair_payload_sha256 char(71), dataset_pair_source_commit char(40), dataset_pair_fingerprint char(71),
    dataset_pair_publication_scenario text, dataset_pair_state text, dataset_pair_state_effective_at timestamptz,
    config_authority_id uuid, config_reference varchar(256), config_payload bytea,
    config_payload_sha256 char(71), config_source_commit char(40), config_kind text,
    config_schema_version smallint, config_state text, config_state_effective_at timestamptz,
    readiness_authority_id uuid, readiness_reference varchar(256), readiness_payload bytea,
    readiness_payload_sha256 char(71), readiness_source_commit char(40), readiness_pair_fingerprint char(71),
    readiness_config_fingerprint char(71), readiness_evaluated_at timestamptz,
    readiness_valid_until timestamptz, readiness_result text,
    readiness_state text, readiness_state_effective_at timestamptz
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    returned_snapshot_count integer;
BEGIN
    IF current_setting('transaction_isolation') <> 'repeatable read'
       OR current_setting('transaction_read_only') <> 'on' THEN
        RAISE EXCEPTION USING ERRCODE = '25006', MESSAGE = 'repeatable read-only prerequisite snapshot required';
    END IF;
    IF requested_pair_fingerprint !~ '^sha256:[0-9a-f]{64}$'
       OR requested_config_fingerprint !~ '^sha256:[0-9a-f]{64}$'
       OR requested_readiness_fingerprint !~ '^sha256:[0-9a-f]{64}$' THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'prerequisite snapshot binding invalid';
    END IF;
    RETURN QUERY
    SELECT
        transaction_timestamp(),
        version_row.authority_id, version_identity.domain_key, version_row.payload_bytes,
        version_row.payload_sha256, version_row.source_commit, version_current.state,
        version_current.state_effective_at,
        manifest_row.authority_id, manifest_identity.domain_key, manifest_row.payload_bytes,
        manifest_row.payload_sha256, manifest_row.source_commit, manifest_current.state,
        manifest_current.state_effective_at,
        pair_row.authority_id, pair_identity.domain_key, pair_row.payload_bytes,
        pair_row.payload_sha256, pair_row.source_commit, pair_row.pair_fingerprint,
        pair_row.publication_scenario, pair_current.state, pair_current.state_effective_at,
        config_row.authority_id, config_identity.domain_key, config_row.payload_bytes,
        config_row.payload_sha256, config_row.source_commit, config_row.config_kind,
        config_row.config_schema_version, config_current.state, config_current.state_effective_at,
        readiness_row.authority_id, readiness_identity.domain_key, readiness_row.payload_bytes,
        readiness_row.payload_sha256, readiness_row.source_commit, readiness_row.dataset_pair_fingerprint,
        readiness_row.config_fingerprint, readiness_row.evaluated_at, readiness_row.valid_until,
        readiness_row.readiness_result, readiness_current.state, readiness_current.state_effective_at
    FROM dohalm_training_v1.dataset_version_authority AS version_row
    JOIN dohalm_training_v1.training_authority_identity AS version_identity
      ON version_identity.authority_id = version_row.authority_id AND version_identity.subject_family = 'dataset_version'
    JOIN dohalm_training_v1.training_authority_current AS version_current
      ON version_current.authority_id = version_row.authority_id
    JOIN dohalm_training_v1.dataset_manifest_authority AS manifest_row
      ON manifest_row.authority_id = requested_dataset_manifest_authority_id
    JOIN dohalm_training_v1.training_authority_identity AS manifest_identity
      ON manifest_identity.authority_id = manifest_row.authority_id AND manifest_identity.subject_family = 'dataset_manifest'
    JOIN dohalm_training_v1.training_authority_current AS manifest_current
      ON manifest_current.authority_id = manifest_row.authority_id
    JOIN dohalm_training_v1.dataset_pair_authority AS pair_row
      ON pair_row.dataset_version_authority_id = version_row.authority_id
     AND pair_row.dataset_manifest_authority_id = manifest_row.authority_id
     AND pair_row.pair_fingerprint = requested_pair_fingerprint
    JOIN dohalm_training_v1.training_authority_identity AS pair_identity
      ON pair_identity.authority_id = pair_row.authority_id AND pair_identity.subject_family = 'dataset_pair'
    JOIN dohalm_training_v1.training_authority_current AS pair_current
      ON pair_current.authority_id = pair_row.authority_id
    JOIN dohalm_training_v1.training_config_authority AS config_row
      ON config_row.authority_id = requested_config_authority_id
     AND config_row.payload_sha256 = requested_config_fingerprint
    JOIN dohalm_training_v1.training_authority_identity AS config_identity
      ON config_identity.authority_id = config_row.authority_id AND config_identity.subject_family = 'config'
    JOIN dohalm_training_v1.training_authority_current AS config_current
      ON config_current.authority_id = config_row.authority_id
    JOIN dohalm_training_v1.training_readiness_authority AS readiness_row
      ON readiness_row.authority_id = requested_readiness_authority_id
     AND readiness_row.payload_sha256 = requested_readiness_fingerprint
     AND readiness_row.dataset_pair_fingerprint = pair_row.pair_fingerprint
     AND readiness_row.config_fingerprint = config_row.payload_sha256
    JOIN dohalm_training_v1.training_authority_identity AS readiness_identity
      ON readiness_identity.authority_id = readiness_row.authority_id AND readiness_identity.subject_family = 'readiness'
    JOIN dohalm_training_v1.training_authority_current AS readiness_current
      ON readiness_current.authority_id = readiness_row.authority_id
    WHERE version_row.authority_id = requested_dataset_version_authority_id
    ORDER BY pair_row.authority_id;
    GET DIAGNOSTICS returned_snapshot_count = ROW_COUNT;
    IF returned_snapshot_count > 1 THEN
        RAISE EXCEPTION USING ERRCODE = '21000', MESSAGE = 'prerequisite snapshot relationship conflict';
    END IF;
END
$$;

CREATE FUNCTION dohalm_training_v1.read_c2_training_decision_snapshot(
    requested_decision_authority_id uuid,
    requested_request_fingerprint char(71),
    requested_decision_policy_reference varchar(256)
)
RETURNS TABLE (
    snapshot_at timestamptz,
    decision_authority_id uuid, decision_reference varchar(256), decision_payload bytea,
    decision_payload_sha256 char(71), decision_source_commit char(40), decision_state text,
    decision_state_effective_at timestamptz, decision_valid_until timestamptz,
    decision_value text, authorization_id varchar(256), request_fingerprint char(71),
    evidence_reference varchar(256), decision_policy_reference varchar(256), issued_at timestamptz,
    issuer_authority_id uuid, issuer_id varchar(256), issuer_payload bytea,
    issuer_payload_sha256 char(71), issuer_adapter_kind text, issuer_active_from timestamptz,
    issuer_active_until timestamptz, issuer_state text, issuer_state_effective_at timestamptz,
    approver_authority_id uuid, approver_reference varchar(256), approver_payload bytea,
    approver_payload_sha256 char(71), approver_active_from timestamptz,
    approver_active_until timestamptz, approver_state text, approver_state_effective_at timestamptz
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    IF current_setting('transaction_isolation') <> 'repeatable read'
       OR current_setting('transaction_read_only') <> 'on' THEN
        RAISE EXCEPTION USING ERRCODE = '25006', MESSAGE = 'repeatable read-only decision snapshot required';
    END IF;
    IF requested_request_fingerprint !~ '^sha256:[0-9a-f]{64}$'
       OR requested_decision_policy_reference !~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$' THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'decision snapshot binding invalid';
    END IF;
    RETURN QUERY
    SELECT
        transaction_timestamp(),
        decision_row.authority_id, decision_identity.domain_key, decision_row.payload_bytes,
        decision_row.payload_sha256, decision_row.source_commit, decision_current.state,
        decision_current.state_effective_at, decision_row.valid_until, decision_row.decision,
        decision_row.authorization_id, decision_row.request_fingerprint,
        decision_row.evidence_reference, requested_decision_policy_reference, decision_row.issued_at,
        issuer_row.authority_id, issuer_row.issuer_id, issuer_row.payload_bytes,
        issuer_row.payload_sha256, issuer_row.adapter_kind, issuer_row.active_from,
        issuer_row.active_until, issuer_current.state, issuer_current.state_effective_at,
        approver_row.authority_id, approver_row.approver_reference, approver_row.payload_bytes,
        approver_row.payload_sha256, approver_row.active_from, approver_row.active_until,
        approver_current.state, approver_current.state_effective_at
    FROM dohalm_training_v1.training_execution_decision_authority AS decision_row
    JOIN dohalm_training_v1.training_authority_identity AS decision_identity
      ON decision_identity.authority_id = decision_row.authority_id AND decision_identity.subject_family = 'decision'
    JOIN dohalm_training_v1.training_authority_current AS decision_current
      ON decision_current.authority_id = decision_row.authority_id
    JOIN dohalm_training_v1.training_issuer_registry AS issuer_row
      ON issuer_row.authority_id = decision_row.issuer_authority_id
     AND issuer_row.issuer_id = decision_row.issuer_id
    JOIN dohalm_training_v1.training_authority_current AS issuer_current
      ON issuer_current.authority_id = issuer_row.authority_id
    JOIN dohalm_training_v1.training_approver_registry AS approver_row
      ON approver_row.authority_id = decision_row.approver_authority_id
     AND approver_row.approver_reference = decision_row.approver_reference
    JOIN dohalm_training_v1.training_authority_current AS approver_current
      ON approver_current.authority_id = approver_row.authority_id
    WHERE decision_row.authority_id = requested_decision_authority_id
      AND decision_row.request_fingerprint = requested_request_fingerprint;
END
$$;

CREATE FUNCTION dohalm_training_v1.read_c2_training_execution_journal(requested_run_id varchar(256))
RETURNS SETOF dohalm_training_v1.training_execution_journal
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION USING ERRCODE = '25006', MESSAGE = 'read committed journal read required';
    END IF;
    RETURN QUERY SELECT journal.*
    FROM dohalm_training_v1.training_execution_journal AS journal
    WHERE journal.run_id = requested_run_id;
END
$$;

CREATE FUNCTION dohalm_training_v1.claim_c2_training_execution_journal(
    requested_run_id varchar(256), requested_request_fingerprint char(71),
    requested_intent_fingerprint char(71), requested_orchestration_correlation_id varchar(256),
    requested_dataset_version_id varchar(256), requested_dataset_manifest_id varchar(256),
    requested_dataset_pair_fingerprint char(71), requested_config_fingerprint char(71),
    requested_readiness_fingerprint char(71), requested_source_commit char(40),
    requested_prerequisite_policy_reference varchar(256), requested_process_boundary_id varchar(256)
)
RETURNS TABLE (
    claim_status text,
    journal_run_id varchar(256), journal_request_fingerprint char(71), journal_intent_fingerprint char(71),
    journal_host_schema_version smallint, journal_host_lifecycle_version smallint,
    journal_orchestration_correlation_id varchar(256), journal_dataset_version_id varchar(256),
    journal_dataset_manifest_id varchar(256), journal_dataset_pair_fingerprint char(71),
    journal_config_fingerprint char(71), journal_readiness_fingerprint char(71), journal_source_commit char(40),
    journal_prerequisite_policy_reference varchar(256), journal_authorization_id varchar(256),
    journal_issuer_id varchar(256), journal_approver_reference varchar(256), journal_evidence_reference varchar(256),
    journal_authorization_fingerprint char(71), journal_decision_evidence_fingerprint char(71),
    journal_decision_policy_reference varchar(256), journal_phase text, journal_version bigint,
    journal_backend_entered boolean, journal_reconciliation_required boolean,
    journal_reconciliation_reason_code varchar(128), journal_process_boundary_id varchar(256),
    journal_created_at timestamptz, journal_updated_at timestamptz, journal_reservation_group_id uuid
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    resolved_claim_status text;
    resolved_claimed_run_id varchar(256);
BEGIN
    SELECT claimed_result.claim_status, claimed_result.claimed_run_id
    INTO STRICT resolved_claim_status, resolved_claimed_run_id
    FROM dohalm_training_v1.claim_training_execution_journal(
        requested_run_id, requested_request_fingerprint, requested_intent_fingerprint,
        requested_orchestration_correlation_id, requested_dataset_version_id,
        requested_dataset_manifest_id, requested_dataset_pair_fingerprint,
        requested_config_fingerprint, requested_readiness_fingerprint,
        requested_source_commit, requested_prerequisite_policy_reference,
        requested_process_boundary_id
    ) AS claimed_result;
    RETURN QUERY
    SELECT resolved_claim_status,
           journal.run_id, journal.request_fingerprint, journal.intent_fingerprint,
           journal.host_schema_version, journal.host_lifecycle_version,
           journal.orchestration_correlation_id, journal.dataset_version_id,
           journal.dataset_manifest_id, journal.dataset_pair_fingerprint,
           journal.config_fingerprint, journal.readiness_fingerprint, journal.source_commit,
           journal.prerequisite_resolution_policy_reference, journal.authorization_id,
           journal.issuer_id, journal.approver_reference, journal.evidence_reference,
           journal.authorization_fingerprint, journal.decision_evidence_fingerprint,
           journal.decision_policy_reference, journal.phase, journal.journal_version,
           journal.backend_entered, journal.reconciliation_required,
           journal.reconciliation_reason_code, journal.process_boundary_id,
           journal.created_at, journal.updated_at, journal.reservation_group_id
    FROM dohalm_training_v1.training_execution_journal AS journal
    WHERE journal.run_id = resolved_claimed_run_id;
END
$$;

CREATE FUNCTION dohalm_training_v1.transition_c2_training_execution_journal(
    requested_run_id varchar(256), requested_request_fingerprint char(71),
    requested_expected_phase text, requested_expected_journal_version bigint, requested_next_phase text,
    requested_process_boundary_id varchar(256), requested_reason_code varchar(128) DEFAULT NULL,
    requested_authorization_id varchar(256) DEFAULT NULL, requested_issuer_id varchar(256) DEFAULT NULL,
    requested_approver_reference varchar(256) DEFAULT NULL, requested_evidence_reference varchar(256) DEFAULT NULL,
    requested_authorization_fingerprint char(71) DEFAULT NULL,
    requested_decision_evidence_fingerprint char(71) DEFAULT NULL,
    requested_decision_policy_reference varchar(256) DEFAULT NULL
)
RETURNS SETOF dohalm_training_v1.training_execution_journal
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    PERFORM * FROM dohalm_training_v1.transition_training_execution_journal(
        requested_run_id, requested_request_fingerprint, requested_expected_phase,
        requested_expected_journal_version, requested_next_phase, requested_process_boundary_id,
        requested_reason_code, requested_authorization_id, requested_issuer_id,
        requested_approver_reference, requested_evidence_reference,
        requested_authorization_fingerprint, requested_decision_evidence_fingerprint,
        requested_decision_policy_reference
    );
    RETURN QUERY SELECT journal.*
    FROM dohalm_training_v1.training_execution_journal AS journal
    WHERE journal.run_id = requested_run_id;
END
$$;

ALTER FUNCTION dohalm_training_v1.read_c2_training_prerequisite_snapshot(uuid, uuid, uuid, uuid, char, char, char) OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.read_c2_training_decision_snapshot(uuid, char, varchar) OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.read_c2_training_execution_journal(varchar) OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.claim_c2_training_execution_journal(varchar, char, char, varchar, varchar, varchar, char, char, char, char, varchar, varchar) OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.transition_c2_training_execution_journal(varchar, char, text, bigint, text, varchar, varchar, varchar, varchar, varchar, varchar, char, char, varchar) OWNER TO dohalm_training_owner;

REVOKE ALL ON FUNCTION dohalm_training_v1.read_c2_training_prerequisite_snapshot(uuid, uuid, uuid, uuid, char, char, char) FROM PUBLIC;
REVOKE ALL ON FUNCTION dohalm_training_v1.read_c2_training_decision_snapshot(uuid, char, varchar) FROM PUBLIC;
REVOKE ALL ON FUNCTION dohalm_training_v1.read_c2_training_execution_journal(varchar) FROM PUBLIC;
REVOKE ALL ON FUNCTION dohalm_training_v1.claim_c2_training_execution_journal(varchar, char, char, varchar, varchar, varchar, char, char, char, char, varchar, varchar) FROM PUBLIC;
REVOKE ALL ON FUNCTION dohalm_training_v1.transition_c2_training_execution_journal(varchar, char, text, bigint, text, varchar, varchar, varchar, varchar, varchar, varchar, char, char, varchar) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION dohalm_training_v1.read_c2_training_prerequisite_snapshot(uuid, uuid, uuid, uuid, char, char, char) TO dohalm_training_resolver;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.read_c2_training_decision_snapshot(uuid, char, varchar) TO dohalm_training_resolver;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.read_c2_training_execution_journal(varchar) TO dohalm_training_journal;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.claim_c2_training_execution_journal(varchar, char, char, varchar, varchar, varchar, char, char, char, char, varchar, varchar) TO dohalm_training_journal;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.transition_c2_training_execution_journal(varchar, char, text, bigint, text, varchar, varchar, varchar, varchar, varchar, varchar, char, char, varchar) TO dohalm_training_journal;
