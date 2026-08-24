DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dohalm_dataset_review_owner') THEN
        CREATE ROLE dohalm_dataset_review_owner NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dohalm_dataset_review_authority') THEN
        CREATE ROLE dohalm_dataset_review_authority LOGIN NOINHERIT;
    END IF;
END
$$;

ALTER ROLE dohalm_dataset_review_owner
    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE dohalm_dataset_review_authority
    LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

CREATE UNIQUE INDEX dataset_version_proposal_authority_identity_fingerprint_uq
ON dohalm_dataset_governance_v1.dataset_version_proposal_authority
    (object_id, dataset_id, dataset_version, proposal_fingerprint);

CREATE TABLE dohalm_dataset_governance_v1.dataset_version_review_authority (
    object_id varchar(256) NOT NULL CHECK (
        object_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$'
    ),
    dataset_id varchar(256) NOT NULL CHECK (
        dataset_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$'
    ),
    dataset_version varchar(256) NOT NULL CHECK (
        dataset_version ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$'
    ),
    proposal_fingerprint char(71) NOT NULL CHECK (
        proposal_fingerprint ~ '^sha256:[0-9a-f]{64}$'
    ),
    lifecycle_state varchar(16) NOT NULL DEFAULT 'reviewing' CHECK (
        lifecycle_state = 'reviewing'
    ),
    reviewer_reference varchar(256) NOT NULL CHECK (
        reviewer_reference ~ '^[A-Za-z][A-Za-z0-9._:@-]{1,255}$'
    ),
    review_started_at timestamptz NOT NULL,
    request_reference varchar(256) CHECK (
        request_reference IS NULL OR
        request_reference ~ '^[A-Za-z][A-Za-z0-9._:@-]{1,255}$'
    ),
    authority_reference varchar(256) NOT NULL UNIQUE CHECK (
        authority_reference ~ '^dataset-review:[0-9a-f]{64}$'
    ),
    authority_version smallint NOT NULL DEFAULT 1 CHECK (authority_version = 1),
    schema_revision smallint NOT NULL DEFAULT 1 CHECK (schema_revision = 1),
    record_fingerprint char(71) NOT NULL CHECK (
        record_fingerprint ~ '^sha256:[0-9a-f]{64}$'
    ),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    PRIMARY KEY (object_id, dataset_id, dataset_version),
    FOREIGN KEY (object_id, dataset_id, dataset_version, proposal_fingerprint)
        REFERENCES dohalm_dataset_governance_v1.dataset_version_proposal_authority
            (object_id, dataset_id, dataset_version, proposal_fingerprint)
);

CREATE FUNCTION dohalm_dataset_governance_v1.reject_review_authority_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION 'dataset review authority rows are immutable' USING ERRCODE = '55000';
END
$$;

CREATE TRIGGER dataset_version_review_authority_immutable
BEFORE UPDATE OR DELETE ON dohalm_dataset_governance_v1.dataset_version_review_authority
FOR EACH ROW EXECUTE FUNCTION dohalm_dataset_governance_v1.reject_review_authority_mutation();

CREATE FUNCTION dohalm_dataset_governance_v1.compute_dataset_review_record_fingerprint(
    stored_object_id varchar(256),
    stored_dataset_id varchar(256),
    stored_dataset_version varchar(256),
    stored_proposal_fingerprint char(71),
    stored_lifecycle_state varchar(16),
    stored_reviewer_reference varchar(256),
    stored_review_started_at timestamptz,
    stored_request_reference varchar(256),
    stored_authority_reference varchar(256),
    stored_authority_version smallint
)
RETURNS char(71)
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT 'sha256:' || pg_catalog.encode(
        pg_catalog.sha256(
            pg_catalog.convert_to(
                '{"authority_reference":' || pg_catalog.to_jsonb(stored_authority_reference)::text ||
                ',"authority_version":' || stored_authority_version::text ||
                ',"identity":{"dataset_id":' || pg_catalog.to_jsonb(stored_dataset_id)::text ||
                ',"dataset_version":' || pg_catalog.to_jsonb(stored_dataset_version)::text ||
                ',"object_id":' || pg_catalog.to_jsonb(stored_object_id)::text ||
                '},"lifecycle_state":' || pg_catalog.to_jsonb(stored_lifecycle_state)::text ||
                ',"proposal_fingerprint":' || pg_catalog.to_jsonb(pg_catalog.rtrim(stored_proposal_fingerprint))::text ||
                ',"request_reference":' || COALESCE(
                    pg_catalog.to_jsonb(stored_request_reference)::text,
                    'null'
                ) ||
                ',"review_started_at":' || pg_catalog.to_jsonb(
                    pg_catalog.to_char(
                        stored_review_started_at AT TIME ZONE 'UTC',
                        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                    )
                )::text ||
                ',"reviewer_reference":' || pg_catalog.to_jsonb(stored_reviewer_reference)::text ||
                E'}\n',
                'UTF8'
            )
        ),
        'hex'
    )
$$;

CREATE FUNCTION dohalm_dataset_governance_v1.start_dataset_version_review(
    requested_object_id varchar(256),
    requested_dataset_id varchar(256),
    requested_dataset_version varchar(256),
    requested_proposal_fingerprint char(71),
    requested_reviewer_reference varchar(256),
    requested_review_started_at timestamptz,
    requested_request_reference varchar(256),
    requested_record_fingerprint char(71)
)
RETURNS TABLE (
    outcome text,
    object_id varchar(256),
    dataset_id varchar(256),
    dataset_version varchar(256),
    proposal_fingerprint char(71),
    lifecycle_state varchar(16),
    reviewer_reference varchar(256),
    review_started_at timestamptz,
    request_reference varchar(256),
    authority_reference varchar(256),
    authority_version smallint,
    record_fingerprint char(71),
    created_at timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    authoritative_proposal_fingerprint char(71);
    expected_authority_reference varchar(256);
    expected_record_fingerprint char(71);
    stored dohalm_dataset_governance_v1.dataset_version_review_authority%ROWTYPE;
BEGIN
    IF requested_object_id IS NULL OR
       requested_object_id !~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$' OR
       requested_dataset_id IS NULL OR
       requested_dataset_id !~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$' OR
       requested_dataset_version IS NULL OR
       requested_dataset_version !~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$' OR
       requested_proposal_fingerprint IS NULL OR
       requested_proposal_fingerprint !~ '^sha256:[0-9a-f]{64}$' OR
       requested_reviewer_reference IS NULL OR
       requested_reviewer_reference !~ '^[A-Za-z][A-Za-z0-9._:@-]{1,255}$' OR
       requested_review_started_at IS NULL OR
       (requested_request_reference IS NOT NULL AND
        requested_request_reference !~ '^[A-Za-z][A-Za-z0-9._:@-]{1,255}$') OR
       requested_record_fingerprint IS NULL OR
       requested_record_fingerprint !~ '^sha256:[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'invalid dataset review start input' USING ERRCODE = '22023';
    END IF;

    BEGIN
        SELECT proposal.proposal_fingerprint
        INTO authoritative_proposal_fingerprint
        FROM dohalm_dataset_governance_v1.read_dataset_version_proposal(
            requested_object_id,
            requested_dataset_id,
            requested_dataset_version
        ) AS proposal;
    EXCEPTION WHEN SQLSTATE 'XX001' THEN
        RAISE EXCEPTION 'proposal authority corrupt' USING ERRCODE = 'P5003';
    END;

    IF authoritative_proposal_fingerprint IS NULL THEN
        RAISE EXCEPTION 'authoritative proposal not found' USING ERRCODE = 'P5001';
    END IF;
    IF authoritative_proposal_fingerprint <> requested_proposal_fingerprint THEN
        RAISE EXCEPTION 'proposal fingerprint mismatch' USING ERRCODE = 'P5002';
    END IF;

    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtext('dohalm.dataset-review.identity'),
        pg_catalog.hashtext(
            requested_object_id || chr(31) || requested_dataset_id || chr(31) ||
            requested_dataset_version
        )
    );

    expected_authority_reference := 'dataset-review:' || pg_catalog.encode(
        pg_catalog.sha256(
            pg_catalog.convert_to(
                requested_object_id || chr(31) || requested_dataset_id || chr(31) ||
                requested_dataset_version || chr(31) || requested_proposal_fingerprint,
                'UTF8'
            )
        ),
        'hex'
    );
    expected_record_fingerprint :=
        dohalm_dataset_governance_v1.compute_dataset_review_record_fingerprint(
            requested_object_id,
            requested_dataset_id,
            requested_dataset_version,
            requested_proposal_fingerprint,
            'reviewing'::varchar(16),
            requested_reviewer_reference,
            requested_review_started_at,
            requested_request_reference,
            expected_authority_reference,
            1::smallint
        );
    IF expected_record_fingerprint <> requested_record_fingerprint THEN
        RAISE EXCEPTION 'review record fingerprint mismatch' USING ERRCODE = '22023';
    END IF;

    SELECT review.* INTO stored
    FROM dohalm_dataset_governance_v1.dataset_version_review_authority AS review
    WHERE review.object_id = requested_object_id
      AND review.dataset_id = requested_dataset_id
      AND review.dataset_version = requested_dataset_version;

    IF FOUND THEN
        IF stored.proposal_fingerprint <> requested_proposal_fingerprint OR
           stored.lifecycle_state <> 'reviewing' OR
           stored.authority_reference <> expected_authority_reference OR
           stored.authority_version <> 1 OR
           stored.schema_revision <> 1 OR
           stored.record_fingerprint <>
               dohalm_dataset_governance_v1.compute_dataset_review_record_fingerprint(
                   stored.object_id,
                   stored.dataset_id,
                   stored.dataset_version,
                   stored.proposal_fingerprint,
                   stored.lifecycle_state,
                   stored.reviewer_reference,
                   stored.review_started_at,
                   stored.request_reference,
                   stored.authority_reference,
                   stored.authority_version
               ) THEN
            RAISE EXCEPTION 'dataset review authority corrupt' USING ERRCODE = 'XX001';
        END IF;
        IF stored.reviewer_reference = requested_reviewer_reference AND
           stored.request_reference IS NOT DISTINCT FROM requested_request_reference THEN
            RETURN QUERY SELECT
                'REPLAYED'::text, stored.object_id, stored.dataset_id,
                stored.dataset_version, stored.proposal_fingerprint,
                stored.lifecycle_state, stored.reviewer_reference,
                stored.review_started_at, stored.request_reference,
                stored.authority_reference, stored.authority_version,
                stored.record_fingerprint, stored.created_at;
        ELSE
            RETURN QUERY SELECT
                'CONFLICT'::text, requested_object_id, requested_dataset_id,
                requested_dataset_version, requested_proposal_fingerprint,
                NULL::varchar(16), NULL::varchar(256), NULL::timestamptz,
                NULL::varchar(256), expected_authority_reference, 1::smallint,
                NULL::char(71), NULL::timestamptz;
        END IF;
        RETURN;
    END IF;

    INSERT INTO dohalm_dataset_governance_v1.dataset_version_review_authority (
        object_id, dataset_id, dataset_version, proposal_fingerprint,
        reviewer_reference, review_started_at, request_reference,
        authority_reference, record_fingerprint
    ) VALUES (
        requested_object_id, requested_dataset_id, requested_dataset_version,
        requested_proposal_fingerprint, requested_reviewer_reference,
        requested_review_started_at, requested_request_reference,
        expected_authority_reference, requested_record_fingerprint
    ) RETURNING * INTO stored;

    RETURN QUERY SELECT
        'STARTED'::text, stored.object_id, stored.dataset_id,
        stored.dataset_version, stored.proposal_fingerprint,
        stored.lifecycle_state, stored.reviewer_reference,
        stored.review_started_at, stored.request_reference,
        stored.authority_reference, stored.authority_version,
        stored.record_fingerprint, stored.created_at;
END
$$;

CREATE FUNCTION dohalm_dataset_governance_v1.read_dataset_version_review(
    requested_object_id varchar(256),
    requested_dataset_id varchar(256),
    requested_dataset_version varchar(256),
    requested_proposal_fingerprint char(71)
)
RETURNS TABLE (
    object_id varchar(256),
    dataset_id varchar(256),
    dataset_version varchar(256),
    proposal_fingerprint char(71),
    lifecycle_state varchar(16),
    reviewer_reference varchar(256),
    review_started_at timestamptz,
    request_reference varchar(256),
    authority_reference varchar(256),
    authority_version smallint,
    record_fingerprint char(71),
    created_at timestamptz
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    stored dohalm_dataset_governance_v1.dataset_version_review_authority%ROWTYPE;
    expected_authority_reference varchar(256);
BEGIN
    IF requested_object_id IS NULL OR
       requested_object_id !~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$' OR
       requested_dataset_id IS NULL OR
       requested_dataset_id !~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$' OR
       requested_dataset_version IS NULL OR
       requested_dataset_version !~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$' OR
       requested_proposal_fingerprint IS NULL OR
       requested_proposal_fingerprint !~ '^sha256:[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'invalid dataset review read input' USING ERRCODE = '22023';
    END IF;

    SELECT review.* INTO stored
    FROM dohalm_dataset_governance_v1.dataset_version_review_authority AS review
    WHERE review.object_id = requested_object_id
      AND review.dataset_id = requested_dataset_id
      AND review.dataset_version = requested_dataset_version;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    IF stored.proposal_fingerprint <> requested_proposal_fingerprint THEN
        RAISE EXCEPTION 'review proposal fingerprint mismatch' USING ERRCODE = 'P5004';
    END IF;

    expected_authority_reference := 'dataset-review:' || pg_catalog.encode(
        pg_catalog.sha256(
            pg_catalog.convert_to(
                stored.object_id || chr(31) || stored.dataset_id || chr(31) ||
                stored.dataset_version || chr(31) || stored.proposal_fingerprint,
                'UTF8'
            )
        ),
        'hex'
    );
    IF stored.lifecycle_state <> 'reviewing' OR
       stored.authority_reference <> expected_authority_reference OR
       stored.authority_version <> 1 OR
       stored.schema_revision <> 1 OR
       stored.record_fingerprint <>
           dohalm_dataset_governance_v1.compute_dataset_review_record_fingerprint(
               stored.object_id,
               stored.dataset_id,
               stored.dataset_version,
               stored.proposal_fingerprint,
               stored.lifecycle_state,
               stored.reviewer_reference,
               stored.review_started_at,
               stored.request_reference,
               stored.authority_reference,
               stored.authority_version
           ) THEN
        RAISE EXCEPTION 'dataset review authority corrupt' USING ERRCODE = 'XX001';
    END IF;

    RETURN QUERY SELECT
        stored.object_id, stored.dataset_id, stored.dataset_version,
        stored.proposal_fingerprint, stored.lifecycle_state,
        stored.reviewer_reference, stored.review_started_at,
        stored.request_reference, stored.authority_reference,
        stored.authority_version, stored.record_fingerprint, stored.created_at;
END
$$;

ALTER TABLE dohalm_dataset_governance_v1.dataset_version_review_authority
    OWNER TO dohalm_dataset_review_owner;
ALTER FUNCTION dohalm_dataset_governance_v1.reject_review_authority_mutation()
    OWNER TO dohalm_dataset_review_owner;
ALTER FUNCTION dohalm_dataset_governance_v1.compute_dataset_review_record_fingerprint(
    varchar, varchar, varchar, char, varchar, varchar, timestamptz, varchar, varchar, smallint
) OWNER TO dohalm_dataset_review_owner;
ALTER FUNCTION dohalm_dataset_governance_v1.start_dataset_version_review(
    varchar, varchar, varchar, char, varchar, timestamptz, varchar, char
) OWNER TO dohalm_dataset_review_owner;
ALTER FUNCTION dohalm_dataset_governance_v1.read_dataset_version_review(
    varchar, varchar, varchar, char
) OWNER TO dohalm_dataset_review_owner;

REVOKE ALL ON ALL TABLES IN SCHEMA dohalm_dataset_governance_v1
    FROM PUBLIC, dohalm_dataset_review_authority;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA dohalm_dataset_governance_v1
    FROM PUBLIC, dohalm_dataset_review_authority;
GRANT USAGE ON SCHEMA dohalm_dataset_governance_v1
    TO dohalm_dataset_review_authority;
GRANT USAGE ON SCHEMA dohalm_dataset_governance_v1
    TO dohalm_dataset_review_owner;
GRANT EXECUTE ON FUNCTION dohalm_dataset_governance_v1.read_dataset_version_proposal(
    varchar, varchar, varchar
) TO dohalm_dataset_review_owner;
GRANT EXECUTE ON FUNCTION dohalm_dataset_governance_v1.start_dataset_version_review(
    varchar, varchar, varchar, char, varchar, timestamptz, varchar, char
) TO dohalm_dataset_review_authority;
GRANT EXECUTE ON FUNCTION dohalm_dataset_governance_v1.read_dataset_version_review(
    varchar, varchar, varchar, char
) TO dohalm_dataset_review_authority;
