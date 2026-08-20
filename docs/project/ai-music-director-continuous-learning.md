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
| Product/adapter learning | runtime consumer 없음 | 별도 producer mapping·Dataset·Evaluation Gate 필요 |
| Reference·Similarity | Common 객체 정의만 authority | DohaLM typed consumer·해석 capability 미구현 |
| Model promotion | 자동 promotion 없음 | Evaluation과 별도 사용자 승인 계약 필요 |

## Authoritative owner matrix

| 책임 | owner | DohaLM 경계 |
|---|---|---|
| 사용자 work·project·asset·job·orchestration | DohaMusic | 제품 intelligence만 제공 |
| `LearningCandidate`, rights·consent evidence | DohaMusic·권리 검토 계층 / Common authority | 직접 생성하지 않음 |
| audio analysis·feature 계산 | DohaAudio | `ReferenceAnalysis`·`FeatureRecord` 소비 후보 |
| vocal analysis·rendering | DohaVocal | typed evidence 소비 후보 |
| DatasetVersion·Manifest publication | DohaLM | 현행 immutable publication 유지 |
| Training·Evaluation·Model lineage | DohaLM / Common authority | Foundation과 product 계보 분리 |
| planning·lyrics·prompt·QA·RevisionPlan | DohaLM | ADR-024 승인 뒤 세부 capability 결정 |

## 객체별 현재성

| 객체·단계 | 현재 상태 | 다음 Gate |
|---|---|---|
| `LearningCandidate` | Common 계약과 DohaMusic ownership이 기준 | producer/transport mapping |
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
upstream typed evidence
  -> explicit consumer validation
  -> separately approved DatasetVersion publication
  -> explicit Training approval and durable journal
  -> EvaluationRun
  -> separately approved ModelVersion promotion
```

- [확정] 각 화살표는 독립 Gate다.
- [확정] candidate 또는 similarity evidence가 Training approval을 암묵적으로 만들지 않는다.
- [확정] Foundation checkpoint와 product/adapter artifact는 identity와 lineage를 공유하지 않는다.
- [확정] 현재 문서는 물리적 directory 이동이나 schema migration을 지시하지 않는다.

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
| 2026-08-20 | PR #103의 제품 방향을 current authority에 맞춰 이관하고 현재 구현과 후속 product learning을 분리 |
