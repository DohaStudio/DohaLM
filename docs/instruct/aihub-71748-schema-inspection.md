# AIHUB-71748 SFT Schema Inspection

- 문서 상태: `review`
- 최종 검토일: 2026-07-28
- 조사 유형: `data`, `documentation`
- 조사 상태: `completed_with_output_incident`
- 실행 상태: `execution_allowed:false`
- 관련 문서: [SFT 이용조건 검토](./aihub-71748-sft-terms-review.md), [SFT 검증 계획](./aihub-71748-sft-validation-plan.md), [Safe Dataset Inspector](./safe-dataset-inspector.md), [Instruction Schema](./instruction-schema.md)

## 1. Scope

이번 조사는 AIHUB-71748의 `SFTdata`와 `SFTlabel` schema만 확인했다. Training과 Validation의 허용된
네 JSON member를 ZIP stream으로 직접 읽었으며 General Corpus, RM과 PPO payload에는 접근하지 않았다.
Dataset 선택·변환·join·PII·중복·누수·Adapter·SFT backend·학습은 수행하지 않았다.

## 2. Read-only 정책과 incident

- ZIP member는 `ZipFile.open` stream에서 메모리로 읽었고 압축 해제·temp·cache·JSON 재저장을 하지 않았다.
- field 이름, 자료형, null/missing, 문자열 길이와 category 집계만 계산했다.
- ID, 질문, 답변과 metadata value를 문서나 파일에 기록하지 않았다.
- 원본 dataset은 수정·복사·이동·삭제하지 않았다.

`data_category.main`의 종류를 category label로 보고 집계값을 터미널에 출력했으나, 이 field에는 정상적인 짧은
category 외에 원문성 장문이 혼재했다. 그 결과 실제 문자열이 표준 출력에 일시 노출되는 경계 위반이 1회
발생했다. 출력은 별도 파일·cache·문서에 저장하지 않았고 즉시 값 출력 방식을 폐기했다. 이후 집계는 승인된
canonical label 일치 건수, distinct 수, 비정상 건수와 길이만 사용했다. 따라서 이번 작업은
`original_text_output: zero`를 충족하지 못하며 후속 inspector는 category를 포함한 모든 값 출력을 구조적으로
차단해야 한다.

## 3. Component inventory

| Component | Split | ZIP | JSON file | containing ZIP bytes | member compressed bytes | member uncompressed bytes | Records |
|---|---|---:|---:|---:|---:|---:|---:|
| SFTdata | Training | 1 | 1 | 46,680,605 | 658,881 | 3,361,065 | 10,580 |
| SFTlabel | Training | 1 | 1 | 50,001,412 | 5,365,519 | 19,517,679 | 10,580 |
| SFTdata | Validation | 1 | 1 | 5,829,783 | 82,845 | 419,445 | 1,322 |
| SFTlabel | Validation | 1 | 1 | 6,255,134 | 682,244 | 2,471,396 | 1,322 |
| SFTdata 합계 | Training + Validation | 2 | 2 | 52,510,388 | 741,726 | 3,780,510 | 11,902 |
| SFTlabel 합계 | Training + Validation | 2 | 2 | 56,256,546 | 6,047,763 | 21,989,075 | 11,902 |

Containing ZIP에는 SFT 외 RLHF member도 존재하므로 ZIP 전체 byte를 SFT component 크기로 해석하지 않는다.
Component 크기는 member compressed/uncompressed byte로 분리했다.

## 4. JSON과 split 구조

| 항목 | SFTdata | SFTlabel |
|---|---|---|
| JSON 최상위 타입 | object | object |
| 최상위 key | `dataset_info`, `data_info` | `dataset_info`, `data_info` |
| Record container | `data_info` array | `data_info` array |
| Training | 존재, 10,580 records | 존재, 10,580 records |
| Validation | 존재, 1,322 records | 존재, 1,322 records |
| Test | 미관찰 | 미관찰 |
| Record 기준 최대 nesting depth | 2 | 2 |
| Split별 record schema variant | 각 1 | 각 1 |
| JSON object duplicate key | 전체 4개 member에서 0 | 전체 4개 member에서 0 |

Split은 archive 경로로만 판정했으며 record 내부 `split` field는 없다. Split 간 ID 비교는 Join/Leakage Scan에
해당하므로 수행하지 않았다.

## 5. Field와 자료형

모든 표의 비율은 해당 component/split record에서 `1.0`이었다. 관찰된 field는 missing 0, null 0이며
Training과 Validation의 자료형이 같았다.

### SFTdata

| Field | Type | Nullable | 구조 |
|---|---|---|---|
| `data_id` | string | no | record ID 후보 |
| `question` | string | no | instruction 후보 |
| `question_count` | integer | no | metadata 후보 |
| `question_type` | string | no | metadata/category 후보 |
| `data_category` | object | no | metadata 후보 |
| `data_category.main` | string | no | 오염 가능 category 후보 |
| `data_category.middle` | string | no | domain 후보 |

### SFTlabel

SFTdata의 모든 field와 다음 field가 추가된다.

| Field | Type | Nullable | 구조 |
|---|---|---|---|
| `answer` | object | no | target wrapper |
| `answer.contents` | string | no | output 후보 |
| `answer.answer_count` | integer | no | metadata 후보 |

### 후보 field 존재 여부

| 후보 | SFTdata | SFTlabel |
|---|---|---|
| `id` | missing | missing |
| `data_id` | present | present |
| `question` | present | present |
| `instruction` | missing | missing |
| `input` | missing | missing |
| `context` | missing | missing |
| `answer` | missing | present |
| `answer.contents` | missing | present |
| `metadata` | missing | missing |
| `category` | missing; `data_category` 존재 | missing; `data_category` 존재 |
| `domain` | missing | missing |
| `source` | missing | missing |
| `conversation_id` | missing | missing |
| `turn_id` | missing | missing |
| `split` | missing | missing |
| `quality` | missing | missing |
| `safety` | missing | missing |

## 6. 문자열 길이 통계

실제 문자열과 substring은 기록하지 않았다.

| Field | Split | Min | Max | Average | Empty | Whitespace-only |
|---|---|---:|---:|---:|---:|---:|
| `data_id` | Training / Validation | 36 / 36 | 36 / 36 | 36.000 / 36.000 | 0 / 0 | 0 / 0 |
| `question` | Training / Validation | 10 / 8 | 107 / 81 | 30.086 / 30.089 | 0 / 0 | 0 / 0 |
| `question_type` | Training / Validation | 2 / 2 | 2 / 2 | 2.000 / 2.000 | 0 / 0 | 0 / 0 |
| `data_category.main` | Training / Validation | 2 / 2 | 883 / 65 | 3.562 / 3.259 | 0 / 0 | 0 / 0 |
| `data_category.middle` | Training / Validation | 2 / 2 | 3 / 3 | 2.135 / 2.138 | 0 / 0 | 0 / 0 |
| `answer.contents` | Training / Validation | 13 / 19 | 1,721 / 1,689 | 603.838 / 615.421 | 0 / 0 | 0 / 0 |

SFTdata와 SFTlabel은 같은 split에서 `question`과 category의 길이 집계가 같았지만 key 단위 비교는 하지
않았다. 이는 Join Integrity 결과가 아니다.

## 7. Metadata key

| 위치 | Key |
|---|---|
| 최상위 `dataset_info` | `dataset_type`, `last_updated` |
| Record category object | `data_category.main`, `data_category.middle` |
| Record scalar metadata 후보 | `data_id`, `question_count`, `question_type` |
| Label 전용 metadata 후보 | `answer.answer_count` |

`metadata`라는 record object는 존재하지 않는다. `dataset_info`와 metadata 후보의 value는 출력하지 않았다.

## 8. Category와 오염 신호

안전한 category 목록은 짧은 allowlist와 exact match만 보고한다.

- `question_type`: `생성` 1종. Training 10,580, Validation 1,322.
- `data_category.middle`: `공학`, `기타`, `명칭`, `보건`, `사회`, `산업`, `예체능`, `인문`, `자연`, `종교` 10종.
- `data_category.main`: canonical 후보 `구어체`, `문어체`.

| Split | main distinct | canonical `구어체` | canonical `문어체` | noncanonical records |
|---|---:|---:|---:|---:|
| Training | 103 | 4,671 | 5,790 | 119 |
| Validation | 19 | 561 | 742 | 19 |

`data_category.main`의 noncanonical 값에는 최대 883자의 원문성 장문이 있어 category taxonomy로 직접
사용할 수 없다. 실제 값은 문서화하지 않는다. `data_category.middle`도 현재는 metadata 후보이며 학습 prompt에
포함하지 않는다.

## 9. DohaLM Schema mapping 후보

```yaml
mapping_candidate:
  instruction: question
  input: null
  output: answer.contents
  system: null
  join_key_candidate: data_id
  metadata:
    source_record_id: data_id
    question_count: question_count
    question_type: question_type
    category_main: data_category.main
    category_middle: data_category.middle
    answer_count: answer.answer_count
    split: archive_path_derived
```

이 mapping은 schema 후보일 뿐 변환·join·dataset 선택 승인이 아니다. `data_category.main`은 오염 검증과
filter 정책 승인 전 metadata에도 신뢰해 사용할 수 없으며 prompt/output serialization은 금지한다.

## 10. Blocker

1. `data_category.main`에 정상 category와 원문성 장문이 혼재하고 Training 119건, Validation 19건이
   canonical 두 종류와 일치하지 않는다.
2. Dataset 내부에 명시적인 `instruction`, `input`, `system`, `split`, `quality`, `safety` field가 없다.
3. SFTdata에는 answer가 없고 SFTlabel에만 존재하므로 `data_id` Join Integrity가 필수지만 미실행이다.
4. Record shape는 split별 1종이지만 명시적 schema version field가 없어 provider schema version은 미확정이다.
5. Validation은 존재하므로 학습 제외·평가 격리 계약이 필요하다.
6. PII, duplicate, leakage, answer quality와 unsafe content는 모두 미검사다.
7. category 값 출력 incident 때문에 후속 도구의 aggregate allowlist와 로그 비노출 synthetic test가 필요하다.

Object nesting은 record 기준 최대 depth 2로 과다하지 않았고 JSON duplicate key는 0건이었다.

## 11. Readiness

```yaml
schema_structure: completed
mapping_defined: completed
inspection_incident: raw_value_stdout_once
original_text_output_requirement: failed
safe_inspector_implementation: completed
safe_inspector_synthetic_validation: completed
payload_reread: not_approved
dataset: not_selected
dataset_processing: not_approved
join_scan: not_started
pii_scan: not_started
duplicate_scan: not_started
leakage_scan: not_started
sft_backend: not_started
training: not_approved
execution_allowed: false
```

Schema 구조와 mapping 후보는 정리됐고 [Safe Dataset Inspector](./safe-dataset-inspector.md)의 synthetic-only
회귀가 완료됐다. Dataset 적격성은 판정할 수 없으며 다음 단계는 실제 payload 재열람과 Join Integrity의
별도 승인이지 Dataset Processing이나 SFT 실행이 아니다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | Safe Dataset Inspector synthetic 검증 완료와 실제 payload 재열람·Join 미승인 상태 연결 |
| 2026-07-28 | SFTdata/SFTlabel 4개 ZIP member의 read-only schema·type·길이·category·split 집계와 category value 출력 incident 기록 |
