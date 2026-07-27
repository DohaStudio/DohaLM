# DohaLM 평가 제외 목록

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-26 |
| 선행 문서 | [데이터셋 후보 등록부](./dataset-candidate-registry.md), [데이터 분할 및 누수 정책](./data-split-and-leakage-policy.md), [Benchmark 정책](../evaluation/benchmark-policy.md), [ADR-005](../decisions/ADR-005-evaluation-and-experiment-policy.md) |
| 후속 문서·작업 | sample inspection, fingerprint·near duplicate·benchmark contamination 검사 |
| 구현 전 필수 여부 | 실제 tokenizer·pretraining·SFT·평가 corpus 승인 전 예 |

- [확정] 이 문서는 학습과 평가 간 contamination·누수 방지 기준을 관리한다.
- [확정] `AIHUB-71748`의 최소 schema metadata만 확인했으며 record text fingerprint·benchmark contamination은 검사하지 않았다. 따라서 모든 중복·누수 판정은 `pending_review`다.
- [확정] `AIHUB-71748/Validation/**`은 tokenizer development 입력에서 전부 제외한다.

## 2. 제외·검토 목록

| Dataset ID | Subset | 평가 전용 여부 | 학습 제외 여부 | 관련 benchmark | 중복 검사 | 누수 위험 | 현재 상태 | 검사 방식 | 비고 |
|---|---|---|---|---|---|---|---|---|---|
| `AIHUB-71748` | 공식 평가 subset | 예 후보 | 예 | [검증 필요] 공식 구조 확인 | 필수 | `high` | `pending_review` | subset manifest·fingerprint·benchmark prompt exact/near 비교 | 평가 subset 식별 전 전체 기본 제외 |
| `AIHUB-71748` | 공개 QA·instruction 중복 가능 subset | [검증 필요] | 예, contamination 판정 전 | 공개 instruction·QA 후보 | 필수 | `high` | `pending_review` | exact·near·prompt/answer pair 검사 | 특정 외부 dataset 중복은 미확정 |
| `AIHUB-71477` | overcorrection validation | 예 후보 | 기본 제외 | 과교정 평가 | 필수 | `high` | `pending_review` | source/corrected/overcorrection pair group split·fingerprint | 평가 후보 |
| `AIHUB-71477` | grammar correction evaluation | 예 후보 | 기본 제외 | 문법 교정 | 필수 | `high` | `pending_review` | pair·label 기준 group holdout | corrected text도 자동 학습 승인 금지 |
| `AIHUB-86` | emotion classification | 조건부 | 학습·평가 split 분리 필수 | 감정 분류 | 필수 | `medium` | `pending_review` | conversation/session group split·text fingerprint | 같은 대화 turn 교차 금지 |
| `AIHUB-86` | dialogue emotion understanding | 조건부 | 학습·평가 split 분리 필수 | 대화 감정 이해 | 필수 | `medium` | `pending_review` | speaker/session group·near duplicate 검사 | PII·민감 상담 격리 선행 |
| `AIHUB-653` | 도서 장문 corpus | 아니요 | 평가로 재사용 비권장 | memorization·verbatim overlap | 필수 | `high` | `pending_review` | train/output n-gram·긴 문자열 overlap·canary 없는 holdout | 원문 암기·재현 검사 필수 |
| `AIHUB-110` | source별 holdout | 조건부 | 선택 source holdout 필요 | 전문분야 평가 | 필수 | `medium` | `pending_review` | 법령·판례·특허·논문 source/time group split | source별 분포 기록 |
| `AIHUB-110` | 판례 | 조건부 | privacy review 전 제외 | 법률 이해 후보 | 필수 | `high` | `pending_review` | 사건·당사자 group, PII·비식별 검사 | court case privacy review 필수 |

## 3. 데이터셋별 필수 플래그

```yaml
AIHUB-71748:
  contamination_status: pending_review
  tokenizer_development_validation_excluded: true
  training_exclusion:
    - all_validation
    - official_evaluation_subset
    - high_risk_qa_instruction_subset

AIHUB-71477:
  evaluation_only_candidate:
    - overcorrection_validation
    - grammar_correction_evaluation
  training_status: excluded_by_default

AIHUB-86:
  training_and_evaluation_split_required: true

AIHUB-653:
  memorization_test_required: true
  verbatim_overlap_test_required: true

AIHUB-110:
  source_specific_holdout_required: true
  court_case_privacy_review_required: true
```

## 4. 운영 원칙

- [확정] evaluation 후보를 tokenizer·pretraining·SFT 입력에 자동 포함하지 않는다.
- [확정] subset 이름만 다르고 source record가 같을 수 있으므로 record·normalized text·group·source fingerprint를 교차 검사한다.
- [확정] exact 검사를 통과해도 near·semantic contamination이 없다고 단정하지 않는다.
- [확정] contamination 검사 전 평가 결과를 공식 benchmark 성능으로 보고하지 않는다.
- [검증 필요] 실제 benchmark 목록, threshold와 semantic 검사 방식은 데이터 접근 후 결정한다.

## 5. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | [확정] Pilot `pilot-v1`은 AI Hub 원래 Validation을 사용하지 않고 Training 내부 5% evaluation 4,800문서를 학습 DataLoader에서 제외하며 document/source ID 교차 0건을 검증함 |
| 2026-07-26 | [확정] AIHUB-71748 `Validation/**` 전체를 tokenizer development에서 제외하고 Training 내부 contamination은 `pending_review`로 유지함 |
| 2026-07-26 | [확정] AIHUB-71748 로컬 package 존재를 반영하되 본문·fingerprint·contamination 미검사로 모든 제외 판정을 `pending_review`로 유지함 |
| 2026-07-23 | [확정] AIHUB-71748·110·86·71477·653의 평가 제외·holdout·누수 검사 후보를 등록함 |
