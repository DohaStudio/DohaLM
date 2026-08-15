# Exact official entrypoint reachability

The image executes `docker-entrypoint.sh` with `postgres`. When started as root, line 343 performs `exec gosu postgres "$BASH_SOURCE" "$@"`.
The exact gosu path parses the user/group specification, reads passwd/group data, applies supplementary groups/GID/UID, sets `HOME`, resolves the target executable, and ends with `syscall.Exec`.

The gosu source and linked binary contain no `encoding/asn1`, `net/http`, `encoding/xml`, `crypto/tls`, or `html/template` package. They therefore expose no ASN.1/XML/template parser, HTTP server, TLS handshake, DNS, or network protocol path. PostgreSQL behavior occurs only after gosu has replaced itself via `syscall.Exec` and is not a call path inside the scanned `/usr/local/bin/gosu` artifact.

This conclusion is limited to the exact official entrypoint candidate and exact binary digest. Artifact, source, advisory, symbol, or entrypoint drift invalidates reuse.
