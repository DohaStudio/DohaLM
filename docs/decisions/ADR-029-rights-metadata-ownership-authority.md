# ADR-029: RightsMetadata producer와 authority ownership 경계

- 문서 상태: `draft`
- 마지막 검토일: 2026-08-25
- 결정 상태: `proposed`
- 실행 영향: 없음
- 기준 DohaLM commit: `5127d594869b289ec60ed414dcdfcd22b32bb031`
- 기준 DohaLM tree: `bc023d67b95e56c8e0699ee81925a4b1cd653011`
- Common 권위 기준: `DohaStudio/.github@dd75fc88c16e9ae9a04acfafb72756a905f6365b`
- package: `dohastudio-common-ai-contracts==0.1.0`
- 선행 ADR: [ADR-014](./ADR-014-dataset-product-governance-boundary.md),
  [ADR-015](./ADR-015-dataset-version-publication-contract.md),
  [ADR-025](./ADR-025-dataset-version-proposal-authority-contract.md),
  [ADR-026](./ADR-026-dataset-review-authority-contract.md),
  [ADR-027](./ADR-027-dataset-governance-production-prerequisites.md),
  [ADR-028](./ADR-028-current-evidence-source-authority.md)
- 관련 문서: [데이터 라이선스 정책](../data/data-license-policy.md),
  [제품 지속 학습 경계](../project/ai-music-director-continuous-learning.md)

## Context

[현재] ADR-028은 RightsMetadata producer를 `D. PRODUCER OWNERSHIP BLOCKED`, durable authority를
`D. AUTHORITY BLOCKED`, current projection을 `D. CURRENT PROJECTION BLOCKED`로 판정했다. 이 Gate는 구현을
시작하지 않고 accountable business owner, create·replacement·revoke writer, logical identity, durable authority와
authenticated read owner를 결정할 근거가 실제로 있는지 조사한다.

[현재] Common authority 문서는 DohaMusic이 사용자 작업과 Rights·Provenance·Consent를 소유하는 방향을 제안한다. 그러나
DohaLM의 ADR-014, DohaVocal의 Consent 문서와 DohaMusic의 voice consent policy는 모두 구체적인 canonical RightsMetadata
producer·전체 source 유형의 business owner·운영 legal actor를 승인한 계약이 아니다. repository 방향을 조직적으로 승인된
accountable owner로 확대 해석하지 않는다.

[현재] 이번 조사에서 production source, test, migration, runtime, CLI/API/worker와 다른 repository는 변경하지 않는다.
접근 가능한 저장소와 Common package를 읽기 전용으로 조사하고 문서만 변경한다.

## RightsMetadata domain semantic

[현재] Common RightsMetadata는 특정 Dataset의 승인 객체가 아니라 source/reference의 목적별 권리 판정이다. canonical payload는
다음을 증명한다.

- envelope `object_id`, `created_at`, `created_by`, `producer`와 optional `workspace_id`
- `rights_metadata_id`, `user_created|generated|reference|uploaded|external|mixed` source type과
  `unknown|pending_review|approved_limited|approved|rejected|expired|revoked` rights status
- user-created/generated/reference/uploaded/external source flags와 각 flag의 optional evidence refs
- analysis, training, redistribution, derivative-generation 허용 상태
- consent evidence reference, jurisdiction, reviewer와 review 시각
- Boolean 또는 목적 scope와 expiry를 가진 structured retention 판정; current Dataset Gate는 structured form만 허용

[현재] `producer`는 canonical object를 누가 어떤 version으로 발행했는지 나타내며 business owner, reviewer, database owner 또는
current selector를 대신하지 않는다. `reviewed_by`는 검토 metadata이지 인증된 writer 권한이나 IAM principal의 증거가 아니다.
`rights_status=revoked`는 권리 판정 결과지만 revoke command, effective revision과 current projection을 정의하지 않는다.

[현재] Common RightsMetadata에는 candidate identity, DatasetVersionIdentity, task, authority revision, supersedes, current marker,
snapshot token과 authority reference가 없다. Dataset Governance 편의를 위해 이를 canonical payload에 추정·삽입하지 않는다.

## Dataset-level binding과 현재 relation

[현재] LearningCandidate가 `rights_metadata_id`와 opaque `consent_evidence_refs`를 직접 참조한다. TrainingEligibility도
`candidate_id`와 같은 `rights_metadata_id`를 참조한다. DohaLM Candidate Consumer·Review·Handoff·Composition은 다음 상위
관계로 exact binding을 검증한다.

```text
LearningCandidate.rights_metadata_id
  == RightsMetadata.object_id
  == RightsMetadata.rights_metadata_id
  == TrainingEligibility.rights_metadata_id
```

[현재] Product Dataset member binding은 candidate ID, RightsMetadata ID, TrainingEligibility ID와 producer를 보존한다.
DatasetVersionIdentity, member task와 proposal fingerprint는 DohaLM coordinator-level binding이며 Rights authority lookup key가
아니다. 별도 production mapping table이나 source artifact가 RightsMetadata ID를 authoritative하게 소유하는 구현은 찾지 못했다.

[제안] direct candidate field를 RightsMetadata에 추가하지 않는다. candidate가 특정 historical Rights resource ID를 참조하는
관계와 그 resource chain에서 무엇이 current인지 판정하는 source authority는 별도 책임이다.

## Producer와 repository inventory

조사 기준은 test, fixture, example과 schema validator를 제외한 production constructor, consent ingestion, licensing workflow,
copyright review, source registration, asset import, data intake, rights validation, revoke/withdraw와 replacement path다.

| repository | 조사 commit | consumer | canonical producer/writer | read authority | revoke path·business owner 근거 |
|---|---|---|---|---|---|
| `DohaStudio/DohaLM` | `5127d594869b289ec60ed414dcdfcd22b32bb031` | Common validator, candidate·Dataset binding | 0 | Protocol만 존재 | 데이터 라이선스 검토는 있으나 Common Rights authority가 아님 |
| `DohaStudio/DohaMusic` | `63633d462043ad3ba78fee92473d19e90c361431` | Common consumer 0 | canonical producer 0 | canonical read 0 | voice consent boolean·policy/time 저장과 profile 삭제는 구현; 전용 withdrawal/revoked state·감사 흐름은 미구현 |
| `DohaStudio/DohaVocal` | `932466adb435b2a987baacdbefd2361470a2a7fa` | 문서상 Consent gate | 0 | 0 | 제안 문서가 Consent 결정을 DohaMusic에 두지만 Dataset 기술 계보만 소유 |
| `DohaStudio/DohaAudio` | `5133c49c91c4928878d254de47bd0c0c39d21358` | 0 | 0 | 0 | source-level Rights/Consent domain 근거 0 |
| `DohaStudio/DohaMusicBook` | `4235b9d8e262d3a6155b125aaa3688d29099837a` | 문서 참조 범위 | 0 | 0 | source-level authority 근거 0 |
| `DohaStudio/.github` Common | `dd75fc88c16e9ae9a04acfafb72756a905f6365b` | schema·validator·version policy | product producer 아님 | runtime read service 아님 | repository 방향 문서는 있으나 DB·workflow·IAM을 소유하지 않음 |

[현재] 접근 가능한 조직 저장소는 위 여섯 개이며 별도 workspace/source registry repository는 찾지 못했다. private 또는
unavailable repository와 조직의 실제 legal ownership은 code search만으로 부재를 증명할 수 없다.

[현재] DohaMusic의 voice consent row는 subject/resource scope, complete rights flags, canonical identity, immutable replacement,
revoked state, Common validation과 current projection이 없으므로 RightsMetadata producer가 아니다. physical profile 삭제도
canonical revoke event 또는 replacement Rights resource 발행과 같지 않다.

## Source-level과 Dataset-level ownership

| 항목 | Source-level authority | DohaLM Dataset-level copy |
|---|---|---|
| source of truth | source 권리·consent가 발생한 domain | upstream truth를 복제함 |
| revoke propagation | upstream projection에서 즉시 current 판정 가능 | 동기화 지연과 누락 위험 |
| multi-product reuse | Audio·Vocal·Music·LM이 같은 resource reference 사용 가능 | Dataset별 중복 판정 |
| DatasetVersion binding | exact historical resource ID를 참조 | local surrogate가 upstream identity를 가림 |
| 운영 비용 | cross-repository contract와 authenticated read 필요 | local lookup은 단순하나 이중 SoT·drift 비용이 큼 |

[제안] Model A인 source-level Rights Authority가 책임 방향으로 적합하다. DohaLM이 candidate 또는 Dataset proposal 시점에
RightsMetadata를 복제·생성하는 Model B는 기각한다. Dataset proposal은 권리를 추론해 만드는 event가 아니며 existing source
판정을 read-only로 검증해야 한다.

[현재] 적합한 방향이 곧 accountable owner의 승인 증거는 아니다. Common 문서의 DohaMusic 방향, voice-only consent 구현과
DohaVocal 제안만으로 모든 audio/vocal/music/imported source의 create policy, retention, revoke, audit와 authorization 책임을
DohaMusic 운영 domain에 확정할 수 없다.

## Business owner와 writer 판정

### Accountable business owner

[현재] DohaLM 데이터 라이선스 정책은 provider·이용조건·목적·삭제·reviewer 기록을 요구하지만 승인 책임자와 법률 검토
escalation은 `[검증 필요]`다. DohaMusic voice policy도 인증, consent record, withdrawal·audit을 공개 운영 선행 조건으로 남긴다.

[제안] 최종 Business Owner 판정은 `D. OWNER BLOCKED`다. `B. EXISTING DOHASTUDIO RIGHTS/CONSENT OWNER`는 문서 방향상
후보이나, 다음 책임을 가진 accountable domain이 승인되지 않았다.

- source 유형별 create와 replacement policy
- consent withdrawal, license cancellation·expiry, legal takedown과 ownership correction
- retention·deletion semantics와 historical audit
- producer·reviewer·revoke actor authorization
- workspace/resource scoped read authorization

`C. NEW CROSS-REPOSITORY RIGHTS DOMAIN REQUIRED`도 후보지만 이번 Gate가 새 조직 owner를 발명하거나 지정하지 않는다.

### Create writer

[현재] canonical RightsMetadata production constructor는 0이다. source ingest, rights review, consent review와 manual operator 중
어느 event가 canonical issue를 허용하는지 승인된 계약이 없다.

[제안] Create Writer는 `BLOCKED`다. Dataset proposal, Dataset ingestion adapter, Common validator와 fixture는 writer가 될 수 없다.
owner가 승인되면 owner domain의 authenticated rights/consent review event가 새 immutable canonical resource를 발행하는 후보다.

### Replacement writer

[제안] Replacement Writer는 `BLOCKED`다. 기존 row UPDATE나 timestamp latest-wins는 금지하고 새 immutable RightsMetadata와
authority-owned supersession metadata를 발행해야 하지만, actor·predecessor chain·revision contract가 없다.

### Revocation owner와 trigger

[현재] 실제 문서에 존재하는 trigger는 consent withdrawal, license expiry/cancellation, legal takedown, source ownership correction,
compliance decision과 데이터 삭제 요청이다. DohaMusic voice policy는 withdrawal 전용 API와 revoked state가 미구현임을 명시한다.

[제안] Revocation Owner는 `D. REVOCATION OWNER BLOCKED`다. 권리 검토자, consent owner, legal/operator authority와 source owner
중 누가 어떤 trigger를 인증하고 새 revoked resource/event를 발행하는지 조직 결정이 없다. DohaLM training pipeline과 Dataset
Governance는 revoke writer가 아니다.

## Immutable history와 authority metadata

[제안] future Rights Authority는 canonical RightsMetadata resource를 발행 후 immutable하게 보존해야 한다. correction,
expiry 재검토, replacement와 revoke는 기존 payload UPDATE가 아니라 새 canonical resource 또는 immutable authority event다.

[제안] Common payload에 없는 authority metadata를 곧바로 Common schema에 추가하지 않는다. 최소 후보는 다음의 분리다.

| concern | 후보 위치 | 현재 판정 |
|---|---|---|
| canonical rights facts | unchanged Common RightsMetadata | 사용 가능 |
| authority reference·logical chain identity | authority envelope | owner/key 미정으로 BLOCKED |
| positive revision·predecessor relation | authority envelope/history record | BLOCKED |
| selected current resource·revoked projection | projection table 또는 service projection | BLOCKED |
| snapshot token | future service response/bundle | 이번 Gate 제외 |

[제안] authority envelope가 canonical payload를 감싸거나 참조할 수 있지만 payload key·value·type을 바꾸지 않아야 한다. raw DB row,
private path, credential, legal/consent 원문과 unrelated PII를 envelope/read result에 넣지 않는다.

## Current projection과 logical identity

[현재] Common schema에서 직접 표현되는 source-independent identity는 `rights_metadata_id`와 envelope `object_id`이며 validator가
둘의 equality를 강제한다. optional `workspace_id`는 authorization scope 후보일 뿐 source asset, consent subject 또는 replacement
chain identity가 아니다. `rights_metadata_id`는 immutable resource ID이므로 새 replacement resource들의 stable logical key로
재사용할 수 없다.

[현재] source asset ID, candidate ID, consent subject, `(workspace, source)`와 stable Rights chain identity 중 어느 것도
RightsMetadata v1만으로 완전하게 표현되지 않는다. candidate ID를 source key로 사용하면 source-level ownership을 Dataset
identity에 종속시키고 하나의 source가 여러 candidate에 사용되는 관계를 깨뜨린다. DatasetVersionIdentity와 task를 key에 넣지 않는다.

[제안] Logical Key는 `BLOCKED`다. owner의 source identity 계약 또는 authority envelope의 stable opaque chain reference가 먼저
승인돼야 한다. 이 결정을 피해 `max(created_at)`, latest `reviewed_at`, array order, filesystem mtime, ingestion order와
process-local last write를 selector로 사용하지 않는다.

[제안] 따라서 Current Projection Owner도 `BLOCKED`다. future owner는 logical key별 at most one current state, revision ordering,
replacement/revocation의 atomic projection update, read consistency와 corruption fail-closed를 함께 소유해야 한다.

## Unique-current, supersession과 revocation projection

- [제안] unique-current invariant는 승인된 logical key마다 at most one selected immutable resource 또는 explicit unusable state다.
- [제안] duplicate current, missing referenced resource, broken predecessor chain, non-positive revision과 projection/resource mismatch는
  fail closed다.
- [제안] supersession은 authority-owned positive revision sequence와 projection pointer 또는 explicit predecessor envelope 중
  승인된 계약으로 표현한다. timestamp-only supersession은 금지한다.
- [제안] revoke 결과는 current revoked RightsMetadata를 선택하거나 `revoked state + exact record reference`를 projection에서
  반환할 수 있다. 어느 형식을 채택할지는 owner contract 전 `BLOCKED`다.
- [제안] expiry는 `evaluated_at`과 structured retention expiry의 비교이며 revocation event를 대신하지 않는다.

## Durable authority와 storage

[제안] 최종 Durable Authority는 `D. AUTHORITY BLOCKED`다. Business Owner, logical key와 writer가 없으므로 owner PostgreSQL,
owner filesystem registry, service-managed DB와 shared registry 중 하나를 선택할 근거가 없다.

[제안] source-level owner가 승인된다면 owner-local immutable history와 current projection이 duplication risk가 가장 낮은 후보다.
DohaLM PostgreSQL에 Rights rows를 복제 저장하는 모델은 별도 sync authority 없이 이중 source of truth와 stale revoke를 만든다.
storage technology, migration, table/function, backup과 recovery는 다음 contract 이후 별도 구현 Gate다.

## Authenticated read boundary

[제안] 최종 Read Boundary는 `D. READ CONTRACT BLOCKED`다. public anonymous read와 caller-provided payload는 금지하지만 source가
없어 DB role, authenticated service read, immutable registry read 중 하나를 승인할 수 없다.

future read가 최소 보존해야 할 의미 후보는 다음과 같다.

- unchanged canonical RightsMetadata
- safe authority reference와 positive authority/projection revision
- selected resource ID와 workspace/resource authorization 결과
- 선택된 snapshot token이 있을 경우 그 opaque reference

[제안] raw internal row ID, SQL, DSN, password, private path, consent/legal 원문과 internal topology는 반환·오류·로그에 노출하지
않는다. source lookup request 후보는 owner가 승인한 logical/source reference, workspace scope, purpose와 explicit
`evaluated_at`이다. proposal fingerprint와 DatasetVersionIdentity는 source lookup key가 아니라 DohaLM coordinator binding이다.

## Service identity와 workspace authorization

[현재] dedicated DB read role, service credential, mTLS identity와 protected local IPC 중 하나를 선택할 runtime/IAM 근거가 없다.
DohaMusic local MVP는 인증이 없어 consent actor identity와 다른 workspace 접근을 안전하게 증명하지 못한다.

[제안] Service Identity와 Workspace Authorization Owner는 Business Owner의 authority contract에 포함되어야 하며 현재
`BLOCKED`다. opaque resource ID를 안다는 사실이나 process가 secret을 가진 사실만으로 다른 workspace read를 허용하지 않는다.
DohaLM은 read-only principal이어야 하며 create, replacement, revoke 또는 authority projection write 권한을 갖지 않는다.

## Availability와 cache

- [제안] authority unavailable, timeout, authorization failure, corrupt envelope와 unknown revision은 CurrentEvidence에서 fail closed다.
- [제안] Proposal, Review Start, Approval과 Publication도 current Rights를 얻지 못하면 fail closed다.
- [제안] stale cache 허용은 0이다. immutable snapshot identity와 revocation semantics가 승인되기 전 TTL/read-through/process-local
  fallback을 사용하지 않는다.
- [제안] caller payload, legacy license status, DohaMusic consent row와 fixture를 fallback authority로 사용하지 않는다.

## Common schema change

[현재] Common RightsMetadata v1은 canonical rights fact와 immutable resource identity를 표현하고 DohaLM validation에는 충분하다.
그러나 source logical key, authority revision, current selection과 supersession은 표현하지 않는다.

[제안] Common schema change 최종 판정은 `BLOCKED`다. owner의 source identity와 cross-repository interoperability 요구가
확정되지 않아 authority envelope만으로 충분한지, canonical Common extension이 필요한지 결정할 수 없다. 구현 편의를 위한
candidate/source field, revision, supersedes와 current marker 추가는 금지한다. Common 변경이 필요해지면 `.github` 별도 ADR·PR,
version compatibility와 consumer migration Gate를 거친다.

## TrainingEligibility linkage

[현재] TrainingEligibility는 exact historical RightsMetadata ID를 참조한다. linked Rights가 current projection에서 replacement 또는
revoked 상태가 되면 historical Eligibility payload를 수정하지 않고 current Dataset invocation을 fail closed하고 새 Eligibility
판정을 발행해야 한다.

[제안] Eligibility authority가 Rights logical key나 current selector를 추정하지 않는다. Rights read가 반환한 exact selected
resource·authority revision과 Eligibility decision의 Rights ID를 coordinator가 검증해야 한다. exact cross-source revision binding은
Snapshot Gate의 책임이다.

## Snapshot과 Publication TOCTOU 영향

[현재] Rights Authority가 revision/snapshot metadata를 제공하지 않으면 Eligibility와 같은 authoritative state인지 증명할 수 없다.
owner 결정과 snapshot protocol은 분리할 수 있지만 Rights contract는 최소 positive authority/projection revision을 반환할 수 있어야
후속 snapshot 모델의 입력이 된다.

[현재] Publication validation 뒤 filesystem commit 전에 Rights가 revoke될 수 있다. existing frozen Version/issued Manifest pair는
Rights authority revision이나 snapshot token을 보존하지 않는다.

[제안] 이번 Gate는 snapshot protocol과 ADR-015 payload/fingerprint 변경을 결정하지 않는다. Rights owner·logical key·authority
contract가 승인된 뒤 별도 CurrentEvidence Snapshot Architecture Gate와 Publication Binding Gate에서 commit 전 token validity,
final pair lineage와 replay semantics를 결정한다.

## Audit requirement

future authority는 최소 다음 질문에 답할 수 있어야 한다.

1. 어떤 logical source/chain에 어떤 Rights resource가 current였는가
2. 누가 어떤 producer version으로 canonical resource를 발행했는가
3. 어떤 authenticated actor가 어떤 근거로 revoke 또는 replacement를 승인했는가
4. 어떤 predecessor를 대체했고 projection revision이 어떻게 전이됐는가
5. DohaLM이 어떤 principal·workspace·purpose·revision에서 읽었는가

[현재] reviewer roster, legal escalation, audit retention과 actor identity source는 제품 문서에서 미정이다. 이 항목을
`reviewed_by` 문자열이나 OS/Git user로 추정하지 않는다.

## Decision matrices

### Ownership

| 항목 | DohaLM | Existing external owner | New Rights domain | BLOCKED |
|---|---|---|---|---|
| business fit | Dataset-only라 부적합 | Common 방향과 일부 voice consent 근거 | cross-product 방향에 적합 가능 | accountable approval 없음 |
| source-level semantics | upstream 의미를 복제 | 적합 가능 | 적합 가능 | source identity 미정 |
| consent ownership | legal/consent actor 아님 | DohaMusic voice 범위 후보 | 공통 owner 후보 | 전체 범위 미승인 |
| revocation | stale copy 위험 | withdrawal path 미완성 | 새 workflow 필요 | writer 미정 |
| duplication risk | 높음 | 낮을 수 있음 | 낮을 수 있음 | 비교 계약 미완성 |
| multi-product reuse | 낮음 | 높을 수 있음 | 높음 | 조직 경계 미승인 |
| security | 권한 확대 | 인증 없는 현재 구현 | 새 IAM 필요 | trust anchor 없음 |
| operational cost | local은 낮으나 drift 높음 | 기존 owner 확장 비용 | 가장 높음 | 산정 근거 없음 |

### Authority

| 항목 | Owner DB | Service API | Registry | BLOCKED |
|---|---|---|---|---|
| durability | transaction 후보 | service DB에 의존 | immutable file 후보 | owner/storage 미정 |
| current projection | unique constraint 후보 | service projection 후보 | pointer/CAS 필요 | logical key 미정 |
| revocation | atomic event+projection 후보 | command+projection 후보 | append/CAS 필요 | actor 미정 |
| revision metadata | envelope/table 후보 | response metadata 후보 | manifest 후보 | contract 미정 |
| workspace auth | role/RLS 후보 | service authorization 후보 | ACL만으로 부족 | principal owner 미정 |
| availability | DB failure domain | service failure domain | registry read failure | SLA 미정 |
| DohaLM integration | least-privilege port 후보 | authenticated read 후보 | immutable read 후보 | read boundary 미정 |

## Final decisions

| 결정 | 판정 |
|---|---|
| Rights Business Owner | `D. OWNER BLOCKED` |
| Rights Producer | `D. PRODUCER BLOCKED` |
| Create Writer | `BLOCKED` |
| Replacement Writer | `BLOCKED` |
| Revocation Owner | `D. REVOCATION OWNER BLOCKED` |
| Durable Authority | `D. AUTHORITY BLOCKED` |
| Current Projection Owner | `BLOCKED` |
| Logical Key | `BLOCKED` |
| Read Boundary | `D. READ CONTRACT BLOCKED` |
| Common schema change | `BLOCKED`; owner/source identity contract 전 확정하지 않음 |
| 전체 Rights authority architecture | `STILL BLOCKED` |

`READY FOR RIGHTS AUTHORITY CONTRACT` 조건인 accountable owner, create·replacement·revoke writer, durable authority owner,
current projection owner, logical key, unique-current invariant, authenticated read owner와 workspace authorization owner가 모두
확정되지 않았다. 따라서 port, adapter, migration, service API와 runtime composition 설계를 시작하지 않는다.

## Required next decision

다음 Gate는 code가 아니라 cross-repository·organizational ownership 결정이어야 한다.

[후속] [ADR-030](./ADR-030-cross-repository-rights-domain-ownership.md)은 이 Gate를 수행했다. DohaMusic은 가장 강한 existing
owner 후보, 새 cross-repository Rights domain은 가장 응집도 높은 architecture 후보지만 organizational/legal actor,
stable source identity, create·replacement·revoke writer와 authority/read owner 승인이 없어
`D. ORGANIZATIONAL OWNERSHIP STILL BLOCKED`로 판정했다. 따라서 아래 요구는 해소되지 않았으며 조직 승인 입력으로 남는다.

1. DohaMusic Rights/Consent domain을 모든 supported source의 accountable owner로 승인할지 결정
2. 그렇지 않다면 새 cross-repository Rights/Licensing domain과 accountable owner를 명시
3. supported source identity와 stable logical Rights chain key 승인
4. create·replacement·revoke actor, trigger와 audit accountability 승인
5. owner-local authority와 authenticated workspace-scoped read owner 승인
6. authority envelope만으로 충분한지 Common schema 변경이 필요한지 재판정

이 결정이 승인된 뒤 `RightsMetadata Authority Contract`가 immutable history, projection, revision, read DTO와 failure contract를
설계할 수 있다. 그 전에는 구현 repository, service 이름, DB와 credential 방식을 확정하지 않는다.

## Excluded scope

- [제외] production RightsMetadata producer, writer, source, persistence, migration과 projection 구현
- [제외] adapter, coordinator, cache, runtime config/factory/preflight 구현
- [제외] CLI, API, worker, Training, Evaluation과 promotion activation
- [제외] Common schema/resource/version과 다른 repository 변경·PR
- [제외] snapshot protocol과 Publication pair binding 변경
- [제외] reviewer/legal roster, IAM role, secret provisioning과 storage technology 확정

## Acceptance and approval Gate

- [제안] canonical Rights semantic과 없는 field를 Common schema와 일치시켰다.
- [제안] candidate·Eligibility 상위 binding을 authority current selection과 분리했다.
- [제안] fixture, validator, legacy license status와 voice consent row를 canonical producer로 오인하지 않았다.
- [제안] source-level 방향과 accountable owner 승인을 구분했다.
- [제안] owner·logical key·revoke writer·read owner가 없음을 숨기지 않고 `STILL BLOCKED`로 유지했다.
- [제안] production source·test·migration·runtime·CLI/API/worker와 다른 repository 변경은 0이어야 한다.

이 ADR은 `draft`·`proposed`다. 독립 검토, 사용자 명시 승인과 병합 전에는 authoritative implementation requirement가 아니다.
병합되더라도 Rights Authority contract, Common 변경, port/adapter design, runtime activation 또는 Training을 승인하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-25 | [후속] ADR-030의 cross-repository ownership Gate가 Option D·`STILL BLOCKED`를 판정해 조직 승인 요구를 유지 |
| 2026-08-25 | [제안] accountable owner·canonical producer·logical key·revoke/read authority 미확정으로 Rights authority를 `STILL BLOCKED` 판정 |
