# ADR-028: CurrentEvidence source authority와 snapshot 경계

- 문서 상태: `draft`
- 마지막 검토일: 2026-08-25
- 결정 상태: `proposed`
- 실행 영향: 없음; RightsMetadata ownership과 cross-source snapshot은 차단하고 DohaLM TrainingEligibility producer·authority 필요성만 제안
- 기준 revision: `DohaStudio/DohaLM@05b6df6abe1f201a98b4300ccf47bde9af467470`
- Common 권위: `DohaStudio/.github@dd75fc88c16e9ae9a04acfafb72756a905f6365b`
- Common package / policy: `dohastudio-common-ai-contracts==0.1.0` / `1.0.0`
- 관련 결정: [ADR-014](./ADR-014-dataset-product-governance-boundary.md),
  [ADR-015](./ADR-015-dataset-version-publication-contract.md),
  [ADR-025](./ADR-025-dataset-version-proposal-authority-contract.md),
  [ADR-026](./ADR-026-dataset-review-authority-contract.md),
  [ADR-027](./ADR-027-dataset-governance-production-prerequisites.md)
- 관련 문서: [제품 지속 학습 경계](../project/ai-music-director-continuous-learning.md)

## Context

[현재] Product Dataset Proposal·Review Start·Approval·Publication service chain은 모든 lifecycle invocation에서
`DatasetProposalCurrentEvidenceAuthority`를 요구한다. 이 port는 canonical proposal, proposal fingerprint와 explicit
timezone-aware lifecycle 시각을 받아 `CURRENT`, `MISSING`, `EXPIRED`, `REVOKED`, `INVALID`, `IDENTITY_MISMATCH` 중 하나를
반환하지만 production implementation은 없다.

[현재] candidate-level `LearningCandidateReviewAuthority`도 exact RightsMetadata·TrainingEligibility ID와 `checked_at`으로
두 객체를 resolve하는 Protocol일 뿐이다. DohaLM production source, durable writer, current projection, revoke API와 runtime
composition은 없다.

[현재] ADR-027은 source를 찾지 못해 CurrentEvidence를 `D. BLOCKED — EVIDENCE SOURCE NOT DEFINED`로 판정했다. 이번 Gate는
실제 Common 계약, DohaLM 구현과 2026-08-25에 접근 가능한 DohaStudio 저장소를 더 조사해 producer·writer·projection·snapshot과
Publication TOCTOU 경계를 구체화한다. source, migration, config, adapter, CLI, API, worker와 Training은 구현하지 않는다.

## Common contract inventory

### RightsMetadata v1

| 구분 | 실제 계약 |
|---|---|
| resource identity | envelope `object_id`와 `rights_metadata_id`; validator가 equality 강제 |
| candidate/member binding | 직접 field 없음; LearningCandidate의 `rights_metadata_id`와 coordinator가 결속 |
| producer/audit | envelope `producer{name,version}`, `created_by`, `created_at` |
| workspace | optional envelope `workspace_id`; 없으면 global로 추정하지 않음 |
| purpose/task | 직접 field 없음; `retention_allowed.scope`는 `training` 또는 `runtime`; Dataset purpose·task는 coordinator가 결속 |
| status | `unknown`, `pending_review`, `approved_limited`, `approved`, `rejected`, `expired`, `revoked` |
| retention/expiry | Boolean 또는 `{allowed, expires_at, scope}`; gated use는 structured form만 허용 |
| review | `reviewed_at`, `reviewed_by` |
| evidence | `consent_evidence_refs`; source flag object의 `evidence_refs` |
| version/revision | `schema_version`, `producer.version`; authority revision·sequence·current marker 없음 |
| revocation | `rights_status=revoked`; revoke command·effective timestamp·replacement link 없음 |

- [현재] Dataset training Gate는 status가 `approved|approved_limited`, `training_allowed=true`, structured
  `retention_allowed.allowed=true`, `scope=training`, timezone-aware expiry가 `evaluated_at`보다 뒤인 경우만 허용한다.
- [현재] missing과 `unknown|pending_review|rejected|expired|revoked`, Boolean retention, malformed·naive·expired retention은 fail
  closed다. analysis permission은 training permission이 아니다.
- [현재] `valid_from`, generic `valid_until`, `supersedes`, authority revision, canonical resource fingerprint와 candidate ID는 없다.

### TrainingEligibility v1

| 구분 | 실제 계약 |
|---|---|
| resource identity | envelope `object_id`와 `training_eligibility_id`; validator가 equality 강제 |
| candidate binding | `candidate_id`, `candidate_status`, `rights_metadata_id` |
| Dataset/member binding | DatasetVersion identity·member ID 직접 field 없음; coordinator와 Dataset scenario가 결속 |
| producer/audit | envelope `producer{name,version}`, `created_by`, `created_at` |
| workspace | optional envelope `workspace_id` |
| purpose/task | `usage_purpose`; task field 없음 |
| decision | `eligible`, `ineligible`, `needs_review`, `revoked` |
| review/expiry | `reviewed_by`, `reviewed_at`, timezone-aware `expires_at` |
| policy/evidence | `policy_version`, 10개 typed `checks`, `reason_codes`, linked `rights_metadata_id` |
| version/revision | `schema_version`, `policy_version`, `producer.version`; authority revision·sequence·current marker 없음 |
| revocation | `decision=revoked`; revoke command·effective timestamp·replacement link 없음 |

- [현재] `training_allowed=true`이면 `approved=true`, `candidate_status=approved`, `decision=eligible`이고 모든 check가 `pass`여야 한다.
- [현재] Dataset Gate는 `(candidate_id, usage_purpose)`마다 정확히 한 decision만 허용한다. 두 개 이상이면 object ID나 timestamp
  순서와 무관하게 fail closed한다.
- [현재] eligibility expiry가 `evaluated_at` 이하이거나 linked RightsMetadata가 training Gate를 통과하지 못하면 Dataset 전체가
  fail closed한다.
- [현재] `valid_from`, generic `valid_until`, `supersedes`, authority revision, current marker와 canonical resource fingerprint는 없다.

### Common package 역할

- [현재] Common은 schema, offline registry, version policy, object/scenario validator와 synthetic fixture의 owner다.
- [현재] Common은 Runtime, API, database, Dataset pipeline, producer, persistence, current selector, revoke writer 또는 external read
  service를 구현하지 않는다. schema `$id`도 network endpoint가 아니다.
- [제안] Common canonical payload schema는 현재 그대로 사용할 수 있다. authority revision·projection·snapshot metadata는
  canonical resource와 구분된 source read envelope로 먼저 설계한다. Common schema 변경이나 새 bundle resource가 실제로 필요한지는
  source owner와 snapshot model이 결정된 뒤 별도 Common Gate에서 판단한다.

## Producer와 authority inventory

### DohaLM

- [현재] `validate_rights_metadata()`와 `validate_training_eligibility()`는 payload를 변경하지 않는 Common validator adapter다.
- [현재] Candidate Consumer·Review·Handoff·Composition은 caller가 이미 가진 canonical objects를 검증하고 safe identity·producer
  binding을 보존한다. create, issue, persist, update, revoke 또는 authoritative current lookup을 수행하지 않는다.
- [현재] `DatasetProposalCurrentEvidenceAuthority`와 `LearningCandidateReviewAuthority`의 production implementation은 0이다.
- [현재] Proposal·Review PostgreSQL authority는 Dataset lifecycle만 소유하며 RightsMetadata·TrainingEligibility table, writer,
  projection 또는 read function을 소유하지 않는다.
- [현재] fixture, fake, test constructor, legacy approval/readiness evidence와 caller-provided `upstream_objects`는 production producer나
  authority가 아니다.

### 접근 가능한 DohaStudio 저장소

조사한 default/pinned revision은 다음과 같다.

| repository | revision | 결과 |
|---|---|---|
| `DohaStudio/DohaMusic` | `63633d462043ad3ba78fee92473d19e90c361431` | consent-gated voice profile/enrollment persistence는 있으나 Common dependency·RightsMetadata producer/read/revoke 0 |
| `DohaStudio/DohaVocal` | `932466adb435b2a987baacdbefd2361470a2a7fa` | canonical resource producer·authority 0 |
| `DohaStudio/DohaMusicBook` | `4235b9d8e262d3a6155b125aaa3688d29099837a` | 교육 문서의 RightsMetadata 언급만 존재; implementation 0 |
| `DohaStudio/DohaAudio` | `5133c49c91c4928878d254de47bd0c0c39d21358` | canonical resource producer·authority 0 |
| `DohaStudio/.github` | `dd75fc88c16e9ae9a04acfafb72756a905f6365b` | schema·validator·specification owner; producer·storage·read service 0 |

- [현재] DohaMusic의 consent boolean, policy version, voice profile row와 delete API는 Common RightsMetadata가 아니다. canonical
  identity, full rights scope, immutable evidence reference, append-only revoke/current projection과 Common validation을 제공하지 않는다.
- [현재] 접근 가능한 구현에서 TrainingEligibility producer, durable store, current read와 revoke/re-review writer도 찾지 못했다.

## Ownership과 writer 결정

### RightsMetadata

- [제안] business domain은 Rights/Licensing·Consent Review 계층이어야 하며 DohaLM Dataset Governance가 편의상 소유하지 않는다.
- [현재] ADR-014의 DohaMusic 방향은 draft proposal이고 DohaMusic default branch에는 canonical producer가 없다. accountable
  cross-repository owner 승인, producer workflow와 운영 legal/reviewer authority가 없으므로 구체 owner는 차단 상태다.
- [제안] create writer, revoke writer와 replacement writer는 같은 accountable Rights authority가 승인된 command/event 계약으로
  소유해야 한다. 현재 세 writer 모두 미정이다.

### TrainingEligibility

- [제안] business owner는 DohaLM Dataset Governance다. Common의 domain 책임과 ADR-014의 Dataset boundary에 일치한다.
- [제안] `C. NEW PRODUCER REQUIRED`: approved candidate와 authoritative current rights·review·policy를 입력으로 새 immutable
  eligibility decision을 발행하는 DohaLM producer가 필요하다.
- [제안] `A. DOHALM-OWNED`: durable history, current projection, decision/revoke/re-review writer와 authenticated read authority는
  DohaLM Dataset Governance가 소유해야 한다. 이는 구현 완료를 뜻하지 않는다.
- [제안] decision, revoke와 re-review는 기존 Common object를 UPDATE하지 않고 각각 새 immutable decision/event와 projection
  update로 표현한다. exact event schema와 transaction은 별도 구현 전 ADR이 필요하다.

### Producer와 authority 분리

- [제안] producer workflow와 read authority는 같은 process일 필요가 없다. producer는 검토·판정과 새 immutable resource 발행을,
  durable authority는 history·unique-current projection·authenticated read를 소유한다.
- [제안] canonical payload를 만드는 producer가 database connection, current selector 또는 DohaLM coordinator 역할까지 직접
  노출하지 않는다.

## Storage, current projection과 revocation

### Storage model

- [제안] 두 resource 모두 **immutable history + authoritative current projection** 원칙을 사용한다. mutable current row만 UPDATE해
  history를 잃거나 timestamp last-write-wins로 판정하는 모델은 채택하지 않는다.
- [제안] history resource는 발행 뒤 immutable이고 revoke·re-review·replacement는 새 authority event/resource다. projection은
  logical key별 선택된 immutable resource와 authority revision을 가리킨다.
- [현재] Common v1에는 ordering, supersession, unique-current marker나 authority revision이 없다. 따라서 이 원칙만으로 selector를
  구현할 수 없으며 projection protocol은 차단 상태다.

### Logical key와 unique-current invariant

- [제안] Rights logical key는 source/candidate ownership contract가 결정해야 한다. RightsMetadata schema 자체에 candidate ID가
  없으므로 `(candidate_id, purpose)`를 Rights authority key로 임의 채택하지 않는다.
- [제안] Eligibility logical key는 최소 `(candidate_id, usage_purpose)`다. workspace scope가 있으면 authority key와 authorization
  scope에 반드시 포함한다. task는 Common Eligibility field가 아니므로 source key에 암묵적으로 추가하지 않는다.
- [제안] projection은 logical key마다 at most one current immutable resource를 반환해야 한다. 두 current 후보, missing projection,
  broken revision chain과 resource/projection mismatch는 fail closed다.
- [제안] `max(created_at)`, latest `reviewed_at`, array order, filesystem mtime, ingestion order와 process-local last write는 금지한다.

### Revocation과 expiry

- [현재] expiry는 `evaluated_at`과 Rights retention expiry 또는 Eligibility `expires_at`의 시간 비교다.
- [현재] revocation은 authority action의 결과인 `rights_status=revoked` 또는 `decision=revoked`다. expiry와 같은 event로 취급하지
  않는다.
- [제안] future authority는 revoke command의 authenticated writer, immutable revoke event, projection update의 atomicity와
  replacement 허용 규칙을 함께 결정해야 한다. Common payload에 없는 effective timestamp를 발명하지 않는다.
- [제안] Rights revocation은 linked Eligibility의 재평가를 촉발해야 하지만 기존 eligibility를 수정하지 않는다. 새 revoked 또는
  replacement decision과 projection 전이는 Eligibility authority가 소유한다.

## Currentness algorithm과 historical time

[제안] future DohaLM coordinator는 한 lifecycle invocation에서 다음 순서를 지킨다.

1. canonical proposal과 member binding에서 exact candidate, Rights ID, Eligibility ID, producer, workspace, purpose와 task를 고정한다.
2. authority가 보증하는 unique-current projection/snapshot에서 exact canonical resources를 resolve한다.
3. Common package·policy·schema compatibility와 canonical object validation을 수행한다.
4. projection identity·authority revision과 resource identity·producer·workspace를 검증한다.
5. Rights/Eligibility revocation을 판정한다.
6. explicit lifecycle `evaluated_at`으로 created/reviewed future evidence와 expiry를 판정한다.
7. candidate·rights·eligibility, usage purpose·task와 proposal member binding을 검증한다.
8. snapshot consistency와 proposal fingerprint binding을 검증한 뒤 typed Dataset evidence decision을 반환한다.

- [제안] `evaluated_at`은 Proposal create, Review Start, Approval 또는 Publication invocation의 explicit lifecycle action time이다.
  arbitrary historical time-travel query를 승인하지 않는다.
- [현재] port는 timezone-aware 값만 검사하고 trusted-now, maximum skew 또는 historical mode를 구분하지 않는다. production entrypoint가
  old timestamp로 currentness를 우회하지 못하게 하는 time authority/maximum-skew 계약은 별도 runtime input Gate로 남는다.
- [제안] source는 caller가 요청한 과거 시각에 맞춰 임의 historical record를 선택하지 않는다. historical audit read가 필요해지면
  current decision port와 분리된 read-only contract로 결정한다.

## Read, authentication과 data minimization

### Read request와 result

- [제안] source-level request는 exact resource/logical identity, workspace scope와 `evaluated_at`만 받는다. candidate·purpose binding이
  source logical key이면 그 authority contract에 명시한다.
- [제안] DatasetVersion identity, member task와 proposal fingerprint는 DohaLM coordinator-level binding이다. source storage key로
  자동 승격하지 않는다.
- [제안] 최소 source result는 unchanged canonical resource, selected resource identity, safe authority reference, positive immutable
  authority revision과 선택된 snapshot/reference다. raw DB row, SQL, credential, private path와 internal topology를 노출하지 않는다.
- [현재] exact symbol, transport와 result envelope는 source/snapshot owner가 미정이므로 구현 이름으로 고정하지 않는다.

### Authentication과 authorization

- [제안] public anonymous read는 금지한다. authority는 authenticated service identity 또는 fixed least-privilege DB role처럼
  검증 가능한 principal을 요구해야 한다.
- [제안] source authority가 resource와 workspace authorization을 강제한다. runtime secret이 scoped capability가 되려면 role/service
  policy가 그 scope를 실제로 제한해야 하며 단순히 secret을 소유했다는 사실만으로 authorization을 주장하지 않는다.
- [제안] DohaLM Eligibility authority는 Proposal·Review role과 분리된 read/write 역할이 필요할 가능성이 높지만 role 이름,
  migration과 grant는 구현 Gate 전 결정하지 않는다.
- [현재] Rights source가 없어 service credential, mTLS, DB role 또는 protected IPC 중 하나를 선택할 근거가 없다. authenticated read
  interface owner는 차단 상태다.

### Data minimization

- [제안] adapter/coordinator는 canonical resource와 safe authority metadata만 메모리에서 소비한다. raw legal/consent body, PII,
  credential, filesystem path, internal SQL, unrelated workspace resource와 source topology를 result·error·log·publication에 저장하지
  않는다.
- [제안] consent는 opaque `consent_evidence_refs`로만 결속하고 원문을 가져오지 않는다.

## Availability, cache, restart와 multi-worker

- [제안] source timeout, unavailable, corrupt result와 authorization failure는 fail closed다. fallback source와 caller payload를
  사용하지 않는다.
- [제안] cache 판정은 `A. NO CACHE`다. source/snapshot contract가 생기기 전 read-through, TTL, stale, process-local 또는
  cross-invocation cache를 승인하지 않는다. future snapshot cache는 immutable snapshot ID 검증 계약이 있을 때 별도 검토한다.
- [제안] hidden retry로 두 번 읽어 결과가 같으면 snapshot으로 인정하지 않는다. transport retry는 같은 immutable snapshot token을
  유지하는 idempotent read 계약이 생긴 뒤에만 bounded policy로 결정한다.
- [제안] restart와 multi-worker에서 같은 exact input·authority snapshot은 같은 resource IDs, revisions와 decision을 반환해야 한다.
  process-local mapping, worker-local selection과 global hidden singleton은 금지한다.
- [현재] source와 projection이 없으므로 이 결정론·availability 요구는 미충족이다.

## Snapshot consistency와 atomicity

### Snapshot model matrix

| 항목 | Same datastore transaction | Independent authorities + revision token | Evidence bundle/snapshot | Independent read |
|---|---|---|---|---|
| consistency | 단일 transaction snapshot이면 강함 | comparable token·binding이 있을 때 강함 | bundle authority가 atomic snapshot을 발행하면 강함 | revocation race를 검출하지 못함 |
| cross-source | owner/storage 통합 또는 복제 필요 | owner 분리 유지 가능 | owner 분리 가능하나 bundle issuer 필요 | source별 의미 분리 |
| complexity | 운영·ownership 결합 높음 | revision/barrier protocol 높음 | 새 resource·issuer·lifecycle 높음 | 낮지만 안전하지 않음 |
| availability | 한 DB failure domain | 양쪽 source와 token 검증 필요 | bundle authority 의존 | 부분 성공이 모순을 숨김 |
| TOCTOU | transaction 안에서는 제어 가능 | commit 전 token 유효성 확인 필요 | immutable bundle binding 필요 | 제어 불가 |
| publication suitability | 같은 transaction에 filesystem commit을 넣을 수 없어 추가 binding 필요 | token을 pair에 결속하면 후보 | snapshot ID를 pair에 결속하면 후보 | 부적합 |

- [제안] Model D independent read는 기각한다. Rights read 뒤 revoke되고 Eligibility read가 성공하는 실행을 current로 승인할 수 없다.
- [현재] Model A는 cross-owner 방향과 충돌하고 distributed filesystem publication까지 atomic하게 만들지 못한다. Model B에는
  comparable authority revision/barrier가 없고 Model C에는 bundle owner·schema·issuer가 없다.
- [제안] 최종 Snapshot Model은 `BLOCKED`다. B 또는 C를 선택하려면 Rights owner, Eligibility projection과 publication binding을
  함께 승인해야 한다. 숨은 retry나 timestamp equality는 snapshot token이 아니다.

### Operation별 consistency와 race

- [제안] Proposal create, Review Start, Approval과 Publication 모두 한 invocation 안에서 Rights와 Eligibility가 같은 authoritative
  snapshot을 나타내야 한다.
- [제안] Proposal과 Review Start는 snapshot 뒤 revocation이 발생해도 historical lifecycle fact를 삭제하지 않고 후속 invocation이
  다시 검증한다. Approval은 transient라 restart 후 재사용하지 않는다. 이는 inconsistent two-read snapshot을 허용한다는 뜻이 아니다.
- [제안] Publication은 final frozen/issued pair를 durable authority로 만들기 때문에 가장 강한 binding이 필요하다. validation 뒤
  revoke와 filesystem commit 사이의 unbound window를 단순히 짧다고 승인하지 않는다.
- [제안] distributed transaction을 기본 요구하지 않는다. 선택된 revision/snapshot token을 evidence decision과 final publication
  identity에 결속하고, source contract가 요구하면 commit 직전 같은 token의 유효성을 확인하는 방식이 후보다. exact protocol은
  Snapshot Model 결정 전 확정하지 않는다.

## Publication binding과 fingerprint

- [현재] DatasetVersion extension의 member binding은 Rights/Eligibility ID와 producer를 보존하지만 두 canonical resource의 bytes,
  resource fingerprint, authority revision 또는 snapshot token은 보존하지 않는다.
- [현재] Publication scenario의 `upstream_objects`는 validation 입력일 뿐 final `dataset-version.json`과
  `dataset-manifest.json`에 저장되지 않는다. pair fingerprint도 frozen Version과 issued Manifest만 포함한다.
- [현재] 따라서 current decision 뒤 revoke가 발생해도 final pair가 검증한 exact authority snapshot을 독립적으로 증명하지 못한다.
- [제안] source/snapshot contract가 정해지면 ADR-015 Publication contract 변경 Gate에서 snapshot/reference와 필요한 immutable
  evidence identity를 final pair fingerprint/lineage에 어떻게 결속할지 결정해야 한다. 기존 payload field를 임의 추가하거나
  private storage file을 늘리지 않는다.
- [제안] 지금 combined evidence fingerprint를 새로 만들지 않는다. Common Rights/Eligibility에는 canonical content fingerprint가
  없고 local checksum만으로 current authority를 증명할 수 없다. future source가 canonical resource fingerprint를 정의하면 그대로
  재사용하고, combined fingerprint는 source revisions·snapshot token·`evaluated_at`·member binding의 projection으로 별도 검토한다.

## DohaLM ownership boundary

| concern | owner decision |
|---|---|
| Rights production·legal decision·storage·revocation | external Rights authority; accountable owner는 현재 BLOCKED |
| Eligibility production·history·projection·revocation | new DohaLM Dataset Governance producer/authority REQUIRED |
| Common schema·validator | Common package; source authority 아님 |
| source-specific current selection | 각 authority source; DohaLM coordinator가 timestamp로 대체하지 않음 |
| cross-source snapshot | 미정 snapshot authority/protocol; BLOCKED |
| Common validation·member/workspace/purpose/task binding | DohaLM CurrentEvidence coordinator |
| proposal fingerprint와 typed decision binding | DohaLM CurrentEvidence coordinator |
| publication snapshot binding | DohaLM Publication boundary, ADR-015 amendment 필요 가능 |

## Decision matrices

### RightsMetadata

| 항목 | DohaLM-owned | External Authority | Registry | BLOCKED |
|---|---|---|---|---|
| producer ownership | domain 침범 | Rights/Licensing 방향과 일치 | workflow owner 없음 | accountable external owner 미승인 |
| writer | 편의상 생성 금지 | create/revoke/replacement 후보 | writer trust 없음 | actual writer 0 |
| revocation | upstream legal action 복제 위험 | owner가 소유해야 함 | event protocol 없음 | revoke writer 미정 |
| current selection | source 의미를 추정함 | source projection 후보 | latest-wins 위험 | logical key·revision 미정 |
| durability | 복제 DB가 이중 SoT | external durable history 후보 | 파일 durability 미정 | source 0 |
| restart | DB 구현 시 가능 | source가 보장하면 가능 | 계약 필요 | 현재 불가 |
| multi-worker | DB transaction 필요 | source consistency 필요 | lock 필요 | 현재 불가 |
| snapshot support | Eligibility와 결합은 쉽지만 ownership 위반 | token/bundle 필요 | snapshot contract 없음 | 미정 |
| security | legal evidence 복제·권한 확대 | authenticated scoped read 필요 | ACL만으로 부족 | trust anchor 없음 |
| duplication risk | 높음 | 낮을 수 있음 | stale duplicate 높음 | 판단 보류 |

### TrainingEligibility

| 항목 | DohaLM-owned | External Authority | Registry | BLOCKED |
|---|---|---|---|---|
| producer ownership | Dataset Governance와 일치; 신규 필요 | domain owner와 불일치 | workflow owner 없음 | 구현은 아직 0 |
| writer | decision/revoke/re-review 역할 필요 | cross-repo 위임 근거 없음 | writer trust 없음 | exact contract 미정 |
| revocation | 새 decision/event로 가능 | 책임 분산 | protocol 없음 | 구현 미정 |
| current selection | `(candidate_id, usage_purpose[, workspace])` projection 후보 | 불필요한 외부화 | duplicate fail-closed만 가능 | revision/current marker 없음 |
| durability | immutable history+projection 후보 | 운영 경계 증가 | 파일 concurrency 미정 | 구현 0 |
| restart | durable authority 구현 시 가능 | source SLA 필요 | 계약 필요 | 현재 불가 |
| multi-worker | DB uniqueness/projection 필요 | cross-source consistency 필요 | lock 필요 | 현재 불가 |
| snapshot support | Rights token을 bind하는 projection 필요 | 두 external source가 됨 | snapshot contract 없음 | 현재 미정 |
| security | dedicated scoped roles 후보 | service trust 추가 | ACL만으로 부족 | role/grant 미정 |
| duplication risk | domain SoT와 일치 | 높음 | stale duplicate 높음 | 판단 보류 |

## Final decisions

| 결정 | 판정 |
|---|---|
| RightsMetadata Producer | `D. PRODUCER OWNERSHIP BLOCKED` |
| RightsMetadata Durable Authority | `D. AUTHORITY BLOCKED` |
| TrainingEligibility Producer | `C. NEW PRODUCER REQUIRED` |
| TrainingEligibility Durable Authority | `A. DOHALM-OWNED` |
| Current Projection | `D. CURRENT PROJECTION BLOCKED` |
| Snapshot Model | `BLOCKED`; revision token 또는 evidence bundle은 후속 후보일 뿐 미선택 |
| 전체 CurrentEvidence architecture | `STILL BLOCKED` |

`READY FOR PORT/ADAPTER DESIGN`으로 전환하려면 Rights accountable owner·writer·durable authority, 두 source의 immutable history와
unique-current projection, authenticated scoped read, selected cross-source snapshot model과 Publication binding이 모두 승인돼야 한다.

## Cross-repository changes와 후속 Gate

1. [차단] Rights/Licensing accountable repository와 create/revoke/replacement writer를 cross-repository decision으로 승인한다.
2. [차단] 그 repository에서 immutable Rights history, unique-current projection, authenticated scoped read와 revision/snapshot
   contract를 설계·구현한다.
3. [계획] DohaLM TrainingEligibility producer·immutable history/current projection·writer/read authority ADR을 작성한다. Rights
   source와 snapshot contract 승인 전 migration·adapter 구현은 시작하지 않는다.
4. [차단] independent revision token 또는 authoritative evidence bundle 중 cross-source snapshot model을 선택한다.
5. [계획] 선택한 snapshot을 CurrentEvidence decision port와 ADR-015 publication pair에 결속하는 변경 Gate를 수행한다.
6. [후순위] 위 architecture가 승인된 뒤 governance runtime config, source adapter/coordinator와 read-only preflight를 구현한다.

- [현재] Common canonical schema 변경은 지금 필수로 판정하지 않는다. 새 Common bundle resource 또는 canonical authority metadata가
  필요해지면 `DohaStudio/.github` 변경은 별도 ADR·PR·version compatibility 검토가 필요하다.
- [제안] DohaMusic의 현재 consent table을 자동 migration·wrapper로 승격하지 않는다. 실제 Rights owner로 승인되더라도 canonical
  producer와 immutable authority migration은 별도 작업이다.
- [제외] 이번 Gate에서 다른 repository를 수정하거나 PR을 생성하지 않는다.

## Excluded scope

- [제외] production producer, source, migration, database role, adapter, coordinator와 cache 구현
- [제외] governance runtime config/factory/preflight 구현
- [제외] CLI, API, worker, Training, Evaluation과 promotion activation
- [제외] Common schema/resource/version 변경과 다른 repository 변경
- [제외] reviewer roster, legal process, IAM과 secret provisioning 구현

## Acceptance and approval Gate

- [제안] exact Common fields와 validator invariant를 기록하고 없는 field를 발명하지 않았다.
- [제안] fixture, Common validator와 DohaMusic consent row를 production authority로 오인하지 않았다.
- [제안] producer, writer, durable authority, projection, snapshot, TOCTOU와 publication binding을 분리했다.
- [제안] unresolved cross-repository ownership과 snapshot을 숨기지 않고 전체를 `STILL BLOCKED`로 유지한다.
- [제안] source·test·migration·runtime·CLI/API/worker 변경은 0이어야 한다.

이 ADR은 `draft`·`proposed`다. 독립 검토, 사용자 명시 승인과 병합 전에는 authoritative implementation requirement가 아니다.
병합되더라도 producer, authority, port/adapter design, runtime activation 또는 Training을 승인하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-25 | [제안] Rights producer/authority와 cross-source projection/snapshot을 BLOCKED, 새 DohaLM TrainingEligibility producer·authority를 REQUIRED로 판정 |
