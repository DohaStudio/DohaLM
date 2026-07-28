# AIHUB-71748 SFT Near Duplicate Scan 결과

- 문서 상태: `review`
- 마지막 검토일: 2026-07-29
- Dataset ID: `AIHUB-71748`
- 실행 ID: `AIHUB-71748-NEAR-DUPLICATE-SCAN-20260729-0002`
- Scan 상태: `completed`
- 정책 상태: `proposed_not_approved`
- 관련 문서: [Scanner 최적화](./aihub-71748-near-duplicate-optimization.md), [Exact Duplicate 결과](./aihub-71748-exact-duplicate-result.md), [Exact Duplicate 정책](./aihub-71748-exact-duplicate-policy.md), [Safe Dataset Inspector](./safe-dataset-inspector.md), [ADR-004](../decisions/ADR-004-data-governance.md), [ADR-010](../decisions/ADR-010-dohalm-instruct-strategy.md)

## 1. Scope

[확정] 이 문서는 승인된 새 execution ID로 `SFTdata`·`SFTlabel`의 Training과 Validation을 read-only로
스트리밍한 Near Duplicate Scan의 aggregate-only 결과다. Question은 검증된 canonical
`SFTdata.question`, Answer는 `SFTlabel.answer.contents`, QA Pair는 두 field의 결합만 사용했다.

[확정] General Corpus, RM, PPO, Leakage·Benchmark Contamination, Dataset Processing, Tokenization, Adapter,
SFT backend와 학습에는 접근하지 않았다. Dataset은 선택되지 않았고 `execution_allowed: false`를 유지한다.

## 2. 승인과 실행 이력

```yaml
attempt_history:
  - attempt: 1
    status: failed_closed
    reason_code: RUNTIME_TIMEOUT
    timeout_seconds: 604
    approval_consumed: true
    completed_result: false
    retry_performed: false
    raw_value_leak: false
    dataset_modified: false

  - attempt: 2
    execution_id: AIHUB-71748-NEAR-DUPLICATE-SCAN-20260729-0002
    status: completed
    actual_scan_calls: 1
    maximum_runtime_seconds: 300
    retry_allowed: false
    resume_allowed: false
    extension_allowed: false
```

[확정] 두 번째 실행은 첫 실행의 retry나 resume가 아닌 새 독립 승인이다. 실제 scanner process 시작 전에 발생한
PowerShell wrapper 인자 구성 오류는 Python process와 Dataset 접근 없이 종료됐으며 실제 Scan 호출로 계산하지
않았다. 이후 실제 scanner는 정확히 한 번만 시작됐다.

## 3. 최적화와 고정 계약

[확정] 첫 timeout 이후 normalized value group, SimHash 4×16-bit band, MinHash 4×4 band, 결정론적 bounded
candidate accumulator, cheap filter와 candidate-only `SequenceMatcher.quick_ratio()`를 적용했다. 실제 실행 전체
시간에는 archive 계약과 ZIP 스트리밍도 포함하도록 monitor 시작점을 보완했다.

| 상한 | 승인값 | 관측값 | 결과 |
|---|---:|---:|---|
| Record별 candidate | 256 | 상한 미초과 | `passed` |
| 전체 candidate pair | 250,000 | 103,372 deduplicated | `passed` |
| Expensive comparison | 100,000 | 38,782 | `passed` |
| Memory estimate | 512 MiB | 486,724,147 bytes (약 464.18 MiB) | `passed` |
| Runtime | 300초 | 155.547초 | `passed` |

## 4. Record 수

| 대상 | Training | Validation | 합계 | 계약 |
|---|---:|---:|---:|---|
| Question | 10,580 | 1,322 | 11,902 | `passed` |
| Answer | 10,580 | 1,322 | 11,902 | `passed` |
| QA Pair | 10,580 | 1,322 | 11,902 | `passed` |

## 5. Question 결과

| 항목 | 집계 |
|---|---:|
| Scanned record | 11,902 |
| Raw exact 제외 group | 6 |
| Raw exact 제외 pair | 8 |
| Normalized exact 제외 group | 2 |
| Normalized exact 제외 pair | 2 |
| Near candidate group | 167 |
| Near candidate record | 362 |
| Near candidate pair | 210 |
| Blocked-proposal band pair | 25 |

## 6. Answer 결과

| 항목 | 집계 |
|---|---:|
| Scanned record | 11,902 |
| Raw exact 제외 group | 3 |
| Raw exact 제외 pair | 8,857 |
| Normalized exact 제외 group | 0 |
| Normalized exact 제외 pair | 0 |
| Near candidate group | 4 |
| Near candidate record | 20 |
| Near candidate pair | 16 |
| Blocked-proposal band pair | 13 |

## 7. QA Pair 결과

| 항목 | 집계 |
|---|---:|
| Scanned record | 11,902 |
| Raw exact 제외 group | 6 |
| Raw exact 제외 pair | 8 |
| Normalized exact 제외 group | 2 |
| Normalized exact 제외 pair | 2 |
| Near candidate group | 0 |
| Near candidate record | 0 |
| Near candidate pair | 0 |
| Blocked-proposal band pair | 0 |

[확정] Question과 Answer가 각각 Near Duplicate인 관계가 있어도 같은 record pair에서 두 조건이 함께 충족되지
않으면 QA Pair 후보로 집계하지 않는다. 후보 0은 Near Duplicate 부재의 절대적 증명이 아니다.

## 8. Cross-split 결과

| 유형 | Candidate group | Affected record | Candidate pair | Blocked-proposal band pair |
|---|---:|---:|---:|---:|
| Question | 40 | 85 | 45 | 6 |
| Answer | 1 | 3 | 2 | 2 |
| QA Pair | 0 | 0 | 0 | 0 |

[확정] 모든 후보의 상태는 `REVIEW_REQUIRED`다. Cross-split 후보를 자동 제외하거나 split을 변경하지 않았다.

## 9. Similarity histogram

현재 구현의 고정 구간을 사용했으며 exact `1.0`은 Near Duplicate에서 제외했다.

| 대상 | 0.90–0.93 | 0.93–0.97 | 0.97–1.00 미만 |
|---|---:|---:|---:|
| Question | 108 | 77 | 25 |
| Answer | 2 | 1 | 13 |
| QA Pair | 0 | 0 | 0 |
| Cross-split Question | 22 | 17 | 6 |
| Cross-split Answer | 0 | 0 | 2 |
| Cross-split QA Pair | 0 | 0 | 0 |

## 10. Candidate와 정밀 비교 통계

| 대상 | Raw candidate pair | Deduplicated candidate pair | 중복 candidate 제거 | Expensive comparison |
|---|---:|---:|---:|---:|
| Question | 52,418 | 38,665 | 13,753 | 18,496 |
| Answer | 77,340 | 64,707 | 12,633 | 20,286 |
| 합계 | 129,758 | 103,372 | 26,386 | 38,782 |

## 11. Safety와 무결성

```yaml
safety:
  safe_inspector: passed
  output_guard: passed
  raw_output: false
  substring_output: false
  preview_output: false
  data_id_output: false
  hash_output: false
  stdout_leak: false
  stderr_leak: false
  exception_leak: false
  logging_leak: false
  archive_path_output: false
  worker_processes_after_exit: 0
  temporary_files: false
  dataset_root_write: false
  dataset_modified: false
```

[확정] 실행 전후 외부 package의 파일 수 55개, 총 byte 17,256,335,769와 파일 timestamp aggregate가 일치했다.
Dataset·ZIP·JSON을 수정·복사·이동·삭제하지 않았고 원문·부분 문자열·실제 ID·hash·candidate pair 목록을
출력하거나 저장하지 않았다.

## 12. Threshold와 Blocker

| Threshold | 제안값 | 승인 | 자동 처리 |
|---|---:|---|---|
| Review candidate | 0.90 | `not_approved` | 없음 |
| Blocked candidate | 0.97 | `not_approved` | 없음 |

[확정] `blocked_candidate`는 정책 제안 구간 이름이며 Dataset 자동 차단이나 제거 승인이 아니다. Near Duplicate
처리 정책, Cross-split 조치, Leakage Scan, Dataset 선택·처리와 SFT는 각각 별도 승인이 필요하다.

## 13. Readiness

```yaml
AIHUB_71748_SFT:
  exact_duplicate_scan: completed
  exact_duplicate_policy: completed
  near_duplicate_scan: completed
  near_duplicate_policy: proposed_not_approved
  leakage_scan: not_approved
  dataset_selection: not_selected
  dataset_processing: not_approved
overall:
  sft_backend: not_started
  sft_training: not_approved
  execution_allowed: false
```

## 14. 다음 승인

[승인 필요] 다음 단계는 Near Duplicate threshold와 Cross-split 후보 처리 정책을 확정하거나, 별도 범위·입력·출력
계약으로 Leakage Scan을 승인하는 것이다. 이 결과만으로 Dataset 선택·처리, Adapter, Tokenization 또는 SFT를
시작할 수 없다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-29 | 새 독립 승인 Run 0002의 1회 aggregate-only Near Duplicate Scan 결과와 안전·상한 검증 기록 |
