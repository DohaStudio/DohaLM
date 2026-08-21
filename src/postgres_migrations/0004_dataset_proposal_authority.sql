DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dohalm_dataset_proposal_owner') THEN
        CREATE ROLE dohalm_dataset_proposal_owner NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dohalm_dataset_proposal_authority') THEN
        CREATE ROLE dohalm_dataset_proposal_authority LOGIN NOINHERIT;
    END IF;
END
$$;

ALTER ROLE dohalm_dataset_proposal_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE dohalm_dataset_proposal_authority LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

CREATE SCHEMA dohalm_dataset_governance_v1 AUTHORIZATION dohalm_dataset_proposal_owner;
REVOKE ALL ON SCHEMA dohalm_dataset_governance_v1 FROM PUBLIC;

CREATE TABLE dohalm_dataset_governance_v1.dataset_version_proposal_authority (
    object_id varchar(256) NOT NULL CHECK (char_length(object_id) BETWEEN 1 AND 256),
    dataset_id varchar(256) NOT NULL CHECK (char_length(dataset_id) BETWEEN 1 AND 256),
    dataset_version varchar(256) NOT NULL CHECK (char_length(dataset_version) BETWEEN 1 AND 256),
    proposal_fingerprint char(71) NOT NULL CHECK (
        proposal_fingerprint ~ '^sha256:[0-9a-f]{64}$'
    ),
    canonical_payload bytea NOT NULL CHECK (
        octet_length(canonical_payload) BETWEEN 2 AND 16777216
    ),
    authority_reference varchar(256) NOT NULL UNIQUE CHECK (
        authority_reference ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$'
    ),
    authority_version smallint NOT NULL DEFAULT 1 CHECK (authority_version = 1),
    schema_revision smallint NOT NULL DEFAULT 1 CHECK (schema_revision = 1),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    PRIMARY KEY (object_id, dataset_id, dataset_version)
);

CREATE FUNCTION dohalm_dataset_governance_v1.reject_proposal_authority_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'dataset proposal authority is immutable';
END
$$;

CREATE TRIGGER dataset_version_proposal_authority_immutable
BEFORE UPDATE OR DELETE ON dohalm_dataset_governance_v1.dataset_version_proposal_authority
FOR EACH ROW EXECUTE FUNCTION dohalm_dataset_governance_v1.reject_proposal_authority_mutation();

CREATE FUNCTION dohalm_dataset_governance_v1.lock_dataset_version_proposal_identity(
    requested_object_id varchar(256),
    requested_dataset_id varchar(256),
    requested_dataset_version varchar(256)
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    IF requested_object_id IS NULL OR char_length(requested_object_id) NOT BETWEEN 1 AND 256
       OR requested_dataset_id IS NULL OR char_length(requested_dataset_id) NOT BETWEEN 1 AND 256
       OR requested_dataset_version IS NULL OR char_length(requested_dataset_version) NOT BETWEEN 1 AND 256 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'dataset proposal identity invalid';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        jsonb_build_array(requested_object_id, requested_dataset_id, requested_dataset_version)::text,
        4922229310947483724
    ));
END
$$;

CREATE FUNCTION dohalm_dataset_governance_v1.compare_and_create_dataset_version_proposal(
    requested_object_id varchar(256),
    requested_dataset_id varchar(256),
    requested_dataset_version varchar(256),
    requested_proposal_fingerprint char(71),
    requested_canonical_payload bytea
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
    created_at timestamptz
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
       OR octet_length(requested_canonical_payload) NOT BETWEEN 2 AND 16777216 THEN
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
       OR decoded_payload->>'status' IS DISTINCT FROM 'draft' THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'dataset proposal identity invalid';
    END IF;

    computed_authority_reference := 'dataset-proposal:' || encode(sha256(convert_to(
        jsonb_build_array(requested_object_id, requested_dataset_id, requested_dataset_version)::text,
        'UTF8'
    )), 'hex');

    INSERT INTO dohalm_dataset_governance_v1.dataset_version_proposal_authority AS proposal_record (
        object_id, dataset_id, dataset_version, proposal_fingerprint,
        canonical_payload, authority_reference
    ) VALUES (
        requested_object_id, requested_dataset_id, requested_dataset_version,
        requested_proposal_fingerprint, requested_canonical_payload,
        computed_authority_reference
    )
    ON CONFLICT ON CONSTRAINT dataset_version_proposal_authority_pkey DO NOTHING
    RETURNING proposal_record.* INTO stored;
    inserted := FOUND;

    IF NOT inserted THEN
        RETURN;
    END IF;

    IF 'sha256:' || encode(sha256(stored.canonical_payload), 'hex')
       <> rtrim(stored.proposal_fingerprint)
       OR stored.authority_reference <> computed_authority_reference THEN
        RAISE EXCEPTION USING ERRCODE = 'XX001', MESSAGE = 'dataset proposal authority integrity failure';
    END IF;

    RETURN QUERY SELECT
        'CREATED',
        stored.object_id,
        stored.dataset_id,
        stored.dataset_version,
        stored.proposal_fingerprint,
        stored.canonical_payload,
        stored.authority_reference,
        stored.authority_version,
        stored.created_at;
END
$$;

CREATE FUNCTION dohalm_dataset_governance_v1.read_dataset_version_proposal(
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
    created_at timestamptz
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
       OR stored.authority_reference <> computed_authority_reference THEN
        RAISE EXCEPTION USING ERRCODE = 'XX001', MESSAGE = 'dataset proposal authority integrity failure';
    END IF;
    RETURN QUERY SELECT
        stored.object_id,
        stored.dataset_id,
        stored.dataset_version,
        stored.proposal_fingerprint,
        stored.canonical_payload,
        stored.authority_reference,
        stored.authority_version,
        stored.created_at;
END
$$;

ALTER TABLE dohalm_dataset_governance_v1.dataset_version_proposal_authority
    OWNER TO dohalm_dataset_proposal_owner;
ALTER FUNCTION dohalm_dataset_governance_v1.reject_proposal_authority_mutation()
    OWNER TO dohalm_dataset_proposal_owner;
ALTER FUNCTION dohalm_dataset_governance_v1.lock_dataset_version_proposal_identity(varchar, varchar, varchar)
    OWNER TO dohalm_dataset_proposal_owner;
ALTER FUNCTION dohalm_dataset_governance_v1.compare_and_create_dataset_version_proposal(varchar, varchar, varchar, char, bytea)
    OWNER TO dohalm_dataset_proposal_owner;
ALTER FUNCTION dohalm_dataset_governance_v1.read_dataset_version_proposal(varchar, varchar, varchar)
    OWNER TO dohalm_dataset_proposal_owner;

REVOKE ALL ON ALL TABLES IN SCHEMA dohalm_dataset_governance_v1 FROM PUBLIC, dohalm_dataset_proposal_authority;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA dohalm_dataset_governance_v1 FROM PUBLIC, dohalm_dataset_proposal_authority;
GRANT USAGE ON SCHEMA dohalm_dataset_governance_v1 TO dohalm_dataset_proposal_authority;
GRANT EXECUTE ON FUNCTION dohalm_dataset_governance_v1.compare_and_create_dataset_version_proposal(varchar, varchar, varchar, char, bytea)
    TO dohalm_dataset_proposal_authority;
GRANT EXECUTE ON FUNCTION dohalm_dataset_governance_v1.lock_dataset_version_proposal_identity(varchar, varchar, varchar)
    TO dohalm_dataset_proposal_authority;
GRANT EXECUTE ON FUNCTION dohalm_dataset_governance_v1.read_dataset_version_proposal(varchar, varchar, varchar)
    TO dohalm_dataset_proposal_authority;
