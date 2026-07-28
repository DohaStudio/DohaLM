# AIHUB-71748 SFT PII False Positive 및 Threshold 정책

- 문서 상태: `review`
- 마지막 검토일: 2026-07-29
- Dataset ID: `AIHUB-71748`
- 관련 문서: [PII Scan 결과](./aihub-71748-pii-scan-result.md), [SFT 검증 계획](./aihub-71748-sft-validation-plan.md), [Safe Dataset Inspector](./safe-dataset-inspector.md), [ADR-004](../decisions/ADR-004-data-governance.md), [ADR-010](../decisions/ADR-010-dohalm-instruct-strategy.md)

## 1. Scope

[확정] 이 문서는 기존 PII Scan의 원문 비노출 집계와 detector 구현을 해석하는 정책 계약이다. 실제 AI Hub
payload 재열람, scan 재실행, record 판정·변경, 자동 마스킹·제외와 Dataset 사용 승인을 포함하지 않는다.

## 2. 현재 PII Scan 결과

| 항목 | 값 |
|---|---:|
| Field scan | 35,706 |
| 후보 Component-record | 4,390 |
| 복수 유형 Component-record | 513 |
| None / Low / Medium / High / Critical | 19,414 / 4,175 / 156 / 59 / 0 |

주요 occurrence는 medical 5,704, religion 5,657, family 1,787, legal 1,187, financial 835, address 281이다.
이는 detector 규칙 일치 수이며 실제 개인정보 확정 건수가 아니다.

## 3. 결과 해석 제한

- [확정] 35,706은 세 field의 scan 합계이지 고유 record나 고유 문장 수가 아니다.
- [확정] SFTdata와 SFTlabel 질문이 Component 간 중복될 수 있으나 내용 동일성은 검증하지 않았다.
- [확정] 4,390은 Component-record 단위이며 고유 문장 비율로 환산하지 않는다.
- [확정] 후보 0건은 PII 부재 증명이 아니고 후보 존재는 실제 PII 확정이 아니다.
- [확정] 이 결과는 Dataset 선택·처리·학습 승인이 아니다.

## 4. 탐지 분류 체계

| 계층 | 대표 유형 | 정책 의미 |
|---|---|---|
| 직접 식별정보 | resident/foreign ID, passport, driver license, phone, email, account/card, detailed address, vehicle/patient/employee/student ID | 단독 검토, 검증된 고위험 또는 결합 시 차단 후보 |
| 준식별정보 | name, birth date, age, gender, region, school/company/department/job, family relation | 단독 자동 차단 금지, 복수 결합 시 검토 |
| 민감 주제 언급 | medical, mental health, legal, financial, religion, political, disability, sexual orientation, labor union, criminal | 개인 귀속 없는 일반 지식일 수 있어 단독 정보성 후보 |
| 결합 민감정보 | 식별자·사람·주소·생년·기관 역할과 민감 주제 결합 | `block_candidate`, 실제 처리는 별도 승인 |

Scanner 호환 alias인 `address`, `postal_code`, `organization_role_combination`과 `*_candidate` 이름은 정책 계층에서
명시적으로 번역한다. 알 수 없는 detector type은 `UNKNOWN_DETECTOR_TYPE`으로 Fail Closed한다.

## 5. False Positive 정책

| 유형 | 탐지 방식 | 예상 True Positive | 주요 False Positive | 단독/결합 신뢰도 | 권장 처리 | 자동 차단 | 원문 검토 | 향후 마스킹 |
|---|---|---|---|---|---|---|---|---|
| 의료 | keyword | 개인 건강 맥락 | 일반 의학·질병 정의·보건 정책 | 낮음/높음 | 단독 유지, 식별자 결합 차단 후보 | 아니요 | 결합 시 별도 승인 | 정책 미승인 |
| 종교 | keyword | 개인 종교 맥락 | 역사·철학·문화·경전 지식 | 낮음/높음 | 단독 유지, 사람 결합 검토 | 아니요 | 결합 시 별도 승인 | 정책 미승인 |
| 법률 | keyword | 개인 사건 맥락 | 법률 상식·제도 설명 | 낮음~중간/높음 | 단독 유지, 식별자 결합 차단 후보 | 아니요 | 결합 시 별도 승인 | 정책 미승인 |
| 금융 | keyword | 개인 금융 맥락 | 금융 상식·제도·상품 설명 | 낮음~중간/높음 | 단독 유지, 계좌·카드 결합 차단 후보 | 아니요 | 결합 시 별도 승인 | 정책 미승인 |
| 가족 관계 | keyword | 개인 관계 맥락 | 일반 관계·가족 제도 설명 | 낮음/중간 | 단독 유지, 이름 등 결합 검토 | 아니요 | 결합 시 별도 승인 | 정책 미승인 |
| 주소 | pattern | 상세 개인 주소 | 공공기관·관광지·역사 장소·지역명 | 중간/높음 | 개인 상세 주소 여부 검토 | 아니요 | 별도 승인 필요 | 정책 미승인 |
| 전화·이메일 | pattern | 연락처 | 예시·공개 기관 연락처 | 높음/높음 | 검토·마스킹 후보 | 아니요 | 별도 승인 필요 | 후보만 정의 |
| 주민·외국인 ID 유사 | validated format | 고위험 식별자 | 합성·예시 번호 | 매우 높음/매우 높음 | 차단 후보 | 정책 label만 | 별도 승인 필요 | 정책 미승인 |
| 카드번호 유사 | checksum format | 결제 식별자 | 테스트 카드 번호 | 검증 시 높음/매우 높음 | 차단 후보 | 정책 label만 | 별도 승인 필요 | 정책 미승인 |

## 6. Detection Risk와 Policy Risk

Scanner Detection Risk `none/low/medium/high/critical`은 기술적 탐지 집계다. 정책 계층은 별도로
`informational/review_candidate/restricted_candidate/block_candidate`를 반환한다. 기존 medium/high만으로 삭제,
마스킹 또는 제외하지 않는다.

| 조합 | Policy Risk | Label |
|---|---|---|
| 민감 주제만 | `informational` | `PII_TOPIC_ONLY` |
| 준식별자 1개 | `informational` | `PII_UNRESOLVED` |
| 준식별자 복수 | `review_candidate` | `PII_REVIEW_REQUIRED` |
| 직접 식별자 1개 | `review_candidate` | `PII_REVIEW_REQUIRED` |
| 직접+준식별자 | `restricted_candidate` | `PII_EXCLUDE_CANDIDATE` |
| 직접+민감 또는 linked | `block_candidate` | `PII_BLOCKED` |
| 검증된 고위험 식별자 | `block_candidate` | `PII_BLOCKED` |

## 7. Dataset·Record·Field Threshold

```yaml
dataset_thresholds:
  critical_candidate_count:
    condition: greater_than_0
    action: block_next_processing_until_policy_review
  direct_identifier_candidate_rate: {threshold: not_approved, status: proposal_only}
  linked_sensitive_candidate_rate: {threshold: not_approved, status: proposal_only}
  high_risk_candidate_rate: {threshold: not_approved, status: proposal_only}
record_policy:
  sensitive_topic_only: retain_pending_general_quality_review
  quasi_identifier_only: retain_or_review_pending_threshold
  single_direct_identifier: review_or_mask_pending_policy
  multiple_direct_identifiers: block_candidate
  direct_identifier_with_sensitive_topic: block_candidate
field_policy:
  $.sftdata.question: {role: user_instruction, pii_tolerance: strict}
  $.sftlabel.question: {role: duplicated_or_related_question_component, pii_tolerance: strict}
  $.sftlabel.answer.contents: {role: model_target, pii_tolerance: very_strict}
```

[검증 필요] 수치 threshold는 모두 `proposal_only`이며 사용자 승인 없이 확정하지 않는다. 답변 target은 질문보다
엄격한 검토 대상으로 표시하지만 실제 처리 효과는 없다.

## 8. 처리 후보

정책 출력 action은 `retain`, `review`, `mask_candidate`, `exclude_candidate`, `block_candidate` 중 후보만 표현한다.
`candidate`는 실행 명령이 아니며 Dataset Processing 승인 전에는 어떤 record에도 적용하지 않는다.

## 9. 자동 처리 금지

[제외] 자동 삭제·제외·마스킹·대체·일반화, 주소 축약, 이름 치환, 숫자·민감 keyword 제거와 Dataset 재저장은
승인되지 않았다. 정책 계층은 원문을 입력받지 않고 record label manifest도 생성하지 않는다.

## 10. 민감 주제 해석

의료·종교·법률·금융·가족 탐지는 “민감 주제 관련 탐지 규칙에 일치한 occurrence”로만 표현한다. 일반 지식형
질문에서 오탐 가능성이 높으며 “의료 개인정보 5,704건”과 같은 표현을 금지한다.

## 11. 정책 Matrix

| 탐지 유형 | 단독 탐지 | 식별자 결합 | 정책 후보 |
|---|---:|---:|---|
| 의료·종교 주제 | 낮은 신뢰도 | 높은 위험 | 단독 유지, 결합 차단 후보 |
| 법률·금융 주제 | 낮음~중간 | 높은 위험 | 단독 유지, 사건·계좌·카드 결합 차단 후보 |
| 가족 관계 | 낮음 | 중간 | 이름·주소 결합 시 검토 |
| 주소 | 중간 | 높음 | 상세 개인 주소 여부 검토 |
| 전화·이메일 | 높음 | 높음 | 마스킹·제외 후보 |
| 주민번호·카드번호 유사 | 검증 시 매우 높음 | 매우 높음 | 차단 후보 |

## 12. 수동 검토 정책

```yaml
manual_review:
  design: proposed
  execution: not_approved
```

별도 승인 시에도 전수·터미널 원문 출력 금지, 최소 권한·제한 건수·마스킹 UI, 원문 저장 금지, label·검토자·날짜·
고정 reason code만 기록, 실제 식별값 재기록 금지를 요구한다.

## 13. 향후 처리 Label

`PII_CLEAR_BY_RULE`, `PII_TOPIC_ONLY`, `PII_REVIEW_REQUIRED`, `PII_MASK_CANDIDATE`,
`PII_EXCLUDE_CANDIDATE`, `PII_BLOCKED`, `PII_UNRESOLVED`를 설계했다. 이번 작업은 실제 record label 부여,
mapping·처리 manifest 생성 또는 Dataset 수정을 수행하지 않는다.

## 14. Synthetic 테스트

[확정] 실제 AI Hub 문자열 없이 민감 주제 단독, 이름·전화·이메일, 고위험 ID, 직접 식별자+민감 주제,
가족+이름, 일반 지역·공공기관 주소, 복수 민감 주제, unknown detector Fail Closed와 field tolerance를 검증한다.

## 15. Approval Gate

정책 문서만으로 manual review, PII processing, Content/Near Duplicate, Leakage, Dataset 선택·처리 또는 SFT가
승인되지 않는다. Critical 후보가 1개 이상이면 다음 처리를 정책 검토까지 차단한다.

## 16. Readiness

```yaml
AIHUB_71748_SFT:
  schema_inspection: completed
  safe_inspector: validated
  join_integrity_scan: completed
  join_contract: passed
  pii_scan: completed_candidates_detected
  pii_false_positive_policy: completed
  pii_threshold_policy: proposed_not_approved
  manual_pii_review: not_approved
  pii_processing: not_approved
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

## 17. 다음 단계

[승인 필요] 권장 순서는 PII Policy → Content Exact Duplicate Scan → Near Duplicate Scan → Leakage Scan →
PII 처리 여부 최종 결정이다. 원문 검토가 필요하면 제한적 PII 수동 검토 도구 설계를 별도로 승인한다. 이번 단계는
어느 경로도 실행하지 않았다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-29 | 원문 비입력 PII 후보 정책 계층, false positive·threshold proposal과 Fail Closed 계약 작성 |
