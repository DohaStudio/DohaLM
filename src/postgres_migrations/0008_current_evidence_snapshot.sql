DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dohalm_current_evidence_owner') THEN
        CREATE ROLE dohalm_current_evidence_owner NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dohalm_current_evidence_coordinator') THEN
        CREATE ROLE dohalm_current_evidence_coordinator LOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dohalm_current_evidence_resolver') THEN
        CREATE ROLE dohalm_current_evidence_resolver LOGIN NOINHERIT;
    END IF;
END $$;

CREATE TABLE dohalm_dataset_governance_v1.current_evidence_snapshot (
    snapshot_id uuid PRIMARY KEY,
    idempotency_key varchar(255) NOT NULL UNIQUE,
    snapshot_fingerprint char(71) NOT NULL CHECK (snapshot_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    proposal_fingerprint char(71) NOT NULL CHECK (proposal_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    canonical_payload jsonb NOT NULL,
    canonical_bytes bytea NOT NULL,
    created_at timestamptz NOT NULL,
    CHECK (octet_length(canonical_bytes) > 0)
);

CREATE TABLE dohalm_dataset_governance_v1.current_evidence_lifecycle_binding (
    object_id varchar(256) NOT NULL,
    dataset_id varchar(256) NOT NULL,
    dataset_version varchar(256) NOT NULL,
    lifecycle_stage varchar(16) NOT NULL CHECK (lifecycle_stage IN ('review','approval','publication')),
    proposal_fingerprint char(71) NOT NULL CHECK (proposal_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    snapshot_id uuid NOT NULL REFERENCES dohalm_dataset_governance_v1.current_evidence_snapshot(snapshot_id),
    snapshot_fingerprint char(71) NOT NULL CHECK (snapshot_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    PRIMARY KEY (object_id, dataset_id, dataset_version, lifecycle_stage)
);

CREATE TABLE dohalm_dataset_governance_v1.readiness_current_evidence_binding (
    readiness_authority_id uuid NOT NULL,
    readiness_fingerprint char(71) NOT NULL CHECK (readiness_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    snapshot_id uuid NOT NULL REFERENCES dohalm_dataset_governance_v1.current_evidence_snapshot(snapshot_id),
    snapshot_fingerprint char(71) NOT NULL CHECK (snapshot_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    PRIMARY KEY (readiness_authority_id, readiness_fingerprint)
);

ALTER TABLE dohalm_dataset_governance_v1.current_evidence_snapshot
    OWNER TO dohalm_current_evidence_owner;
ALTER TABLE dohalm_dataset_governance_v1.current_evidence_lifecycle_binding
    OWNER TO dohalm_current_evidence_owner;
ALTER TABLE dohalm_dataset_governance_v1.readiness_current_evidence_binding
    OWNER TO dohalm_current_evidence_owner;
REVOKE ALL ON dohalm_dataset_governance_v1.current_evidence_snapshot FROM PUBLIC;
REVOKE ALL ON dohalm_dataset_governance_v1.current_evidence_lifecycle_binding FROM PUBLIC;
REVOKE ALL ON dohalm_dataset_governance_v1.readiness_current_evidence_binding FROM PUBLIC;

CREATE FUNCTION dohalm_dataset_governance_v1.put_current_evidence_snapshot(
    requested_snapshot_id uuid,
    requested_idempotency_key varchar,
    requested_snapshot_fingerprint char(71),
    requested_proposal_fingerprint char(71),
    requested_payload jsonb,
    requested_canonical_bytes bytea,
    requested_created_at timestamptz
) RETURNS TABLE(snapshot_id uuid, snapshot_fingerprint char(71), canonical_payload jsonb)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp AS $$
DECLARE existing dohalm_dataset_governance_v1.current_evidence_snapshot%ROWTYPE;
BEGIN
    SELECT * INTO existing
    FROM dohalm_dataset_governance_v1.current_evidence_snapshot s
    WHERE s.idempotency_key = requested_idempotency_key
    FOR UPDATE;
    IF FOUND THEN
        IF existing.snapshot_fingerprint <> requested_snapshot_fingerprint
           OR existing.proposal_fingerprint <> requested_proposal_fingerprint
           OR existing.canonical_bytes <> requested_canonical_bytes THEN
            RAISE EXCEPTION USING ERRCODE = '23505', MESSAGE = 'snapshot replay conflict';
        END IF;
        RETURN QUERY SELECT existing.snapshot_id, existing.snapshot_fingerprint, existing.canonical_payload;
        RETURN;
    END IF;
    INSERT INTO dohalm_dataset_governance_v1.current_evidence_snapshot VALUES (
        requested_snapshot_id, requested_idempotency_key, requested_snapshot_fingerprint,
        requested_proposal_fingerprint, requested_payload, requested_canonical_bytes,
        requested_created_at
    );
    RETURN QUERY SELECT requested_snapshot_id, requested_snapshot_fingerprint, requested_payload;
END $$;

CREATE FUNCTION dohalm_dataset_governance_v1.read_current_evidence_snapshot(requested_snapshot_id uuid)
RETURNS TABLE(snapshot_id uuid, snapshot_fingerprint char(71), canonical_payload jsonb)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp AS $$
    SELECT s.snapshot_id, s.snapshot_fingerprint, s.canonical_payload
    FROM dohalm_dataset_governance_v1.current_evidence_snapshot s
    WHERE s.snapshot_id = requested_snapshot_id
$$;

CREATE FUNCTION dohalm_dataset_governance_v1.read_current_evidence_snapshot_by_key(requested_key varchar)
RETURNS TABLE(snapshot_id uuid, snapshot_fingerprint char(71), canonical_payload jsonb)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    SELECT s.snapshot_id, s.snapshot_fingerprint, s.canonical_payload
    FROM dohalm_dataset_governance_v1.current_evidence_snapshot s
    WHERE s.idempotency_key = requested_key
$$;

CREATE FUNCTION dohalm_dataset_governance_v1.bind_current_evidence_lifecycle(
    requested_object_id varchar, requested_dataset_id varchar, requested_dataset_version varchar,
    requested_stage varchar, requested_proposal_fingerprint char(71),
    requested_snapshot_id uuid, requested_snapshot_fingerprint char(71)
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE existing dohalm_dataset_governance_v1.current_evidence_lifecycle_binding%ROWTYPE;
BEGIN
    SELECT * INTO existing FROM dohalm_dataset_governance_v1.current_evidence_lifecycle_binding b
    WHERE b.object_id=requested_object_id AND b.dataset_id=requested_dataset_id
      AND b.dataset_version=requested_dataset_version AND b.lifecycle_stage=requested_stage
    FOR UPDATE;
    IF FOUND THEN
        IF existing.proposal_fingerprint <> requested_proposal_fingerprint
           OR existing.snapshot_id <> requested_snapshot_id
           OR existing.snapshot_fingerprint <> requested_snapshot_fingerprint THEN
            RAISE EXCEPTION USING ERRCODE='23505', MESSAGE='lifecycle binding conflict';
        END IF;
        RETURN;
    END IF;
    INSERT INTO dohalm_dataset_governance_v1.current_evidence_lifecycle_binding VALUES (
        requested_object_id, requested_dataset_id, requested_dataset_version, requested_stage,
        requested_proposal_fingerprint, requested_snapshot_id, requested_snapshot_fingerprint
    );
END $$;

CREATE FUNCTION dohalm_dataset_governance_v1.read_current_evidence_lifecycle(
    requested_object_id varchar, requested_dataset_id varchar, requested_dataset_version varchar,
    requested_stage varchar
) RETURNS TABLE(proposal_fingerprint char(71), snapshot_id uuid, snapshot_fingerprint char(71))
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    SELECT b.proposal_fingerprint, b.snapshot_id, b.snapshot_fingerprint
    FROM dohalm_dataset_governance_v1.current_evidence_lifecycle_binding b
    WHERE b.object_id=requested_object_id AND b.dataset_id=requested_dataset_id
      AND b.dataset_version=requested_dataset_version AND b.lifecycle_stage=requested_stage
$$;

CREATE FUNCTION dohalm_dataset_governance_v1.bind_readiness_current_evidence(
    requested_readiness_authority_id uuid, requested_readiness_fingerprint char(71),
    requested_snapshot_id uuid, requested_snapshot_fingerprint char(71)
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE existing dohalm_dataset_governance_v1.readiness_current_evidence_binding%ROWTYPE;
BEGIN
    SELECT * INTO existing FROM dohalm_dataset_governance_v1.readiness_current_evidence_binding b
    WHERE b.readiness_authority_id=requested_readiness_authority_id
      AND b.readiness_fingerprint=requested_readiness_fingerprint FOR UPDATE;
    IF FOUND THEN
        IF existing.snapshot_id <> requested_snapshot_id
           OR existing.snapshot_fingerprint <> requested_snapshot_fingerprint THEN
            RAISE EXCEPTION USING ERRCODE='23505', MESSAGE='readiness binding conflict';
        END IF;
        RETURN;
    END IF;
    INSERT INTO dohalm_dataset_governance_v1.readiness_current_evidence_binding VALUES (
        requested_readiness_authority_id, requested_readiness_fingerprint,
        requested_snapshot_id, requested_snapshot_fingerprint
    );
END;
$$;

CREATE FUNCTION dohalm_dataset_governance_v1.resolve_readiness_current_evidence(
    requested_readiness_authority_id uuid, requested_readiness_fingerprint char(71)
) RETURNS TABLE(snapshot_id uuid, snapshot_fingerprint char(71))
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    SELECT b.snapshot_id, b.snapshot_fingerprint
    FROM dohalm_dataset_governance_v1.readiness_current_evidence_binding b
    WHERE b.readiness_authority_id=requested_readiness_authority_id
      AND b.readiness_fingerprint=requested_readiness_fingerprint
$$;

ALTER FUNCTION dohalm_dataset_governance_v1.put_current_evidence_snapshot(uuid,varchar,char,char,jsonb,bytea,timestamptz)
    OWNER TO dohalm_current_evidence_owner;
ALTER FUNCTION dohalm_dataset_governance_v1.read_current_evidence_snapshot(uuid)
    OWNER TO dohalm_current_evidence_owner;
ALTER FUNCTION dohalm_dataset_governance_v1.read_current_evidence_snapshot_by_key(varchar) OWNER TO dohalm_current_evidence_owner;
ALTER FUNCTION dohalm_dataset_governance_v1.bind_current_evidence_lifecycle(varchar,varchar,varchar,varchar,char,uuid,char) OWNER TO dohalm_current_evidence_owner;
ALTER FUNCTION dohalm_dataset_governance_v1.read_current_evidence_lifecycle(varchar,varchar,varchar,varchar) OWNER TO dohalm_current_evidence_owner;
ALTER FUNCTION dohalm_dataset_governance_v1.bind_readiness_current_evidence(uuid,char,uuid,char) OWNER TO dohalm_current_evidence_owner;
ALTER FUNCTION dohalm_dataset_governance_v1.resolve_readiness_current_evidence(uuid,char) OWNER TO dohalm_current_evidence_owner;
REVOKE ALL ON FUNCTION dohalm_dataset_governance_v1.put_current_evidence_snapshot(uuid,varchar,char,char,jsonb,bytea,timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION dohalm_dataset_governance_v1.read_current_evidence_snapshot(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION dohalm_dataset_governance_v1.read_current_evidence_snapshot_by_key(varchar) FROM PUBLIC;
REVOKE ALL ON FUNCTION dohalm_dataset_governance_v1.bind_current_evidence_lifecycle(varchar,varchar,varchar,varchar,char,uuid,char) FROM PUBLIC;
REVOKE ALL ON FUNCTION dohalm_dataset_governance_v1.read_current_evidence_lifecycle(varchar,varchar,varchar,varchar) FROM PUBLIC;
REVOKE ALL ON FUNCTION dohalm_dataset_governance_v1.bind_readiness_current_evidence(uuid,char,uuid,char) FROM PUBLIC;
REVOKE ALL ON FUNCTION dohalm_dataset_governance_v1.resolve_readiness_current_evidence(uuid,char) FROM PUBLIC;
GRANT USAGE ON SCHEMA dohalm_dataset_governance_v1
    TO dohalm_current_evidence_owner, dohalm_current_evidence_coordinator,
       dohalm_current_evidence_resolver;
GRANT EXECUTE ON FUNCTION dohalm_dataset_governance_v1.put_current_evidence_snapshot(uuid,varchar,char,char,jsonb,bytea,timestamptz)
    TO dohalm_current_evidence_coordinator;
GRANT EXECUTE ON FUNCTION dohalm_dataset_governance_v1.read_current_evidence_snapshot(uuid)
    TO dohalm_current_evidence_coordinator, dohalm_current_evidence_resolver;
GRANT EXECUTE ON FUNCTION dohalm_dataset_governance_v1.read_current_evidence_snapshot_by_key(varchar),
    dohalm_dataset_governance_v1.read_current_evidence_lifecycle(varchar,varchar,varchar,varchar),
    dohalm_dataset_governance_v1.resolve_readiness_current_evidence(uuid,char)
    TO dohalm_current_evidence_coordinator, dohalm_current_evidence_resolver;
GRANT EXECUTE ON FUNCTION dohalm_dataset_governance_v1.bind_current_evidence_lifecycle(varchar,varchar,varchar,varchar,char,uuid,char),
    dohalm_dataset_governance_v1.bind_readiness_current_evidence(uuid,char,uuid,char)
    TO dohalm_current_evidence_coordinator;
