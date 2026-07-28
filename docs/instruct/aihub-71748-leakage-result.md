# AIHUB-71748 SFT Leakage / Benchmark Contamination Scan 결과

- 문서 상태: `review`
- 마지막 검토일: 2026-07-29
- Dataset ID: `AIHUB-71748`
- 실행 ID: `AIHUB-71748-LEAKAGE-SCAN-20260729-0001`
- Scan 상태: `completed`
- 정책 상태: `review_required`
- 관련 문서: [Near Duplicate 결과](./aihub-71748-near-duplicate-result.md), [Near Duplicate 처리 정책](./aihub-71748-near-duplicate-policy.md), [SFT 검증 계획](./aihub-71748-sft-validation-plan.md), [Safe Dataset Inspector](./safe-dataset-inspector.md), [ADR-004](../decisions/ADR-004-data-governance.md), [ADR-010](../decisions/ADR-010-dohalm-instruct-strategy.md)

## 1. Scope

[확정] 승인된 `SFTdata`와 `SFTlabel`의 Training·Validation만 ZIP에서 read-only 스트리밍했다. 비교 입력은
`SFTdata.question`, `SFTlabel.question`, `SFTlabel.answer.contents`로 제한했다. Dataset 처리·선택·수정,
Threshold 승인, 외부 Benchmark 다운로드, Tokenization, Adapter, Backend와 Training은 수행하지 않았다.

## 2. Approval과 실행 한도

```yaml
execution_id: AIHUB-71748-LEAKAGE-SCAN-20260729-0001
actual_scan_calls: 1
maximum_real_scans: 1
retry_allowed: false
resume_allowed: false
runtime_extension_allowed: false
runtime_budget_seconds: 300
memory_budget_mib: 512
status: completed
```

## 3. 입력 범위와 성능

| 항목 | Training | Validation | 합계 |
|---|---:|---:|---:|
| Question | 10,580 | 1,322 | 11,902 |
| Answer | 10,580 | 1,322 | 11,902 |
| QA Pair | 10,580 | 1,322 | 11,902 |

| 항목 | 관측값 | 승인 한도 | 결과 |
|---|---:|---:|---|
| Runtime | 47.125초 | 300초 | `passed` |
| Peak memory | 43,449,178 bytes | 536,870,912 bytes | `passed` |
| Worker process | 0 | 0 | `passed` |
| Temporary file | 0 | 0 | `passed` |

## 4. Train / Validation 교차 결과

| Leakage 유형 | Exact group / pair | Normalized-only group / pair | Near group / pair | 총 candidate pair |
|---|---:|---:|---:|---:|
| `TRAIN_VALIDATION_QUESTION_LEAK` | 2 / 2 | 1 / 1 | 40 / 45 | 48 |
| `TRAIN_VALIDATION_ANSWER_LEAK` | 2 / 1,688 | 0 / 0 | 1 / 2 | 1,690 |
| `TRAIN_VALIDATION_QA_LEAK` | 2 / 2 | 1 / 1 | 0 / 0 | 3 |

[확정] Near 수치는 기존 승인 실행 `AIHUB-71748-NEAR-DUPLICATE-SCAN-20260729-0002`의 Cross-split
aggregate를 재사용했다. Near Duplicate Scan은 재실행하지 않았다. 모든 후보는 `REVIEW_REQUIRED`이며 자동 제거,
필터링 또는 split 변경을 하지 않았다.

## 5. Repository evaluation prompt 비교

| Leakage 유형 | Source | Prompt | Exact Question | Exact Answer | Normalized Question | Normalized Answer | Candidate |
|---|---|---:|---:|---:|---:|---:|---:|
| `EVALUATION_PROMPT_LEAK` | `configs/evaluation-prompts.example.yaml` | 10 | 0 | 0 | 0 | 0 | 0 |
| `MODEL_EVALUATION_LEAK` | `configs/eos-generation-prompts.example.yaml` | 15 | 0 | 0 | 0 | 0 | 0 |

[확정] 두 source는 저장소의 `source: synthetic`, `pii_free: true` 계약을 확인한 뒤 비교했다. Near prompt 비교는
기존 Near Scan 재실행 금지 때문에 수행하지 않았다.

## 6. Benchmark 범위와 한계

```yaml
benchmark:
  local_sources: 0
  prompts_scanned: 0
  candidates: 0
  status: not_available_local
  external_download: false
```

[검증 필요] 저장소에는 별도 외부 공개 Benchmark prompt source와 고정 version이 없다. 따라서 이번 결과는
`BENCHMARK_CONTAMINATION_CANDIDATE`가 없음을 입증하지 않으며 Benchmark clear 판정도 아니다. 외부 인터넷이나
외부 Benchmark를 다운로드하지 않았다.

## 7. Risk

```yaml
risk:
  candidate_types_without_hits: 3
  informational: 0
  review_candidate_pairs: 1741
  blocked_candidate: 0
  policy: REVIEW_REQUIRED
  threshold_status: not_approved
```

[확정] Candidate pair 합계는 Train/Validation Question 48, Answer 1,690, QA Pair 3이다. Evaluation,
Candidate Model과 local Benchmark candidate는 각각 0이다. Threshold와 자동 처리 정책은 승인되지 않았으므로
어떤 후보도 자동 분류·제거하지 않는다.

## 8. Safety와 무결성

```yaml
safety:
  raw_output: false
  substring_output: false
  preview_output: false
  data_id_output: false
  hash_output: false
  benchmark_raw_output: false
  stdout_leak: false
  stderr_leak: false
  exception_leak: false
  temporary_files: false
  worker_processes: false
  dataset_write: false
  external_internet: false
```

[확정] 실행 전후 package는 파일 55개와 총 17,256,335,769 bytes로 기존 package inventory와 일치했다.
Scanner에는 Dataset 쓰기 경로가 없고 Dataset·ZIP·JSON을 수정·복사·이동·삭제하지 않았다. 출력은 aggregate와
고정 error code로 제한했고 원문·substring·preview·실제 ID·hash·candidate pair 목록을 저장하거나 출력하지 않았다.

## 9. Readiness

```yaml
AIHUB_71748_SFT:
  schema_inspection: completed
  safe_inspector: validated
  join_integrity_scan: passed
  pii_scan: completed
  pii_policy: completed
  exact_duplicate_scan: completed
  exact_duplicate_policy: completed
  near_duplicate_scan: completed
  near_duplicate_policy: completed
  leakage_scan: completed
  leakage_policy: review_required
  benchmark_contamination: not_available_local
  dataset_selection: not_selected
  dataset_processing: not_approved
overall:
  sft_backend: not_started
  sft_training: not_approved
  execution_allowed: false
```

## 10. 다음 승인

[승인 필요] Dataset 선택이나 처리 전에 Train/Validation 1,741 candidate pair의 처리 원칙, 실제 Threshold,
Validation 보존 방식과 외부 Benchmark source/version 계약을 별도로 승인해야 한다. 이번 결과만으로 Dataset 처리,
Adapter, SFT Backend 또는 Training을 시작할 수 없다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-29 | 승인된 1회 aggregate-only Leakage Scan, repository prompt 비교와 local Benchmark 부재 기록 |
