# PostgreSQL 16.15 Alpine accepted C1 image decision evidence

- 문서 상태: `accepted`
- 마지막 검토일: 2026-08-14
- Decision ID: `C1-PG16-ALPINE-1615-20260814-01`
- accepted: `true`
- execution authorized: `true` — 아래 exact image의 local/CI isolated ephemeral test 범위만 허용

## 결론

[확정] exact candidate는 `postgres@sha256:075f7ba66bc9b3ce7d6b8b635208ff61cd7cf1a67d71ec530eec5d7ae0cbe571`
`linux/amd64`다. 새 Docker Scout 1.24.0 unsuppressed scan은 Critical 2, High 17, Medium 18, Low 5,
Unspecified 8, 전체 50건을 재현했다.

[확정] 이번 correction의 fresh raw SARIF SHA-256은
`fec111471d556f2e984e72d1017142aeb8146e72d8e761e2862143eaefdcb701`이다. 이전
`c149af944a83a552ffa445967cd69a0f384fd48033759ac33987b56e9e210a18`과 비교해 43개 finding의 EPSS
percentile만 변경됐고 CVE 추가·삭제, severity, component/PURL, installed/affected/fixed range, location, EPSS score,
scanner와 artifact identity 변경은 0이다.

[확정] 세 finding의 exact-artifact adjudication 후 residual Critical 1 / High 15를 local/CI isolated ephemeral-only로
정확히 30일 허용하는 Option B를 accountable approver `DDORINY`가 `2026-08-14T23:45:32.1303728+09:00`에 명시 승인했다.
승인은 같은 시각에 시작하여 `2026-09-13T23:45:32.1303728+09:00`에 만료한다. 이 권한은 exact image test에만 적용되며
C1 구현, Psycopg 선택·설치 또는 production activation을 발생시키지 않는다.

## Artifact와 scan

| 항목 | Evidence |
|---|---|
| OCI identity | [image-identity.json](./image-identity.json), [index](./oci-index.json), [manifest](./oci-manifest.json) |
| raw SARIF | [scout-cves.sarif.json](./scout-cves.sarif.json) |
| field-by-field scan delta | [scan-delta.json](./scan-delta.json) |
| normalized Markdown | [scout-cves.md](./scout-cves.md) |
| SBOM/package | [SPDX](./sbom.spdx.json), [package summary](./packages.txt) |
| scanner | [scanner-provenance.json](./scanner-provenance.json) |
| PostgreSQL security | [postgresql-security-snapshot.json](./postgresql-security-snapshot.json) |
| Alpine secdb | [main](./supporting/alpine-main.json), [community](./supporting/alpine-community.json) |

SARIF는 scanner 원본이고 Markdown derivative는 각 line의 trailing whitespace만 제거하고 LF로 고정했다. SARIF finding은
삭제·수정하지 않았다. Scout service exception 4건은 관찰됐지만 적용된 exception과 ignore/suppression/VEX filter는 0이다.
OCI inspect와 preflight JSON은 Windows PowerShell 기본 writer 대신 explicit UTF-8 no-BOM writer로 새로 생성했다. bundle뿐
아니라 repository 전체 JSON·SARIF·SPDX가 lenient `utf-8-sig` fallback 없이 strict UTF-8 parser를 통과해야 한다.

## Adjudication

| Raw finding | Current OSV | 판정 | Child bundle |
|---|---|---|---|
| `CVE-2026-39821` / `GO-2026-5026` Critical | modified `2026-08-14T10:42:19.830132264Z`; OSV SHA `5fed8bde…a4977` | `not_applicable_exact_artifact` | [evidence](./adjudications/CVE-2026-39821/adjudication-summary.md) |
| `CVE-2026-39836` / `GO-2026-4971` High | modified `2026-08-01T10:44:51.653864484Z`; OSV SHA `36b46ef5…2142` | `not_affected` | [evidence](./adjudications/CVE-2026-39836/adjudication-summary.md) |
| `CVE-2026-46600` / `GO-2026-5942` High | modified `2026-08-13T22:00:14.273346398Z`; OSV SHA `b8da7fb2…3bed` | `not_applicable_exact_artifact` | [evidence](./adjudications/CVE-2026-46600/adjudication-summary.md) |

세 child bundle은 current OSV schema·PURL·range·전체 symbol·related metadata, exact gosu SHA-256, Go build metadata,
complete symbol table search, source dependency graph, fresh govulncheck binary/source SARIF와 runtime reachability를 포함한다.
GO-2026-5026의 변경된 `net/http`·HTTP/2 및 `x/net/idna` symbol도 다시 판정했다. 공식 vendor VEX는 없다.

## Accepted residual set

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

fresh exact image preflight `C1-PG1615-PROPOSED-20260814-PREFLIGHT-20260814204334`는 official initdb, PostgreSQL 16.15,
linux/amd64, UTF8/UTC, private network/public port 0,
NOLOGIN/LOGIN role topology, schema/privilege, SECURITY DEFINER와 고정 search path, PUBLIC EXECUTE revoke, direct DML denial,
composite FK/CHECK, advisory transaction lock, transactional DDL rollback, graceful shutdown과 restart persistence를 통과했다.

- [preflight results](./preflight/preflight-results.json)
- [preflight cleanup](./preflight/preflight-cleanup.json)
- [cleanup policy](./cleanup-policy.md)
- [final cleanup evidence](./cleanup-evidence.json)

## Approval Gate

[확정] [accepted record](./risk-decision-record.yaml)은 accountable approver `DDORINY`의 명시 승인, 시작 시각
`2026-08-14T23:45:32.1303728+09:00`과 정확히 30일 뒤인 만료 시각 `2026-09-13T23:45:32.1303728+09:00`을 고정한다.
`execution_authorized: true`는 exact accepted manifest의 local/CI isolated ephemeral test에만 적용된다. Psycopg
binary/system-libpq provenance blocker는 유지되며, C1-A/B/C, C2/C3, Activation, production/staging/shared/live DB와
actual Training은 모두 미승인·미구현이다.

## Integrity

[확정] 각 adjudication child `SHA256SUMS`와 parent [SHA256SUMS](./SHA256SUMS)의 scope는
[manifest-scope.json](./manifest-scope.json)에 정의한다. risk record와 parent manifest의 circular hash는 명시적 exclusion과
외부 검증 hash로 차단한다. 각 entry는 SHA-256과 decimal byte length를 함께 결속한다.
