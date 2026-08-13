# ADR-022: C1 Ephemeral PostgreSQL Test Image Security Policy

- 문서 상태: `draft`
- 마지막 검토일: 2026-08-13
- 결정 상태: `proposed`
- 실행 영향: 없음
- 관련 문서: [ADR-021](./ADR-021-production-training-adapters-and-durable-journal.md),
  [Definition of Ready](../governance/definition-of-ready.md),
  [Definition of Done](../governance/definition-of-done.md),
  [테스트 전략](../quality/test-strategy.md),
  [테스트 체크리스트](../quality/testing-checklist.md)

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
| prior Docker Scout counts | Critical 1, High 16, Medium 18 |
| current metadata result | 이전 Security Gate와 동일 digest/provenance; 새 official rebuild 없음 |

[확정] 이번 문서 작업은 동일 digest를 pull, 재스캔 또는 기능 probe하지 않았다. 위 취약점 수치는 후속 Security Decision
Packet에서 전달된 historical scanner evidence이며 이번 PR이 생성한 새 scan 결과가 아니다. exact scanner report artifact,
advisory timestamp와 report hash는 현재 저장소에 영속화되지 않았으므로 선택지 B 승인 전 새 evidence로 보완해야 한다.

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
| `CVE-2026-39836` | Windows-specific | `linux/amd64` not affected; 승인 시 공식 근거 재확인 필요 |
| `CVE-2026-42499` | gosu embedded Go stdlib | residual risk; 공식 VEX/not-affected 없음 |
| `CVE-2026-42504` | gosu embedded Go stdlib | residual risk; 공식 VEX/not-affected 없음 |

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

- source Dockerfile과 base digest를 저장소가 소유하고 `gosu` 대체 또는 제거 가능성을 검토한다.
- SBOM, rebuild cadence, signing/provenance, registry ownership과 patch SLA가 필요하다.
- 새로운 supply-chain 및 유지보수 책임을 만들므로 별도 ADR과 사용자 승인 전 자동 채택하지 않는다.

### 선택지 D — Hardened third-party PostgreSQL image

- provider trust, license, PostgreSQL compatibility, SBOM, signing과 update policy를 별도 검토한다.
- Docker Official Image에서 다른 authority로 이동하는 결정이므로 공급자 Decision Gate 전 자동 채택하지 않는다.

### 선택지 E — Container 없는 PostgreSQL contract-test 전략

- isolated test fixture/service, managed runner 또는 OS package 사용 가능성을 검토한다.
- version pin, reproducibility, isolation, cleanup과 local/CI parity 계약이 필요하다.
- production credential과 shared/live database 사용은 계속 금지하며 별도 infrastructure ADR 전 자동 채택하지 않는다.

## Proposed recommendation

[제안] C1 schema/dependency 개발용 isolated ephemeral test에 한정해 선택지 B를 우선 검토한다. 이 권고는 production runtime
image에 적용하지 않으며 risk acceptance 자체가 아니다. 사용자가 선택지 B를 명시 승인하려면 아래 exact record와 최신 scan,
tracker 및 기능 evidence를 먼저 완성해야 한다.

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
| `cleanup_policy` | test container, volume, network와 temporary report의 deterministic teardown |
| `starts_at` | timezone-aware 승인 시작 시각 |
| `expires_at` | `starts_at` 이후 최대 30일; 연장 불가 |
| `early_termination` | fixed official image, digest drift, 새 Critical/High, exploitability/VEX/advisory 변화 중 하나라도 발생 |
| `ready_revalidation` | PR Ready 직전 동일 digest 재조회, 전체 scan, tracker와 functional verification 필수 |
| `evidence_location` | repository-relative immutable evidence 위치; 예: `docs/security/c1-postgres-image/<decision_id>/` |
| `evidence_sha256` | canonical Decision Packet/report bundle SHA-256 |
| `renewal_policy` | 새 evidence와 새 사용자 명시 승인 없이는 갱신 금지 |

[확정] 이 record는 C1 local/CI contract test의 제한적 사용 범위만 표현한다. production activation, production DB credential,
Dataset/Model 접근, approval issuance, backend invocation 또는 Training 권한을 부여하지 않는다.

## 재검증과 fail-closed 조건

선택지 B가 별도 승인되더라도 다음을 모두 적용한다.

1. C1 구현 시작 직전 tag/index/platform manifest digest를 재조회한다.
2. C1 Draft PR 생성 직전과 Ready 전 전체 image scan을 실행한다.
3. Critical/High 전체와 Alpine, Go, Docker Official Image 및 PostgreSQL official tracker를 교차 검증한다.
4. digest, component, CVE, exploitability, VEX 또는 official provenance가 바뀌면 기존 exception을 사용하지 않는다.
5. fixed official image가 공개되면 exception을 즉시 종료하고 새 immutable candidate를 독립 검증한다.
6. cleanup 실패, public exposure 또는 production credential/data 접촉은 Gate 실패다.

## Decision Packet

사용자는 다음 중 하나를 별도로 선택해야 한다.

1. Zero Critical/High 절대 Gate 유지 — 공식 rebuild까지 C1 중단
2. Exact Alpine digest에 대해 C1 local/CI ephemeral-only, time-bound risk acceptance 검토
3. Repository-owned minimal test image 설계 ADR 진행
4. Hardened third-party image 공급자 ADR 진행
5. Container-free test infrastructure ADR 진행
6. 작업 중단

[검증 필요] 선택지 2는 이 ADR 또는 문서 PR의 병합으로 승인되지 않는다. exact CVE, 최신 evidence, accountable approver와
만료 조건을 포함한 별도 사용자 명시 승인이 필요하다.

## Scope와 non-goals

- [제외] image risk acceptance 승인 또는 CVE suppression
- [제외] Dockerfile, Compose, dependency, lockfile, migration, SQL, schema와 workflow 변경
- [제외] custom/third-party image build·pull·push 또는 자동 채택
- [제외] live/shared/production PostgreSQL, DSN, credential과 data 접근
- [제외] C1/C2/C3 구현, Production Activation, Dataset, Model, GPU, Training과 Evaluation

## 승인 Gate

이 ADR은 `draft`와 `proposed`이며 실행 영향이 없다. 독립 검증과 사용자 명시 승인 전에는 어느 선택지도 accepted decision이
아니다. 병합되더라도 Decision Packet의 기록 형식과 선택지를 등록할 뿐 risk acceptance, C1 착수 또는 production 사용을
승인하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-13 | [제안] ADR-021의 확정 C1 contract와 후속 image Security Gate를 분리하고 다섯 정책 선택지·time-bound exception schema를 등록 |
