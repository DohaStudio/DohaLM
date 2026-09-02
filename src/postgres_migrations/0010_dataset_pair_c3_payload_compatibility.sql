SET search_path = pg_catalog, pg_temp;

ALTER TABLE dohalm_training_v1.dataset_pair_authority
DROP CONSTRAINT dataset_pair_authority_schema_version_check;

ALTER TABLE dohalm_training_v1.dataset_pair_authority
ADD CONSTRAINT dataset_pair_authority_schema_version_check
CHECK (schema_version IN (1, 2));

CREATE FUNCTION dohalm_training_v1.replace_training_dataset_pair(
    requested_previous_pair_authority_id uuid,
    requested_expected_previous_projection_version bigint,
    requested_version_authority_id uuid,
    requested_manifest_authority_id uuid,
    requested_pair_authority_id uuid,
    requested_pair_domain_key varchar(256),
    requested_version_payload bytea,
    requested_manifest_payload bytea,
    requested_pair_payload bytea,
    requested_dataset_version_id varchar(256),
    requested_dataset_manifest_id varchar(256),
    requested_pair_fingerprint char(71),
    requested_source_commit char(40),
    requested_publication_scenario text,
    requested_valid_until timestamptz,
    requested_pair_event_id uuid,
    requested_supersede_event_id uuid,
    requested_correlation_reference varchar(256),
    requested_evidence_reference varchar(256),
    requested_pair_payload_sha256 char(71)
)
RETURNS TABLE (
    version_authority_id uuid,
    version_domain_key varchar(256),
    version_payload_sha256 char(71),
    version_authority_state text,
    version_projection_version bigint,
    manifest_authority_id uuid,
    manifest_domain_key varchar(256),
    manifest_payload_sha256 char(71),
    manifest_authority_state text,
    manifest_projection_version bigint,
    pair_authority_id uuid,
    pair_domain_key varchar(256),
    pair_payload_sha256 char(71),
    pair_authority_state text,
    pair_projection_version bigint,
    previous_pair_authority_id uuid,
    previous_pair_state text,
    previous_pair_projection_version bigint,
    pair_fingerprint char(71),
    pair_schema_version smallint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    existing_pair_id uuid;
    previous_projection dohalm_training_v1.training_authority_current%ROWTYPE;
    pair_projection dohalm_training_v1.training_authority_current%ROWTYPE;
    pair_sha char(71) := 'sha256:' || encode(sha256(requested_pair_payload), 'hex');
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed'
       OR current_setting('transaction_read_only') <> 'off' THEN
        RAISE EXCEPTION USING ERRCODE = '25006', MESSAGE = 'read committed producer transaction required';
    END IF;
    IF requested_pair_payload_sha256 <> pair_sha
       OR requested_previous_pair_authority_id = requested_pair_authority_id
       OR requested_expected_previous_projection_version < 1
       OR requested_publication_scenario <> 'internal-production-training-c3-compatible'
       OR requested_pair_domain_key = ''
       OR requested_correlation_reference = ''
       OR requested_evidence_reference = '' THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'Dataset pair replacement input invalid';
    END IF;

    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
        'dataset-pair-replacement' || chr(31) || requested_previous_pair_authority_id::text ||
        chr(31) || requested_pair_domain_key, 0));

    PERFORM 1
    FROM dohalm_training_v1.dataset_version_authority version_row
    JOIN dohalm_training_v1.training_authority_current version_state
      ON version_state.authority_id = version_row.authority_id
    WHERE version_row.authority_id = requested_version_authority_id
      AND version_row.payload_bytes = requested_version_payload
      AND version_row.common_object_id = requested_dataset_version_id
      AND version_state.state = 'current';
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = '23503', MESSAGE = 'current DatasetVersion authority unavailable';
    END IF;

    PERFORM 1
    FROM dohalm_training_v1.dataset_manifest_authority manifest_row
    JOIN dohalm_training_v1.training_authority_current manifest_state
      ON manifest_state.authority_id = manifest_row.authority_id
    WHERE manifest_row.authority_id = requested_manifest_authority_id
      AND manifest_row.payload_bytes = requested_manifest_payload
      AND manifest_row.common_object_id = requested_dataset_manifest_id
      AND manifest_state.state = 'current';
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = '23503', MESSAGE = 'current DatasetManifest authority unavailable';
    END IF;

    SELECT state.* INTO previous_projection
    FROM dohalm_training_v1.dataset_pair_authority pair_row
    JOIN dohalm_training_v1.training_authority_current state
      ON state.authority_id = pair_row.authority_id
    WHERE pair_row.authority_id = requested_previous_pair_authority_id
      AND pair_row.dataset_version_authority_id = requested_version_authority_id
      AND pair_row.dataset_manifest_authority_id = requested_manifest_authority_id
      AND pair_row.pair_fingerprint = requested_pair_fingerprint
    FOR UPDATE OF state;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = '23503', MESSAGE = 'legacy Dataset pair authority unavailable';
    END IF;

    SELECT identity.authority_id INTO existing_pair_id
    FROM dohalm_training_v1.training_authority_identity identity
    WHERE identity.subject_family = 'dataset_pair'
      AND identity.domain_key = requested_pair_domain_key;

    IF existing_pair_id IS NULL THEN
        IF previous_projection.state <> 'current'
           OR previous_projection.projection_version <> requested_expected_previous_projection_version THEN
            RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'legacy Dataset pair stream conflict';
        END IF;
        INSERT INTO dohalm_training_v1.training_authority_identity(
            authority_id, subject_family, domain_key
        ) VALUES (
            requested_pair_authority_id, 'dataset_pair', requested_pair_domain_key
        );
        INSERT INTO dohalm_training_v1.dataset_pair_authority(
            authority_id, schema_version, payload_bytes, payload_sha256,
            valid_from, valid_until, source_commit, dataset_version_authority_id,
            dataset_manifest_authority_id, pair_fingerprint, publication_scenario
        ) VALUES (
            requested_pair_authority_id, 2, requested_pair_payload, pair_sha,
            transaction_timestamp(), requested_valid_until, requested_source_commit,
            requested_version_authority_id, requested_manifest_authority_id,
            requested_pair_fingerprint, requested_publication_scenario
        );
        PERFORM dohalm_training_v1.write_training_authority_event(
            requested_pair_event_id, requested_pair_authority_id, 'dataset_pair', 0,
            'published', NULL, transaction_timestamp(),
            requested_correlation_reference, requested_evidence_reference
        );
        PERFORM dohalm_training_v1.write_training_authority_event(
            requested_supersede_event_id, requested_previous_pair_authority_id,
            'dataset_pair', requested_expected_previous_projection_version,
            'superseded', requested_pair_authority_id, transaction_timestamp(),
            requested_correlation_reference, requested_evidence_reference
        );
        existing_pair_id := requested_pair_authority_id;
    ELSIF existing_pair_id <> requested_pair_authority_id
       OR NOT EXISTS (
            SELECT 1
            FROM dohalm_training_v1.dataset_pair_authority pair_row
            WHERE pair_row.authority_id = existing_pair_id
              AND pair_row.schema_version = 2
              AND pair_row.payload_bytes = requested_pair_payload
              AND pair_row.payload_sha256 = pair_sha
              AND pair_row.source_commit = requested_source_commit
              AND pair_row.dataset_version_authority_id = requested_version_authority_id
              AND pair_row.dataset_manifest_authority_id = requested_manifest_authority_id
              AND pair_row.pair_fingerprint = requested_pair_fingerprint
              AND pair_row.publication_scenario = requested_publication_scenario
              AND pair_row.valid_until IS NOT DISTINCT FROM requested_valid_until
       ) THEN
        RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'Dataset pair replacement conflict';
    END IF;

    SELECT state.* INTO previous_projection
    FROM dohalm_training_v1.training_authority_current state
    WHERE state.authority_id = requested_previous_pair_authority_id;
    SELECT state.* INTO pair_projection
    FROM dohalm_training_v1.training_authority_current state
    WHERE state.authority_id = existing_pair_id;
    IF previous_projection.state <> 'superseded'
       OR previous_projection.superseded_by_authority_id <> existing_pair_id
       OR pair_projection.state <> 'current' THEN
        RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'Dataset pair replacement projection conflict';
    END IF;

    RETURN QUERY SELECT
        version_identity.authority_id,
        version_identity.domain_key,
        version_row.payload_sha256,
        version_state.state,
        version_state.projection_version,
        manifest_identity.authority_id,
        manifest_identity.domain_key,
        manifest_row.payload_sha256,
        manifest_state.state,
        manifest_state.projection_version,
        pair_identity.authority_id,
        pair_identity.domain_key,
        pair_row.payload_sha256,
        pair_state.state,
        pair_state.projection_version,
        previous_projection.authority_id,
        previous_projection.state,
        previous_projection.projection_version,
        pair_row.pair_fingerprint,
        pair_row.schema_version
    FROM dohalm_training_v1.dataset_pair_authority pair_row
    JOIN dohalm_training_v1.training_authority_identity pair_identity
      ON pair_identity.authority_id = pair_row.authority_id
    JOIN dohalm_training_v1.training_authority_current pair_state
      ON pair_state.authority_id = pair_row.authority_id
    JOIN dohalm_training_v1.dataset_version_authority version_row
      ON version_row.authority_id = pair_row.dataset_version_authority_id
    JOIN dohalm_training_v1.training_authority_identity version_identity
      ON version_identity.authority_id = version_row.authority_id
    JOIN dohalm_training_v1.training_authority_current version_state
      ON version_state.authority_id = version_row.authority_id
    JOIN dohalm_training_v1.dataset_manifest_authority manifest_row
      ON manifest_row.authority_id = pair_row.dataset_manifest_authority_id
    JOIN dohalm_training_v1.training_authority_identity manifest_identity
      ON manifest_identity.authority_id = manifest_row.authority_id
    JOIN dohalm_training_v1.training_authority_current manifest_state
      ON manifest_state.authority_id = manifest_row.authority_id
    WHERE pair_row.authority_id = existing_pair_id;
END
$$;

ALTER FUNCTION dohalm_training_v1.replace_training_dataset_pair(
    uuid, bigint, uuid, uuid, uuid, varchar, bytea, bytea, bytea, varchar,
    varchar, char, char, text, timestamptz, uuid, uuid, varchar, varchar, char
) OWNER TO dohalm_training_owner;

REVOKE ALL ON FUNCTION dohalm_training_v1.replace_training_dataset_pair(
    uuid, bigint, uuid, uuid, uuid, varchar, bytea, bytea, bytea, varchar,
    varchar, char, char, text, timestamptz, uuid, uuid, varchar, varchar, char
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION dohalm_training_v1.replace_training_dataset_pair(
    uuid, bigint, uuid, uuid, uuid, varchar, bytea, bytea, bytea, varchar,
    varchar, char, char, text, timestamptz, uuid, uuid, varchar, varchar, char
) TO dohalm_training_authority_producer;
