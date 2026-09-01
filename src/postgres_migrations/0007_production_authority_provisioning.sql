-- Narrow, replay-safe production authority creation surfaces.
-- Runtime roles retain zero direct table DML; only the producer may execute these
-- family-specific SECURITY DEFINER functions.

CREATE FUNCTION dohalm_training_v1.provision_training_issuer(
    requested_authority_id uuid, requested_domain_key varchar(256),
    requested_payload_bytes bytea, requested_payload_sha256 char(71),
    requested_source_commit char(40), requested_valid_from timestamptz,
    requested_valid_until timestamptz, requested_issuer_id varchar(256),
    requested_event_id uuid, requested_correlation_reference varchar(256),
    requested_evidence_reference varchar(256)
)
RETURNS TABLE (
    authority_id uuid, domain_key varchar(256), payload_sha256 char(71),
    authority_state text, projection_version bigint
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp
AS $$
DECLARE existing_id uuid;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed'
       OR current_setting('transaction_read_only') <> 'off' THEN
        RAISE EXCEPTION USING ERRCODE = '25006', MESSAGE = 'read committed producer transaction required';
    END IF;
    IF requested_payload_sha256 <> 'sha256:' || encode(sha256(requested_payload_bytes), 'hex') THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'issuer payload fingerprint mismatch';
    END IF;
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('issuer' || chr(31) || requested_domain_key, 0));
    SELECT identity.authority_id INTO existing_id
    FROM dohalm_training_v1.training_authority_identity identity
    WHERE identity.subject_family = 'issuer' AND identity.domain_key = requested_domain_key;
    IF existing_id IS NULL THEN
        INSERT INTO dohalm_training_v1.training_authority_identity(authority_id, subject_family, domain_key)
        VALUES (requested_authority_id, 'issuer', requested_domain_key);
        INSERT INTO dohalm_training_v1.training_issuer_registry(
            authority_id, payload_bytes, payload_sha256, valid_from, valid_until,
            source_commit, issuer_id, adapter_kind, active_from, active_until
        ) VALUES (
            requested_authority_id, requested_payload_bytes, requested_payload_sha256,
            transaction_timestamp(), requested_valid_until, requested_source_commit,
            requested_issuer_id, 'same_process_training_execution_issuer',
            transaction_timestamp(), requested_valid_until
        );
        PERFORM dohalm_training_v1.write_training_authority_event(
            requested_event_id, requested_authority_id, 'issuer', 0, 'published', NULL,
            transaction_timestamp(), requested_correlation_reference, requested_evidence_reference
        );
        existing_id := requested_authority_id;
    ELSIF NOT EXISTS (
        SELECT 1 FROM dohalm_training_v1.training_issuer_registry row
        WHERE row.authority_id = existing_id AND row.payload_bytes = requested_payload_bytes
          AND row.payload_sha256 = requested_payload_sha256 AND row.source_commit = requested_source_commit
          AND row.valid_until IS NOT DISTINCT FROM requested_valid_until
          AND row.issuer_id = requested_issuer_id
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'issuer provisioning conflict';
    END IF;
    RETURN QUERY SELECT identity.authority_id, identity.domain_key, row.payload_sha256,
        state.state, state.projection_version
    FROM dohalm_training_v1.training_authority_identity identity
    JOIN dohalm_training_v1.training_issuer_registry row ON row.authority_id = identity.authority_id
    JOIN dohalm_training_v1.training_authority_current state ON state.authority_id = identity.authority_id
    WHERE identity.authority_id = existing_id AND state.state = 'current';
END $$;

CREATE FUNCTION dohalm_training_v1.provision_training_approver(
    requested_authority_id uuid, requested_domain_key varchar(256),
    requested_payload_bytes bytea, requested_payload_sha256 char(71),
    requested_source_commit char(40), requested_valid_from timestamptz,
    requested_valid_until timestamptz, requested_approver_reference varchar(256),
    requested_event_id uuid, requested_correlation_reference varchar(256),
    requested_evidence_reference varchar(256)
)
RETURNS TABLE (
    authority_id uuid, domain_key varchar(256), payload_sha256 char(71),
    authority_state text, projection_version bigint
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp
AS $$
DECLARE existing_id uuid;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed'
       OR current_setting('transaction_read_only') <> 'off' THEN
        RAISE EXCEPTION USING ERRCODE = '25006', MESSAGE = 'read committed producer transaction required';
    END IF;
    IF requested_payload_sha256 <> 'sha256:' || encode(sha256(requested_payload_bytes), 'hex') THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'approver payload fingerprint mismatch';
    END IF;
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('approver' || chr(31) || requested_domain_key, 0));
    SELECT identity.authority_id INTO existing_id
    FROM dohalm_training_v1.training_authority_identity identity
    WHERE identity.subject_family = 'approver' AND identity.domain_key = requested_domain_key;
    IF existing_id IS NULL THEN
        INSERT INTO dohalm_training_v1.training_authority_identity(authority_id, subject_family, domain_key)
        VALUES (requested_authority_id, 'approver', requested_domain_key);
        INSERT INTO dohalm_training_v1.training_approver_registry(
            authority_id, payload_bytes, payload_sha256, valid_from, valid_until,
            source_commit, approver_reference, active_from, active_until
        ) VALUES (
            requested_authority_id, requested_payload_bytes, requested_payload_sha256,
            transaction_timestamp(), requested_valid_until, requested_source_commit,
            requested_approver_reference, transaction_timestamp(), requested_valid_until
        );
        PERFORM dohalm_training_v1.write_training_authority_event(
            requested_event_id, requested_authority_id, 'approver', 0, 'published', NULL,
            transaction_timestamp(), requested_correlation_reference, requested_evidence_reference
        );
        existing_id := requested_authority_id;
    ELSIF NOT EXISTS (
        SELECT 1 FROM dohalm_training_v1.training_approver_registry row
        WHERE row.authority_id = existing_id AND row.payload_bytes = requested_payload_bytes
          AND row.payload_sha256 = requested_payload_sha256 AND row.source_commit = requested_source_commit
          AND row.valid_until IS NOT DISTINCT FROM requested_valid_until
          AND row.approver_reference = requested_approver_reference
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'approver provisioning conflict';
    END IF;
    RETURN QUERY SELECT identity.authority_id, identity.domain_key, row.payload_sha256,
        state.state, state.projection_version
    FROM dohalm_training_v1.training_authority_identity identity
    JOIN dohalm_training_v1.training_approver_registry row ON row.authority_id = identity.authority_id
    JOIN dohalm_training_v1.training_authority_current state ON state.authority_id = identity.authority_id
    WHERE identity.authority_id = existing_id AND state.state = 'current';
END $$;

CREATE FUNCTION dohalm_training_v1.provision_training_config(
    requested_authority_id uuid, requested_domain_key varchar(256),
    requested_payload_bytes bytea, requested_payload_sha256 char(71),
    requested_source_commit char(40), requested_valid_from timestamptz,
    requested_valid_until timestamptz, requested_event_id uuid,
    requested_correlation_reference varchar(256), requested_evidence_reference varchar(256)
)
RETURNS TABLE (
    authority_id uuid, domain_key varchar(256), payload_sha256 char(71),
    authority_state text, projection_version bigint
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp
AS $$
DECLARE existing_id uuid;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed'
       OR current_setting('transaction_read_only') <> 'off' THEN
        RAISE EXCEPTION USING ERRCODE = '25006', MESSAGE = 'read committed producer transaction required';
    END IF;
    IF requested_payload_sha256 <> 'sha256:' || encode(sha256(requested_payload_bytes), 'hex') THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'config payload fingerprint mismatch';
    END IF;
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('config' || chr(31) || requested_domain_key, 0));
    SELECT identity.authority_id INTO existing_id
    FROM dohalm_training_v1.training_authority_identity identity
    WHERE identity.subject_family = 'config' AND identity.domain_key = requested_domain_key;
    IF existing_id IS NULL THEN
        INSERT INTO dohalm_training_v1.training_authority_identity(authority_id, subject_family, domain_key)
        VALUES (requested_authority_id, 'config', requested_domain_key);
        INSERT INTO dohalm_training_v1.training_config_authority(
            authority_id, payload_bytes, payload_sha256, valid_from, valid_until,
            source_commit, config_kind, config_schema_version
        ) VALUES (
            requested_authority_id, requested_payload_bytes, requested_payload_sha256,
            transaction_timestamp(), requested_valid_until, requested_source_commit,
            'full_pretraining', 1
        );
        PERFORM dohalm_training_v1.write_training_authority_event(
            requested_event_id, requested_authority_id, 'config', 0, 'published', NULL,
            transaction_timestamp(), requested_correlation_reference, requested_evidence_reference
        );
        existing_id := requested_authority_id;
    ELSIF NOT EXISTS (
        SELECT 1 FROM dohalm_training_v1.training_config_authority row
        WHERE row.authority_id = existing_id AND row.payload_bytes = requested_payload_bytes
          AND row.payload_sha256 = requested_payload_sha256 AND row.source_commit = requested_source_commit
          AND row.valid_until IS NOT DISTINCT FROM requested_valid_until
          AND row.config_kind = 'full_pretraining' AND row.config_schema_version = 1
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'config provisioning conflict';
    END IF;
    RETURN QUERY SELECT identity.authority_id, identity.domain_key, row.payload_sha256,
        state.state, state.projection_version
    FROM dohalm_training_v1.training_authority_identity identity
    JOIN dohalm_training_v1.training_config_authority row ON row.authority_id = identity.authority_id
    JOIN dohalm_training_v1.training_authority_current state ON state.authority_id = identity.authority_id
    WHERE identity.authority_id = existing_id AND state.state = 'current';
END $$;

CREATE FUNCTION dohalm_training_v1.provision_training_readiness(
    requested_authority_id uuid, requested_domain_key varchar(256),
    requested_payload_bytes bytea, requested_payload_sha256 char(71),
    requested_source_commit char(40), requested_dataset_pair_fingerprint char(71),
    requested_config_fingerprint char(71), requested_evaluated_at timestamptz,
    requested_valid_from timestamptz, requested_valid_until timestamptz,
    requested_event_id uuid, requested_correlation_reference varchar(256),
    requested_evidence_reference varchar(256)
)
RETURNS TABLE (
    authority_id uuid, domain_key varchar(256), payload_sha256 char(71),
    authority_state text, projection_version bigint
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp
AS $$
DECLARE existing_id uuid;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed'
       OR current_setting('transaction_read_only') <> 'off' THEN
        RAISE EXCEPTION USING ERRCODE = '25006', MESSAGE = 'read committed producer transaction required';
    END IF;
    IF requested_payload_sha256 <> 'sha256:' || encode(sha256(requested_payload_bytes), 'hex')
       OR requested_valid_until IS NULL
       OR NOT (requested_valid_from <= requested_evaluated_at AND requested_evaluated_at < requested_valid_until) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'readiness payload or validity mismatch';
    END IF;
    PERFORM 1 FROM dohalm_training_v1.dataset_pair_authority pair_row
    JOIN dohalm_training_v1.training_authority_current pair_state ON pair_state.authority_id = pair_row.authority_id
    WHERE pair_row.pair_fingerprint = requested_dataset_pair_fingerprint AND pair_state.state = 'current';
    IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE = '23503', MESSAGE = 'Dataset pair is not current'; END IF;
    PERFORM 1 FROM dohalm_training_v1.training_config_authority config_row
    JOIN dohalm_training_v1.training_authority_current config_state ON config_state.authority_id = config_row.authority_id
    WHERE config_row.payload_sha256 = requested_config_fingerprint AND config_state.state = 'current';
    IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE = '23503', MESSAGE = 'config is not current'; END IF;
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('readiness' || chr(31) || requested_domain_key, 0));
    SELECT identity.authority_id INTO existing_id FROM dohalm_training_v1.training_authority_identity identity
    WHERE identity.subject_family = 'readiness' AND identity.domain_key = requested_domain_key;
    IF existing_id IS NULL THEN
        INSERT INTO dohalm_training_v1.training_authority_identity(authority_id, subject_family, domain_key)
        VALUES (requested_authority_id, 'readiness', requested_domain_key);
        INSERT INTO dohalm_training_v1.training_readiness_authority(
            authority_id, payload_bytes, payload_sha256, valid_from, valid_until,
            source_commit, dataset_pair_fingerprint, config_fingerprint, evaluated_at, readiness_result
        ) VALUES (
            requested_authority_id, requested_payload_bytes, requested_payload_sha256,
            transaction_timestamp(), requested_valid_until, requested_source_commit,
            requested_dataset_pair_fingerprint, requested_config_fingerprint,
            requested_evaluated_at, 'READY'
        );
        PERFORM dohalm_training_v1.write_training_authority_event(
            requested_event_id, requested_authority_id, 'readiness', 0, 'published', NULL,
            transaction_timestamp(), requested_correlation_reference, requested_evidence_reference
        );
        existing_id := requested_authority_id;
    ELSIF NOT EXISTS (
        SELECT 1 FROM dohalm_training_v1.training_readiness_authority row
        WHERE row.authority_id = existing_id AND row.payload_bytes = requested_payload_bytes
          AND row.payload_sha256 = requested_payload_sha256 AND row.source_commit = requested_source_commit
          AND row.dataset_pair_fingerprint = requested_dataset_pair_fingerprint
          AND row.config_fingerprint = requested_config_fingerprint
          AND row.evaluated_at = requested_evaluated_at
          AND row.valid_until = requested_valid_until AND row.readiness_result = 'READY'
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'readiness provisioning conflict';
    END IF;
    RETURN QUERY SELECT identity.authority_id, identity.domain_key, row.payload_sha256,
        state.state, state.projection_version
    FROM dohalm_training_v1.training_authority_identity identity
    JOIN dohalm_training_v1.training_readiness_authority row ON row.authority_id = identity.authority_id
    JOIN dohalm_training_v1.training_authority_current state ON state.authority_id = identity.authority_id
    WHERE identity.authority_id = existing_id AND state.state = 'current';
END $$;

CREATE FUNCTION dohalm_training_v1.register_training_dataset_publication(
    requested_version_authority_id uuid, requested_manifest_authority_id uuid,
    requested_pair_authority_id uuid, requested_version_domain_key varchar(256),
    requested_manifest_domain_key varchar(256), requested_pair_domain_key varchar(256),
    requested_version_payload bytea, requested_manifest_payload bytea,
    requested_pair_payload bytea, requested_dataset_version_id varchar(256),
    requested_dataset_manifest_id varchar(256), requested_pair_fingerprint char(71),
    requested_source_commit char(40), requested_publication_scenario text,
    requested_eligibility_reference varchar(256), requested_source_lineage_reference varchar(256),
    requested_valid_from timestamptz, requested_valid_until timestamptz,
    requested_version_event_id uuid, requested_manifest_event_id uuid,
    requested_pair_event_id uuid, requested_correlation_reference varchar(256),
    requested_internal_training_allowed boolean, requested_commercial_allowed boolean,
    requested_redistribution_allowed boolean
)
RETURNS TABLE (
    version_authority_id uuid, version_domain_key varchar(256), version_payload_sha256 char(71),
    version_authority_state text, version_projection_version bigint,
    manifest_authority_id uuid, manifest_domain_key varchar(256), manifest_payload_sha256 char(71),
    manifest_authority_state text, manifest_projection_version bigint,
    pair_authority_id uuid, pair_domain_key varchar(256), pair_payload_sha256 char(71),
    pair_authority_state text, pair_projection_version bigint,
    dataset_version_id varchar(256), dataset_manifest_id varchar(256), pair_fingerprint char(71)
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    existing_version_id uuid; existing_manifest_id uuid; existing_pair_id uuid;
    version_sha char(71) := 'sha256:' || encode(sha256(requested_version_payload), 'hex');
    manifest_sha char(71) := 'sha256:' || encode(sha256(requested_manifest_payload), 'hex');
    pair_sha char(71) := 'sha256:' || encode(sha256(requested_pair_payload), 'hex');
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed'
       OR current_setting('transaction_read_only') <> 'off' THEN
        RAISE EXCEPTION USING ERRCODE = '25006', MESSAGE = 'read committed producer transaction required';
    END IF;
    IF requested_internal_training_allowed IS NOT TRUE
       OR requested_commercial_allowed IS NOT FALSE
       OR requested_redistribution_allowed IS NOT FALSE
       OR requested_eligibility_reference = '' OR requested_source_lineage_reference = ''
       OR requested_version_authority_id IN (requested_manifest_authority_id, requested_pair_authority_id)
       OR requested_manifest_authority_id = requested_pair_authority_id THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'Dataset eligibility or identity invalid';
    END IF;
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
        'dataset-publication' || chr(31) || requested_version_domain_key || chr(31) || requested_manifest_domain_key || chr(31) || requested_pair_domain_key, 0));
    SELECT identity.authority_id INTO existing_version_id FROM dohalm_training_v1.training_authority_identity identity
      WHERE identity.subject_family = 'dataset_version' AND identity.domain_key = requested_version_domain_key;
    SELECT identity.authority_id INTO existing_manifest_id FROM dohalm_training_v1.training_authority_identity identity
      WHERE identity.subject_family = 'dataset_manifest' AND identity.domain_key = requested_manifest_domain_key;
    SELECT identity.authority_id INTO existing_pair_id FROM dohalm_training_v1.training_authority_identity identity
      WHERE identity.subject_family = 'dataset_pair' AND identity.domain_key = requested_pair_domain_key;
    IF existing_version_id IS NULL AND existing_manifest_id IS NULL AND existing_pair_id IS NULL THEN
        INSERT INTO dohalm_training_v1.training_authority_identity(authority_id, subject_family, domain_key) VALUES
          (requested_version_authority_id, 'dataset_version', requested_version_domain_key),
          (requested_manifest_authority_id, 'dataset_manifest', requested_manifest_domain_key),
          (requested_pair_authority_id, 'dataset_pair', requested_pair_domain_key);
        INSERT INTO dohalm_training_v1.dataset_version_authority(
          authority_id, payload_bytes, payload_sha256, valid_from, valid_until, source_commit, common_object_id
        ) VALUES (requested_version_authority_id, requested_version_payload, version_sha, transaction_timestamp(),
          requested_valid_until, requested_source_commit, requested_dataset_version_id);
        INSERT INTO dohalm_training_v1.dataset_manifest_authority(
          authority_id, payload_bytes, payload_sha256, valid_from, valid_until, source_commit, common_object_id
        ) VALUES (requested_manifest_authority_id, requested_manifest_payload, manifest_sha, transaction_timestamp(),
          requested_valid_until, requested_source_commit, requested_dataset_manifest_id);
        INSERT INTO dohalm_training_v1.dataset_pair_authority(
          authority_id, payload_bytes, payload_sha256, valid_from, valid_until, source_commit,
          dataset_version_authority_id, dataset_manifest_authority_id, pair_fingerprint, publication_scenario
        ) VALUES (requested_pair_authority_id, requested_pair_payload, pair_sha, transaction_timestamp(),
          requested_valid_until, requested_source_commit, requested_version_authority_id,
          requested_manifest_authority_id, requested_pair_fingerprint, requested_publication_scenario);
        PERFORM dohalm_training_v1.write_training_authority_event(requested_version_event_id,
          requested_version_authority_id, 'dataset_version', 0, 'published', NULL, transaction_timestamp(),
          requested_correlation_reference, requested_eligibility_reference);
        PERFORM dohalm_training_v1.write_training_authority_event(requested_manifest_event_id,
          requested_manifest_authority_id, 'dataset_manifest', 0, 'published', NULL, transaction_timestamp(),
          requested_correlation_reference, requested_source_lineage_reference);
        PERFORM dohalm_training_v1.write_training_authority_event(requested_pair_event_id,
          requested_pair_authority_id, 'dataset_pair', 0, 'published', NULL, transaction_timestamp(),
          requested_correlation_reference, requested_eligibility_reference);
        existing_version_id := requested_version_authority_id;
        existing_manifest_id := requested_manifest_authority_id;
        existing_pair_id := requested_pair_authority_id;
    ELSIF existing_version_id IS NULL OR existing_manifest_id IS NULL OR existing_pair_id IS NULL
       OR NOT EXISTS (
          SELECT 1 FROM dohalm_training_v1.dataset_version_authority row
          WHERE row.authority_id = existing_version_id AND row.payload_bytes = requested_version_payload
            AND row.payload_sha256 = version_sha AND row.source_commit = requested_source_commit
            AND row.common_object_id = requested_dataset_version_id
            AND row.valid_until IS NOT DISTINCT FROM requested_valid_until)
       OR NOT EXISTS (
          SELECT 1 FROM dohalm_training_v1.dataset_manifest_authority row
          WHERE row.authority_id = existing_manifest_id AND row.payload_bytes = requested_manifest_payload
            AND row.payload_sha256 = manifest_sha AND row.source_commit = requested_source_commit
            AND row.common_object_id = requested_dataset_manifest_id
            AND row.valid_until IS NOT DISTINCT FROM requested_valid_until)
       OR NOT EXISTS (
          SELECT 1 FROM dohalm_training_v1.dataset_pair_authority row
          WHERE row.authority_id = existing_pair_id AND row.payload_bytes = requested_pair_payload
            AND row.payload_sha256 = pair_sha AND row.source_commit = requested_source_commit
            AND row.dataset_version_authority_id = existing_version_id
            AND row.dataset_manifest_authority_id = existing_manifest_id
            AND row.pair_fingerprint = requested_pair_fingerprint
            AND row.publication_scenario = requested_publication_scenario
            AND row.valid_until IS NOT DISTINCT FROM requested_valid_until)
    THEN
        RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'Dataset publication registration conflict';
    END IF;
    RETURN QUERY SELECT
      vi.authority_id, vi.domain_key, v.payload_sha256, vs.state, vs.projection_version,
      mi.authority_id, mi.domain_key, m.payload_sha256, ms.state, ms.projection_version,
      pi.authority_id, pi.domain_key, p.payload_sha256, ps.state, ps.projection_version,
      v.common_object_id, m.common_object_id, p.pair_fingerprint
    FROM dohalm_training_v1.dataset_pair_authority p
    JOIN dohalm_training_v1.training_authority_identity pi ON pi.authority_id = p.authority_id
    JOIN dohalm_training_v1.training_authority_current ps ON ps.authority_id = p.authority_id
    JOIN dohalm_training_v1.dataset_version_authority v ON v.authority_id = p.dataset_version_authority_id
    JOIN dohalm_training_v1.training_authority_identity vi ON vi.authority_id = v.authority_id
    JOIN dohalm_training_v1.training_authority_current vs ON vs.authority_id = v.authority_id
    JOIN dohalm_training_v1.dataset_manifest_authority m ON m.authority_id = p.dataset_manifest_authority_id
    JOIN dohalm_training_v1.training_authority_identity mi ON mi.authority_id = m.authority_id
    JOIN dohalm_training_v1.training_authority_current ms ON ms.authority_id = m.authority_id
    WHERE p.authority_id = existing_pair_id AND ps.state = 'current' AND vs.state = 'current' AND ms.state = 'current';
END $$;

CREATE FUNCTION dohalm_training_v1.create_training_execution_decision(
    requested_authority_id uuid, requested_domain_key varchar(256),
    requested_payload_bytes bytea, requested_payload_sha256 char(71),
    requested_source_commit char(40), requested_decision text,
    requested_authorization_id varchar(256), requested_issuer_authority_id uuid,
    requested_issuer_id varchar(256), requested_approver_authority_id uuid,
    requested_approver_reference varchar(256), requested_decision_evidence_reference varchar(256),
    requested_request_fingerprint char(71), requested_issued_at timestamptz,
    requested_valid_from timestamptz, requested_valid_until timestamptz,
    requested_event_id uuid, requested_correlation_reference varchar(256),
    requested_event_evidence_reference varchar(256)
)
RETURNS TABLE (
    authority_id uuid, domain_key varchar(256), payload_sha256 char(71),
    authority_state text, projection_version bigint
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp
AS $$
DECLARE existing_id uuid;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed'
       OR current_setting('transaction_read_only') <> 'off' THEN
        RAISE EXCEPTION USING ERRCODE = '25006', MESSAGE = 'read committed producer transaction required';
    END IF;
    IF requested_payload_sha256 <> 'sha256:' || encode(sha256(requested_payload_bytes), 'hex')
       OR requested_issuer_authority_id = requested_approver_authority_id
       OR requested_valid_until IS NULL
       OR NOT (requested_valid_from <= requested_issued_at AND requested_issued_at < requested_valid_until) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'decision payload, role, or validity invalid';
    END IF;
    PERFORM 1 FROM dohalm_training_v1.training_issuer_registry issuer
    JOIN dohalm_training_v1.training_authority_current state ON state.authority_id = issuer.authority_id
    WHERE issuer.authority_id = requested_issuer_authority_id AND issuer.issuer_id = requested_issuer_id
      AND state.state = 'current';
    IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE = '23503', MESSAGE = 'issuer is not current'; END IF;
    PERFORM 1 FROM dohalm_training_v1.training_approver_registry approver
    JOIN dohalm_training_v1.training_authority_current state ON state.authority_id = approver.authority_id
    WHERE approver.authority_id = requested_approver_authority_id
      AND approver.approver_reference = requested_approver_reference AND state.state = 'current';
    IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE = '23503', MESSAGE = 'approver is not current'; END IF;
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('decision' || chr(31) || requested_domain_key, 0));
    SELECT identity.authority_id INTO existing_id FROM dohalm_training_v1.training_authority_identity identity
    WHERE identity.subject_family = 'decision' AND identity.domain_key = requested_domain_key;
    IF existing_id IS NULL THEN
        INSERT INTO dohalm_training_v1.training_authority_identity(authority_id, subject_family, domain_key)
        VALUES (requested_authority_id, 'decision', requested_domain_key);
        INSERT INTO dohalm_training_v1.training_execution_decision_authority(
          authority_id, payload_bytes, payload_sha256, valid_from, valid_until, source_commit,
          decision, authorization_id, issuer_authority_id, issuer_id, approver_authority_id,
          approver_reference, evidence_reference, request_fingerprint, issued_at
        ) VALUES (
          requested_authority_id, requested_payload_bytes, requested_payload_sha256,
          transaction_timestamp(), requested_valid_until, requested_source_commit,
          requested_decision, requested_authorization_id, requested_issuer_authority_id,
          requested_issuer_id, requested_approver_authority_id, requested_approver_reference,
          requested_decision_evidence_reference, requested_request_fingerprint, transaction_timestamp()
        );
        PERFORM dohalm_training_v1.write_training_authority_event(
          requested_event_id, requested_authority_id, 'decision', 0, 'published', NULL,
          transaction_timestamp(), requested_correlation_reference, requested_event_evidence_reference);
        existing_id := requested_authority_id;
    ELSIF NOT EXISTS (
        SELECT 1 FROM dohalm_training_v1.training_execution_decision_authority row
        WHERE row.authority_id = existing_id AND row.payload_bytes = requested_payload_bytes
          AND row.payload_sha256 = requested_payload_sha256 AND row.source_commit = requested_source_commit
          AND row.decision = requested_decision AND row.authorization_id = requested_authorization_id
          AND row.issuer_authority_id = requested_issuer_authority_id AND row.issuer_id = requested_issuer_id
          AND row.approver_authority_id = requested_approver_authority_id
          AND row.approver_reference = requested_approver_reference
          AND row.evidence_reference = requested_decision_evidence_reference
          AND row.request_fingerprint = requested_request_fingerprint
          AND row.valid_until = requested_valid_until
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'decision provisioning conflict';
    END IF;
    RETURN QUERY SELECT identity.authority_id, identity.domain_key, row.payload_sha256,
      state.state, state.projection_version
    FROM dohalm_training_v1.training_authority_identity identity
    JOIN dohalm_training_v1.training_execution_decision_authority row ON row.authority_id = identity.authority_id
    JOIN dohalm_training_v1.training_authority_current state ON state.authority_id = identity.authority_id
    WHERE identity.authority_id = existing_id AND state.state = 'current';
END $$;

ALTER FUNCTION dohalm_training_v1.provision_training_issuer(uuid, varchar, bytea, char, char, timestamptz, timestamptz, varchar, uuid, varchar, varchar) OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.provision_training_approver(uuid, varchar, bytea, char, char, timestamptz, timestamptz, varchar, uuid, varchar, varchar) OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.provision_training_config(uuid, varchar, bytea, char, char, timestamptz, timestamptz, uuid, varchar, varchar) OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.provision_training_readiness(uuid, varchar, bytea, char, char, char, char, timestamptz, timestamptz, timestamptz, uuid, varchar, varchar) OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.register_training_dataset_publication(uuid, uuid, uuid, varchar, varchar, varchar, bytea, bytea, bytea, varchar, varchar, char, char, text, varchar, varchar, timestamptz, timestamptz, uuid, uuid, uuid, varchar, boolean, boolean, boolean) OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.create_training_execution_decision(uuid, varchar, bytea, char, char, text, varchar, uuid, varchar, uuid, varchar, varchar, char, timestamptz, timestamptz, timestamptz, uuid, varchar, varchar) OWNER TO dohalm_training_owner;

REVOKE ALL ON FUNCTION dohalm_training_v1.provision_training_issuer(uuid, varchar, bytea, char, char, timestamptz, timestamptz, varchar, uuid, varchar, varchar) FROM PUBLIC;
REVOKE ALL ON FUNCTION dohalm_training_v1.provision_training_approver(uuid, varchar, bytea, char, char, timestamptz, timestamptz, varchar, uuid, varchar, varchar) FROM PUBLIC;
REVOKE ALL ON FUNCTION dohalm_training_v1.provision_training_config(uuid, varchar, bytea, char, char, timestamptz, timestamptz, uuid, varchar, varchar) FROM PUBLIC;
REVOKE ALL ON FUNCTION dohalm_training_v1.provision_training_readiness(uuid, varchar, bytea, char, char, char, char, timestamptz, timestamptz, timestamptz, uuid, varchar, varchar) FROM PUBLIC;
REVOKE ALL ON FUNCTION dohalm_training_v1.register_training_dataset_publication(uuid, uuid, uuid, varchar, varchar, varchar, bytea, bytea, bytea, varchar, varchar, char, char, text, varchar, varchar, timestamptz, timestamptz, uuid, uuid, uuid, varchar, boolean, boolean, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION dohalm_training_v1.create_training_execution_decision(uuid, varchar, bytea, char, char, text, varchar, uuid, varchar, uuid, varchar, varchar, char, timestamptz, timestamptz, timestamptz, uuid, varchar, varchar) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION dohalm_training_v1.provision_training_issuer(uuid, varchar, bytea, char, char, timestamptz, timestamptz, varchar, uuid, varchar, varchar) TO dohalm_training_authority_producer;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.provision_training_approver(uuid, varchar, bytea, char, char, timestamptz, timestamptz, varchar, uuid, varchar, varchar) TO dohalm_training_authority_producer;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.provision_training_config(uuid, varchar, bytea, char, char, timestamptz, timestamptz, uuid, varchar, varchar) TO dohalm_training_authority_producer;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.provision_training_readiness(uuid, varchar, bytea, char, char, char, char, timestamptz, timestamptz, timestamptz, uuid, varchar, varchar) TO dohalm_training_authority_producer;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.register_training_dataset_publication(uuid, uuid, uuid, varchar, varchar, varchar, bytea, bytea, bytea, varchar, varchar, char, char, text, varchar, varchar, timestamptz, timestamptz, uuid, uuid, uuid, varchar, boolean, boolean, boolean) TO dohalm_training_authority_producer;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.create_training_execution_decision(uuid, varchar, bytea, char, char, text, varchar, uuid, varchar, uuid, varchar, varchar, char, timestamptz, timestamptz, timestamptz, uuid, varchar, varchar) TO dohalm_training_authority_producer;
