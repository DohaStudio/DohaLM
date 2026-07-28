# AIHUB-71748 SFT 제한 PII Scan 결과

- 문서 상태: `review`
- 마지막 검토일: 2026-07-29
- Dataset ID: `AIHUB-71748`
- 실행 ID: `AIHUB-71748-PII-SCAN-20260729-0002`
- 결과: `completed_candidates_detected`
- 관련 문서: [검증 계획](./aihub-71748-sft-validation-plan.md), [Schema Inspection](./aihub-71748-schema-inspection.md), [Safe Dataset Inspector](./safe-dataset-inspector.md), [Join Integrity 결과](./aihub-71748-join-integrity-result.md), [ADR-004](../decisions/ADR-004-data-governance.md)

## 1. Scope

[확정] AIHUB-71748의 SFTdata·SFTlabel Training/Validation에서 승인된 질문·답변 field의 PII 및 민감정보
의심 패턴만 read-only로 탐지·집계했다. 이는 PII 존재 확정, PII 부재 증명, Dataset 선택·처리 또는 학습 승인이 아니다.

## 2. 승인 ID

두 번째 독립 실행 승인 ID는 `AIHUB-71748-PII-SCAN-20260729-0002`이며 실제 full scan 1회, retry·resume·extension
금지 계약으로 실행했다.

## 3. 이전 실패와 수정

```yaml
attempt_history:
  - attempt: 1
    status: failed_closed
    error_code: UNSAFE_OUTPUT_STRING
    cause: result_field_path_allowlist_mismatch
    raw_value_leak: false
    dataset_modified: false
  - attempt: 2
    execution_id: AIHUB-71748-PII-SCAN-20260729-0002
    status: completed_candidates_detected
    full_scan_count: 1
    raw_value_leak: false
    dataset_modified: false
```

[확정] 첫 실패를 삭제하거나 retry로 재분류하지 않았다. 수정은 결과 field path를 세 개의 고정 `$.…` allowlist로
제한하고 unknown·dynamic path를 `UNSAFE_OUTPUT_STRING`으로 차단한 것이다.

## 4. 실행 범위

허용된 네 ZIP의 SFT JSON entry만 추출 없이 bounded streaming으로 읽었다. General Corpus, RM, PPO 및 알 수 없는
component·split은 접근하지 않았다. 원본·ZIP·Dataset Root 쓰기와 payload 임시 저장은 0건이다.

## 5. Component와 field

| Component | 허용 field | Record |
|---|---|---:|
| SFTdata | `$.sftdata.question` | 11,902 |
| SFTlabel | `$.sftlabel.question` | 11,902 |
| SFTlabel | `$.sftlabel.answer.contents` | 11,902 |

SFTdata와 SFTlabel record는 각각 Training 10,580건, Validation 1,322건으로 Join 계약과 일치했다.

## 6. Synthetic Gate

합성 PII, Safe Dataset Inspector, Join Integrity, 고정 field allowlist, unknown/dynamic path 차단, stdout·stderr·log·
exception·serialization·16자 substring 누출 테스트 70건이 실제 실행 전에 통과했다.

## 7. 실제 Scan 횟수

[확정] 두 번째 승인으로 실제 full scan을 정확히 1회 호출했다. 추가 실행과 자동 retry는 없었다.

## 8. Record 수

| 구분 | Scanned record | 후보 record |
|---|---:|---:|
| SFTdata | 11,902 | 731 |
| SFTlabel | 11,902 | 3,659 |
| Training | 21,160 | 3,925 |
| Validation | 2,644 | 465 |
| 합계 | 23,804 | 4,390 |

Field scan 합계는 35,706건이다. Component별 record는 독립 집계했으며 질문 내용 동일성은 검사하지 않았다.

## 9. Field별 후보 집계

| Field | Split | Scanned | 후보 record | Occurrence |
|---|---|---:|---:|---:|
| `$.sftdata.question` | Training | 10,580 | 656 | 761 |
| `$.sftdata.question` | Validation | 1,322 | 75 | 91 |
| `$.sftlabel.question` | Training | 10,580 | 656 | 761 |
| `$.sftlabel.question` | Validation | 1,322 | 75 | 91 |
| `$.sftlabel.answer.contents` | Training | 10,580 | 3,254 | 12,755 |
| `$.sftlabel.answer.contents` | Validation | 1,322 | 390 | 1,546 |

## 10. 유형별 occurrence와 affected record

| Candidate type | Occurrence | Affected record |
|---|---:|---:|
| account number like | 2 | 2 |
| address | 281 | 200 |
| IP address | 1 | 1 |
| postal code | 14 | 8 |
| URL | 7 | 4 |
| person name candidate | 94 | 70 |
| organization-role combination | 107 | 88 |
| medical sensitive candidate | 5,704 | 1,630 |
| mental-health candidate | 131 | 70 |
| legal sensitive candidate | 1,187 | 821 |
| financial sensitive candidate | 835 | 213 |
| religion candidate | 5,657 | 1,064 |
| political candidate | 198 | 92 |
| family-relation candidate | 1,787 | 680 |

Email, phone, resident ID like, passport like, driver license like, birth date, card number like, vehicle number like,
social handle 및 other 후보는 occurrence와 affected record가 모두 0이었다.

## 11. Risk level

| Risk | Record |
|---|---:|
| none | 19,414 |
| low | 4,175 |
| medium | 156 |
| high | 59 |
| critical | 0 |

위험 등급은 검토용 규칙 기반 후보이며 삭제·마스킹·학습 허용 기준이 아니다.

## 12. 복수 패턴 결합

복수 candidate type record는 513건이다. Person+address 1건, medical+person 4건이며 person+phone,
birth+address, account+person 결합은 0건이다. Direct identifier 후보 record 215건, quasi identifier 후보 158건,
sensitive information 후보 4,134건이다.

## 13. Safety 결과

```yaml
safety:
  raw_value_output: false
  partial_value_output: false
  raw_context_output: false
  stable_identifier_output: false
  stdout_leak: false
  stderr_leak: false
  logging_leak: false
  exception_leak: false
  dataset_root_write: false
  dataset_modified: false
```

실제 질문·답변·PII 의심값·부분 문자열·data_id·hash·record 위치는 출력하거나 저장하지 않았다.

## 14. False positive 한계

- 정규식과 숫자 형식은 일반 숫자열을 오탐할 수 있다.
- 이름·주소·기관·직책 후보는 일반 문맥일 수 있다.
- 의료·법률·금융·종교·정치·가족 키워드는 개인과 무관한 설명일 수 있다.
- 탐지되지 않은 PII가 존재할 수 있다.
- 결과는 `pii_absent` 또는 `safe_to_train` 판정이 아니다.
- 수동 원문 검토, 삭제 및 마스킹 기준으로 바로 사용할 수 없다.

## 15. Dataset 변경

[확정] 원본 수정·복사·추출·JSON 재저장·정제·마스킹·필터링 및 파생 Dataset 생성은 모두 0건이다.

## 16. 현재 blocker

PII 후보 처리 threshold와 정책은 미결정이다. Content Duplicate, Near Duplicate, Leakage, Benchmark
Contamination, 품질 검증, Dataset 선택·처리, SFT backend 및 학습은 승인되지 않았다.

## 17. Readiness

```yaml
AIHUB_71748_SFT:
  schema_inspection: completed
  safe_inspector: validated
  join_integrity_scan: completed
  join_contract: passed
  pii_scan: completed
  pii_review: pending_policy_decision
  dataset_candidate_status: pending_policy_decision
  content_duplicate_scan: not_approved
  near_duplicate_scan: not_approved
  leakage_scan: not_approved
  dataset_selection: not_selected
  dataset_processing: not_approved
overall:
  sft_backend: not_started
  sft_training: not_approved
  execution_allowed: false
```

Critical 후보가 0건이므로 자동 `review_required_before_next_scan` 상태는 적용하지 않았다. 이는 Dataset 적격 판정이 아니다.

## 18. 다음 승인

[승인 필요] 후보 유형별 false positive 처리와 PII 정책·threshold를 결정해야 한다. 이후 scan도 Content Duplicate,
Near Duplicate, Leakage 각각 별도 승인이 필요하며 Dataset 선택·처리와 SFT는 계속 금지된다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-29 | 첫 Fail Closed 이력을 보존하고 두 번째 독립 승인 PII 후보 scan의 안전 집계 결과 기록 |
