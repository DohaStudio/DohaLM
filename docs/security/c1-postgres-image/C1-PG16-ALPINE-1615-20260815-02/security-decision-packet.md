# PR #128 New-High Exact-Artifact Decision Packet

Technical adjudication completed for the four newly High Docker Scout findings against the exact PostgreSQL 16.15 Alpine linux/amd64 manifest and exact gosu 1.19 binary.

All four remain preserved in the raw Scout SARIF. Go stdlib 1.24.6 is version-affected, but each affected package is absent from the exact gosu source dependency graph and linked ELF symbol inventory; binary and source govulncheck find no vulnerable symbol call. The official entrypoint invokes gosu only for privilege transition and process replacement, with none of the required parser, HTTP, XML, or TLS input paths.

Verdicts:

- CVE-2026-33818: `not_applicable_exact_artifact`
- CVE-2026-56853: `not_applicable_exact_artifact`
- CVE-2026-56859: `not_applicable_exact_artifact`
- CVE-2026-56862: `not_applicable_exact_artifact`

CVE-2026-56858 is retained as a Medium severity delta and has the same exact-artifact result; it is not included in the Critical/High adjudication set.

This packet does not reactivate the terminated Option B record, approve residual risk, make PR #128 Ready, merge it, or authorize C1 implementation. A corrected immutable evidence/risk record and independent revalidation are required before explicit risk acceptance can be considered.
