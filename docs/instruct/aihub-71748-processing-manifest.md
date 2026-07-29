# AIHUB-71748 SFT Processing Manifest

- 문서 상태: `approved`
- 마지막 검토일: 2026-07-30
- Manifest: `configs/data/aihub-71748-sft-processing-v1.yaml`
- Manifest 상태: `completed_non_executable`
- Rule threshold 상태: `approved_for_processing_manifest`
- Processing 실행: `not_approved`
- `execution_allowed`: `false`
- 관련 문서: [Selection Decision](./aihub-71748-selection-decision.md), [Dataset Readiness](./aihub-71748-readiness.md), [Processing Backend](./processing-backend.md), [Manifest Schema](./processing-manifest-schema.md), [ADR-004](../decisions/ADR-004-data-governance.md), [ADR-010](../decisions/ADR-010-dohalm-instruct-strategy.md)

## 1. Scope

[확정] 이 문서는 기존 aggregate Scan 결과와 정책만 사용해 AIHUB-71748 SFT Processing 계약을 고정한다.
Dataset·ZIP·JSON 재열람, Scan 재실행, 실제 label 부여, Processing, Processed Dataset 생성, Tokenization과
Training은 수행하지 않는다. Manifest는 canonical 계약이지만 Approval이 비어 있어 consume하거나 실행할 수 없다.

## 2. Dataset Identity

```yaml
manifest_type: sft_dataset_processing
manifest_version: 1
provider: AI_Hub
dataset_id: AIHUB-71748
component: SFT
input_components: [SFTdata, SFTlabel]
allowed_splits: [Training, Validation]
source_selection_status: CONDITIONALLY_SELECTED
```

[확정] source는 `${DOHALM_DATASET_ROOT}/AIHUB-71748` 논리 경로만 사용한다. 절대 로컬 경로는 Manifest에
포함하지 않으며 이번 검증은 환경변수나 경로를 resolve하지 않는다.

## 3. Input Contract

| 항목 | Training | Validation | Total |
|---|---:|---:|---:|
| Record | 10,580 | 1,322 | 11,902 |

- Join key: `data_id`
- Join 관계: `one_to_one`
- Component question expected match/mismatch: `11,902 / 0`
- SFTdata 필수 field: `data_id`, `question`, `question_count`, `question_type`, `data_category`
- SFTlabel 필수 field: `data_id`, `question`, `answer.contents`, `answer.answer_count`

[확정] 수, schema, join 관계가 다르면 실제 Processing은 Fail Closed 대상이다.

## 4. Output Schema

| Field | Source | Type | 학습 입력 |
|---|---|---|---|
| `instruction` | `SFTdata.question` | string, required | 예 |
| `input` | `null` | null 또는 string | 예 |
| `output` | `SFTlabel.answer.contents` | string, required | 예 |
| `system` | `null` | null 또는 string | 예 |
| `metadata` | 고정 계보 field | object | 아니요 |

Metadata는 provider, Dataset ID, Component, source split, question type, category와 내부 전용 source record ID
계보를 보존한다. 실제 `data_id`는 문서·로그·공개 결과에 출력하지 않는다.

## 5. Rule Order

1. `INPUT_IDENTITY_VALIDATION`
2. `SCHEMA_VALIDATION`
3. `JOIN_VALIDATION`
4. `OUTPUT_SCHEMA_MAPPING`
5. `PII_POLICY`
6. `EXACT_DUPLICATE_POLICY`
7. `NEAR_DUPLICATE_POLICY`
8. `LEAKAGE_POLICY`
9. `VALIDATION_SPLIT_POLICY`
10. `FINAL_SCHEMA_VALIDATION`
11. `STATISTICS_VALIDATION`
12. `MANIFEST_FINALIZATION`

[확정] Manifest Rule의 `enabled: true`는 별도 승인된 향후 실행에서 적용할 계약이라는 뜻이며 현재 실행 권한이
아니다.

## 6. PII Rule

| 조건 | Action |
|---|---|
| 직접 식별정보가 없는 민감 주제 단독 | `KEEP` |
| 단일 직접 식별정보 후보 | `REVIEW_REQUIRED` |
| 복수 직접 식별정보 | `BLOCKED` |
| 직접 식별정보와 민감 주제 결합 | `BLOCKED` |
| Critical 후보 | `BLOCKED` |

[확정] 기존 집계는 후보 Component-record 4,390건, none/low/medium/high/critical
19,414/4,175/156/59/0이다. 실제 record 판정이나 label 적용은 하지 않았다.

## 7. Exact Duplicate Rule

- 같은 split의 동일 QA pair: `CANONICAL_CANDIDATE`; source order의 첫 record를 결정론적 후보로 사용한다.
- Cross-split 동일 QA pair: Training `KEEP`, Validation `VALIDATION_EXCLUSION_CANDIDATE`.
- 동일 question과 다른 answer: `BLOCKED`.
- 다른 question의 동일 answer: `KEEP`; Answer-only 중복은 자동 제거하지 않는다.

기준 aggregate는 Question 6그룹/초과 7건, Answer 3그룹/초과 145건, QA pair 6그룹/초과 7건,
Cross-split QA pair 2개다.

## 8. Near Duplicate Rule

```yaml
review_min: 0.90
high_similarity_min: 0.97
```

- 같은 split `0.90 ≤ similarity < 0.97`: `KEEP`.
- 같은 split `0.97 ≤ similarity < 1.00`: `REVIEW_REQUIRED`.
- Cross-split Question 0.90~0.97: `REVIEW_REQUIRED`.
- Cross-split Question 0.97~1.00: Training `KEEP`, Validation `VALIDATION_EXCLUSION_CANDIDATE`.
- Cross-split Answer: `REVIEW_REQUIRED`.
- QA pair Near Duplicate: Training `KEEP`, Validation `VALIDATION_EXCLUSION_CANDIDATE`.

기준 aggregate는 Question 167그룹/362 record, Answer 4그룹/20 record, QA pair 0그룹이며 Cross-split
Question 40그룹/45 pair, Answer 1그룹/2 pair다.

## 9. Leakage Rule

- Train/Validation QA Exact·Normalized: Training `KEEP`, Validation `VALIDATION_EXCLUSION_CANDIDATE`.
- Question Exact·Normalized: Training `KEEP`, Validation `VALIDATION_EXCLUSION_CANDIDATE`.
- Question Near: `REVIEW_REQUIRED`.
- Answer-only overlap: `KEEP`.
- Evaluation 및 Candidate A/B prompt 후보: `BLOCKED`.
- Benchmark: `blocked_not_available`; record action은 없지만 최종 평가·공개 전에 별도 검증이 필요하다.

기준 후보는 Question Exact/Normalized/Near `2/1/45`, Answer `1,688/0/2`, QA `2/1/0`이며 고정 Evaluation
prompt 후보는 0건이다.

## 10. Validation Policy

[확정] Exact·Normalized·고유사도 Cross-split QA는 Validation 제외 후보로 분류한다. Cross-split Question Near는
검토하고 Answer-only overlap은 제거하지 않는다. 처리 후 Validation이 1,000건 미만이면
`VALIDATION_SIZE_BELOW_MINIMUM`으로 Fail Closed한다.

## 11. Conflict Resolution

```text
BLOCKED
  > VALIDATION_EXCLUSION_CANDIDATE
  > REVIEW_REQUIRED
  > CANONICAL_CANDIDATE
  > KEEP
```

[확정] 가장 제한적인 action을 선택하고 알 수 없는 조합은 Fail Closed한다. `MERGE_CANDIDATE`는 이 Manifest에서
사용하지 않는다.

## 12. REVIEW_REQUIRED 처리

- 일반 Training 후보: `KEEP`와 내부 policy label을 요구한다.
- 일반 Validation 후보: `VALIDATION_EXCLUSION_CANDIDATE`.
- PII `REVIEW_REQUIRED`: Training과 Validation 모두 `VALIDATION_EXCLUSION_CANDIDATE`.
- 실제 source text 수동 검토: `false`.

[확정] 위 값은 label 계약이며 이번 작업에서 record에 적용하지 않는다.

## 13. Threshold와 Statistics Contract

| 계약 | 값 |
|---|---:|
| Critical PII 최대 | 0 |
| Question conflict 최대 그룹 | 0 |
| 최소 Training record | 10,000 |
| 최소 Validation record | 1,000 |
| 최대 총 제외율 | 0.10 |

[확정] 정확한 output record 수는 중첩 Rule 때문에 `unknown_until_processing`이다. 위 값은 예상 성능이 아니라
Processing 결과의 Fail Closed guardrail이다. 위반 오류는 `TRAINING_SIZE_BELOW_MINIMUM`,
`VALIDATION_SIZE_BELOW_MINIMUM`, `EXCLUSION_RATE_ABOVE_LIMIT`이다.

## 14. Output Contract

```yaml
raw_root: ${DOHALM_DATASET_ROOT}/AIHUB-71748
processed_root: ${DOHALM_DATASET_ROOT}/processed/instruct/AIHUB-71748
run_root: ${DOHALM_DATASET_ROOT}/processed/instruct/AIHUB-71748/${PROCESSING_RUN_ID}
overwrite_allowed: false
run_id_reuse_allowed: false
in_place_update_allowed: false
```

허용 파일은 `train.jsonl`, `validation.jsonl`, `manifest.yaml`, `statistics.json`, `checksums.sha256`,
`processing-result.yaml`뿐이다. 원문 preview, content가 포함된 rejected record, PII sample, candidate pair·stable
hash·raw ID 목록은 금지한다.

## 15. Processing Approval Schema

[확정] Approval ID, Run ID, Manifest SHA-256, Git commit, 승인자와 승인 시각은 모두 `null`이다. 최대 실행 수는
1이지만 processing·tokenization·training·execution, retry·resume·overwrite 권한은 모두 `false`다.

Run ID 형식은 `AIHUB-71748-SFT-PROCESSING-YYYYMMDD-NNNN`, Approval ID 형식은
`AIHUB-71748-SFT-PROCESSING-APPROVAL-YYYYMMDD-NNNN`이다. 실제 값은 별도 사용자 승인에서만 발급한다.

## 16. Fail Closed

Identity·count·schema·join·Rule 순서·action·threshold·output path·Approval·권한·통계 불일치는 고정 오류 코드로
중단한다. Validator는 Mapping만 입력받고 Dataset, 파일, ZIP, JSON, 환경변수, 네트워크에 접근하지 않는다.

## 17. Current Status

```yaml
processing_manifest: completed
rule_thresholds: approved_for_processing_manifest
processing_backend: implemented_hardened_synthetic_validated
processing_execution: not_approved
processing_run_0008: preflight_passed
approval_0008: prepared_not_issued
processed_dataset: not_created
tokenization: not_started
sft_backend: not_started
sft_training: not_approved
execution_allowed: false
```

[확정] Run 0001은 local Mapping 필수 field 부족으로 Approval 생성 전 Mapping Gate에서 Fail Closed됐으며 재사용할
수 없다. [실제 Backend와 Mapping 계약](./aihub-71748-real-processing-backend.md)은 구현·Synthetic 검증됐고
[Run 0002 Preflight](./aihub-71748-processing-run-0002-preflight.md)는
`retired_failed_closed_before_consumption`이고 Approval 0002는 `retired_not_issued`다.
[Run 0003 Backend 계약](./aihub-71748-run-0003-backend-hardening.md)은 Synthetic 검증됐지만 metadata-only
Preflight에서 식별자 선언을 사용 흔적으로 오인해 Fail Closed했다. Run 0003은
`retired_failed_closed_before_approval`, Approval 0003은 `retired_not_issued`다.
[Run 0004 Preflight](./aihub-71748-processing-run-0004-preflight.md)는 수정된 registry validator에서
통과했고 당시 Approval 0004는 `prepared_not_issued`였다. 이후 발급 없이 폐기됐으며 실제 실행 권한은
부여되지 않았다.

[Run 0005](./aihub-71748-processing-run-0005-preflight.md)는 validator가 명시적 ID 대신 0004 상수를 비교한
결함으로 폐기됐고 Approval은 발급되지 않았다. 이 결함을 수정한 새 immutable commit에서
[Run 0006](./aihub-71748-processing-run-0006-preflight.md)는 metadata-only Preflight를 통과했다.
당시 Approval 0006은 `prepared_not_issued`, `execution_allowed=false`였다.
후속 발급 검토에서 permission·schema·lineage 불일치가 발견되어 Run 0006은
`retired_approval_contract_failure`, Approval 0006은 `retired_not_issued`로 폐기했다.
[Approval·Lineage 계약](./aihub-71748-approval-lineage-contract.md)이 후속 Run의 발급·실행 경계를 대체한다.

## 18. Next Approval

[확정] [Processing 계약 v2](./aihub-71748-processing-contract-v2.md)는 Manifest version 1과 budget·allowlist를
유지한 채 Synthetic 전체 E2E를 통과했다. Run 0007은 계약 불일치로 시작 전 폐기됐다.

[확정] [Run 0008 metadata-only Preflight](./aihub-71748-processing-run-0008-preflight.md)는 Manifest를 변경하거나
소비하지 않고 통과했으며 Approval은 `prepared_not_issued`다.

[승인 필요] 다음 단계는 최신 develop과 freshness를 live 재검증한 Approval 0008 발급의 별도 승인이다. 별도 승인 전에는 Approval 발급·소비,
Manifest consume, Dataset Processing과 Processed Dataset 생성이 금지된다. Processing 성공도
Tokenization이나 SFT Training을 자동 승인하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-30 | Run 0008 metadata-only Preflight 통과와 Manifest 비소비 상태 기록 |
| 2026-07-30 | Processing 계약 v2 동결과 Run 0008 별도 승인 경계 반영 |
| 2026-07-30 | Run 0006 Approval 계약 실패 폐기와 후속 Approval·Lineage 계약 연결 |
| 2026-07-29 | Run 0004 metadata-only Preflight와 non-issued Approval 초안 상태 연결 |
| 2026-07-29 | Run 0003 metadata-only Preflight 오탐 Fail Closed와 ID 폐기 상태 연결 |
| 2026-07-29 | Run 0002 폐기와 Run 0003 hardened backend·Preflight 미시작 상태 연결 |
| 2026-07-29 | Run 0002 metadata-only Preflight와 non-executable Approval 초안 상태 연결 |
| 2026-07-29 | Run 0001 Mapping Gate Fail Closed·폐기와 실제 Backend/Mapping 구현 상태 연결; Run 0002 미승인 유지 |
| 2026-07-29 | AIHUB-71748 SFT Manifest identity·Rule·threshold·output·Approval 계약 확정; 실행 미승인 유지 |
