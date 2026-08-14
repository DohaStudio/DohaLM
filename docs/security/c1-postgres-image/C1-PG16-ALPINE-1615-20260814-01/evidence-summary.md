# PostgreSQL 16.15 Alpine proposed C1 image decision evidence

- 문서 상태: `proposed`
- 마지막 검토일: 2026-08-14
- Decision ID: `C1-PG16-ALPINE-1615-20260814-01`
- accepted: `false`
- execution authorized: `false`

## 결론

[확정] exact candidate는 `postgres@sha256:075f7ba66bc9b3ce7d6b8b635208ff61cd7cf1a67d71ec530eec5d7ae0cbe571`
`linux/amd64`다. 새 Docker Scout 1.24.0 unsuppressed scan은 Critical 2, High 17, Medium 18, Low 5,
Unspecified 8, 전체 50건을 재현했다.

[제안] 세 finding의 exact-artifact adjudication 후 residual Critical 1 / High 15를 local/CI isolated ephemeral-only로
최대 30일 수용하는 Option B를 검토한다. 사용자는 이 제안을 아직 승인하지 않았다. 이 Draft PR의 작성 또는 병합은 risk
acceptance, execution authority, C1 구현이나 production activation을 발생시키지 않는다.

## Artifact와 scan

| 항목 | Evidence |
|---|---|
| OCI identity | [image-identity.json](./image-identity.json), [index](./oci-index.json), [manifest](./oci-manifest.json) |
| raw SARIF | [scout-cves.sarif.json](./scout-cves.sarif.json) |
| normalized Markdown | [scout-cves.md](./scout-cves.md) |
| SBOM/package | [SPDX](./sbom.spdx.json), [package summary](./packages.txt) |
| scanner | [scanner-provenance.json](./scanner-provenance.json) |
| PostgreSQL security | [postgresql-security-snapshot.json](./postgresql-security-snapshot.json) |
| Alpine secdb | [main](./supporting/alpine-main.json), [community](./supporting/alpine-community.json) |

SARIF는 scanner 원본이고 Markdown derivative는 각 line의 trailing whitespace만 제거하고 LF로 고정했다. SARIF finding은
삭제·수정하지 않았다. Scout service exception 4건은 관찰됐지만 ignore/suppression/VEX filter는 적용하지 않았다.

## Adjudication

| Raw finding | 판정 | Child bundle |
|---|---|---|
| `CVE-2026-39821` / `GO-2026-5026` Critical | `not_applicable_exact_artifact` | [evidence](./adjudications/CVE-2026-39821/adjudication-summary.md) |
| `CVE-2026-39836` / `GO-2026-4971` High | `not_affected` | [evidence](./adjudications/CVE-2026-39836/adjudication-summary.md) |
| `CVE-2026-46600` / `GO-2026-5942` High | `not_applicable_exact_artifact` | [evidence](./adjudications/CVE-2026-46600/adjudication-summary.md) |

세 child bundle은 current OSV snapshot, exact gosu SHA-256, Go build metadata, complete symbol table search, source dependency graph,
fresh govulncheck binary/source SARIF와 runtime reachability를 포함한다. 공식 vendor VEX는 없다.

## Proposed residual set

- Critical: `CVE-2025-68121`
- High: `CVE-2025-58187`, `CVE-2025-58188`, `CVE-2025-61723`, `CVE-2025-61725`,
  `CVE-2025-61726`, `CVE-2025-61729`, `CVE-2026-25679`, `CVE-2026-32280`, `CVE-2026-32281`,
  `CVE-2026-32283`, `CVE-2026-33811`, `CVE-2026-33814`, `CVE-2026-39820`, `CVE-2026-42499`,
  `CVE-2026-42504`

raw C/H는 residual과 adjudicated set의 합집합과 같고 두 집합의 교집합은 비어 있다.

## Currentness와 predecessor 종료

[확정] PostgreSQL 16.15 official image 공개로 기존
[`C1-PG16-ALPINE-20260814-01`](../C1-PG16-ALPINE-20260814-01/risk-acceptance-record.yaml)의 fixed-image와
artifact/advisory drift 조기 종료 조건이 충족됐다. 기존 record는 변경하지 않고
[termination evidence](./termination-C1-PG16-ALPINE-20260814-01.yaml)에서 종료 사실만 append-only로 참조한다.
기존 승인은 16.15 authorization으로 재사용할 수 없다.

## Preflight와 cleanup

fresh exact image preflight는 official initdb, PostgreSQL 16.15, linux/amd64, UTF8/UTC, private network/public port 0,
NOLOGIN/LOGIN role topology, schema/privilege, SECURITY DEFINER와 고정 search path, PUBLIC EXECUTE revoke, direct DML denial,
composite FK/CHECK, advisory transaction lock, transactional DDL rollback, graceful shutdown과 restart persistence를 통과했다.

- [preflight results](./preflight/preflight-results.json)
- [preflight cleanup](./preflight/preflight-cleanup.json)
- [cleanup policy](./cleanup-policy.md)
- [final cleanup evidence](./cleanup-evidence.json)

## Approval Gate

[확정] [proposed record](./risk-decision-record.yaml)의 approver, approved/start/expiry는 모두 null이고 accepted와
execution_authorized는 false다. 명시적 사용자 승인 전 fail closed다. Psycopg binary/system-libpq provenance blocker도 유지된다.
C1-A/B/C, C2/C3, Activation, production/staging/shared/live DB와 actual Training은 모두 미승인·미구현이다.

## Integrity

[확정] 각 adjudication child `SHA256SUMS`와 parent [SHA256SUMS](./SHA256SUMS)의 scope는
[manifest-scope.json](./manifest-scope.json)에 정의한다. risk record와 parent manifest의 circular hash는 명시적 exclusion과
외부 검증 hash로 차단한다.
