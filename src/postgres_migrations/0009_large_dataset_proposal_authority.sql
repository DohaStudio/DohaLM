ALTER TABLE dohalm_dataset_governance_v1.dataset_version_proposal_authority
    ADD COLUMN proposal_schema_version smallint NOT NULL DEFAULT 1
    CHECK (proposal_schema_version IN (1, 2));

CREATE FUNCTION dohalm_dataset_governance_v1.compare_and_create_dataset_version_proposal_v2(
    requested_object_id varchar(256),
    requested_dataset_id varchar(256),
    requested_dataset_version varchar(256),
    requested_proposal_fingerprint char(71),
    requested_canonical_payload bytea,
    requested_proposal_schema_version smallint
)
RETURNS TABLE (
    outcome text,
    object_id varchar(256),
    dataset_id varchar(256),
    dataset_version varchar(256),
    proposal_fingerprint char(71),
    canonical_payload bytea,
    authority_reference varchar(256),
    authority_version smallint,
    created_at timestamptz,
    proposal_schema_version smallint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    stored dohalm_dataset_governance_v1.dataset_version_proposal_authority%ROWTYPE;
    inserted boolean := false;
    computed_fingerprint text;
    computed_authority_reference text;
    decoded_payload jsonb;
BEGIN
    IF requested_object_id IS NULL OR char_length(requested_object_id) NOT BETWEEN 1 AND 256
       OR requested_dataset_id IS NULL OR char_length(requested_dataset_id) NOT BETWEEN 1 AND 256
       OR requested_dataset_version IS NULL OR char_length(requested_dataset_version) NOT BETWEEN 1 AND 256
       OR requested_proposal_fingerprint !~ '^sha256:[0-9a-f]{64}$'
       OR requested_canonical_payload IS NULL
       OR octet_length(requested_canonical_payload) NOT BETWEEN 2 AND 16777216
       OR requested_proposal_schema_version NOT IN (1, 2) THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'dataset proposal input invalid';
    END IF;

    computed_fingerprint := 'sha256:' || encode(sha256(requested_canonical_payload), 'hex');
    IF computed_fingerprint <> rtrim(requested_proposal_fingerprint) THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'dataset proposal fingerprint invalid';
    END IF;
    BEGIN
        decoded_payload := convert_from(requested_canonical_payload, 'UTF8')::jsonb;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'dataset proposal payload invalid';
    END;
    IF jsonb_typeof(decoded_payload) <> 'object'
       OR decoded_payload->>'object_id' IS DISTINCT FROM requested_object_id
       OR decoded_payload->>'dataset_id' IS DISTINCT FROM requested_dataset_id
       OR decoded_payload->>'dataset_version' IS DISTINCT FROM requested_dataset_version
       OR decoded_payload->>'status' IS DISTINCT FROM 'draft'
       OR (requested_proposal_schema_version = 1 AND decoded_payload->>'schema_name' IS DISTINCT FROM 'dataset_version')
       OR (requested_proposal_schema_version = 2 AND (
            decoded_payload->>'schema_name' IS DISTINCT FROM 'dataset_version_proposal_root'
            OR decoded_payload->>'schema_version' IS DISTINCT FROM '2.0.0'
            OR jsonb_typeof(decoded_payload->'composition') IS DISTINCT FROM 'object'
            OR jsonb_typeof(decoded_payload->'member_manifest') IS DISTINCT FROM 'object'
            OR jsonb_typeof(decoded_payload->'dataset_manifest') IS DISTINCT FROM 'object'
            OR jsonb_typeof(decoded_payload->'allocation_manifest') IS DISTINCT FROM 'object'
       )) THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'dataset proposal identity invalid';
    END IF;

    computed_authority_reference := 'dataset-proposal:' || encode(sha256(convert_to(
        jsonb_build_array(requested_object_id, requested_dataset_id, requested_dataset_version)::text,
        'UTF8'
    )), 'hex');

    INSERT INTO dohalm_dataset_governance_v1.dataset_version_proposal_authority AS proposal_record (
        object_id, dataset_id, dataset_version, proposal_fingerprint,
        canonical_payload, authority_reference, proposal_schema_version
    ) VALUES (
        requested_object_id, requested_dataset_id, requested_dataset_version,
        requested_proposal_fingerprint, requested_canonical_payload,
        computed_authority_reference, requested_proposal_schema_version
    )
    ON CONFLICT ON CONSTRAINT dataset_version_proposal_authority_pkey DO NOTHING
    RETURNING proposal_record.* INTO stored;
    inserted := FOUND;

    IF NOT inserted THEN
        RETURN;
    END IF;
    IF 'sha256:' || encode(sha256(stored.canonical_payload), 'hex')
       <> rtrim(stored.proposal_fingerprint)
       OR stored.authority_reference <> computed_authority_reference
       OR stored.proposal_schema_version <> requested_proposal_schema_version THEN
        RAISE EXCEPTION USING ERRCODE = 'XX001', MESSAGE = 'dataset proposal authority integrity failure';
    END IF;

    RETURN QUERY SELECT
        'CREATED', stored.object_id, stored.dataset_id, stored.dataset_version,
        stored.proposal_fingerprint, stored.canonical_payload,
        stored.authority_reference, stored.authority_version, stored.created_at,
        stored.proposal_schema_version;
END
$$;

CREATE FUNCTION dohalm_dataset_governance_v1.read_dataset_version_proposal_v2(
    requested_object_id varchar(256),
    requested_dataset_id varchar(256),
    requested_dataset_version varchar(256)
)
RETURNS TABLE (
    object_id varchar(256),
    dataset_id varchar(256),
    dataset_version varchar(256),
    proposal_fingerprint char(71),
    canonical_payload bytea,
    authority_reference varchar(256),
    authority_version smallint,
    created_at timestamptz,
    proposal_schema_version smallint
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    stored dohalm_dataset_governance_v1.dataset_version_proposal_authority%ROWTYPE;
    computed_authority_reference text;
BEGIN
    computed_authority_reference := 'dataset-proposal:' || encode(sha256(convert_to(
        jsonb_build_array(requested_object_id, requested_dataset_id, requested_dataset_version)::text,
        'UTF8'
    )), 'hex');
    SELECT proposal_record.* INTO stored
    FROM dohalm_dataset_governance_v1.dataset_version_proposal_authority AS proposal_record
    WHERE proposal_record.object_id = requested_object_id
      AND proposal_record.dataset_id = requested_dataset_id
      AND proposal_record.dataset_version = requested_dataset_version;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    IF 'sha256:' || encode(sha256(stored.canonical_payload), 'hex')
       <> rtrim(stored.proposal_fingerprint)
       OR stored.authority_reference <> computed_authority_reference
       OR stored.proposal_schema_version NOT IN (1, 2) THEN
        RAISE EXCEPTION USING ERRCODE = 'XX001', MESSAGE = 'dataset proposal authority integrity failure';
    END IF;
    RETURN QUERY SELECT
        stored.object_id, stored.dataset_id, stored.dataset_version,
        stored.proposal_fingerprint, stored.canonical_payload,
        stored.authority_reference, stored.authority_version, stored.created_at,
        stored.proposal_schema_version;
END
$$;

ALTER FUNCTION dohalm_dataset_governance_v1.compare_and_create_dataset_version_proposal_v2(varchar, varchar, varchar, char, bytea, smallint)
    OWNER TO dohalm_dataset_proposal_owner;
ALTER FUNCTION dohalm_dataset_governance_v1.read_dataset_version_proposal_v2(varchar, varchar, varchar)
    OWNER TO dohalm_dataset_proposal_owner;

REVOKE ALL ON FUNCTION dohalm_dataset_governance_v1.compare_and_create_dataset_version_proposal_v2(varchar, varchar, varchar, char, bytea, smallint)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION dohalm_dataset_governance_v1.read_dataset_version_proposal_v2(varchar, varchar, varchar)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION dohalm_dataset_governance_v1.compare_and_create_dataset_version_proposal_v2(varchar, varchar, varchar, char, bytea, smallint)
    TO dohalm_dataset_proposal_authority;
GRANT EXECUTE ON FUNCTION dohalm_dataset_governance_v1.read_dataset_version_proposal_v2(varchar, varchar, varchar)
    TO dohalm_dataset_proposal_authority;
