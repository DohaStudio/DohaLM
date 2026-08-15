# ADR-022: C1 Ephemeral PostgreSQL Test Image Security Policy

- 문서 상태: `approved`
- 마지막 검토일: 2026-08-15
- 결정 상태: 정책 `approved`; 현재 risk decision `accepted`
- 실행 영향: 새 Option B risk record의 local/CI isolated ephemeral C1 test 권한 활성; production activation 없음
- 관련 문서: [ADR-021](./ADR-021-production-training-adapters-and-durable-journal.md),
  [Definition of Ready](../governance/definition-of-ready.md),
  [Definition of Done](../governance/definition-of-done.md),
  [테스트 전략](../quality/test-strategy.md),
  [테스트 체크리스트](../quality/testing-checklist.md),
  [종료된 16.14 risk-acceptance record](../security/c1-postgres-image/C1-PG16-ALPINE-20260814-01/risk-acceptance-record.yaml),
  [종료된 16.15 Decision Packet](../security/c1-postgres-image/C1-PG16-ALPINE-1615-20260814-01/evidence-summary.md),
  [새 proposed Decision Packet](../security/c1-postgres-image/C1-PG16-ALPINE-1615-20260815-02/evidence-summary.md)

## Context

[확정] [ADR-021](./ADR-021-production-training-adapters-and-durable-journal.md)은 production authority catalog와 durable
journal의 architecture contract, PostgreSQL compatibility policy와 C1 → C2 → C3 → 별도 Production Activation Gate를
승인했다. 그러나 ADR-021은 C1의 isolated contract-test image에 적용할 취약점 허용 기준이나 exception 승인 절차를 결정하지
않았다.

[확정] 후속 Security Gate 프롬프트는 공식 PostgreSQL 16 Alpine image의 embedded `gosu` Go standard library finding을
근거로 `Critical 0 / High 0`을 C1 자동 차단 기준으로 사용했다. 이는 보수적인 임시 운영 판단이지만 저장소의 승인된 ADR에는
기록되지 않았다. 따라서 ADR-021의 기존 결정으로 소급하지 않고 이 ADR의 별도 Decision Packet으로 관리한다.

[확정] 이 문서는 선택지를 비교하고 필요한 risk-acceptance record를 정의하는 문서 전용 제안이다. 이 Draft의 작성·병합만으로
어떤 CVE도 수용하지 않으며 image, dependency, migration, schema, credential, runtime 또는 Training을 변경하지 않는다.

## 기존 확정 계약과 추가 미승인 정책

### 저장소의 기존 확정 계약

ADR-021에서 이미 승인된 범위는 다음과 같다.

- initial PostgreSQL major allowlist는 `{16}`이다.
- upstream이 지원하고 compatibility matrix가 승인한 major의 current supported minor를 사용한다.
- isolated local/CI ephemeral contract test image는 platform-specific immutable manifest digest로 pin한다.
- image와 driver/migration dependency의 provenance, compatibility와 security metadata를 C1에서 검토한다.
- test는 production credential, production data, shared/live database와 Production Activation에서 분리한다.
- C1은 schema/dependency와 isolated migration/restore/contract test만 다루며 C2 adapter, C3 composition과 actual Training을
  활성화하지 않는다.

### 후속 프롬프트에서 추가된 미승인 정책

다음은 Security Gate 프롬프트의 보수적 조건이지만 ADR-021의 기존 확정 요구사항은 아니다.

- scanner의 모든 Critical/High finding을 자동 차단한다.
- 공식 VEX 또는 not-affected 근거가 없으면 실행 도달성과 무관하게 residual risk로 유지한다.
- `gosu`가 수정된 Go toolchain으로 공식 rebuild될 때까지 C1을 중단한다.
- Docker Official Image만 허용하고 repository-owned 또는 third-party 대안을 배제한다.

[검증 필요] 위 정책 중 무엇을 repository contract로 채택할지는 사용자의 별도 명시 결정이 필요하다.

## 현재 image evidence

2026-08-13T20:56:31+09:00에 Docker Official Image metadata를 read-only로 한 번 재조회했다. exact tag와 floating Alpine
tag는 아래 동일 artifact를 가리켰다.

| 항목 | 확인값 |
|---|---|
| exact candidate | `postgres:16.14-alpine@sha256:7a396fd264a2067788b6551122b50f162bf6136312c7fc9d74381cb92c648382` |
| platform | `linux/amd64` |
| multi-arch index | `sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777` |
| config | `sha256:de3a4eab8fdfa507ea92aac488b916b08089e515db49b055fe71dfa271ba3a28` |
| source revision | `4f9ced003ba58a854656ba150d146243d27ae3ac` |
| Alpine base | `sha256:79ff19e9084a00eece421b2523fb93e22d730e2c0e525905de047e848e56d95f` |
| image created | `2026-07-07T17:45:07Z` |
| gosu evidence | `1.19`, Go `1.24.6`, binary SHA-256 `52c8749d0142edd234e9d6bd5237dff2d81e71f43537e2f4f66f75dd4b243dd0` |
| current Docker Scout 1.24.0 counts | Critical 2, High 17, Medium 18, Low 5, Unspecified 8; total 50 |
| current metadata result | 동일 digest/provenance; 새 official rebuild 없음; suppression 0 |

[확정] evidence correction에서 동일 digest를 pull하고 Docker Scout 1.24.0으로 full unsuppressed scan을 재실행했다.
raw SARIF, normalized Markdown derivative, SPDX SBOM과 report hash를 immutable evidence directory에 영속화했다.

### PostgreSQL 16.15 currentness update

[확정] 2026-08-13 PostgreSQL 16.15 official Alpine image가 공개되면서 기존 16.14 record의 fixed-image,
artifact/advisory drift 조기 종료 조건이 충족됐다. 기존 immutable approval을 덮어쓰지 않고
[termination evidence](../security/c1-postgres-image/C1-PG16-ALPINE-1615-20260814-01/termination-C1-PG16-ALPINE-20260814-01.yaml)로
append-only 기록한다. `C1-PG16-ALPINE-20260814-01`은 16.15 authorization으로 재사용할 수 없다.

[확정] 새 `linux/amd64` manifest
`sha256:075f7ba66bc9b3ce7d6b8b635208ff61cd7cf1a67d71ec530eec5d7ae0cbe571`에 대한
[`C1-PG16-ALPINE-1615-20260814-01`](../security/c1-postgres-image/C1-PG16-ALPINE-1615-20260814-01/risk-decision-record.yaml)은
당시 scan과 세 adjudication 뒤 residual Critical 1 / High 15를 local/CI isolated ephemeral-only로 정확히 30일 허용했던
historical accepted record다.
Accountable approver `DDORINY`가 Option B를 `2026-08-14T23:45:32.1303728+09:00`에 명시 승인했다.

[확정] 이 historical record의 `accepted`와 `execution_authorized`는 true였고 승인 시작은 `2026-08-14T23:45:32.1303728+09:00`,
만료는 정확히 30일 뒤인 `2026-09-13T23:45:32.1303728+09:00`이다. 실행 권한은 exact manifest의 local/CI isolated
ephemeral test에만 적용된다. Psycopg binary/system-libpq provenance blocker는 유지하며 C1-A/B/C는 미구현이다.
C1→C2→C3→별도 Production Activation 순서도 변경하지 않는다.

[확정] 2026-08-15 fresh unsuppressed scan에서 네 finding이 Unspecified에서 High로, 한 finding이 Medium으로 바뀌어
위 16.15 accepted record의 당시 조기 종료 조건이 충족됐다. 기존 record와 evidence는 수정하지 않고 새
[termination evidence](../security/c1-postgres-image/C1-PG16-ALPINE-1615-20260815-02/termination-C1-PG16-ALPINE-1615-20260814-01.yaml)에
종료를 기록한다. 남은 expiry와 execution authorization은 재사용하지 않는다.

[확정] 최신 raw Critical 2 / High 21, 신규 four-High adjudication, residual Critical 1 / High 15를 결속한 새
[`C1-PG16-ALPINE-1615-20260815-02`](../security/c1-postgres-image/C1-PG16-ALPINE-1615-20260815-02/risk-decision-record.yaml)는
사용자 `DDORINY`가 `2026-08-15T13:45:06.7768148+09:00`에 명시 승인했다. `accepted: true`,
`execution_authorized: true`이며 만료는 정확히 30일 뒤인 `2026-09-14T13:45:06.7768148+09:00`다. exact manifest의
local/CI isolated ephemeral C1 schema·migration·restore contract test에만 적용하고 조기 종료 정책을 유지한다.

### Historical Critical/High 목록

| CVE | historical 분류 | 현재 문서 판정 |
|---|---|---|
| `CVE-2025-68121` | gosu embedded Go stdlib | residual risk; 공식 VEX/not-affected 없음 |
| `CVE-2025-58187` | gosu embedded Go stdlib | residual risk; 공식 VEX/not-affected 없음 |
| `CVE-2025-58188` | gosu embedded Go stdlib | residual risk; 공식 VEX/not-affected 없음 |
| `CVE-2025-61723` | gosu embedded Go stdlib | residual risk; 공식 VEX/not-affected 없음 |
| `CVE-2025-61725` | gosu embedded Go stdlib | residual risk; 공식 VEX/not-affected 없음 |
| `CVE-2025-61726` | gosu embedded Go stdlib | residual risk; 공식 VEX/not-affected 없음 |
| `CVE-2025-61729` | gosu embedded Go stdlib | residual risk; 공식 VEX/not-affected 없음 |
| `CVE-2026-25679` | gosu embedded Go stdlib | residual risk; 공식 VEX/not-affected 없음 |
| `CVE-2026-32280` | gosu embedded Go stdlib | residual risk; 공식 VEX/not-affected 없음 |
| `CVE-2026-32281` | gosu embedded Go stdlib | residual risk; 공식 VEX/not-affected 없음 |
| `CVE-2026-32283` | gosu embedded Go stdlib | residual risk; 공식 VEX/not-affected 없음 |
| `CVE-2026-33811` | gosu embedded Go stdlib | residual risk; 공식 VEX/not-affected 없음 |
| `CVE-2026-33814` | gosu embedded Go stdlib | residual risk; 공식 VEX/not-affected 없음 |
| `CVE-2026-39820` | gosu embedded Go stdlib | residual risk; 공식 VEX/not-affected 없음 |
| `CVE-2026-39821` | gosu embedded Go stdlib | exact artifact package/symbol evidence로 `not_applicable_exact_artifact` |
| `CVE-2026-39836` | Windows-specific | official OSV와 exact `linux/amd64` evidence로 `not_affected` |
| `CVE-2026-42499` | gosu embedded Go stdlib | residual risk; 공식 VEX/not-affected 없음 |
| `CVE-2026-42504` | gosu embedded Go stdlib | residual risk; 공식 VEX/not-affected 없음 |
| `CVE-2026-46600` | gosu embedded Go stdlib | exact artifact package/symbol evidence로 `not_applicable_exact_artifact` |

[확정] 이 목록은 false positive 선언이나 suppression allowlist가 아니다. 같은 digest라도 advisory, exploitability 또는 VEX가
변경되면 새 Decision Gate가 필요하다.

## 검토할 정책 선택지

### 선택지 A — Zero Critical/High 절대 Gate

- 공식 `library/postgres` image에서 Critical 0, High 0만 허용한다.
- 장점: 규칙이 단순하고 보수적이며 별도 residual-risk 승인이 필요 없다.
- 단점: C1의 isolated test 경로와 무관한 finding 하나로 개발이 무기한 정지될 수 있다.
- 현재 결과: 조건을 만족하는 공식 rebuild가 없어 C1 중단을 유지한다.

### 선택지 B — Ephemeral C1 한정의 시간 제한 risk acceptance

- production runtime image 승인과 분리해 exact digest와 exact CVE 목록만 검토한다.
- 허용 범위는 isolated local/CI ephemeral schema·migration·restore contract test뿐이다.
- production/staging/shared/live data, production credential, public port publish와 actual Training을 금지한다.
- container, volume과 test network는 disposable이며 각 실행 뒤 정리한다.
- non-root 또는 최소 권한 실행 가능성과 official entrypoint 동작을 별도 검증한다.
- 승인일부터 최대 30일 또는 fixed official image 공개 중 먼저 도래하는 시점에 만료한다.
- 새 Critical/High, exploitability·official advisory 변화 또는 digest drift가 발생하면 즉시 fail closed한다.
- 장점: production activation 없이 C1 schema contract 개발을 진행할 수 있다.
- 단점: accountable approver가 명시적으로 residual risk를 수용해야 한다.

### 선택지 C — Repository-owned minimal test image

- 적용 범위: C1 local/CI contract test 전용 minimal PostgreSQL image이며 production runtime image가 아니다.
- 장점: 불필요한 package와 entrypoint helper를 제거·교체하고 base, PostgreSQL package, startup helper와 build toolchain을
  review 가능한 Dockerfile에 고정할 수 있다. digest, SBOM, provenance와 rebuild도 repository review에 결속된다.
- 위험/비용과 ownership: repository가 registry, rebuild, signing/provenance, patch SLA와 공급망 유지보수를 새로 소유해야 한다.
- C1 재개 증거: 별도 승인된 image design ADR 또는 동등한 governance decision, review 가능한 Dockerfile과 exact base/package
  digest, PostgreSQL 16 current supported minor, build provenance·SBOM, signature/attestation 또는 승인된 대체 무결성 증거,
  Critical/High 전체 scan·disposition, entrypoint/initdb/role/transaction/volume/restart contract suite, CI가 동일
  `linux/amd64` artifact를 사용한다는 증거와 registry/rebuild/patch owner·cadence가 모두 필요하다.
- 자동 채택 금지: 이 ADR만으로 custom image를 build·push하거나 registry를 도입할 수 없다. 새 supply-chain owner와 maintenance
  책임에 대한 별도 사용자 승인 전에는 C1에 사용할 수 없다.

### 선택지 D — Hardened third-party PostgreSQL image

- 적용 범위: 별도 승인된 third-party PostgreSQL image를 C1 local/CI contract test에만 사용하는 후보이며 production 채택이 아니다.
- 장점: 공급자가 reduced attack surface, frequent rebuild, SBOM/signing 또는 hardened defaults를 제공하면 공식 image rebuild
  대기 시간을 줄일 수 있다.
- 위험/비용과 ownership: provider trust, license, source·build provenance, update/EOL/CVE response와 공급 중단·digest drift·
  compromise 대응 owner를 새로 결정해야 한다.
- C1 재개 증거: 공급자 identity·trust assessment, license/redistribution/use 조건, source availability·build provenance,
  SBOM/signature/attestation 검증, update/EOL/CVE response policy, exact `linux/amd64` digest, PostgreSQL 16 current supported minor와
  extension/locale/entrypoint compatibility, role/transaction/migration/restore/restart contract suite가 모두 필요하다.
- 자동 채택 금지: Docker Official Image에서 authority가 이동하므로 별도 공급자 ADR과 사용자 승인이 필요하다. scanner 수치가
  낮다는 이유만으로 채택하지 않는다.

### 선택지 E — Container 없는 PostgreSQL contract-test 전략

- 적용 범위: container 대신 승인된 isolated fixture/service, managed runner 또는 OS package로 C1 contract test를 수행하는
  infrastructure 후보이며 shared/live database 경로가 아니다.
- 장점: container base와 entrypoint helper의 CVE를 C1 경로에서 제거할 수 있고, 승인된 runner/service가 있다면 startup
  overhead와 image supply-chain 의존을 줄일 수 있다.
- 위험/비용과 ownership: infrastructure owner가 provisioning, availability, failure, teardown, version drift와 Windows local·
  Linux CI parity 또는 승인된 차이를 책임져야 한다.
- C1 재개 증거: exact provisioning contract와 owner, PostgreSQL 16 current supported minor pin, test별 isolated
  database/schema/role, shared state·production credential/data 부재 증거, deterministic reset/cleanup, local/CI parity 또는 차이의
  명시 승인, migration lock·concurrency·restore/restart test 가능성, version drift detection과 availability/failure/teardown
  contract가 모두 필요하다.
- 자동 채택 금지: shared live DB, developer-owned persistent DB와 production service는 사용할 수 없다. 별도 infrastructure ADR과
  사용자 승인 없이 managed service 또는 OS package를 선택하지 않는다.

## Decision rationale

[확정] C1 schema/dependency 개발용 isolated ephemeral test에 한정해 선택지 B를 채택한다. 이 결정은 production runtime
image에 적용하지 않으며 아래 exact record와 최신 scan, tracker 및 기능 evidence가 유효한 동안에만 효력이 있다.

[제안] 선택지 A도 유효한 보수적 선택이다. 개발 속도를 근거로 CVE를 false positive 또는 negligible risk로 축소하지 않는다.
선택지 C~E는 각각 별도 supply-chain, provider 또는 infrastructure 결정이 필요하다.

## Time-bound risk acceptance record

선택지 B를 승인할 경우 record는 다음 field를 모두 가진 immutable Decision Packet이어야 한다.

| field | exact contract |
|---|---|
| `decision_id` | non-empty stable identifier; renewal마다 새 값 |
| `accountable_approver_role` | risk를 명시 승인할 repository governance role; 개인 credential 아님 |
| `repository` | exact `library/postgres` 또는 별도 승인된 repository authority |
| `exact_tag` | exact supported `16.x-alpine` tag |
| `platform` | exact `linux/amd64` |
| `manifest_digest` | `sha256:` + lowercase hex 64; platform manifest |
| `index_digest` | multi-arch tag drift 감시용 digest |
| `config_digest` | exact image config digest |
| `base_digest` | exact base image digest |
| `source_revision` | exact official source commit |
| `scanner` | scanner name, exact version과 advisory source |
| `scanned_at` | timezone-aware scan/advisory timestamp |
| `critical_high_findings` | 모든 Critical/High의 ID, severity, component, installed/fixed version과 status |
| `not_affected_findings` | official evidence URI/hash와 platform 근거가 있는 항목만 분리 |
| `residual_risk_findings` | not-affected가 아닌 exact remaining 목록; suppression 0 |
| `allowed_environments` | exact `local_ephemeral`, `ci_ephemeral` only |
| `forbidden_environments` | production, staging, shared DB, live data와 actual Training |
| `network_policy` | public port publish 금지; test-scoped private network만 허용 |
| `credential_policy` | synthetic test credential only; production DSN/secret 금지 |
| `runtime_privilege` | non-root 또는 검증된 최소 권한과 privilege-drop evidence |
| `cleanup_policy` | 실행 전 승인된 deterministic teardown 절차; disposable container, volume, network, image archive/cache와 credential fixture의 제거 대상·책임자·시점 및 기존 사용자 자원 불변 조건 |
| `cleanup_evidence` | 실제 test 종료 뒤 생성한 redacted cleanup 결과; execution/correlation ID, 완료 시각, disposable container/volume/network 잔존 수, 전후 inventory 또는 승인 delta, sanitized result/status, evidence reference·SHA-256, verifier/process-boundary identity와 failure/ambiguity 상태 |
| `starts_at` | timezone-aware 승인 시작 시각 |
| `expires_at` | `starts_at` 이후 최대 30일; 연장 불가 |
| `early_termination` | fixed official image, digest drift, 새 Critical/High, exploitability/VEX/advisory 변화 중 하나라도 발생 |
| `ready_revalidation` | PR Ready 직전 동일 digest 재조회, 전체 scan, tracker와 functional verification 필수 |
| `evidence_location` | repository-relative immutable evidence 위치; 예: `docs/security/c1-postgres-image/<decision_id>/` |
| `evidence_sha256` | canonical Decision Packet/report bundle SHA-256 |
| `renewal_policy` | 새 evidence와 새 사용자 명시 승인 없이는 갱신 금지 |

[확정] 이 record는 C1 local/CI contract test의 제한적 사용 범위만 표현한다. production activation, production DB credential,
Dataset/Model 접근, approval issuance, backend invocation 또는 Training 권한을 부여하지 않는다.

[확정] `cleanup_policy`는 실행 전에 승인하는 절차이고 `cleanup_evidence`는 실제 ephemeral test 종료 뒤에만 기록하는 결과다.
`cleanup_evidence`는 raw Docker command, PID, private path, credential, DSN 또는 token을 저장하지 않으며 실행 전에 성공
placeholder로 만들 수 없다. evidence가 없으면 cleanup을 PASS로 표현하지 않는다.

## 재검증과 fail-closed 조건

선택지 B가 별도 승인되더라도 변화는 다음 세 범주로 판정한다.

### A. 즉시 authorization 종료

- exact manifest/config/base/source identity drift 또는 새 raw Critical/High CVE ID
- adjudicated finding의 applicable 전환, residual affected range/component/location 확대·변경, official VEX 철회
- vulnerable symbol/call/runtime reachability의 새 확인
- isolation, credential, network, privilege, cleanup 계약 실패
- fixed official image 공개와 compatibility Gate 통과 또는 승인 만료

### B. 실행 중지와 semantic 재검증

- 동일 CVE·component·range·location의 severity 변경 또는 EPSS 변경
- OSV modified timestamp·비의미 metadata, raw JSON ordering/serialization 변화
- scanner advisory DB freshness 미확인

이 범주는 다음 C1 run 전에 재검증하되 자동 risk-set 확대나 영구 종료로 처리하지 않는다. exact-artifact
not-applicable 판정은 package/symbol/reachability가 불변이면 새 사용자 risk acceptance 없이 유지할 수 있다.

### C. 정보성 변화

문구, URL, related reference, transport ordering 또는 artifact/affected contract와 무관한 metadata 변화는 기록만 한다.
어느 범주인지 판정할 evidence가 부족하면 fail closed로 실행을 중지하고 새 Decision Packet을 연다. 이 정책은 이미 종료된
승인을 소급 복구하지 않는다.

## Decision Packet

사용자는 다음 중 하나를 별도로 선택해야 한다.

1. Zero Critical/High 절대 Gate 유지 — 공식 rebuild까지 C1 중단
2. Exact Alpine digest에 대해 C1 local/CI ephemeral-only, time-bound risk acceptance 검토
3. Repository-owned minimal test image 설계 ADR 진행
4. Hardened third-party image 공급자 ADR 진행
5. Container-free test infrastructure ADR 진행
6. 작업 중단

[확정] 선택지 2는 이 ADR 또는 문서 PR의 병합만으로 승인되지 않는다. 이번 결정은 exact CVE, 최신 evidence,
accountable approver와 만료 조건을 포함한 별도 사용자 명시 승인과 아래 immutable record로 그 Gate를 충족했다.

## Historical accepted decision과 current proposed decision

[확정] 2026-08-14 사용자는 선택지 2를 명시 승인했고 accountable approver `DDORINY`로서 최신 unsuppressed scan,
세 개의 독립 adjudication(`CVE-2026-39821` exact-artifact not-applicable, `CVE-2026-39836` linux/amd64 not-affected,
`CVE-2026-46600` exact-artifact not-applicable), exact artifact identity, isolated compatibility preflight와 cleanup evidence를
검토 가능한 immutable record로 고정했다.

[확정] 승인 record는
[C1-PG16-ALPINE-20260814-01](../security/c1-postgres-image/C1-PG16-ALPINE-20260814-01/risk-acceptance-record.yaml)이다.
유효 기간은 `2026-08-14T11:46:52.6887955+09:00`부터 `2026-09-13T11:46:52.6887955+09:00`까지이며, fixed official
image 공개 또는 record의 early termination 조건 발생 시 더 일찍 종료한다. raw scan은 Critical 2 / High 17이고,
세 finding을 suppression 없이 독립 분리한 accepted residual 집합은 Critical 1 / High 15이다. raw SARIF의 finding은
삭제하거나 severity를 변경하지 않았다. 상세 evidence와 layered manifest는
[evidence summary](../security/c1-postgres-image/C1-PG16-ALPINE-20260814-01/evidence-summary.md)에 고정한다.

[확정] 이 승인은 당시 C1 schema·migration·restore contract test를 local/CI isolated ephemeral 환경에서 수행할 수 있게 하는
image risk decision만 승인한다. C1 구현 자체, C2/C3, production/staging/shared/live DB, production credential/data,
public port, Production Activation, Dataset/Model/GPU, Training 또는 Evaluation을 승인하지 않는다.

## Scope와 non-goals

- [제외] 승인 record 범위 밖 image risk acceptance 또는 CVE suppression
- [제외] Dockerfile, Compose, dependency, lockfile, migration, SQL, schema와 workflow 변경
- [제외] custom/third-party image build·pull·push 또는 자동 채택
- [제외] live/shared/production PostgreSQL, DSN, credential과 data 접근
- [제외] C1/C2/C3 구현, Production Activation, Dataset, Model, GPU, Training과 Evaluation

## 승인 Gate

이 ADR의 분류·재검증 정책은 `approved`이고 이전 Option B authorization은 종료 상태를 유지한다. current record는 사용자
명시 승인으로 exact manifest의 local/CI isolated ephemeral C1 test에 한해 유효하다. C1 구현은 별도 Draft PR과 독립 검증
Gate를 따라야 하며 production 사용, C2/C3, Production Activation 또는 실제 Training 권한은 없다.

[확정] 위 문장은 종료 전 16.14 historical record의 승인 사실만 보존한다. 별도 16.15 record는 accountable approver
`DDORINY`가 `2026-08-14T23:45:32.1303728+09:00`에 exact Option B를 명시 승인했으며, 그 승인만이 record에 적힌 제한적
image test 권한을 부여했다. 그 authorization은 2026-08-15 severity/advisory drift로 종료됐고 새 Draft PR의 merge, 문서 존재
또는 preflight 성공은 추가 권한을 부여하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-15 | [확정] DDORINY가 current raw C2/H21·adjudicated 7·residual C1/H15 Option B record를 정확히 30일간 local/CI isolated ephemeral C1 test로 승인 |
| 2026-08-15 | [제안] severity drift로 이전 16.15 authorization을 종료하고 raw C2/H21·adjudicated 7·residual C1/H15 새 proposed record 및 A/B/C 재검증 정책을 등록 |
| 2026-08-14 | [확정] PostgreSQL 16.15 exact Option B를 DDORINY가 명시 승인; local/CI isolated ephemeral image test만 30일 허용하고 C1 구현·Psycopg·production·Training은 계속 차단 |
| 2026-08-14 | [제안] 16.14 record 조기 종료를 append-only로 기록하고 16.15 exact-image proposed/unapproved Decision Packet과 승인 전 fail-closed Gate를 연결 |
| 2026-08-14 | [확정] Scout 1.24.0 raw C2/H17과 세 독립 adjudication을 반영하고 residual C1/H15 및 layered manifest를 동기화 |
| 2026-08-14 | [확정] 사용자 선택지 2 승인, 최신 scan·not-applicable adjudication·preflight·cleanup evidence와 30일 immutable record 고정 |
| 2026-08-14 | [제안] 선택지 C/D/E의 장점·ownership·C1 재개 증거와 실행 후 `cleanup_evidence` fail-closed 계약 보완 |
| 2026-08-13 | [제안] ADR-021의 확정 C1 contract와 후속 image Security Gate를 분리하고 다섯 정책 선택지·time-bound exception schema를 등록 |
