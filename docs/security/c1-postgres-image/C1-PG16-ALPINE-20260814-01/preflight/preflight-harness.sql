-- Sanitized deterministic compatibility contract used by the disposable C1 probe.
-- All identifiers are synthetic. The runner supplies a disposable credential.
CREATE ROLE c1_owner NOLOGIN;
CREATE ROLE c1_app NOLOGIN;
CREATE ROLE c1_runtime LOGIN IN ROLE c1_app;
CREATE SCHEMA c1 AUTHORIZATION c1_owner;
CREATE TABLE c1.parent (tenant_id integer, id integer, PRIMARY KEY (tenant_id, id));
CREATE TABLE c1.child (
  tenant_id integer,
  id integer,
  value integer CHECK (value > 0),
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, id) REFERENCES c1.parent (tenant_id, id)
);
ALTER TABLE c1.parent OWNER TO c1_owner;
ALTER TABLE c1.child OWNER TO c1_owner;
GRANT USAGE ON SCHEMA c1 TO c1_app;
GRANT SELECT ON c1.parent TO c1_app;
CREATE FUNCTION c1.approved_value() RETURNS integer
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp
AS 'SELECT 1';
ALTER FUNCTION c1.approved_value() OWNER TO c1_owner;
GRANT EXECUTE ON FUNCTION c1.approved_value() TO c1_app;
