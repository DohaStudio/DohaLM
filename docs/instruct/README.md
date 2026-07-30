# DohaLM Instruct 설계 문서

- 문서 상태: `review`
- 마지막 검토일: 2026-07-30
- 프로젝트 상태: `design_completed`
- 실행 상태: `execution_not_approved`
- 관련 결정: [ADR-010](../decisions/ADR-010-dohalm-instruct-strategy.md)

## 범위

이 디렉터리는 Candidate B Base를 immutable parent로 사용하는 `DohaLM Instruct Tiny v1`의 목적, lineage,
데이터 schema, prompt template, 평가, tool calling, safety와 readiness를 정의한다. 실제 instruction dataset,
SFT backend, checkpoint와 모델은 생성하지 않는다.

## 문서 목록

- [Instruct 전략](./instruct-strategy.md)
- [Instruction Dataset 전략](./instruction-dataset-strategy.md)
- [Instruction Schema](./instruction-schema.md)
- [AI Hub Instruction Dataset 후보 Read-only 검토](./aihub-dataset-candidate-review.md)
- [AIHUB-71748 SFT 이용조건 검토](./aihub-71748-sft-terms-review.md)
- [AIHUB-71748 SFT 원문 비출력 검증 계획](./aihub-71748-sft-validation-plan.md)
- [AIHUB-71748 SFT Schema Inspection](./aihub-71748-schema-inspection.md)
- [Safe Dataset Inspector](./safe-dataset-inspector.md)
- [AIHUB-71748 SFT Join Integrity 결과](./aihub-71748-join-integrity-result.md)
- [AIHUB-71748 SFT 제한 PII Scan 결과](./aihub-71748-pii-scan-result.md)
- [AIHUB-71748 SFT PII False Positive 및 Threshold 정책](./aihub-71748-pii-policy.md)
- [AIHUB-71748 SFT Content Exact Duplicate Scan 결과](./aihub-71748-exact-duplicate-result.md)
- [AIHUB-71748 SFT Exact Duplicate 처리 정책](./aihub-71748-exact-duplicate-policy.md)
- [AIHUB-71748 SFT Near Duplicate Scanner 최적화](./aihub-71748-near-duplicate-optimization.md)
- [AIHUB-71748 SFT Near Duplicate Scan 결과](./aihub-71748-near-duplicate-result.md)
- [AIHUB-71748 SFT Near Duplicate 처리 정책](./aihub-71748-near-duplicate-policy.md)
- [AIHUB-71748 SFT Leakage / Benchmark Contamination Scan 결과](./aihub-71748-leakage-result.md)
- [AIHUB-71748 SFT Leakage 처리 정책](./aihub-71748-leakage-policy.md)
- [AIHUB-71748 SFT Dataset Readiness](./aihub-71748-readiness.md)
- [AIHUB-71748 SFT Dataset Selection Approval Package](./aihub-71748-selection-approval-package.md)
- [AIHUB-71748 SFT Dataset Selection Decision](./aihub-71748-selection-decision.md)
- [SFT Dataset Processing Backend](./processing-backend.md)
- [SFT Processing Manifest Schema](./processing-manifest-schema.md)
- [AIHUB-71748 SFT Processing Manifest](./aihub-71748-processing-manifest.md)
- [AIHUB-71748 실제 Processing Backend와 Mapping 계약](./aihub-71748-real-processing-backend.md)
- [AIHUB-71748 Processing Run 0002 Preflight](./aihub-71748-processing-run-0002-preflight.md)
- [AIHUB-71748 Processing Run 0003 Backend 계약 보완](./aihub-71748-run-0003-backend-hardening.md)
- [AIHUB-71748 Processing Run 0004 Metadata-Only Preflight](./aihub-71748-processing-run-0004-preflight.md)
- [AIHUB-71748 Processing Run 0005 실패 계보](./aihub-71748-processing-run-0005-preflight.md)
- [AIHUB-71748 Processing Run 0006 Metadata-Only Preflight](./aihub-71748-processing-run-0006-preflight.md)
- [AIHUB-71748 Approval Issuance·Squash-Merge Lineage 계약](./aihub-71748-approval-lineage-contract.md)
- [AIHUB-71748 Processing 실행 계약 v2](./aihub-71748-processing-contract-v2.md)
- [AIHUB-71748 Processing Run 0008 Metadata-Only Preflight](./aihub-71748-processing-run-0008-preflight.md)
- [AIHUB-71748 Processing Run 0009 Metadata-Only Preflight](./aihub-71748-processing-run-0009-preflight.md)
- [AIHUB-71748 RuntimeExecutionRequest v1 계약](./aihub-71748-runtime-execution-request-v1.md)
- [AIHUB-71748 Approval Retirement Contract](./aihub-71748-approval-retirement-contract.md)
- [Prompt Template](./instruction-prompt-template.md)
- [Instruction Evaluation](./instruction-evaluation.md)
- [Tool Calling 전략](./tool-calling-strategy.md)
- [Instruction Safety](./instruction-safety.md)
- [Readiness](./instruction-readiness.md)

## Fail Closed

```text
design_status: design_completed
execution_allowed: false
training: not_approved
backend: not_started
dataset: CONDITIONALLY_SELECTED
dataset_processing: not_approved
processing_backend: implemented_real_backend_hardened_synthetic_validated
processing_manifest: completed_non_executable
processing_run_0002: retired_failed_closed_before_consumption
approval_0002: retired_not_issued
processing_run_0003: retired_failed_closed_before_approval
approval_0003: retired_not_issued
processing_run_0004: retired_execution_source_tree_drift
approval_0004: retired_not_issued
processing_run_0005: retired_preflight_validator_failure
approval_0005: retired_not_issued
processing_run_0006: retired_approval_contract_failure
approval_0006: retired_not_issued
approval_permission_model: separated
squash_merge_lineage: supported
processing_run_0007: retired_contract_mismatch_before_start
approval_0007: not_created_non_reusable
processing_contract_v2: frozen_synthetic_e2e_passed
processing_run_0008: retired_backend_fingerprint_mismatch
approval_0008: retired_not_issued
runtime_execution_request_0008: not_created
processing_run_0009: retired_runtime_request_governance_mismatch
approval_0009: retired_before_consumption
approval_refresh_0009: validated
runtime_execution_request_0009: not_created
runtime_request_writer: implemented_synthetic_validated
approval_retirement_service: implemented_and_executed_for_0009
approval_retirement_0009: completed
rule_thresholds: approved_for_processing_manifest
processed_dataset: not_created
publication: not_approved
```

여기서 `backend: not_started`는 SFT 학습 Backend 상태다. Dataset Processing Backend는 실제 ZIP을 처리할 수 있는
구조까지 구현됐지만 Synthetic로만 실행 검증됐으며 실제 Processing 실행 권한을 부여하지 않는다.

별도 사용자 승인 전에는 dataset 다운로드·생성·변환, SFT, optimizer, backward, evaluation 실행,
checkpoint 생성과 publication을 수행하지 않는다.

Dataset 검토 흐름은 Candidate Review → Terms·Schema·Validation → PII·Duplicate·Leakage → Dataset Readiness →
Selection Approval Package → 별도 사용자 선택 승인 → Processing Manifest 설계 순서다. AIHUB-71748 SFT
Component는 `CONDITIONALLY_SELECTED`로 공식 선정됐지만 Dataset Processing과 Training은 승인되지 않았다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-30 | Approval 0009를 `retired_before_consumption`, Run 0009를 `retired_runtime_request_governance_mismatch`로 영구 폐기 |
| 2026-07-30 | RuntimeExecutionRequest v1 writer·CLI 합성 검증과 Approval 0009 issued/unconsumed 실제 상태 반영 |
| 2026-07-30 | Run 0008 backend drift 폐기와 Run 0009 metadata-only Preflight 통과·Approval 미발급 상태 등록 |
| 2026-07-30 | Run 0008 metadata-only Preflight 통과와 Approval prepared-not-issued 상태 등록 |
| 2026-07-30 | Processing 계약 v2 동결, Run 0007 시작 전 폐기와 Synthetic E2E 통과 |
| 2026-07-30 | Run 0006 Approval 계약 실패 폐기와 capability/runtime gate·squash lineage 계약 구현 |
| 2026-07-30 | Run 0005 validator failure 영구 폐기와 Run 0006 metadata-only Preflight 통과 기록 |
| 2026-07-29 | Run 0004 metadata-only Preflight 통과와 non-issued Approval 초안 등록 |
| 2026-07-29 | Run 0003 metadata-only Preflight가 식별자 선언 오탐으로 Fail Closed되어 Run·Approval ID 폐기 |
| 2026-07-29 | Run 0002 영구 폐기와 Run 0003 hardened backend·Synthetic 검증·Preflight 미시작 상태 등록 |
| 2026-07-29 | AIHUB-71748 Processing Run 0002 metadata-only Preflight와 Approval 초안 등록 |
| 2026-07-29 | AIHUB-71748 외부 Mapping·실제 Processing Backend 구현과 Run 0001 폐기·Run 0002 미승인 경계 등록 |
| 2026-07-29 | AIHUB-71748 SFT 공식 조건부 선정과 Processing·Training 미승인 경계 등록 |
| 2026-07-29 | Dataset Selection Approval Package와 추천 전용 `CONDITIONALLY_SELECTED` 흐름 등록 |
| 2026-07-29 | Leakage 처리 정책·Processing Label·Dataset Readiness Matrix와 Approval Gate 등록 |
| 2026-07-29 | Near Duplicate 유형·구간·Cross-split·canonical 처리 후보와 Fail Closed 정책 등록 |
| 2026-07-29 | 승인된 1회 SFT Leakage Scan과 repository prompt 비교·local Benchmark 부재 결과 등록 |
| 2026-07-29 | 새 독립 승인 Run 0002의 Near Duplicate 1회 aggregate-only 결과와 미승인 처리 경계 등록 |
| 2026-07-29 | Near Duplicate 첫 timeout 보존과 bounded 후보 비교·12,000 Synthetic retry readiness 등록 |
| 2026-07-29 | AIHUB-71748 Exact Duplicate 유형·처리 후보·Fail Closed 정책과 미승인 처리 경계 등록 |
| 2026-07-29 | AIHUB-71748 Content Exact Duplicate 1회 scan과 split overlap·component consistency 결과 등록 |
| 2026-07-29 | AIHUB-71748 PII 민감 주제·식별자 분리, false positive·threshold proposal과 정책 계층 등록 |
| 2026-07-29 | AIHUB-71748 제한 PII 후보 scan과 첫 Fail Closed·두 번째 독립 실행 결과 등록 |
| 2026-07-29 | AIHUB-71748 SFTdata/SFTlabel `data_id` 제한 Join Integrity 계약 통과 결과 등록 |
| 2026-07-28 | AIHUB-71748 Schema Inspection incident와 synthetic-only Safe Dataset Inspector 구현·회귀 문서 등록 |
| 2026-07-28 | AIHUB-71748 SFT 이용조건과 원문 비출력 join·PII·중복·누수·품질 검증 계획 등록 |
| 2026-07-28 | AI Hub dataset 5종의 read-only inventory, schema 적합성, PII·license blocker 검토 문서 등록 |
| 2026-07-28 | DohaLM Instruct 설계·Readiness 문서 진입점 작성 |
