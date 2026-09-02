SET search_path = pg_catalog, pg_temp;

ALTER TABLE dohalm_training_v1.dataset_pair_authority
DROP CONSTRAINT dataset_pair_authority_dataset_version_authority_id_dataset_key;

ALTER TABLE dohalm_training_v1.training_authority_current
ADD COLUMN dataset_pair_logical_key text NULL;

UPDATE dohalm_training_v1.training_authority_current AS current_state
SET dataset_pair_logical_key = concat_ws(
    chr(31),
    pair_row.dataset_version_authority_id::text,
    pair_row.dataset_manifest_authority_id::text,
    btrim(pair_row.pair_fingerprint),
    pair_row.publication_scenario
)
FROM dohalm_training_v1.dataset_pair_authority AS pair_row
WHERE current_state.authority_id = pair_row.authority_id
  AND current_state.subject_family = 'dataset_pair';

ALTER TABLE dohalm_training_v1.training_authority_current
ADD CONSTRAINT training_authority_current_dataset_pair_logical_key_check
CHECK (
    (subject_family = 'dataset_pair' AND dataset_pair_logical_key IS NOT NULL)
    OR (subject_family <> 'dataset_pair' AND dataset_pair_logical_key IS NULL)
);

ALTER TABLE dohalm_training_v1.training_authority_current
ADD COLUMN dataset_pair_current_logical_key text
GENERATED ALWAYS AS (
    CASE
        WHEN subject_family = 'dataset_pair' AND state = 'current'
        THEN dataset_pair_logical_key
        ELSE NULL
    END
) STORED;

ALTER TABLE dohalm_training_v1.training_authority_current
ADD CONSTRAINT training_authority_current_dataset_pair_current_uq
UNIQUE (dataset_pair_current_logical_key)
DEFERRABLE INITIALLY DEFERRED;

CREATE FUNCTION dohalm_training_v1.project_dataset_pair_logical_key()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    IF NEW.subject_family = 'dataset_pair' THEN
        SELECT concat_ws(
            chr(31),
            pair_row.dataset_version_authority_id::text,
            pair_row.dataset_manifest_authority_id::text,
            btrim(pair_row.pair_fingerprint),
            pair_row.publication_scenario
        )
        INTO NEW.dataset_pair_logical_key
        FROM dohalm_training_v1.dataset_pair_authority AS pair_row
        WHERE pair_row.authority_id = NEW.authority_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION USING
                ERRCODE = '23503',
                MESSAGE = 'Dataset pair authority unavailable for current projection';
        END IF;
    ELSE
        NEW.dataset_pair_logical_key := NULL;
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER training_authority_current_dataset_pair_logical_key
BEFORE INSERT OR UPDATE ON dohalm_training_v1.training_authority_current
FOR EACH ROW
EXECUTE FUNCTION dohalm_training_v1.project_dataset_pair_logical_key();

ALTER FUNCTION dohalm_training_v1.project_dataset_pair_logical_key()
OWNER TO dohalm_training_owner;

REVOKE ALL ON FUNCTION dohalm_training_v1.project_dataset_pair_logical_key()
FROM PUBLIC, dohalm_training_runtime, dohalm_training_authority_producer,
     dohalm_training_resolver, dohalm_training_journal,
     dohalm_training_intent_writer;
