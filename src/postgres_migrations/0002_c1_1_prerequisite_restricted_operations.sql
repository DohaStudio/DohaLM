DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dohalm_training_authority_producer') THEN
        CREATE ROLE dohalm_training_authority_producer LOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dohalm_training_resolver') THEN
        CREATE ROLE dohalm_training_resolver LOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dohalm_training_journal') THEN
        CREATE ROLE dohalm_training_journal LOGIN NOINHERIT;
    END IF;
END
$$;

ALTER ROLE dohalm_training_authority_producer LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE dohalm_training_resolver LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE dohalm_training_journal LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint AS constraint_record
        WHERE constraint_record.conname = 'training_execution_journal_pkey'
          AND constraint_record.contype = 'p'
          AND constraint_record.conrelid = 'dohalm_training_v1.training_execution_journal'::regclass
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint AS constraint_record
        WHERE constraint_record.conname = 'training_execution_journal_orchestration_correlation_id_key'
          AND constraint_record.contype = 'u'
          AND constraint_record.conrelid = 'dohalm_training_v1.training_execution_journal'::regclass
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'canonical journal claim constraints unavailable';
    END IF;
END
$$;

CREATE FUNCTION dohalm_training_v1.canonical_training_claim_identity(
    requested_identity_kind text,
    requested_run_id varchar(256),
    requested_request_fingerprint char(71),
    requested_orchestration_correlation_id varchar(256)
)
RETURNS varchar(256)
LANGUAGE sql
IMMUTABLE
STRICT
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT CASE requested_identity_kind
        WHEN 'run_id' THEN requested_run_id
        WHEN 'orchestration_correlation_id' THEN requested_orchestration_correlation_id
        WHEN 'run_request_fingerprint' THEN
            'sha256:' || encode(sha256(convert_to(jsonb_build_object(
                'request_fingerprint', rtrim(requested_request_fingerprint),
                'run_id', requested_run_id
            )::text, 'UTF8')), 'hex')
        ELSE NULL
    END
$$;

CREATE TABLE dohalm_training_v1.training_execution_claim_reservation (
    identity_kind text NOT NULL CHECK (
        identity_kind IN ('run_id', 'orchestration_correlation_id', 'run_request_fingerprint')
    ),
    identity_value varchar(256) NOT NULL,
    reservation_group_id uuid NOT NULL,
    owner_run_id varchar(256) NOT NULL CHECK (
        owner_run_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$'
    ),
    owner_request_fingerprint char(71) NOT NULL CHECK (
        owner_request_fingerprint ~ '^sha256:[0-9a-f]{64}$'
    ),
    owner_orchestration_correlation_id varchar(256) NOT NULL CHECK (
        owner_orchestration_correlation_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$'
    ),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    PRIMARY KEY (identity_kind, identity_value),
    CHECK (
        (identity_kind = 'run_id' AND identity_value = owner_run_id)
        OR (identity_kind = 'orchestration_correlation_id' AND identity_value = owner_orchestration_correlation_id)
        OR (
            identity_kind = 'run_request_fingerprint'
            AND identity_value ~ '^sha256:[0-9a-f]{64}$'
        )
    ),
    CHECK (
        identity_value = dohalm_training_v1.canonical_training_claim_identity(
            identity_kind,
            owner_run_id,
            owner_request_fingerprint,
            owner_orchestration_correlation_id
        )
    )
);

ALTER TABLE dohalm_training_v1.training_execution_journal
ADD COLUMN reservation_group_id uuid NULL;

UPDATE dohalm_training_v1.training_execution_journal AS existing_journal
SET reservation_group_id = gen_random_uuid()
WHERE existing_journal.reservation_group_id IS NULL;

INSERT INTO dohalm_training_v1.training_execution_claim_reservation (
    identity_kind, identity_value, reservation_group_id, owner_run_id,
    owner_request_fingerprint, owner_orchestration_correlation_id
)
SELECT identity_record.identity_kind,
       dohalm_training_v1.canonical_training_claim_identity(
           identity_record.identity_kind,
           existing_journal.run_id,
           existing_journal.request_fingerprint,
           existing_journal.orchestration_correlation_id
       ),
       existing_journal.reservation_group_id,
       existing_journal.run_id,
       existing_journal.request_fingerprint,
       existing_journal.orchestration_correlation_id
FROM dohalm_training_v1.training_execution_journal AS existing_journal
CROSS JOIN (VALUES
    ('orchestration_correlation_id'::text),
    ('run_id'::text),
    ('run_request_fingerprint'::text)
) AS identity_record(identity_kind)
ORDER BY existing_journal.run_id, identity_record.identity_kind;

ALTER TABLE dohalm_training_v1.training_execution_journal
ALTER COLUMN reservation_group_id SET NOT NULL;
ALTER TABLE dohalm_training_v1.training_execution_journal
ADD CONSTRAINT training_execution_journal_reservation_group_key
UNIQUE (reservation_group_id);
ALTER TABLE dohalm_training_v1.training_execution_claim_reservation
ADD CONSTRAINT training_execution_claim_reservation_group_fkey
FOREIGN KEY (reservation_group_id)
REFERENCES dohalm_training_v1.training_execution_journal (reservation_group_id)
ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

CREATE TRIGGER training_execution_claim_reservation_immutable
BEFORE UPDATE OR DELETE ON dohalm_training_v1.training_execution_claim_reservation
FOR EACH ROW EXECUTE FUNCTION dohalm_training_v1.reject_immutable_mutation();

CREATE FUNCTION dohalm_training_v1.write_training_authority_event(
    requested_event_id uuid,
    requested_authority_id uuid,
    requested_subject_family text,
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
    identity_family text;
    row_valid_from timestamptz;
    row_valid_until timestamptz;
    current_projection dohalm_training_v1.training_authority_current%ROWTYPE;
    previous_kind text;
    next_version bigint;
    as_of timestamptz := transaction_timestamp();
    winning_event dohalm_training_v1.training_authority_event%ROWTYPE;
    first_future_start timestamptz;
    next_state text;
    next_state_effective_at timestamptz;
    next_current_event_id uuid;
    next_superseded_by uuid;
    computed_event_fingerprint char(71);
BEGIN
    IF requested_expected_stream_version < 0 THEN
        RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'authority stream conflict';
    END IF;

    SELECT identity_record.subject_family INTO identity_family
    FROM dohalm_training_v1.training_authority_identity AS identity_record
    WHERE identity_record.authority_id = requested_authority_id;
    IF NOT FOUND OR identity_family <> requested_subject_family THEN
        RAISE EXCEPTION USING ERRCODE = '23503', MESSAGE = 'authority identity unavailable';
    END IF;

    CASE requested_subject_family
        WHEN 'config' THEN
            SELECT config_record.valid_from, config_record.valid_until INTO row_valid_from, row_valid_until
            FROM dohalm_training_v1.training_config_authority AS config_record
            WHERE config_record.authority_id = requested_authority_id;
        WHEN 'readiness' THEN
            SELECT readiness_record.valid_from, readiness_record.valid_until INTO row_valid_from, row_valid_until
            FROM dohalm_training_v1.training_readiness_authority AS readiness_record
            WHERE readiness_record.authority_id = requested_authority_id;
        WHEN 'dataset_version' THEN
            SELECT version_record.valid_from, version_record.valid_until INTO row_valid_from, row_valid_until
            FROM dohalm_training_v1.dataset_version_authority AS version_record
            WHERE version_record.authority_id = requested_authority_id;
        WHEN 'dataset_manifest' THEN
            SELECT manifest_record.valid_from, manifest_record.valid_until INTO row_valid_from, row_valid_until
            FROM dohalm_training_v1.dataset_manifest_authority AS manifest_record
            WHERE manifest_record.authority_id = requested_authority_id;
        WHEN 'dataset_pair' THEN
            SELECT pair_record.valid_from, pair_record.valid_until INTO row_valid_from, row_valid_until
            FROM dohalm_training_v1.dataset_pair_authority AS pair_record
            WHERE pair_record.authority_id = requested_authority_id;
        WHEN 'decision' THEN
            SELECT decision_record.valid_from, decision_record.valid_until INTO row_valid_from, row_valid_until
            FROM dohalm_training_v1.training_execution_decision_authority AS decision_record
            WHERE decision_record.authority_id = requested_authority_id;
        WHEN 'issuer' THEN
            SELECT issuer_record.valid_from, issuer_record.valid_until INTO row_valid_from, row_valid_until
            FROM dohalm_training_v1.training_issuer_registry AS issuer_record
            WHERE issuer_record.authority_id = requested_authority_id;
        WHEN 'approver' THEN
            SELECT approver_record.valid_from, approver_record.valid_until INTO row_valid_from, row_valid_until
            FROM dohalm_training_v1.training_approver_registry AS approver_record
            WHERE approver_record.authority_id = requested_authority_id;
        ELSE
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'authority family invalid';
    END CASE;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = '23503', MESSAGE = 'authority payload unavailable';
    END IF;
    IF row_valid_until IS NOT NULL AND (row_valid_until <= as_of OR requested_effective_at >= row_valid_until) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'authority event outside validity';
    END IF;

    SELECT locked_projection.* INTO current_projection
    FROM dohalm_training_v1.training_authority_current AS locked_projection
    WHERE locked_projection.authority_id = requested_authority_id
    FOR UPDATE;

    IF FOUND THEN
        IF current_projection.projection_version <> requested_expected_stream_version THEN
            RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'authority stream conflict';
        END IF;
        SELECT previous_event.event_kind INTO previous_kind
        FROM dohalm_training_v1.training_authority_event AS previous_event
        WHERE previous_event.event_id = current_projection.stream_head_event_id;
        IF previous_kind NOT IN ('published', 'activated')
           OR requested_event_kind NOT IN ('activated', 'revoked', 'superseded') THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'authority transition invalid';
        END IF;
        next_version := requested_expected_stream_version + 1;
    ELSE
        IF requested_expected_stream_version <> 0 OR requested_event_kind <> 'published' THEN
            RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'authority stream conflict';
        END IF;
        next_version := 1;
    END IF;

    IF (requested_event_kind = 'superseded') <> (requested_superseded_by_authority_id IS NOT NULL) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'authority supersession invalid';
    END IF;
    IF requested_event_kind = 'superseded' THEN
        PERFORM 1
        FROM dohalm_training_v1.training_authority_identity replacement
        JOIN dohalm_training_v1.training_authority_current replacement_state
          ON replacement_state.authority_id = replacement.authority_id
        WHERE replacement.authority_id = requested_superseded_by_authority_id
          AND replacement.subject_family = requested_subject_family
          AND replacement_state.state = 'current'
          AND replacement_state.valid_from <= requested_effective_at
          AND (replacement_state.valid_until IS NULL OR requested_effective_at < replacement_state.valid_until);
        IF NOT FOUND OR requested_superseded_by_authority_id = requested_authority_id THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'authority supersession invalid';
        END IF;
        IF EXISTS (
            WITH RECURSIVE chain(authority_id) AS (
                SELECT requested_superseded_by_authority_id
                UNION ALL
                SELECT current_state.superseded_by_authority_id
                FROM dohalm_training_v1.training_authority_current current_state
                JOIN chain ON current_state.authority_id = chain.authority_id
                WHERE current_state.superseded_by_authority_id IS NOT NULL
            )
            SELECT 1 FROM chain AS supersession_chain
            WHERE supersession_chain.authority_id = requested_authority_id
        ) THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'authority supersession cycle';
        END IF;
    END IF;

    computed_event_fingerprint := 'sha256:' || encode(sha256(convert_to(jsonb_build_object(
        'authority_id', requested_authority_id,
        'subject_family', requested_subject_family,
        'subject_version', next_version,
        'event_kind', requested_event_kind,
        'superseded_by_authority_id', requested_superseded_by_authority_id,
        'effective_at', requested_effective_at,
        'producer_role', 'training_authority_producer',
        'correlation_reference', requested_correlation_reference,
        'evidence_reference', requested_evidence_reference
    )::text, 'UTF8')), 'hex');

    INSERT INTO dohalm_training_v1.training_authority_event (
        event_id, authority_id, subject_family, subject_version, event_kind,
        superseded_by_authority_id, effective_at, producer_role,
        correlation_reference, evidence_reference, event_fingerprint
    ) VALUES (
        requested_event_id, requested_authority_id, requested_subject_family, next_version,
        requested_event_kind, requested_superseded_by_authority_id, requested_effective_at,
        'training_authority_producer', requested_correlation_reference,
        requested_evidence_reference, computed_event_fingerprint
    );

    SELECT event.* INTO winning_event
    FROM dohalm_training_v1.training_authority_event event
    WHERE event.authority_id = requested_authority_id AND event.effective_at <= as_of
    ORDER BY event.effective_at DESC, event.subject_version DESC
    LIMIT 1;

    IF winning_event.event_id IS NULL THEN
        SELECT min(greatest(row_valid_from, event.effective_at)) INTO first_future_start
        FROM dohalm_training_v1.training_authority_event event
        WHERE event.authority_id = requested_authority_id
          AND event.event_kind IN ('published', 'activated');
        next_state := 'scheduled';
        next_state_effective_at := first_future_start;
        next_current_event_id := NULL;
        next_superseded_by := NULL;
    ELSIF winning_event.event_kind = 'revoked' THEN
        next_state := 'revoked';
        next_state_effective_at := winning_event.effective_at;
        next_current_event_id := winning_event.event_id;
        next_superseded_by := NULL;
    ELSIF winning_event.event_kind = 'superseded' THEN
        next_state := 'superseded';
        next_state_effective_at := winning_event.effective_at;
        next_current_event_id := winning_event.event_id;
        next_superseded_by := winning_event.superseded_by_authority_id;
    ELSIF row_valid_until IS NOT NULL AND row_valid_until <= as_of THEN
        next_state := 'expired';
        next_state_effective_at := row_valid_until;
        next_current_event_id := winning_event.event_id;
        next_superseded_by := NULL;
    ELSIF greatest(row_valid_from, winning_event.effective_at) <= as_of THEN
        next_state := 'current';
        next_state_effective_at := greatest(row_valid_from, winning_event.effective_at);
        next_current_event_id := winning_event.event_id;
        next_superseded_by := NULL;
    ELSE
        next_state := 'scheduled';
        next_state_effective_at := greatest(row_valid_from, winning_event.effective_at);
        next_current_event_id := NULL;
        next_superseded_by := NULL;
    END IF;

    INSERT INTO dohalm_training_v1.training_authority_current (
        authority_id, subject_family, stream_head_event_id, current_event_id,
        current_subject_version, state, state_effective_at, superseded_by_authority_id,
        valid_from, valid_until, projection_version
    ) VALUES (
        requested_authority_id, requested_subject_family, requested_event_id,
        next_current_event_id, next_version, next_state, next_state_effective_at,
        next_superseded_by, row_valid_from, row_valid_until, next_version
    )
    ON CONFLICT ON CONSTRAINT training_authority_current_pkey DO UPDATE SET
        stream_head_event_id = EXCLUDED.stream_head_event_id,
        current_event_id = EXCLUDED.current_event_id,
        current_subject_version = EXCLUDED.current_subject_version,
        state = EXCLUDED.state,
        state_effective_at = EXCLUDED.state_effective_at,
        superseded_by_authority_id = EXCLUDED.superseded_by_authority_id,
        projection_version = EXCLUDED.projection_version,
        projected_at = transaction_timestamp();

    SELECT final_projection.* INTO current_projection
    FROM dohalm_training_v1.training_authority_current AS final_projection
    WHERE final_projection.authority_id = requested_authority_id;
    RETURN current_projection;
END
$$;

CREATE FUNCTION dohalm_training_v1.read_training_authority_snapshot(requested_authority_ids uuid[])
RETURNS TABLE (
    snapshot_authority_id uuid,
    snapshot_subject_family text,
    snapshot_domain_key varchar(256),
    snapshot_payload_bytes bytea,
    snapshot_payload_sha256 char(71),
    snapshot_source_commit char(40),
    snapshot_state text,
    snapshot_state_effective_at timestamptz,
    snapshot_valid_from timestamptz,
    snapshot_valid_until timestamptz,
    snapshot_projection_version bigint
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    IF current_setting('transaction_isolation') <> 'repeatable read'
       OR current_setting('transaction_read_only') <> 'on' THEN
        RAISE EXCEPTION USING ERRCODE = '25006', MESSAGE = 'repeatable read-only authority snapshot required';
    END IF;
    IF requested_authority_ids IS NULL OR cardinality(requested_authority_ids) = 0
       OR array_position(requested_authority_ids, NULL) IS NOT NULL THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'authority snapshot identity invalid';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM dohalm_training_v1.training_authority_current current_state
        WHERE current_state.authority_id = ANY(requested_authority_ids)
          AND ((current_state.state = 'scheduled' AND current_state.state_effective_at <= transaction_timestamp())
               OR (current_state.state = 'current' AND current_state.valid_until IS NOT NULL
                   AND current_state.valid_until <= transaction_timestamp()))
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'authority projection refresh required';
    END IF;
    RETURN QUERY
    SELECT identity.authority_id, identity.subject_family, identity.domain_key,
           family.payload_bytes, family.payload_sha256, family.source_commit,
           current_state.state, current_state.state_effective_at,
           current_state.valid_from, current_state.valid_until,
           current_state.projection_version
    FROM dohalm_training_v1.training_authority_identity identity
    JOIN dohalm_training_v1.training_authority_current current_state
      ON current_state.authority_id = identity.authority_id
    JOIN LATERAL (
        SELECT value.payload_bytes, value.payload_sha256, value.source_commit
        FROM (
            SELECT c.payload_bytes, c.payload_sha256, c.source_commit FROM dohalm_training_v1.training_config_authority c WHERE c.authority_id = identity.authority_id
            UNION ALL SELECT r.payload_bytes, r.payload_sha256, r.source_commit FROM dohalm_training_v1.training_readiness_authority r WHERE r.authority_id = identity.authority_id
            UNION ALL SELECT d.payload_bytes, d.payload_sha256, d.source_commit FROM dohalm_training_v1.dataset_version_authority d WHERE d.authority_id = identity.authority_id
            UNION ALL SELECT m.payload_bytes, m.payload_sha256, m.source_commit FROM dohalm_training_v1.dataset_manifest_authority m WHERE m.authority_id = identity.authority_id
            UNION ALL SELECT p.payload_bytes, p.payload_sha256, p.source_commit FROM dohalm_training_v1.dataset_pair_authority p WHERE p.authority_id = identity.authority_id
            UNION ALL SELECT x.payload_bytes, x.payload_sha256, x.source_commit FROM dohalm_training_v1.training_execution_decision_authority x WHERE x.authority_id = identity.authority_id
            UNION ALL SELECT i.payload_bytes, i.payload_sha256, i.source_commit FROM dohalm_training_v1.training_issuer_registry i WHERE i.authority_id = identity.authority_id
            UNION ALL SELECT a.payload_bytes, a.payload_sha256, a.source_commit FROM dohalm_training_v1.training_approver_registry a WHERE a.authority_id = identity.authority_id
        ) value
    ) family ON true
    WHERE identity.authority_id = ANY(requested_authority_ids)
    ORDER BY identity.authority_id;
END
$$;

CREATE FUNCTION dohalm_training_v1.claim_training_execution_journal(
    requested_run_id varchar(256), requested_request_fingerprint char(71),
    requested_intent_fingerprint char(71), requested_orchestration_correlation_id varchar(256),
    requested_dataset_version_id varchar(256), requested_dataset_manifest_id varchar(256),
    requested_dataset_pair_fingerprint char(71), requested_config_fingerprint char(71),
    requested_readiness_fingerprint char(71), requested_source_commit char(40),
    requested_prerequisite_policy_reference varchar(256), requested_process_boundary_id varchar(256)
)
RETURNS TABLE (claim_status text, claimed_run_id varchar(256), claimed_request_fingerprint char(71), claimed_phase text,
               claimed_journal_version bigint, claimed_backend_entered boolean, claimed_reconciliation_required boolean,
               claimed_reconciliation_reason_code varchar(128))
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    resolved_journal dohalm_training_v1.training_execution_journal%ROWTYPE;
    requested_reservation_group_id uuid := gen_random_uuid();
    requested_run_request_identity varchar(256);
    reservation_collision boolean := false;
    matching_reservation_count integer := 0;
    exact_owner_count integer := 0;
    reservation_group_count integer := 0;
    existing_reservation_group_id uuid;
    new_phase_event_id uuid := gen_random_uuid();
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed'
       OR current_setting('transaction_read_only') <> 'off' THEN
        RAISE EXCEPTION USING ERRCODE = '25006', MESSAGE = 'read committed journal transaction required';
    END IF;
    IF requested_run_id !~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$'
       OR requested_orchestration_correlation_id !~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$'
       OR requested_request_fingerprint !~ '^sha256:[0-9a-f]{64}$' THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'journal claim identity invalid';
    END IF;
    requested_run_request_identity := dohalm_training_v1.canonical_training_claim_identity(
        'run_request_fingerprint', requested_run_id, requested_request_fingerprint,
        requested_orchestration_correlation_id
    );

    IF EXISTS (
        SELECT 1
        FROM dohalm_training_v1.training_execution_journal AS inconsistent_journal
        WHERE (
            inconsistent_journal.run_id = requested_run_id
            OR inconsistent_journal.orchestration_correlation_id = requested_orchestration_correlation_id
            OR (
                inconsistent_journal.run_id = requested_run_id
                AND inconsistent_journal.request_fingerprint = requested_request_fingerprint
            )
        ) AND NOT EXISTS (
            SELECT 1
            FROM dohalm_training_v1.training_execution_claim_reservation AS owned_reservation
            WHERE owned_reservation.reservation_group_id = inconsistent_journal.reservation_group_id
            GROUP BY owned_reservation.reservation_group_id
            HAVING count(*) = 3
        )
    ) THEN
        RAISE EXCEPTION USING ERRCODE = 'XX001', MESSAGE = 'journal reservation integrity failure';
    END IF;

    BEGIN
        INSERT INTO dohalm_training_v1.training_execution_claim_reservation AS inserted_reservation (
            identity_kind, identity_value, reservation_group_id, owner_run_id,
            owner_request_fingerprint, owner_orchestration_correlation_id
        )
        SELECT requested_identity.identity_kind, requested_identity.identity_value,
               requested_reservation_group_id, requested_run_id,
               requested_request_fingerprint, requested_orchestration_correlation_id
        FROM (VALUES
            ('orchestration_correlation_id'::text, requested_orchestration_correlation_id),
            ('run_id'::text, requested_run_id),
            ('run_request_fingerprint'::text, requested_run_request_identity)
        ) AS requested_identity(identity_kind, identity_value)
        ORDER BY requested_identity.identity_kind;
    EXCEPTION WHEN unique_violation THEN
        reservation_collision := true;
    END;

    IF NOT reservation_collision THEN
        IF EXISTS (
            SELECT 1 FROM dohalm_training_v1.training_execution_journal AS unexpected_journal
            WHERE unexpected_journal.run_id = requested_run_id
               OR unexpected_journal.orchestration_correlation_id = requested_orchestration_correlation_id
               OR (
                   unexpected_journal.run_id = requested_run_id
                   AND unexpected_journal.request_fingerprint = requested_request_fingerprint
               )
        ) THEN
            RAISE EXCEPTION USING ERRCODE = 'XX001', MESSAGE = 'journal reservation integrity failure';
        END IF;
        INSERT INTO dohalm_training_v1.training_execution_journal AS inserted_journal (
            run_id, request_fingerprint, intent_fingerprint, orchestration_correlation_id,
            dataset_version_id, dataset_manifest_id, dataset_pair_fingerprint,
            config_fingerprint, readiness_fingerprint, source_commit,
            prerequisite_resolution_policy_reference, process_boundary_id,
            reservation_group_id
        ) VALUES (
            requested_run_id, requested_request_fingerprint, requested_intent_fingerprint,
            requested_orchestration_correlation_id, requested_dataset_version_id,
            requested_dataset_manifest_id, requested_dataset_pair_fingerprint,
            requested_config_fingerprint, requested_readiness_fingerprint,
            requested_source_commit, requested_prerequisite_policy_reference,
            requested_process_boundary_id, requested_reservation_group_id
        ) RETURNING inserted_journal.* INTO resolved_journal;
        INSERT INTO dohalm_training_v1.training_execution_phase_event AS inserted_event (
            event_id, run_id, request_fingerprint, journal_version, from_phase,
            to_phase, process_boundary_id, reason_code
        ) VALUES (new_phase_event_id, requested_run_id, requested_request_fingerprint, 1, NULL,
                  'claimed', requested_process_boundary_id, NULL);
        claim_status := 'acquired';
    ELSE
        SELECT count(*),
               count(*) FILTER (
                   WHERE existing_reservation.owner_run_id = requested_run_id
                     AND existing_reservation.owner_request_fingerprint = requested_request_fingerprint
                     AND existing_reservation.owner_orchestration_correlation_id = requested_orchestration_correlation_id
               ),
               count(DISTINCT existing_reservation.reservation_group_id),
               min(existing_reservation.reservation_group_id::text)::uuid
        INTO matching_reservation_count, exact_owner_count,
             reservation_group_count, existing_reservation_group_id
        FROM dohalm_training_v1.training_execution_claim_reservation AS existing_reservation
        JOIN (VALUES
            ('orchestration_correlation_id'::text, requested_orchestration_correlation_id),
            ('run_id'::text, requested_run_id),
            ('run_request_fingerprint'::text, requested_run_request_identity)
        ) AS requested_identity(identity_kind, identity_value)
          ON existing_reservation.identity_kind = requested_identity.identity_kind
         AND existing_reservation.identity_value = requested_identity.identity_value;

        IF reservation_group_count > 1 THEN
            RAISE EXCEPTION USING ERRCODE = 'XX001', MESSAGE = 'journal reservation split ownership';
        END IF;
        IF exact_owner_count <> matching_reservation_count THEN
            RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'journal claim conflict';
        END IF;
        IF matching_reservation_count <> 3 OR reservation_group_count <> 1 THEN
            RAISE EXCEPTION USING ERRCODE = 'XX001', MESSAGE = 'journal reservation integrity failure';
        END IF;
        SELECT existing_journal.* INTO resolved_journal
        FROM dohalm_training_v1.training_execution_journal AS existing_journal
        WHERE existing_journal.reservation_group_id = existing_reservation_group_id;
        IF NOT FOUND
           OR resolved_journal.run_id <> requested_run_id
           OR resolved_journal.request_fingerprint <> requested_request_fingerprint
           OR resolved_journal.orchestration_correlation_id <> requested_orchestration_correlation_id THEN
            RAISE EXCEPTION USING ERRCODE = 'XX001', MESSAGE = 'journal reservation integrity failure';
        END IF;
        IF resolved_journal.run_id <> requested_run_id
           OR resolved_journal.request_fingerprint <> requested_request_fingerprint
           OR resolved_journal.intent_fingerprint <> requested_intent_fingerprint
           OR resolved_journal.orchestration_correlation_id <> requested_orchestration_correlation_id
           OR resolved_journal.dataset_version_id <> requested_dataset_version_id
           OR resolved_journal.dataset_manifest_id <> requested_dataset_manifest_id
           OR resolved_journal.dataset_pair_fingerprint <> requested_dataset_pair_fingerprint
           OR resolved_journal.config_fingerprint <> requested_config_fingerprint
           OR resolved_journal.readiness_fingerprint <> requested_readiness_fingerprint
           OR resolved_journal.source_commit <> requested_source_commit
           OR resolved_journal.prerequisite_resolution_policy_reference <> requested_prerequisite_policy_reference
           OR resolved_journal.phase NOT IN ('completed', 'failed') THEN
            RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'journal claim conflict';
        END IF;
        claim_status := 'replay';
    END IF;
    claimed_run_id := resolved_journal.run_id;
    claimed_request_fingerprint := resolved_journal.request_fingerprint;
    claimed_phase := resolved_journal.phase;
    claimed_journal_version := resolved_journal.journal_version;
    claimed_backend_entered := resolved_journal.backend_entered;
    claimed_reconciliation_required := resolved_journal.reconciliation_required;
    claimed_reconciliation_reason_code := resolved_journal.reconciliation_reason_code;
    RETURN NEXT;
END
$$;

CREATE FUNCTION dohalm_training_v1.transition_training_execution_journal(
    requested_run_id varchar(256), requested_request_fingerprint char(71),
    requested_expected_phase text, requested_expected_journal_version bigint, requested_next_phase text,
    requested_process_boundary_id varchar(256), requested_reason_code varchar(128) DEFAULT NULL,
    requested_authorization_id varchar(256) DEFAULT NULL, requested_issuer_id varchar(256) DEFAULT NULL,
    requested_approver_reference varchar(256) DEFAULT NULL, requested_evidence_reference varchar(256) DEFAULT NULL,
    requested_authorization_fingerprint char(71) DEFAULT NULL,
    requested_decision_evidence_fingerprint char(71) DEFAULT NULL,
    requested_decision_policy_reference varchar(256) DEFAULT NULL
)
RETURNS TABLE (transitioned_run_id varchar(256), transitioned_request_fingerprint char(71), transitioned_phase text,
               transitioned_journal_version bigint, transitioned_backend_entered boolean,
               transitioned_reconciliation_required boolean, transitioned_reconciliation_reason_code varchar(128))
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    current_row dohalm_training_v1.training_execution_journal%ROWTYPE;
    next_row dohalm_training_v1.training_execution_journal%ROWTYPE;
    decision_bundle_supplied boolean;
    legal boolean;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed'
       OR current_setting('transaction_read_only') <> 'off' THEN
        RAISE EXCEPTION USING ERRCODE = '25006', MESSAGE = 'read committed journal transaction required';
    END IF;
    SELECT current_journal.* INTO current_row
    FROM dohalm_training_v1.training_execution_journal AS current_journal
    WHERE current_journal.run_id = requested_run_id
      AND current_journal.request_fingerprint = requested_request_fingerprint;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'journal transition conflict';
    END IF;
    legal := requested_next_phase IN ('failed', 'manual_reconciliation_required')
        OR (requested_expected_phase = 'claimed' AND requested_next_phase = 'resolved')
        OR (requested_expected_phase = 'resolved' AND requested_next_phase = 'validated')
        OR (requested_expected_phase = 'validated' AND requested_next_phase = 'decision_submitted')
        OR (requested_expected_phase = 'decision_submitted' AND requested_next_phase = 'approval_consumed')
        OR (requested_expected_phase = 'approval_consumed' AND requested_next_phase = 'backend_entered')
        OR (requested_expected_phase = 'backend_entered' AND requested_next_phase = 'completed');
    IF NOT legal OR current_row.phase IN ('completed', 'failed', 'manual_reconciliation_required')
       OR (requested_next_phase NOT IN ('manual_reconciliation_required')
           AND current_row.process_boundary_id <> requested_process_boundary_id)
       OR ((requested_next_phase IN ('failed', 'manual_reconciliation_required')) <> (requested_reason_code IS NOT NULL)) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'journal transition invalid';
    END IF;
    decision_bundle_supplied := requested_authorization_id IS NOT NULL
        AND requested_issuer_id IS NOT NULL AND requested_approver_reference IS NOT NULL
        AND requested_evidence_reference IS NOT NULL AND requested_authorization_fingerprint IS NOT NULL
        AND requested_decision_evidence_fingerprint IS NOT NULL AND requested_decision_policy_reference IS NOT NULL;
    IF (requested_next_phase = 'decision_submitted') <> decision_bundle_supplied THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'journal decision bundle invalid';
    END IF;

    UPDATE dohalm_training_v1.training_execution_journal AS target SET
        authorization_id = CASE WHEN requested_next_phase = 'decision_submitted' THEN requested_authorization_id ELSE target.authorization_id END,
        issuer_id = CASE WHEN requested_next_phase = 'decision_submitted' THEN requested_issuer_id ELSE target.issuer_id END,
        approver_reference = CASE WHEN requested_next_phase = 'decision_submitted' THEN requested_approver_reference ELSE target.approver_reference END,
        evidence_reference = CASE WHEN requested_next_phase = 'decision_submitted' THEN requested_evidence_reference ELSE target.evidence_reference END,
        authorization_fingerprint = CASE WHEN requested_next_phase = 'decision_submitted' THEN requested_authorization_fingerprint ELSE target.authorization_fingerprint END,
        decision_evidence_fingerprint = CASE WHEN requested_next_phase = 'decision_submitted' THEN requested_decision_evidence_fingerprint ELSE target.decision_evidence_fingerprint END,
        decision_policy_reference = CASE WHEN requested_next_phase = 'decision_submitted' THEN requested_decision_policy_reference ELSE target.decision_policy_reference END,
        phase = requested_next_phase,
        journal_version = target.journal_version + 1,
        backend_entered = target.backend_entered OR requested_next_phase IN ('backend_entered', 'completed'),
        reconciliation_required = requested_next_phase = 'manual_reconciliation_required',
        reconciliation_reason_code = CASE WHEN requested_next_phase = 'manual_reconciliation_required' THEN requested_reason_code ELSE NULL END,
        process_boundary_id = requested_process_boundary_id,
        updated_at = transaction_timestamp()
    WHERE target.run_id = requested_run_id
      AND target.request_fingerprint = requested_request_fingerprint
      AND target.phase = requested_expected_phase
      AND target.journal_version = requested_expected_journal_version
    RETURNING target.* INTO next_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'journal transition conflict';
    END IF;
    INSERT INTO dohalm_training_v1.training_execution_phase_event AS inserted_event (
        event_id, run_id, request_fingerprint, journal_version, from_phase,
        to_phase, process_boundary_id, reason_code
    ) VALUES (
        gen_random_uuid(), requested_run_id, requested_request_fingerprint,
        requested_expected_journal_version + 1, requested_expected_phase, requested_next_phase,
        requested_process_boundary_id, requested_reason_code
    );
    transitioned_run_id := next_row.run_id;
    transitioned_request_fingerprint := next_row.request_fingerprint;
    transitioned_phase := next_row.phase;
    transitioned_journal_version := next_row.journal_version;
    transitioned_backend_entered := next_row.backend_entered;
    transitioned_reconciliation_required := next_row.reconciliation_required;
    transitioned_reconciliation_reason_code := next_row.reconciliation_reason_code;
    RETURN NEXT;
END
$$;

CREATE FUNCTION dohalm_training_v1.read_training_execution_journal(requested_run_id varchar(256))
RETURNS TABLE (journal_run_id varchar(256), journal_request_fingerprint char(71), journal_phase text,
               journal_record_version bigint, journal_backend_entered boolean, journal_reconciliation_required boolean,
               journal_reconciliation_reason_code varchar(128))
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT journal.run_id, journal.request_fingerprint, journal.phase,
           journal.journal_version, journal.backend_entered,
           journal.reconciliation_required, journal.reconciliation_reason_code
    FROM dohalm_training_v1.training_execution_journal journal
    WHERE journal.run_id = requested_run_id
$$;

ALTER FUNCTION dohalm_training_v1.write_training_authority_event(uuid, uuid, text, bigint, text, uuid, timestamptz, varchar, varchar) OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.read_training_authority_snapshot(uuid[]) OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.canonical_training_claim_identity(text, varchar, char, varchar) OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.claim_training_execution_journal(varchar, char, char, varchar, varchar, varchar, char, char, char, char, varchar, varchar) OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.transition_training_execution_journal(varchar, char, text, bigint, text, varchar, varchar, varchar, varchar, varchar, varchar, char, char, varchar) OWNER TO dohalm_training_owner;
ALTER FUNCTION dohalm_training_v1.read_training_execution_journal(varchar) OWNER TO dohalm_training_owner;
ALTER TABLE dohalm_training_v1.training_execution_claim_reservation OWNER TO dohalm_training_owner;

REVOKE ALL ON ALL TABLES IN SCHEMA dohalm_training_v1 FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA dohalm_training_v1 FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA dohalm_training_v1 FROM dohalm_training_authority_producer, dohalm_training_resolver, dohalm_training_journal;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA dohalm_training_v1 FROM dohalm_training_authority_producer, dohalm_training_resolver, dohalm_training_journal;
GRANT USAGE ON SCHEMA dohalm_training_v1 TO dohalm_training_authority_producer, dohalm_training_resolver, dohalm_training_journal;
GRANT INSERT ON dohalm_training_v1.training_authority_identity,
    dohalm_training_v1.training_config_authority,
    dohalm_training_v1.training_readiness_authority,
    dohalm_training_v1.dataset_version_authority,
    dohalm_training_v1.dataset_manifest_authority,
    dohalm_training_v1.dataset_pair_authority,
    dohalm_training_v1.training_execution_decision_authority,
    dohalm_training_v1.training_issuer_registry,
    dohalm_training_v1.training_approver_registry
TO dohalm_training_authority_producer;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.write_training_authority_event(uuid, uuid, text, bigint, text, uuid, timestamptz, varchar, varchar) TO dohalm_training_authority_producer;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.read_training_authority_snapshot(uuid[]) TO dohalm_training_resolver;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.claim_training_execution_journal(varchar, char, char, varchar, varchar, varchar, char, char, char, char, varchar, varchar) TO dohalm_training_journal;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.transition_training_execution_journal(varchar, char, text, bigint, text, varchar, varchar, varchar, varchar, varchar, varchar, char, char, varchar) TO dohalm_training_journal;
GRANT EXECUTE ON FUNCTION dohalm_training_v1.read_training_execution_journal(varchar) TO dohalm_training_journal;
