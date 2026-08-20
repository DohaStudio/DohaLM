# AI Music Director와 Product Continuous Learning 경계

- 문서 상태: `review`
- 마지막 검토일: 2026-08-20
- 선행 결정: [ADR-014](../decisions/ADR-014-dataset-product-governance-boundary.md), [ADR-021](../decisions/ADR-021-production-training-adapters-and-durable-journal.md)
- 제안 결정: [ADR-024](../decisions/ADR-024-ai-music-director-product-boundary.md)

## 목적

이 문서는 현재 구현된 Foundation 실행 기반과 아직 제안 단계인 AI Music Director 제품·지속 학습 기능을 분리한다. Common AI Contract를 단일 의미 기준으로 사용하며 새 schema나 병렬 ownership을 만들지 않는다.

## 현재와 계획

| 영역 | 현재 authority·구현 | 계획 상태 |
|---|---|---|
| 프로젝트 정의 | reusable LLM model provider | AI Music Director intelligence provider는 ADR-024 제안 |
| Dataset governance | DohaLM의 immutable DatasetVersion·Manifest publication 구현 | 제품 candidate를 Dataset으로 승격하는 policy는 미구현 |
| Foundation execution | explicit approval, PostgreSQL authority·journal, Host·composition 구현 | 기존 계보 유지 |
| Product/adapter learning | Common LearningCandidate 소비와 explicit local review Gate 구현 | persistence·Dataset inclusion·Training request·Evaluation Gate는 미구현 |
| Reference·Similarity | Common 객체 정의만 authority | DohaLM typed consumer·해석 capability 미구현 |
| Model promotion | 자동 promotion 없음 | Evaluation과 별도 사용자 승인 계약 필요 |

## Authoritative owner matrix

| 책임 | owner | DohaLM 경계 |
|---|---|---|
| Workspace·MusicProject·Asset·AssetVersion·Artifact·Composition·Job persistence와 orchestration | DohaMusic | 제품 intelligence만 제공 |
| `LearningCandidate`, rights·consent evidence | DohaMusic·권리 검토 계층 / Common authority | 직접 생성하지 않음 |
| music/audio generation·stem separation·analysis·mix·audio runtime | DohaAudio | `ReferenceAnalysis`·`FeatureRecord` 소비 후보 |
| singing·voice conversion·vocal correction·analysis·vocal runtime | DohaVocal | typed evidence 소비 후보 |
| DatasetVersion·Manifest publication | DohaLM | 현행 immutable publication 유지 |
| Training·Evaluation·Model lineage | DohaLM / Common authority | Foundation과 product 계보 분리 |
| planning·lyrics·prompt·QA·RevisionPlan | DohaLM | ADR-024 승인 뒤 세부 capability 결정 |

## 객체별 현재성

| 객체·단계 | 현재 상태 | 다음 Gate |
|---|---|---|
| `LearningCandidate` | Common 계약 소비와 current evidence를 재검증하는 immutable review result 구현 | producer/transport와 review persistence |
| `RightsMetadata` | upstream authoritative evidence; DohaLM producer 아님 | exact consumer boundary |
| `TrainingEligibility` | DohaLM Dataset governance의 candidate 단위 Gate | authoritative producer workflow |
| `DatasetVersion`, `DatasetManifest` | governance·publication 구현 | product candidate 승격 policy |
| `TrainingRun` | Common lineage와 local Foundation execution 존재 | product run identity 분리 |
| `EvaluationRun` | Common lineage; product promotion pipeline 없음 | evaluation contract |
| `ModelVersion` | Common lineage; 자동 runtime promotion 없음 | promotion decision |
| `ReferenceAnalysis`, `FeatureRecord` | DohaLM consumer 없음 | typed capability port |
| `SimilarityReport` | DohaLM consumer 없음; 법적 판단 아님 | evidence interpretation Gate |
| `RevisionPlan` | runtime producer 없음 | product output contract |

## 허용되는 흐름

```text
LearningCandidate creation and review
  -> current RightsMetadata and TrainingEligibility
  -> DatasetVersion draft inclusion
  -> Dataset-level eligibility validation and review
  -> approved DatasetVersion, issued Manifest and freeze
  -> explicit Training approval and durable journal
  -> TrainingRun
  -> EvaluationRun
  -> separate ModelVersion/runtime promotion decision
```

- [확정] 각 화살표는 독립 Gate다.
- [확정] candidate 또는 similarity evidence가 Training approval을 암묵적으로 만들지 않는다.
- [확정] 사용자 수정과 생성 결과는 candidate review 없이 Dataset에 자동 편입되지 않으며, rights·eligibility evidence가 missing·unknown·expired·revoked·invalid이면 fail closed한다.
- [확정] source와 parent lineage는 끝까지 보존한다. Foundation checkpoint와 product/adapter artifact는 별도 identity·lineage record를 사용하되 승인된 명시적 parent/source reference로 연결할 수 있다.
- [확정] Provider끼리 직접 호출하지 않으며 DohaMusic이 Common intent·capability에 따라 orchestration한다.
- [확정] 현재 문서는 물리적 directory 이동이나 schema migration을 지시하지 않는다.

## 구현된 consumer와 review boundary

- [현재] `src.data.learning_candidate_consumer.validate_learning_candidate_for_consumption()`은 pinned Common package로 LearningCandidate·RightsMetadata·TrainingEligibility를 검증하고 immutable consumer view만 반환한다.
- [현재] schema·version·identity·workspace scope, review·consent evidence, source lineage, purpose-matched eligibility와 rights·retention expiry/revocation을 fail closed한다.
- [현재] 입력 payload를 변경하거나 보존하지 않으며 DB persistence, Dataset publication, Training·Evaluation과 promotion을 호출하지 않는다.
- [현재] `src.data.learning_candidate_review.review_learning_candidate()`은 `ValidatedLearningCandidate`만 candidate 입력으로 받고, 명시적 reviewer·reviewed_at·decision과 주입된 current authority port를 사용한다.
- [현재] review 시점의 canonical RightsMetadata·TrainingEligibility를 다시 검증하며 unresolved evidence는 `NEEDS_REVIEW`, 만료·철회·policy-invalid evidence는 `REJECTED`, contract·identity·lineage·scope 위반은 error로 fail closed한다.
- [현재] `ACCEPTED`는 Dataset inclusion review 진입 가능성만 뜻하며 Dataset inclusion/publication, Training request·실행, Evaluation·promotion 권한을 만들지 않는다.
- [계획] Candidate review persistence, DatasetVersion inclusion/publication handoff, Product/Adapter Training request, Evaluation·promotion과 Reference/Similarity runtime은 후속 Gate다.

## 후속 결정 순서

1. [제안] ADR-024 제품 방향 승인 여부 결정
2. [계획] cross-repository producer/consumer 및 version mapping 확정
3. [계획] Reference·Similarity typed capability API 결정
4. [계획] product Dataset 승격과 Evaluation 기준 결정
5. [계획] Model promotion·runtime delivery 결정
6. [계획] 명시 승인된 최소 integration 구현

## 역사적 출처

- [확정] PR #103은 2026-08-20 기준 current `develop`과 충돌하는 미병합 초안이다.
- [확정] 당시 repository inventory, `not_started` 표, 별도 schema와 directory migration 제안은 현재 authority가 아니다.
- [확정] 이 문서는 그 초안에서 제품 방향과 Foundation/product learning 분리 원칙만 현행 Common contract와 ADR에 맞춰 이관했다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-20 | ValidatedLearningCandidate 기반 explicit review와 review 시점 current rights·eligibility 재검증 Gate 구현 상태 반영 |
| 2026-08-20 | Common LearningCandidate·RightsMetadata·TrainingEligibility fail-closed consumer boundary 구현 상태와 후속 Gate 분리 |
| 2026-08-20 | PR #103의 제품 방향을 current authority에 맞춰 이관하고 Provider ownership, candidate Gate와 Foundation/product learning을 분리 |
