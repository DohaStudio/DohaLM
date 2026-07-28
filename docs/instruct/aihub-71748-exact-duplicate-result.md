# AIHUB-71748 SFT Content Exact Duplicate Scan 결과

- 문서 상태: `review`
- 마지막 검토일: 2026-07-29
- Dataset ID: `AIHUB-71748`
- 검사 상태: `completed`
- 실제 Full Scan 횟수: `1`
- 관련 문서: [SFT 검증 계획](./aihub-71748-sft-validation-plan.md), [Join Integrity 결과](./aihub-71748-join-integrity-result.md), [PII 판정 정책](./aihub-71748-pii-policy.md), [Safe Dataset Inspector](./safe-dataset-inspector.md), [ADR-004](../decisions/ADR-004-data-governance.md)

## 1. Scope

[확정] AIHUB-71748 SFTdata·SFTlabel의 Training과 Validation을 ZIP 추출 없이 read-only streaming으로
정확히 한 번 검사했다. Exact raw string equality만 사용했으며 trim, case 변환, Unicode normalization,
punctuation 제거, tokenization과 hash를 사용하지 않았다.

검사 통계의 기준 record는 Join Integrity 계약을 통과한 SFTlabel QA 11,902건이다. SFTdata question은 기존
one-to-one Join과 split별 원본 record 순서를 전제로 SFTlabel question과 lockstep exact consistency만 비교했다.
Scanner는 허용된 question과 answer.contents만 조회·비교했으며 data_id·category·context·metadata는 비교하거나
출력하지 않았다.

## 2. Approval

[확정] 승인 범위는 Content Exact Duplicate Scan, 구현·Synthetic/회귀 검증과 문서 게시까지다. Near Duplicate,
Leakage, Benchmark, Dataset 선택·처리, Adapter, backend와 학습은 승인되지 않았다.

## 3. Scan 범위

| Split | SFTdata question | SFTlabel question | SFTlabel answer.contents |
|---|---:|---:|---:|
| Training | 10,580 | 10,580 | 10,580 |
| Validation | 1,322 | 1,322 | 1,322 |
| 합계 | 11,902 | 11,902 | 11,902 |

`duplicate_records`는 각 그룹의 첫 record를 제외한 초과 record 수이고, `records_in_duplicate_groups`는 중복
그룹에 속한 전체 record 수다. 원문, 부분 문자열, hash와 record 위치는 결과에 포함하지 않았다.

## 4. Duplicate 결과

| 대상 | Scanned | Unique | Duplicate group | Duplicate excess record | Records in duplicate groups |
|---|---:|---:|---:|---:|---:|
| Question | 11,902 | 11,895 | 6 | 7 | 13 |
| Answer | 11,902 | 11,757 | 3 | 145 | 148 |
| QA Pair | 11,902 | 11,895 | 6 | 7 | 13 |

Question과 QA Pair의 중복 통계가 같고 same-question/different-answer 그룹이 0건이므로, 발견된 동일 question
그룹은 모두 동일 answer와 결합돼 있었다. 이는 품질 적격성이나 삭제 대상을 뜻하지 않는다.

## 5. Split별 Duplicate

| Split | 대상 | Scanned | Unique | Duplicate group | Duplicate excess record | Records in duplicate groups |
|---|---|---:|---:|---:|---:|---:|
| Training | Question | 10,580 | 10,575 | 4 | 5 | 9 |
| Training | Answer | 10,580 | 10,451 | 3 | 129 | 132 |
| Training | QA Pair | 10,580 | 10,575 | 4 | 5 | 9 |
| Validation | Question | 1,322 | 1,322 | 0 | 0 | 0 |
| Validation | Answer | 1,322 | 1,308 | 2 | 14 | 16 |
| Validation | QA Pair | 1,322 | 1,322 | 0 | 0 | 0 |

## 6. Split Overlap

Training과 Validation 양쪽에 존재하는 고유 exact value의 교집합을 집계했다.

| 대상 | Training ↔ Validation exact overlap |
|---|---:|
| Question | 2 |
| Answer | 2 |
| QA Pair | 2 |

[확정] Validation과 Training 사이 exact overlap이 있으므로 split 검토 blocker가 존재한다. 이번 작업에서는 해당
record를 식별·출력·필터링·삭제하지 않았다.

## 7. Component Consistency

| Split | Compared | Exact match | Mismatch | Match rate |
|---|---:|---:|---:|---:|
| Training | 10,580 | 10,580 | 0 | 1.0 |
| Validation | 1,322 | 1,322 | 0 | 1.0 |
| 합계 | 11,902 | 11,902 | 0 | 1.0 |

[확정] 기존 Join Integrity의 one-to-one 계약과 split별 record 순서를 기준으로 SFTdata.question과
SFTlabel.question은 모두 exact 일치했다.

## 8. 교차 관계

| 관계 | Group |
|---|---:|
| Same question, different answer | 0 |
| Different question, same answer | 3 |

동일 answer가 서로 다른 question에 연결된 그룹은 3개다. 원문 검토나 품질 판정 없이 boilerplate, 오류 또는 제거
대상으로 해석하지 않는다.

## 9. Safety

```yaml
safety:
  raw_output: false
  substring_output: false
  data_id_output: false
  hash_used: false
  hash_output: false
  hash_stored: false
  stdout_leak: false
  stderr_leak: false
  exception_leak: false
  dataset_modified: false
```

Safe Dataset Inspector output guard는 숫자·boolean·고정 상태값으로 구성된 결과에 적용됐다. Synthetic raw value와
비허용 output string은 각각 `RAW_VALUE_LEAK_DETECTED`, `UNSAFE_OUTPUT_STRING`으로 차단됨을 실행 전에 검증했다.

## 10. 실행 계약

전체 사전 Gate `853 passed` 이후 실제 full scan 함수를 정확히 한 번 호출했다. 결과는 `completed`,
`full_scan_count: 1`이며 자동 retry, resume 또는 추가 실행은 0건이다. 원본 ZIP·JSON·Dataset Root에 대한 쓰기,
복사, 추출, 변환, cache와 결과 manifest 생성도 0건이다.

## 11. Blocker

1. Training/Validation question·answer·QA pair exact overlap이 각각 2개다.
2. 동일 answer가 서로 다른 question에 연결된 그룹이 3개다.
3. 중복 처리·split 조정 threshold와 조치는 승인되지 않았다.
4. Near Duplicate와 Leakage Scan은 미승인·미실행이다.
5. Dataset 선택·처리, SFT backend와 학습은 미승인이다.

## 12. Readiness

```yaml
AIHUB_71748_SFT:
  schema_inspection: completed
  safe_inspector: validated
  join_integrity_scan: completed
  join_contract: passed
  pii_scan: completed_candidates_detected
  pii_policy: completed
  pii_threshold_policy: proposed_not_approved
  content_exact_duplicate_scan: completed
  near_duplicate_scan: not_approved
  leakage_scan: not_approved
  dataset_selection: not_selected
  dataset_processing: not_approved
overall:
  sft_backend: not_started
  sft_training: not_approved
  execution_allowed: false
```

## 13. 다음 단계

[승인 필요] 다음 권장 단계는 별도 범위의 Near Duplicate Scan 설계·실행 승인이다. 이후 Leakage Scan과 exact
overlap 처리 정책을 각각 승인해야 한다. 현재 결과만으로 Dataset 선택·처리 또는 SFT를 승인할 수 없다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-29 | 승인된 1회 Content Exact Duplicate Scan의 원문 비출력 집계와 blocker 기록 |
