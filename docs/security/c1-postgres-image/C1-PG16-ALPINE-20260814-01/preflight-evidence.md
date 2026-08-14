# C1 PostgreSQL image compatibility preflight evidence

- Evidence ID: `C1-PG16-ALPINE-20260814-01-PREFLIGHT`
- Executed at: `2026-08-14T11:45:30+09:00`
- Target: `postgres:16.14-alpine@sha256:7a396fd264a2067788b6551122b50f162bf6136312c7fc9d74381cb92c648382`
- Platform: `linux/amd64`
- Result: `PASS`
- Scope: disposable compatibility probe only; no product migration, schema, dependency, adapter, or workflow implementation

## Verified properties

- PostgreSQL `16.14`, server encoding `UTF8`, timezone `UTC`, database collation `en_US.utf8`
- official entrypoint and `initdb` completed; server became ready before and after restart
- isolated internal Docker network; published host ports `0`
- disposable test credential only; no production/shared resource access
- owner and application group roles are `NOLOGIN`; runtime role is `LOGIN` and a member of the application group
- schema ownership belongs to the owner role
- runtime direct table `INSERT` is denied while approved selective `SELECT` and function execution privileges work
- SECURITY DEFINER function owner is `NOLOGIN` and `search_path` is exactly `pg_catalog, pg_temp`
- composite foreign key and positive-value CHECK reject invalid rows
- transaction-scoped advisory lock succeeds
- rollback removes the probe row
- restart preserves the valid row on the disposable volume

## Harness correction history

Two fail-closed harness corrections preceded the final PASS. The first attempted to read database collation as a GUC instead of from
`pg_database.datcollate`. The second omitted the selective schema `USAGE` needed to resolve the approved function. Both stopped before
an invalid PASS; the disposable database was recreated before the final run. These were probe defects, not image compatibility findings.

## Sanitized reproducibility evidence

- [`preflight/preflight-harness.sql`](./preflight/preflight-harness.sql): deterministic synthetic role, schema, privilege, constraint, and function contract
- [`preflight/preflight-reproduction.json`](./preflight/preflight-reproduction.json): machine-readable result and correction history
- [`preflight/network-exposure.json`](./preflight/network-exposure.json): task-private network and zero published ports
- [`preflight/restart-persistence.json`](./preflight/restart-persistence.json): disposable-volume restart result
- [`preflight/entrypoint-log-extract.txt`](./preflight/entrypoint-log-extract.txt): sanitized official-entrypoint lifecycle markers

These files are covered by the parent `SHA256SUMS`. Raw commands, credentials, private paths, process IDs, and host environment dumps are intentionally excluded.
