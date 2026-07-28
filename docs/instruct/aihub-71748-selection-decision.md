# AIHUB-71748 SFT Dataset Selection Decision

- 문서 상태: `approved`
- 승인 기록일: 2026-07-29
- 승인 ID: `AIHUB-71748-SFT-SELECTION-APPROVAL-20260729-0001`
- Dataset ID: `AIHUB-71748`
- Component: `SFT`
- 선택 상태: `CONDITIONALLY_SELECTED`
- 관련 문서: [Selection Approval Package](./aihub-71748-selection-approval-package.md), [Dataset Readiness](./aihub-71748-readiness.md), [ADR-004](../decisions/ADR-004-data-governance.md), [ADR-010](../decisions/ADR-010-dohalm-instruct-strategy.md)

## 1. 승인 범위

[확정] 프로젝트 소유자의 명시적 승인에 따라 AIHUB-71748의 SFT Component를 조건부 후보로 공식 선정한다.
이 결정은 Dataset Processing, Processing Manifest·Backend 구현, Tokenization, Adapter, SFT Backend, Training,
Checkpoint 또는 Publication 승인이 아니다.

## 2. Approval Record

`git_commit`은 이 승인 판단의 immutable evidence가 된 승인 직전 `develop` commit이다. 승인 문서 자체의
commit을 자기참조하지 않는다. `decision_time`은 저장소에 승인을 기록한 시각이다.

```yaml
dataset_selection_approval:
  approval_id: AIHUB-71748-SFT-SELECTION-APPROVAL-20260729-0001
  dataset_id: AIHUB-71748
  component: SFT
  decision: CONDITIONALLY_SELECTED
  decision_by: project_owner_explicit_approval
  decision_time: 2026-07-29T06:01:16+09:00
  git_commit: 9a5e0cac35f849a8ea55a28f15a5d9939236c4a4
  single_use: true
  consumed: true
  consumed_for: dataset_selection_status_transition
  reason_codes:
    - SCHEMA_VALIDATED
    - JOIN_INTEGRITY_PASSED
    - SAFE_INSPECTOR_VALIDATED
    - PII_POLICY_PENDING
    - DUPLICATE_POLICY_PENDING
    - LEAKAGE_POLICY_PENDING
    - TERMS_EVIDENCE_PENDING
    - BENCHMARK_SOURCE_PENDING
    - PROCESSING_MANIFEST_PENDING
  conditions:
    processing_before_required:
      - Terms Evidence
      - Benchmark Source
      - PII Threshold
      - Duplicate Threshold
      - Leakage Threshold
      - Processing Manifest
      - Processing Backend Approval
  processing_allowed: false
  training_allowed: false
  execution_allowed: false
```

## 3. 결정 근거

- [확정] Schema와 one-to-one Join 검증이 완료됐다.
- [확정] Safe Inspector와 component consistency가 통과했다.
- [확정] PII·Exact Duplicate·Near Duplicate·Leakage 검사는 완료됐으나 처리 threshold는 승인되지 않았다.
- [확정] 이용조건 증빙과 Benchmark source는 계속 미확정이다.
- [확정] 조건부 선정은 후속 처리 설계를 검토할 후보를 고정할 뿐 처리 적격성을 확정하지 않는다.

## 4. 승인 조건

Dataset Processing 전에 Terms Evidence, 고정 Benchmark Source, PII·Duplicate·Leakage threshold, Processing
Manifest와 Fail Closed Processing Backend의 별도 검토·승인을 완료해야 한다. 조건 충족 여부는 이 승인으로
자동 변경되지 않는다.

## 5. 현재 상태

```yaml
dataset_selection: CONDITIONALLY_SELECTED
dataset_processing: not_approved
processing_manifest: not_started
processing_backend: not_started
sft_backend: not_started
sft_training: not_approved
execution_allowed: false
```

[확정] 이전 scan·result·plan 문서의 `not_selected` 표기는 해당 문서 작성 시점의 historical snapshot이다. 현재
선택 상태의 단일 기준은 이 승인 기록, [Dataset Readiness](./aihub-71748-readiness.md)와
[Current Project Status](../project/current-project-status.md)다.

## 6. 다음 승인 경계

[승인 필요] 다음 작업은 미확정 증빙과 threshold를 검토한 뒤 Processing Manifest 설계 범위를 별도로 승인하는
것이다. Dataset 읽기·수정·처리, Backend 구현과 Training은 새로운 명시적 승인 전까지 금지한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-29 | AIHUB-71748 SFT Component의 `CONDITIONALLY_SELECTED` 공식 사용자 승인 기록 |
