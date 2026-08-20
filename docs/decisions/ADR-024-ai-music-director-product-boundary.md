# ADR-024: AI Music Director 제품 방향과 지속 학습 경계

- 문서 상태: `draft`
- 결정일: 미결정
- 작성일: 2026-08-20
- 실행 영향: 없음

## 배경

- [확정] 현재 DohaLM의 승인된 프로젝트 정의는 reusable LLM model provider이며, 이 ADR이 승인되기 전까지 그 정의를 변경하지 않는다.
- [확정] Common AI Contract의 객체 의미와 repository ownership은 DohaStudio `.github` 계약과 [ADR-014](./ADR-014-dataset-product-governance-boundary.md)를 따른다.
- [확정] DatasetVersion publication, Training execution approval, PostgreSQL authority·journal과 production Host lifecycle은 이미 구현된 Foundation 실행 기반이다.
- [확정] 위 실행 기반은 AI Music Director 제품 기능이나 product/adapter continuous learning의 구현을 뜻하지 않는다.
- [확정] 이 문서는 병합되지 않은 PR #103의 방향 가운데 현행 authority와 양립하는 부분만 추출한다. PR #103의 ADR-012 번호, 당시 inventory와 migration 계획은 현재 기준으로 승계하지 않는다.

## 제안 결정

### 제품 책임

- [제안] DohaLM은 AI Music Director의 intelligence provider를 지향한다.
- [제안] 책임 후보는 음악 기획, 가사·prompt 생성, 결과 QA, 분석·유사도 evidence 해석과 `RevisionPlan` 생성이다.
- [제안] DohaMusic은 Workspace·MusicProject·Asset·AssetVersion·Artifact·Composition·Job의 persistence와 제품 orchestration을 소유한다.
- [제안] DohaAudio는 music/audio generation·stem separation·audio analysis·mix와 audio model runtime을, DohaVocal은 singing·voice conversion·vocal correction·analysis와 vocal model runtime을 소유한다.
- [제안] DohaLM은 UI, project storage, raw audio DSP, vocal rendering 또는 타 repository의 producer 책임을 가져오지 않는다.
- [제안] Provider끼리 직접 호출하지 않으며 DohaMusic이 Common `MusicIntent`와 `ProviderCapability`를 사용해 orchestration한다.

### Common AI Contract 재사용

| 객체 | authoritative producer/owner | DohaLM의 제안 역할 |
|---|---|---|
| `LearningCandidate`, `RightsMetadata` | DohaMusic·권리 검토 계층 및 Common contract authority | 승인된 consumer boundary에서만 소비 |
| `TrainingEligibility` | DohaLM Dataset governance | candidate 단위 fail-closed Dataset inclusion evidence를 발행 |
| `ReferenceAnalysis`, `FeatureRecord` | DohaAudio·DohaVocal capability | feature를 재계산하지 않고 typed evidence로 소비 |
| `SimilarityReport` | similarity capability와 Common contract authority | 분석 evidence로 해석; 법적 판단으로 취급하지 않음 |
| `DatasetVersion`, `DatasetManifest` | DohaLM Dataset governance | 현행 publication 계약 유지 |
| `TrainingRun`, `EvaluationRun`, `ModelVersion` | Common contract authority에 따른 DohaLM lifecycle | 기존 Foundation 실행과 향후 product learning 계보를 명시적으로 분리 |
| `RevisionPlan` | DohaLM planning capability | 향후 product-facing output 후보 |

- [제안] local schema를 새로 정의하거나 Common 객체를 복제하지 않는다.
- [제안] `SimilarityReport`는 근거 자료이며 rights, policy 또는 Training eligibility의 법적 판정이 아니다. 실제 Gate는 별도 authoritative decision으로 남긴다.
- [제안] generic payload, hidden mutable context 또는 repository 간 암묵적 ownership을 도입하지 않는다.

### 두 학습 계보의 분리

- [확정] Foundation training은 immutable DatasetVersion·Manifest, explicit execution approval과 durable journal을 사용하는 기존 모델 학습 계보다.
- [제안] product/adapter continuous learning은 제품 feedback·candidate evidence를 별도 승인된 DatasetVersion으로 승격한 뒤에만 시작하는 후속 계보다.
- [제안] candidate 수집, Dataset 승격, Training 실행, Evaluation과 Model promotion은 서로 다른 Gate다.
- [제안] product lifecycle은 DohaMusic의 candidate review, current RightsMetadata와 candidate 단위 TrainingEligibility, DohaLM의 Dataset 집합 eligibility·review·Manifest 발행·freeze, 별도 Training 승인, TrainingRun, EvaluationRun과 별도 ModelVersion/runtime promotion decision 순서를 보존한다.
- [제안] rights·eligibility·lineage evidence가 `missing`, `unknown`, `expired`, `revoked` 또는 invalid이면 fail closed하며 사용자 수정이나 생성 결과를 Dataset에 자동 편입하지 않는다.
- [제안] 자동 Training, 자동 promotion, 자동 runtime 교체는 허용하지 않는다.

## 제외 범위

- [제외] 이 ADR만으로 API, adapter, directory migration, Dataset 생성, Training, Evaluation 또는 Production Activation을 구현하지 않는다.
- [제외] DohaMusic·DohaAudio·DohaVocal의 소유권을 변경하지 않는다.
- [제외] 기존 Foundation checkpoint나 local Training 계보를 product learning 결과로 재분류하지 않는다.

## 미결정 사항

- [검증 필요] cross-repository producer/consumer mapping과 version negotiation
- [검증 필요] Reference·Similarity capability의 typed port와 호출 책임
- [검증 필요] product learning Dataset 승격과 Evaluation·Model promotion Gate
- [검증 필요] `RevisionPlan` 전달 및 제품 orchestration 계약

## 결과

- [제안] 승인 전에는 [현재 경계 문서](../project/ai-music-director-continuous-learning.md)를 검토 자료로만 사용한다.
- [확정] 이 ADR의 등록은 실행 승인, Training 승인 또는 현재 runtime 변경이 아니다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-20 | [제안] PR #103의 유효한 제품 방향을 현행 Common ownership·Provider orchestration·Foundation 실행 계약에 맞춰 ADR-024로 재작성 |
