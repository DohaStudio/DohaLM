CREATE OR REPLACE FUNCTION dohalm_training_v1.read_c2_training_prerequisite_snapshot(
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
     AND pair_current.state = 'current'
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

ALTER FUNCTION dohalm_training_v1.read_c2_training_prerequisite_snapshot(uuid, uuid, uuid, uuid, char, char, char)
OWNER TO dohalm_training_owner;

REVOKE ALL ON FUNCTION dohalm_training_v1.read_c2_training_prerequisite_snapshot(uuid, uuid, uuid, uuid, char, char, char)
FROM PUBLIC, dohalm_training_runtime, dohalm_training_authority_producer,
     dohalm_training_journal, dohalm_training_intent_writer;

GRANT EXECUTE ON FUNCTION dohalm_training_v1.read_c2_training_prerequisite_snapshot(uuid, uuid, uuid, uuid, char, char, char)
TO dohalm_training_resolver;
