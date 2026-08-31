DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dohalm_training_intent_writer') THEN
        CREATE ROLE dohalm_training_intent_writer LOGIN NOINHERIT;
    END IF;
END
$$;

ALTER ROLE dohalm_training_intent_writer LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

ALTER TABLE dohalm_training_v1.training_authority_identity
DROP CONSTRAINT training_authority_identity_subject_family_check;
ALTER TABLE dohalm_training_v1.training_authority_identity
ADD CONSTRAINT training_authority_identity_subject_family_check CHECK (
    subject_family IN (
        'config', 'readiness', 'dataset_version', 'dataset_manifest',
        'dataset_pair', 'decision', 'issuer', 'approver', 'intent_submitter'
    )
);

ALTER TABLE dohalm_training_v1.training_authority_event
DROP CONSTRAINT training_authority_event_subject_family_check;
ALTER TABLE dohalm_training_v1.training_authority_event
ADD CONSTRAINT training_authority_event_subject_family_check CHECK (
    subject_family IN (
        'config', 'readiness', 'dataset_version', 'dataset_manifest',
        'dataset_pair', 'decision', 'issuer', 'approver', 'intent_submitter'
    )
);

CREATE TABLE dohalm_training_v1.training_intent_submitter_authority (
    authority_id uuid PRIMARY KEY,
    subject_family text NOT NULL DEFAULT 'intent_submitter' CHECK (subject_family = 'intent_submitter'),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    payload_bytes bytea NOT NULL CHECK (octet_length(payload_bytes) > 0),
    payload_sha256 char(71) NOT NULL CHECK (payload_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    valid_from timestamptz NOT NULL CHECK (created_at <= valid_from),
    valid_until timestamptz NULL CHECK (valid_until IS NULL OR valid_from < valid_until),
    source_commit char(40) NOT NULL CHECK (source_commit ~ '^[0-9a-f]{40}$'),
    operator_kind text NOT NULL CHECK (operator_kind = 'local_single_user'),
    FOREIGN KEY (authority_id, subject_family)
        REFERENCES dohalm_training_v1.training_authority_identity (authority_id, subject_family)
        ON DELETE RESTRICT
);

CREATE TABLE dohalm_training_v1.training_intent_submission (
    intent_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    action text NOT NULL DEFAULT 'full_pretraining' CHECK (action = 'full_pretraining'),
    submitter_authority_id uuid NOT NULL REFERENCES dohalm_training_v1.training_intent_submitter_authority (authority_id) ON DELETE RESTRICT,
    client_request_id varchar(256) NOT NULL CHECK (client_request_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$'),
    requested_run_id varchar(256) NOT NULL UNIQUE CHECK (requested_run_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$'),
    execution_mode text NOT NULL CHECK (execution_mode IN ('fresh', 'r3_one_epoch_continuation')),
    dataset_version_authority_id uuid NOT NULL REFERENCES dohalm_training_v1.dataset_version_authority (authority_id) ON DELETE RESTRICT,
    dataset_manifest_authority_id uuid NOT NULL REFERENCES dohalm_training_v1.dataset_manifest_authority (authority_id) ON DELETE RESTRICT,
    dataset_pair_authority_id uuid NOT NULL REFERENCES dohalm_training_v1.dataset_pair_authority (authority_id) ON DELETE RESTRICT,
    dataset_version_id varchar(256) NOT NULL,
    dataset_manifest_id varchar(256) NOT NULL,
    dataset_pair_fingerprint char(71) NOT NULL CHECK (dataset_pair_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    config_authority_id uuid NOT NULL REFERENCES dohalm_training_v1.training_config_authority (authority_id) ON DELETE RESTRICT,
    config_fingerprint char(71) NOT NULL CHECK (config_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    readiness_authority_id uuid NOT NULL REFERENCES dohalm_training_v1.training_readiness_authority (authority_id) ON DELETE RESTRICT,
    readiness_fingerprint char(71) NOT NULL CHECK (readiness_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    source_commit char(40) NOT NULL CHECK (source_commit ~ '^[0-9a-f]{40}$'),
    output_logical_root varchar(512) NOT NULL CHECK (
        output_logical_root ~ '^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$'
        AND output_logical_root !~ '(^|/)\.\.(/|$)'
    ),
    predecessor_run_id varchar(256) NULL,
    checkpoint_reference varchar(256) NULL,
    source_step bigint NULL CHECK (source_step IS NULL OR source_step >= 1),
    target_cumulative_steps bigint NULL CHECK (target_cumulative_steps IS NULL OR target_cumulative_steps >= 2),
    intent_fingerprint char(71) NOT NULL CHECK (intent_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    request_fingerprint char(71) NOT NULL CHECK (request_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    UNIQUE (submitter_authority_id, client_request_id),
    CHECK (
        (execution_mode = 'fresh' AND predecessor_run_id IS NULL AND checkpoint_reference IS NULL
         AND source_step IS NULL AND target_cumulative_steps IS NULL)
        OR
        (execution_mode = 'r3_one_epoch_continuation' AND predecessor_run_id IS NOT NULL
         AND checkpoint_reference IS NOT NULL AND source_step IS NOT NULL
         AND target_cumulative_steps IS NOT NULL AND source_step < target_cumulative_steps)
    )
);

CREATE TABLE dohalm_training_v1.training_intent_decision_binding (
    intent_id uuid PRIMARY KEY REFERENCES dohalm_training_v1.training_intent_submission (intent_id) ON DELETE RESTRICT,
    decision_authority_id uuid NOT NULL UNIQUE REFERENCES dohalm_training_v1.training_execution_decision_authority (authority_id) ON DELETE RESTRICT,
    decision text NOT NULL CHECK (decision IN ('approved', 'denied')),
    authorization_id varchar(256) NOT NULL,
    issuer_authority_id uuid NOT NULL,
    issuer_id varchar(256) NOT NULL,
    approver_authority_id uuid NOT NULL,
    approver_reference varchar(256) NOT NULL,
    evidence_reference varchar(256) NOT NULL,
    request_fingerprint char(71) NOT NULL CHECK (request_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    bound_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    FOREIGN KEY (issuer_authority_id, issuer_id)
        REFERENCES dohalm_training_v1.training_issuer_registry (authority_id, issuer_id) ON DELETE RESTRICT,
    FOREIGN KEY (approver_authority_id, approver_reference)
        REFERENCES dohalm_training_v1.training_approver_registry (authority_id, approver_reference) ON DELETE RESTRICT
);

CREATE TRIGGER training_intent_submitter_authority_immutable
BEFORE UPDATE OR DELETE ON dohalm_training_v1.training_intent_submitter_authority
FOR EACH ROW EXECUTE FUNCTION dohalm_training_v1.reject_immutable_mutation();
CREATE TRIGGER training_intent_submission_immutable
BEFORE UPDATE OR DELETE ON dohalm_training_v1.training_intent_submission
FOR EACH ROW EXECUTE FUNCTION dohalm_training_v1.reject_immutable_mutation();
CREATE TRIGGER training_intent_decision_binding_immutable
BEFORE UPDATE OR DELETE ON dohalm_training_v1.training_intent_decision_binding
FOR EACH ROW EXECUTE FUNCTION dohalm_training_v1.reject_immutable_mutation();

CREATE FUNCTION dohalm_training_v1.write_training_intent_submitter_event(
    requested_event_id uuid,
    requested_authority_id uuid,
    requested_expected_stream_version bigint,
    requested_event_kind text,
    requested_superseded_by_authority_id uuid,
    requested_effective_at timestamptz,
    requested_correlation_reference varchar(256),
    requested_evidence_reference varchar(256)
)
RETURNS dohalm_training_v1.training_authority_current
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    payload dohalm_training_v1.training_intent_submitter_authority%ROWTYPE;
    current_projection dohalm_training_v1.training_authority_current%ROWTYPE;
    next_version bigint;
    next_state text;
    next_superseded_by uuid;
    event_fingerprint char(71);
BEGIN
    IF requested_expected_stream_version < 0
       OR requested_event_kind NOT IN ('published', 'activated', 'revoked', 'superseded')
       OR (requested_event_kind = 'superseded') <> (requested_superseded_by_authority_id IS NOT NULL) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'intent submitter transition invalid';
    END IF;
    SELECT row.* INTO payload
    FROM dohalm_training_v1.training_intent_submitter_authority row
    WHERE row.authority_id = requested_authority_id;
    IF NOT FOUND OR requested_effective_at < payload.valid_from
       OR (payload.valid_until IS NOT NULL AND requested_effective_at >= payload.valid_until) THEN
        RAISE EXCEPTION USING ERRCODE = '23503', MESSAGE = 'intent submitter authority unavailable';
    END IF;
    SELECT projection.* INTO current_projection
    FROM dohalm_training_v1.training_authority_current projection
    WHERE projection.authority_id = requested_authority_id
    FOR UPDATE;
    IF FOUND THEN
        IF current_projection.projection_version <> requested_expected_stream_version
           OR requested_event_kind NOT IN ('activated', 'revoked', 'superseded')
           OR current_projection.state NOT IN ('scheduled', 'current') THEN
            RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'intent submitter stream conflict';
        END IF;
        next_version := requested_expected_stream_version + 1;
    ELSE
        IF requested_expected_stream_version <> 0 OR requested_event_kind <> 'published' THEN
            RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'intent submitter stream conflict';
        END IF;
        next_version := 1;
    END IF;
    IF requested_event_kind = 'superseded' THEN
        PERFORM 1
        FROM dohalm_training_v1.training_intent_submitter_authority replacement
        JOIN dohalm_training_v1.training_authority_current replacement_state
          ON replacement_state.authority_id = replacement.authority_id
        WHERE replacement.authority_id = requested_superseded_by_authority_id
          AND replacement_state.state = 'current';
        IF NOT FOUND OR requested_superseded_by_authority_id = requested_authority_id THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'intent submitter supersession invalid';
        END IF;
    END IF;
    event_fingerprint := 'sha256:' || encode(sha256(convert_to(
        replace(replace(jsonb_build_object(
            'authority_id', requested_authority_id,
            'correlation_reference', requested_correlation_reference,
            'effective_at', requested_effective_at,
            'event_kind', requested_event_kind,
            'evidence_reference', requested_evidence_reference,
            'producer_role', 'training_authority_producer',
            'subject_family', 'intent_submitter',
            'subject_version', next_version,
            'superseded_by_authority_id', requested_superseded_by_authority_id
        )::text, ': ', ':'), ', ', ',') || chr(10), 'UTF8')), 'hex');
    INSERT INTO dohalm_training_v1.training_authority_event (
        event_id, authority_id, subject_family, subject_version, event_kind,
        superseded_by_authority_id, effective_at, producer_role,
        correlation_reference, evidence_reference, event_fingerprint
    ) VALUES (
        requested_event_id, requested_authority_id, 'intent_submitter', next_version,
        requested_event_kind, requested_superseded_by_authority_id, requested_effective_at,
        'training_authority_producer', requested_correlation_reference,
        requested_evidence_reference, event_fingerprint
    );
    next_state := CASE requested_event_kind
        WHEN 'revoked' THEN 'revoked'
        WHEN 'superseded' THEN 'superseded'
        ELSE CASE WHEN requested_effective_at <= transaction_timestamp() THEN 'current' ELSE 'scheduled' END
    END;
    next_superseded_by := CASE WHEN next_state = 'superseded' THEN requested_superseded_by_authority_id ELSE NULL END;
    INSERT INTO dohalm_training_v1.training_authority_current (
        authority_id, subject_family, stream_head_event_id, current_event_id,
        current_subject_version, state, state_effective_at, superseded_by_authority_id,
        valid_from, valid_until, projection_version
    ) VALUES (
        requested_authority_id, 'intent_submitter', requested_event_id,
        CASE WHEN next_state = 'scheduled' THEN NULL ELSE requested_event_id END,
        next_version, next_state, requested_effective_at, next_superseded_by,
        payload.valid_from, payload.valid_until, next_version
    ) ON CONFLICT ON CONSTRAINT training_authority_current_pkey DO UPDATE SET
        stream_head_event_id = EXCLUDED.stream_head_event_id,
        current_event_id = EXCLUDED.current_event_id,
        current_subject_version = EXCLUDED.current_subject_version,
        state = EXCLUDED.state,
        state_effective_at = EXCLUDED.state_effective_at,
        superseded_by_authority_id = EXCLUDED.superseded_by_authority_id,
        projection_version = EXCLUDED.projection_version,
        projected_at = transaction_timestamp();
    SELECT projection.* INTO current_projection
    FROM dohalm_training_v1.training_authority_current projection
    WHERE projection.authority_id = requested_authority_id;
    RETURN current_projection;
END
$$;

CREATE FUNCTION dohalm_training_v1.provision_training_intent_submitter(
    requested_authority_id uuid,
    requested_domain_key varchar(256),
    requested_payload_bytes bytea,
    requested_payload_sha256 char(71),
    requested_source_commit char(40),
    requested_valid_from timestamptz,
    requested_valid_until timestamptz,
    requested_event_id uuid,
    requested_correlation_reference varchar(256),
    requested_evidence_reference varchar(256)
)
RETURNS dohalm_training_v1.training_authority_current
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    INSERT INTO dohalm_training_v1.training_authority_identity (
        authority_id, subject_family, domain_key
    ) VALUES (requested_authority_id, 'intent_submitter', requested_domain_key);
    INSERT INTO dohalm_training_v1.training_intent_submitter_authority (
        authority_id, payload_bytes, payload_sha256, valid_from, valid_until,
        source_commit, operator_kind
    ) VALUES (
        requested_authority_id, requested_payload_bytes, requested_payload_sha256,
        requested_valid_from, requested_valid_until, requested_source_commit,
        'local_single_user'
    );
    RETURN dohalm_training_v1.write_training_intent_submitter_event(
        requested_event_id, requested_authority_id, 0, 'published', NULL,
        requested_valid_from, requested_correlation_reference, requested_evidence_reference
    );
END
$$;

CREATE FUNCTION dohalm_training_v1.read_training_intent_submitter(requested_authority_id uuid)
RETURNS TABLE (
    authority_id uuid, domain_key varchar(256), authority_state text,
    state_effective_at timestamptz, created_at timestamptz, valid_from timestamptz,
    valid_until timestamptz, projection_version bigint
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT identity.authority_id, identity.domain_key, current_state.state,
           current_state.state_effective_at, payload.created_at, payload.valid_from,
           payload.valid_until, current_state.projection_version
    FROM dohalm_training_v1.training_authority_identity identity
    JOIN dohalm_training_v1.training_intent_submitter_authority payload
      ON payload.authority_id = identity.authority_id
    JOIN dohalm_training_v1.training_authority_current current_state
      ON current_state.authority_id = identity.authority_id
    WHERE identity.authority_id = requested_authority_id
      AND identity.subject_family = 'intent_submitter'
$$;

CREATE FUNCTION dohalm_training_v1.submit_training_intent(
    requested_submitter_authority_id uuid,
    requested_client_request_id varchar(256), requested_run_id varchar(256), requested_execution_mode text,
    requested_dataset_version_authority_id uuid, requested_dataset_manifest_authority_id uuid,
    requested_dataset_pair_authority_id uuid, requested_dataset_version_id varchar(256),
    requested_dataset_manifest_id varchar(256), requested_dataset_pair_fingerprint char(71),
    requested_config_authority_id uuid, requested_config_fingerprint char(71),
    requested_readiness_authority_id uuid, requested_readiness_fingerprint char(71),
    requested_source_commit char(40), requested_output_logical_root varchar(512),
    requested_predecessor_run_id varchar(256), requested_checkpoint_reference varchar(256),
    requested_source_step bigint, requested_target_cumulative_steps bigint,
    requested_intent_fingerprint char(71), requested_request_fingerprint char(71)
)
RETURNS TABLE (submit_status text, submitted_intent_id uuid)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    existing_record dohalm_training_v1.training_intent_submission%ROWTYPE;
    inserted_record dohalm_training_v1.training_intent_submission%ROWTYPE;
    canonical_intent char(71);
    canonical_request char(71);
    continuation_json text;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed'
       OR current_setting('transaction_read_only') <> 'off' THEN
        RAISE EXCEPTION USING ERRCODE = '25006', MESSAGE = 'read committed intent transaction required';
    END IF;
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
        requested_submitter_authority_id::text || chr(31) || requested_client_request_id, 0
    ));
    PERFORM 1 FROM dohalm_training_v1.training_authority_current current_state
    WHERE current_state.authority_id = requested_submitter_authority_id
      AND current_state.subject_family = 'intent_submitter' AND current_state.state = 'current';
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = '23503', MESSAGE = 'intent submitter is not current';
    END IF;
    PERFORM 1
    FROM dohalm_training_v1.dataset_pair_authority pair_row
    JOIN dohalm_training_v1.training_authority_current pair_state ON pair_state.authority_id = pair_row.authority_id
    JOIN dohalm_training_v1.dataset_version_authority version_row ON version_row.authority_id = pair_row.dataset_version_authority_id
    JOIN dohalm_training_v1.training_authority_current version_state ON version_state.authority_id = version_row.authority_id
    JOIN dohalm_training_v1.dataset_manifest_authority manifest_row ON manifest_row.authority_id = pair_row.dataset_manifest_authority_id
    JOIN dohalm_training_v1.training_authority_current manifest_state ON manifest_state.authority_id = manifest_row.authority_id
    JOIN dohalm_training_v1.training_config_authority config_row ON config_row.authority_id = requested_config_authority_id
    JOIN dohalm_training_v1.training_authority_current config_state ON config_state.authority_id = config_row.authority_id
    JOIN dohalm_training_v1.training_readiness_authority readiness_row ON readiness_row.authority_id = requested_readiness_authority_id
    JOIN dohalm_training_v1.training_authority_current readiness_state ON readiness_state.authority_id = readiness_row.authority_id
    WHERE pair_row.authority_id = requested_dataset_pair_authority_id
      AND version_row.authority_id = requested_dataset_version_authority_id
      AND manifest_row.authority_id = requested_dataset_manifest_authority_id
      AND version_row.common_object_id = requested_dataset_version_id
      AND manifest_row.common_object_id = requested_dataset_manifest_id
      AND pair_row.pair_fingerprint = requested_dataset_pair_fingerprint
      AND config_row.payload_sha256 = requested_config_fingerprint
      AND readiness_row.payload_sha256 = requested_readiness_fingerprint
      AND readiness_row.dataset_pair_fingerprint = requested_dataset_pair_fingerprint
      AND readiness_row.config_fingerprint = requested_config_fingerprint
      AND pair_state.state = 'current' AND version_state.state = 'current'
      AND manifest_state.state = 'current' AND config_state.state = 'current'
      AND readiness_state.state = 'current';
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = '23503', MESSAGE = 'intent prerequisite binding unavailable';
    END IF;
    continuation_json := CASE WHEN requested_execution_mode = 'fresh' THEN 'null' ELSE
        '{"checkpoint_reference":' || to_json(requested_checkpoint_reference)::text ||
        ',"predecessor_run_id":' || to_json(requested_predecessor_run_id)::text ||
        ',"source_step":' || requested_source_step::text ||
        ',"target_cumulative_steps":' || requested_target_cumulative_steps::text || '}' END;
    canonical_intent := 'sha256:' || encode(sha256(convert_to(
        '{"action":"full_pretraining"' ||
        ',"config_authority_id":' || to_json(requested_config_authority_id::text)::text ||
        ',"config_fingerprint":' || to_json(rtrim(requested_config_fingerprint))::text ||
        ',"continuation":' || continuation_json ||
        ',"dataset_manifest_authority_id":' || to_json(requested_dataset_manifest_authority_id::text)::text ||
        ',"dataset_manifest_id":' || to_json(requested_dataset_manifest_id)::text ||
        ',"dataset_pair_authority_id":' || to_json(requested_dataset_pair_authority_id::text)::text ||
        ',"dataset_pair_fingerprint":' || to_json(rtrim(requested_dataset_pair_fingerprint))::text ||
        ',"dataset_version_authority_id":' || to_json(requested_dataset_version_authority_id::text)::text ||
        ',"dataset_version_id":' || to_json(requested_dataset_version_id)::text ||
        ',"execution_mode":' || to_json(requested_execution_mode)::text ||
        ',"output_logical_root":' || to_json(requested_output_logical_root)::text ||
        ',"readiness_authority_id":' || to_json(requested_readiness_authority_id::text)::text ||
        ',"readiness_fingerprint":' || to_json(rtrim(requested_readiness_fingerprint))::text ||
        ',"requested_run_id":' || to_json(requested_run_id)::text ||
        ',"schema_version":1' ||
        ',"source_commit":' || to_json(rtrim(requested_source_commit))::text ||
        ',"submitter_authority_id":' || to_json(requested_submitter_authority_id::text)::text || '}' || chr(10),
        'UTF8')), 'hex');
    canonical_request := 'sha256:' || encode(sha256(convert_to(
        '{"action":"full_pretraining"' ||
        ',"config_fingerprint":' || to_json(rtrim(requested_config_fingerprint))::text ||
        ',"dataset_manifest_id":' || to_json(requested_dataset_manifest_id)::text ||
        ',"dataset_pair_fingerprint":' || to_json(rtrim(requested_dataset_pair_fingerprint))::text ||
        ',"dataset_version_id":' || to_json(requested_dataset_version_id)::text ||
        ',"execution_mode":' || to_json(requested_execution_mode)::text ||
        ',"output_logical_root":' || to_json(requested_output_logical_root)::text ||
        ',"readiness_fingerprint":' || to_json(rtrim(requested_readiness_fingerprint))::text ||
        ',"run_id":' || to_json(requested_run_id)::text ||
        ',"schema_version":1' ||
        ',"source_commit":' || to_json(rtrim(requested_source_commit))::text || '}' || chr(10),
        'UTF8')), 'hex');
    IF canonical_intent <> requested_intent_fingerprint OR canonical_request <> requested_request_fingerprint THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'intent canonical fingerprint mismatch';
    END IF;
    SELECT row.* INTO existing_record
    FROM dohalm_training_v1.training_intent_submission row
    WHERE row.submitter_authority_id = requested_submitter_authority_id
      AND row.client_request_id = requested_client_request_id;
    IF FOUND THEN
        IF existing_record.intent_fingerprint <> requested_intent_fingerprint THEN
            RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'intent idempotency conflict';
        END IF;
        submit_status := 'replayed'; submitted_intent_id := existing_record.intent_id; RETURN NEXT; RETURN;
    END IF;
    BEGIN
        INSERT INTO dohalm_training_v1.training_intent_submission (
            submitter_authority_id, client_request_id, requested_run_id, execution_mode,
            dataset_version_authority_id, dataset_manifest_authority_id, dataset_pair_authority_id,
            dataset_version_id, dataset_manifest_id, dataset_pair_fingerprint,
            config_authority_id, config_fingerprint, readiness_authority_id, readiness_fingerprint,
            source_commit, output_logical_root, predecessor_run_id, checkpoint_reference,
            source_step, target_cumulative_steps, intent_fingerprint, request_fingerprint
        ) VALUES (
            requested_submitter_authority_id, requested_client_request_id, requested_run_id, requested_execution_mode,
            requested_dataset_version_authority_id, requested_dataset_manifest_authority_id, requested_dataset_pair_authority_id,
            requested_dataset_version_id, requested_dataset_manifest_id, requested_dataset_pair_fingerprint,
            requested_config_authority_id, requested_config_fingerprint, requested_readiness_authority_id, requested_readiness_fingerprint,
            requested_source_commit, requested_output_logical_root, requested_predecessor_run_id, requested_checkpoint_reference,
            requested_source_step, requested_target_cumulative_steps, requested_intent_fingerprint, requested_request_fingerprint
        ) RETURNING * INTO inserted_record;
    EXCEPTION WHEN unique_violation THEN
        RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'intent identity conflict';
    END;
    submit_status := 'created'; submitted_intent_id := inserted_record.intent_id; RETURN NEXT;
END
$$;

CREATE FUNCTION dohalm_training_v1.read_training_intent(requested_intent_id uuid)
RETURNS SETOF dohalm_training_v1.training_intent_submission
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp
AS $$ SELECT row.* FROM dohalm_training_v1.training_intent_submission row WHERE row.intent_id = requested_intent_id $$;

CREATE FUNCTION dohalm_training_v1.read_training_intent_by_idempotency(requested_submitter_id uuid, requested_client_request_id varchar)
RETURNS SETOF dohalm_training_v1.training_intent_submission
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp
AS $$ SELECT row.* FROM dohalm_training_v1.training_intent_submission row WHERE row.submitter_authority_id = requested_submitter_id AND row.client_request_id = requested_client_request_id $$;

CREATE FUNCTION dohalm_training_v1.bind_training_intent_decision(requested_intent_id uuid, requested_decision_authority_id uuid)
RETURNS dohalm_training_v1.training_intent_decision_binding
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    intent_row dohalm_training_v1.training_intent_submission%ROWTYPE;
    decision_row dohalm_training_v1.training_execution_decision_authority%ROWTYPE;
    existing_binding dohalm_training_v1.training_intent_decision_binding%ROWTYPE;
    inserted_binding dohalm_training_v1.training_intent_decision_binding%ROWTYPE;
BEGIN
    SELECT row.* INTO intent_row FROM dohalm_training_v1.training_intent_submission row
    WHERE row.intent_id = requested_intent_id;
    IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE = '23503', MESSAGE = 'intent unavailable'; END IF;
    SELECT decision.* INTO decision_row
    FROM dohalm_training_v1.training_execution_decision_authority decision
    JOIN dohalm_training_v1.training_authority_current decision_state ON decision_state.authority_id = decision.authority_id
    JOIN dohalm_training_v1.training_authority_current issuer_state ON issuer_state.authority_id = decision.issuer_authority_id
    JOIN dohalm_training_v1.training_authority_current approver_state ON approver_state.authority_id = decision.approver_authority_id
    WHERE decision.authority_id = requested_decision_authority_id
      AND decision.request_fingerprint = intent_row.request_fingerprint
      AND decision_state.state = 'current' AND issuer_state.state = 'current' AND approver_state.state = 'current';
    IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE = '23503', MESSAGE = 'decision binding unavailable'; END IF;
    SELECT binding.* INTO existing_binding
    FROM dohalm_training_v1.training_intent_decision_binding binding
    WHERE binding.intent_id = requested_intent_id;
    IF FOUND THEN
        IF existing_binding.decision_authority_id <> requested_decision_authority_id THEN
            RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'intent decision binding conflict';
        END IF;
        RETURN existing_binding;
    END IF;
    INSERT INTO dohalm_training_v1.training_intent_decision_binding (
        intent_id, decision_authority_id, decision, authorization_id,
        issuer_authority_id, issuer_id, approver_authority_id, approver_reference,
        evidence_reference, request_fingerprint
    ) VALUES (
        requested_intent_id, decision_row.authority_id, decision_row.decision,
        decision_row.authorization_id, decision_row.issuer_authority_id, decision_row.issuer_id,
        decision_row.approver_authority_id, decision_row.approver_reference,
        decision_row.evidence_reference, decision_row.request_fingerprint
    ) RETURNING * INTO inserted_binding;
    RETURN inserted_binding;
END
$$;

CREATE FUNCTION dohalm_training_v1.read_training_intent_decision_binding(requested_intent_id uuid)
RETURNS SETOF dohalm_training_v1.training_intent_decision_binding
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp
AS $$ SELECT row.* FROM dohalm_training_v1.training_intent_decision_binding row WHERE row.intent_id = requested_intent_id $$;

CREATE FUNCTION dohalm_training_v1.read_training_intent_validation_state(requested_intent_id uuid)
RETURNS TABLE (
    submitter_current boolean, dataset_version_current boolean, dataset_manifest_current boolean,
    dataset_pair_current boolean, config_current boolean, readiness_current boolean,
    decision_current boolean, issuer_current boolean, approver_current boolean
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp
AS $$
    SELECT submitter_state.state = 'current', version_state.state = 'current', manifest_state.state = 'current',
           pair_state.state = 'current', config_state.state = 'current', readiness_state.state = 'current',
           COALESCE(decision_state.state = 'current', false), COALESCE(issuer_state.state = 'current', false),
           COALESCE(approver_state.state = 'current', false)
    FROM dohalm_training_v1.training_intent_submission intent
    JOIN dohalm_training_v1.training_authority_current submitter_state ON submitter_state.authority_id = intent.submitter_authority_id
    JOIN dohalm_training_v1.training_authority_current version_state ON version_state.authority_id = intent.dataset_version_authority_id
    JOIN dohalm_training_v1.training_authority_current manifest_state ON manifest_state.authority_id = intent.dataset_manifest_authority_id
    JOIN dohalm_training_v1.training_authority_current pair_state ON pair_state.authority_id = intent.dataset_pair_authority_id
    JOIN dohalm_training_v1.training_authority_current config_state ON config_state.authority_id = intent.config_authority_id
    JOIN dohalm_training_v1.training_authority_current readiness_state ON readiness_state.authority_id = intent.readiness_authority_id
    LEFT JOIN dohalm_training_v1.training_intent_decision_binding binding ON binding.intent_id = intent.intent_id
    LEFT JOIN dohalm_training_v1.training_authority_current decision_state ON decision_state.authority_id = binding.decision_authority_id
    LEFT JOIN dohalm_training_v1.training_authority_current issuer_state ON issuer_state.authority_id = binding.issuer_authority_id
    LEFT JOIN dohalm_training_v1.training_authority_current approver_state ON approver_state.authority_id = binding.approver_authority_id
    WHERE intent.intent_id = requested_intent_id
$$;

ALTER TABLE dohalm_training_v1.training_intent_submitter_authority OWNER TO dohalm_training_owner;
ALTER TABLE dohalm_training_v1.training_intent_submission OWNER TO dohalm_training_owner;
ALTER TABLE dohalm_training_v1.training_intent_decision_binding OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.write_training_intent_submitter_event(uuid, uuid, bigint, text, uuid, timestamptz, varchar, varchar) OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.provision_training_intent_submitter(uuid, varchar, bytea, char, char, timestamptz, timestamptz, uuid, varchar, varchar) OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.read_training_intent_submitter(uuid) OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.submit_training_intent(uuid, varchar, varchar, text, uuid, uuid, uuid, varchar, varchar, char, uuid, char, uuid, char, char, varchar, varchar, varchar, bigint, bigint, char, char) OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.read_training_intent(uuid) OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.read_training_intent_by_idempotency(uuid, varchar) OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.bind_training_intent_decision(uuid, uuid) OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.read_training_intent_decision_binding(uuid) OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.read_training_intent_validation_state(uuid) OWNER TO dohalm_training_owner;

REVOKE ALL ON ALL TABLES IN SCHEMA dohalm_training_v1 FROM PUBLIC, dohalm_training_intent_writer;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA dohalm_training_v1 FROM PUBLIC, dohalm_training_intent_writer;
GRANT USAGE ON SCHEMA dohalm_training_v1 TO dohalm_training_intent_writer;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.provision_training_intent_submitter(uuid, varchar, bytea, char, char, timestamptz, timestamptz, uuid, varchar, varchar) TO dohalm_training_authority_producer;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.write_training_intent_submitter_event(uuid, uuid, bigint, text, uuid, timestamptz, varchar, varchar) TO dohalm_training_authority_producer;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.submit_training_intent(uuid, varchar, varchar, text, uuid, uuid, uuid, varchar, varchar, char, uuid, char, uuid, char, char, varchar, varchar, varchar, bigint, bigint, char, char) TO dohalm_training_intent_writer;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.bind_training_intent_decision(uuid, uuid) TO dohalm_training_intent_writer;
GRANT USAGE ON SCHEMA dohalm_training_v1 TO dohalm_training_resolver;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.read_training_intent_submitter(uuid) TO dohalm_training_resolver;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.read_training_intent(uuid) TO dohalm_training_resolver;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.read_training_intent_by_idempotency(uuid, varchar) TO dohalm_training_resolver;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.read_training_intent_decision_binding(uuid) TO dohalm_training_resolver;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.read_training_intent_validation_state(uuid) TO dohalm_training_resolver;
