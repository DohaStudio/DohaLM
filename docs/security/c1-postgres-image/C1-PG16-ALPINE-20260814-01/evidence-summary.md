# C1 PostgreSQL image security evidence summary

- Decision: `C1-PG16-ALPINE-20260814-01`
- Exact artifact: `postgres:16.14-alpine@sha256:7a396fd264a2067788b6551122b50f162bf6136312c7fc9d74381cb92c648382`
- Platform: `linux/amd64`
- Current scanner: Docker Scout `1.24.0` (`b1c9331b2166aef7ec690aa16fd655b8798ea4c6`)
- Scan mode: full and unsuppressed; four service exceptions were observed but were not filtered
- Raw distribution: Critical 2, High 17, Medium 18, Low 5, Unspecified 8; total 50
- Accepted residual risk: Critical 1, High 15

## Independent adjudications

| Raw finding | Classification | Evidence bundle |
|---|---|---|
| `CVE-2026-39821` / `GO-2026-5026` (Critical) | `not_applicable_exact_artifact` | [`adjudications/CVE-2026-39821/`](./adjudications/CVE-2026-39821/) |
| `CVE-2026-39836` / `GO-2026-4971` (High) | `not_affected` (Windows-only behavior; artifact is linux/amd64) | [`adjudications/CVE-2026-39836/`](./adjudications/CVE-2026-39836/) |
| `CVE-2026-46600` / `GO-2026-5942` (High) | `not_applicable_exact_artifact` | [`adjudications/CVE-2026-46600/`](./adjudications/CVE-2026-46600/) |

These classifications retain the raw findings and apply no suppression, ignore rule, vendor VEX, or global false-positive declaration. Artifact, advisory, package, symbol, build, scanner, or runtime-path drift invalidates reuse.

## Integrity model

Each adjudication directory has a `SHA256SUMS` covering every internal file except that manifest itself. The parent `SHA256SUMS` covers supporting evidence and the three child manifests. [`manifest-scope.json`](./manifest-scope.json) declares the deterministic include/exclude contract. The risk record is deliberately outside the parent manifest because it stores that manifest's hash; Git commit/tree/path binding closes that edge without a circular hash.

The compatibility preflight references committed sanitized reproduction artifacts, and the raw SARIF remains unmodified. `scout-cves.md` is a line-ending/trailing-whitespace-normalized derivative of the raw scanner Markdown.
