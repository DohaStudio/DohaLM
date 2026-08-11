# ADR-014: Dataset product governance와 Common 객체 ownership 경계

- 문서 상태: `draft`
- 마지막 검토일: 2026-08-12
- 결정 상태: `proposed`
- 실행 영향: 없음
- 권위 기준: `DohaStudio/.github@dd75fc88c16e9ae9a04acfafb72756a905f6365b`
- 관련 문서: [Project Definition](../project/overview.md),
  [ADR-004](./ADR-004-data-governance.md),
  [ADR-013](./ADR-013-initial-common-ai-contract-consumer-boundary.md),
  [Dataset Registry](../data/dataset-registry.md)

## Context

[확정] 현재 DohaLM은 reusable LLM model provider이며 Dataset·학습·평가와 자체 manifest를 소유한다. 사용자 UI,
Workspace·Project workflow, 사용자 승인과 도메인 비즈니스 로직은 외부 소비자 저장소의 책임이다.

[확정] 현재 `src.data.pipeline.build_pipeline()`은 legacy corpus 입력을 정제·분할하고 DohaLM 고유
`source-manifest.json`을 staging에 작성한 뒤 `AtomicArtifactDirectory`로 원자적으로 게시한다. 이 manifest와 설정의
`dataset_version` 문자열은 Common `LearningCandidate`, `DatasetVersion` 또는 `DatasetManifest`가 아니다.

[확정] 현재 Dataset registry의 owner는 미지정이며, 데이터 승인 책임자와 법률 검토 절차도 미결정이다. 기존 approval,
readiness와 execution evidence는 특정 DohaLM Dataset·실험 실행을 제한하는 domain 계약이며 Common candidate review,
RightsMetadata 또는 DatasetVersion lifecycle을 발행하지 않는다.

[확정] Common 의미 계약의 권위는
`DohaStudio/.github@dd75fc88c16e9ae9a04acfafb72756a905f6365b`이다. 이 권위는 DohaMusic이 사용자 작업,
Rights·Provenance·Consent와 LearningCandidate 발생 이력을 소유하고, DohaLM이 DatasetVersion과 Dataset governance를
소유하는 repository 경계를 정의한다.

[확정] Draft PR #103과 ADR-012는 AI Music Director와 continuous learning의 미래 구조를 제안하지만 미병합 Draft다.
이 결정은 PR #103의 제품 방향, 디렉터리 구조 또는 migration plan을 승인 근거로 사용하지 않는다.

## Decision

다음 Dataset product governance ownership을 승인 대상으로 제안한다.

| 영역 | producer repository | accountable Owner domain | DohaLM 역할 |
|---|---|---|---|
| 사용자 작업·수정·선택과 `LearningCandidate` 발생 이력 | `DohaStudio/DohaMusic` | DohaMusic Workspace·Project workflow와 Candidate Intake | 외부 producer가 승인된 후의 downstream Dataset governance |
| Rights·Consent·Provenance evidence | `DohaStudio/DohaMusic` | DohaMusic Rights·Consent Review | immutable evidence reference의 유효성 재검증 |
| Candidate review 요청·승인·거절 | `DohaStudio/DohaMusic` | DohaMusic Candidate Review | review 결과를 승인으로 재해석하지 않음 |
| Candidate 단위 eligibility | `DohaStudio/DohaLM` | DohaLM Dataset Governance | 목적별 fail-closed 판정과 evidence 발행 |
| Dataset 구성·집합 eligibility·승인 | `DohaStudio/DohaLM` | DohaLM Dataset Governance | DatasetVersion 논리 권위 소유 |
| DatasetManifest 발행·DatasetVersion freeze | `DohaStudio/DohaLM` | DohaLM Dataset Publication | Version/Manifest 결속과 원자적 publication 소유 |
| Common 객체 의미·schema·version policy | `DohaStudio/.github` | Common Contract authority | public package로 검증하되 의미를 복제하지 않음 |

위 Owner는 repository와 product domain의 accountable 경계다. 구체적인 service·module·함수, 저장 기술과 reviewer roster는
후속 구현 결정에서 고정하며, 그 전에는 producer 구현이 존재한다고 간주하지 않는다.

### DohaLM의 역할

- [제안] DohaLM은 사용자 생성 LearningCandidate의 최초 producer가 아니다.
- [제안] DohaLM Dataset Governance는 승인된 외부 candidate와 evidence를 입력으로 받는 미래 downstream owner다.
- [제안] DohaLM은 Candidate review나 Rights·Consent 승인 결과를 추정·보완하거나 대행하지 않는다.
- [제안] `TrainingEligibility`는 DatasetVersion draft inclusion을 위한 candidate 단위 evidence이며 Training 실행 권한,
  Dataset 집합 승인 또는 Runtime 승격 권한이 아니다.
- [제안] DatasetVersion은 Dataset identity, 집합 eligibility, approval, split와 freeze의 논리 권위이고 DatasetManifest는
  승인 상태를 독립 변경할 수 없는 immutable reproduction evidence다.

## Legacy corpus 분리

- [제안] 기존 DohaLM corpus, `source-manifest.json`, registry entry와 `dataset_version` 문자열은 Common
  LearningCandidate가 아니다.
- [제안] 이름·경로·field 유사성을 근거로 자동 wrapping, aliasing, default 삽입, key 추가·삭제 또는 type·version 변환을
  수행하지 않는다.
- [제안] 기존 corpus를 사용자 생성 candidate로 재해석하거나 Rights·Consent·Provenance·Review evidence를 추정하지 않는다.
- [제안] 현재 Common LearningCandidate source taxonomy에는 legacy corpus admission 경로가 승인돼 있지 않다. 따라서 legacy
  corpus는 별도 authority schema/lifecycle 결정과 별도 migration ADR이 승인·병합되기 전까지 Common candidate lifecycle에
  들어갈 수 없다.
- [제안] 미래 migration은 source version·checksum·목적·license·rights·provenance·reviewer·transform version과
  revoke/expiry 정책을 고정한 version-scoped admission decision이어야 한다. 이 결정은 해당 migration event나 resource를
  승인하지 않는다.
- [확정] legacy corpus의 artifact identity, checksum, split, Tokenizer compatibility와 domain readiness는 계속 DohaLM
  책임이다.

## Evidence와 review 책임

1. [제안] DohaMusic Rights·Consent Review는 사용자 작업 source와 목적에 결속된 immutable RightsMetadata identity와
   비공개 consent evidence reference를 발행한다.
2. [제안] DohaMusic Candidate Intake는 원문·로컬 경로를 노출하지 않는 input/output reference, content fingerprint와
   RightsMetadata ID를 LearningCandidate에 결속한다.
3. [제안] DohaMusic Candidate Review는 review request, reviewer identity, approval/rejection evidence를 발행한다.
   `rejected`는 terminal이며 수정본은 새 candidate identity와 lineage를 사용한다.
4. [제안] DohaLM Dataset Governance는 candidate status와 목적별 rights·provenance·consent·retention·quality·PII·lineage를
   재검증한 새 eligibility evidence를 발행한다. 외부 evidence 원문을 복제하거나 승인 의미를 확대하지 않는다.
5. [제안] expiry, revocation 또는 evidence 변경은 기존 객체를 수정하지 않고 append-only event와 새 eligibility 판정을
   발생시킨다.

## Lifecycle과 state transition

| event | immutable input | producer / future Owner | output·허용 전이 | validation·failure 책임 |
|---|---|---|---|---|
| candidate created | 사용자 작업·수정·선택 identity | DohaMusic Candidate Intake | 새 candidate `draft` | 입력 reference와 fingerprint 불완전 시 publication 0 |
| evidence attached | candidate와 source identity | DohaMusic Rights·Consent Review | RightsMetadata·evidence reference 결속 | missing·unknown·expired·revoked는 fail closed |
| review requested | 완성 candidate와 evidence | DohaMusic Candidate Review | `draft → submitted → in_review` | reviewer/evidence 누락 시 승인 전이 0 |
| approved/rejected | in-review identity | DohaMusic Candidate Review | `in_review → approved` 또는 terminal `rejected` | 동일 identity 덮어쓰기 0 |
| eligibility evaluated | approved candidate와 현재 evidence | DohaLM Dataset Governance | 새 목적별 eligibility 판정 | 하나라도 non-pass면 inclusion 0 |
| composition proposed | eligible candidate 집합 | DohaLM Dataset Governance | DatasetVersion `draft → reviewing` | 집합·split·lineage 불완전 시 proposal publication 0 |
| Dataset approved | reviewing DatasetVersion과 approval evidence | DohaLM Dataset Governance | `reviewing → approved` | approval과 집합 eligibility 누락 시 전이 0 |
| Manifest issued | approved DatasetVersion과 artifact/checksum set | DohaLM Dataset Publication | immutable DatasetManifest `issued` | Version/Manifest identity 불일치 시 manifest·freeze 0 |
| Dataset frozen | issued Manifest와 approved Version | DohaLM Dataset Publication | `approved → frozen` | 결속 검증 후에만 atomic publication 완료 |
| downstream consumption | frozen Version과 issued Manifest | 후속 resource-specific ADR에서 결정 | 현재 미승인 | Dataset·Model 접근과 Training/Evaluation 0 유지 |

`included_in_dataset`와 `trained` candidate 상태는 성공한 후속 DatasetVersion·TrainingRun의 immutable reference가 있을 때만
append-only projection으로 기록한다. 이전 candidate, eligibility, DatasetVersion과 Manifest를 소급 수정하지 않는다.

## DatasetVersion approval·freeze와 publication transaction

- [제안] DohaLM Dataset Governance가 candidate 집합, 최신 eligibility, purpose, rights summary, split, schema identity와
  approval evidence를 고정해 DatasetVersion approval을 발행한다.
- [제안] Dataset approval은 freeze나 Training 허용을 자동 의미하지 않는다.
- [제안] DohaLM Dataset Publication이 approved DatasetVersion에서 DatasetManifest를 생성하고 stable ID·content fingerprint,
  source DatasetVersion ID/checksum, artifact reference와 split identity를 결속한다.
- [제안] Manifest issuance와 DatasetVersion freeze는 한 publication unit으로 처리한다. 모든 validation이 끝날 때까지 외부에
  issued Manifest, frozen Version 또는 부분 Dataset artifact를 노출하지 않는다.
- [제안] transaction과 staging cleanup 책임은 DohaLM Dataset Publication에 있다. 실패 시 staging, partial file,
  Dataset mutation, Model·Provider 접근과 Training/Evaluation 실행은 0이어야 한다.
- [제안] 동일 immutable input의 retry는 같은 identity와 fingerprint를 확인하는 idempotent 결과만 허용한다. 동일 ID에 다른
  bytes·lineage가 존재하면 overwrite나 fallback 없이 충돌로 실패한다.

## Revoke, supersede와 expiry

- [제안] Rights·Consent expiry/revocation은 기존 evidence, DatasetVersion, Manifest, Run 또는 Model lineage를 삭제하지 않는다.
- [제안] 영향받는 candidate eligibility는 재사용하지 않고 새 `revoked` 또는 fail-closed 판정을 발행한다.
- [제안] frozen DatasetVersion은 제자리에서 candidate를 제거하지 않는다. 재검토된 candidate 집합으로 새 DatasetVersion과
  새 DatasetManifest를 발행하고 `supersedes` lineage를 연결한다.
- [제안] 이미 수행된 TrainingRun·EvaluationRun·ModelVersion은 historical lineage로 보존하고 별도 영향 분석과 Runtime Gate
  재평가 대상으로 표시한다. 이 ADR은 Model rollback이나 Runtime 정책을 승인하지 않는다.

## Common Contract와 domain validation 경계

### Common package

- public API로 envelope, resource schema, object version과 canonical issue를 판정한다.
- package resource와 `$ref`를 offline으로 해결하고 Runtime network lookup은 0이어야 한다.
- unsupported version/policy, unknown resource와 canonical issue는 fail closed다.

### Product·domain owner

- DohaMusic은 사용자 workflow, source identity와 Rights·Consent·Provenance·Review 의미를 판정한다.
- DohaLM은 Dataset 목적, candidate 집합, artifact identity, checksum, split, Tokenizer compatibility, approval·freeze와
  Training readiness를 판정한다.
- validation 전후 payload key, value, type와 `schema_version`을 변경하지 않는다.
- 누락 evidence 추정, default 보완, alias 변환과 기존 manifest 자동 승격을 금지한다.

## 후속 resource-specific ADR 진입 Gate

다음 조건이 모두 실제 evidence로 충족되기 전에는 ADR-013의 resource-specific consumer 결정을 시작하지 않는다.

1. 선택 대상 Common 객체의 producer repository, service/module/function과 accountable Owner가 승인·구현됨
2. 완성 payload와 immutable identity를 생성하는 lifecycle event가 구현·테스트됨
3. Rights·Consent·Provenance·Review evidence producer와 current/revoke/expiry 조회 계약이 구현됨
4. DatasetVersion approval, Manifest issuance, freeze와 supersede transaction이 구현됨
5. validation/publication 실패 시 partial output 0과 idempotent retry·cleanup이 검증됨
6. authority Git commit, package version, policy version과 exact resource identity가 고정됨
7. 정확한 DohaLM consumer module/function, 호출 전후 순서와 expected kind가 결정됨
8. Common validation과 DohaLM domain validation의 책임·오류·sanitization이 테스트 계약으로 고정됨

## 명시적 non-decision

이 ADR은 다음을 승인하지 않는다.

- canonical resource name 또는 `$id`
- Common consumer module·함수·호출 시점
- producer·consumer·loader·adapter·generic wrapper 구현
- Dataset governance, LearningCandidate, TrainingEligibility, DatasetVersion 또는 DatasetManifest 구현
- legacy corpus migration 또는 Common 객체 승격
- dependency, Schema·Registry·resource·fixture·version policy 복제
- Dataset·Model·Provider 접근, Training·Evaluation 또는 Runtime 연결
- PR #103의 제품 방향·디렉터리·migration 제안

## Alternatives

| 대안 | 기각 근거 |
|---|---|
| DohaLM이 LearningCandidate와 사용자 evidence까지 소유 | 현행 Project Definition과 Common repository ownership을 침범함 |
| DohaMusic이 DatasetVersion approval·freeze까지 소유 | Common authority가 지정한 DohaLM Dataset ownership과 충돌함 |
| legacy manifest를 Candidate 또는 DatasetVersion으로 wrapping | evidence·identity·lifecycle 의미를 자동 승격하고 이중 Source of Truth를 만듦 |
| consumer 구현에서 Owner를 나중에 결정 | 실제 producer 없이 빈 loader·범용 wrapper가 생기고 failure transaction을 정할 수 없음 |

## Consequences와 Risks

- 장점: 사용자 workflow와 Dataset governance의 accountability가 repository 경계와 일치한다.
- 장점: legacy corpus와 user-generated candidate를 혼합하지 않고 evidence 추정을 차단한다.
- 장점: DatasetVersion approval, Manifest issuance, freeze와 cleanup의 단일 책임을 고정한다.
- 비용: DohaMusic과 DohaLM 양쪽에 별도 producer·review·publication 구현 결정이 필요하다.
- 위험: cross-repository event 전달과 revocation propagation의 transport·storage가 아직 결정되지 않았다.
- 위험: authority 문서는 조직 공통 의미를 제공하지만 실제 reviewer roster와 운영 법률 절차는 별도 승인이 필요하다.

## Open questions

- [검증 필요] 각 Owner domain의 실제 service·module·function과 저장소 내부 persistence 기술
- [검증 필요] reviewer roster, 법률 검토 escalation과 운영 SLA
- [검증 필요] cross-repository event transport, delivery retry와 관측성 구현
- [검증 필요] legacy corpus를 Common lifecycle로 도입할 authority schema/lifecycle 변경 여부

이 항목은 ownership과 lifecycle 책임을 미정으로 되돌리지 않으며, 구현과 별도 migration의 Ready 조건이다.

## 승인 Gate

이 ADR은 `draft`이며 review·명시 승인·병합 전에는 authoritative implementation requirement가 아니다. 병합되더라도
resource-specific ADR의 진입 조건만 제공하며 consumer 또는 Training 구현을 허가하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-12 | [제안] Common 객체 repository ownership, legacy 분리와 Dataset publication governance 경계를 정의함 |
