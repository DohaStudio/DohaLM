# Safe Dataset Inspector

- 문서 상태: `implemented`
- 최종 검토일: 2026-07-28
- 구현: `src/data/safety/inspector.py`
- Synthetic validation: `completed`
- Real dataset validation: `not_approved`
- 관련 문서: [AIHUB-71748 Schema Inspection](./aihub-71748-schema-inspection.md), [SFT 검증 계획](./aihub-71748-sft-validation-plan.md), [ADR-004](../decisions/ADR-004-data-governance.md)

## 1. 배경과 사고 요약

AIHUB-71748 SFT Schema Inspection 중 `data_category.main`을 category label로 간주해 종류를 출력했으나,
field에 원문성 장문이 혼재해 plaintext가 터미널에 일시 노출됐다. 영구 저장·문서 유출·Dataset 변경은 없었고
값 출력은 즉시 중단했다.

```yaml
incident_type: plaintext_terminal_exposure
affected_field: data_category.main
persistent_storage: false
dataset_modified: false
documentation_leak: false
response:
  value_output_stopped: true
  incident_documented: true
  further_payload_scan_blocked: true
```

Safe Dataset Inspector는 category를 포함한 모든 입력값을 불신하고 Python object를 원문 없는 schema metadata로
변환한다. ZIP reader, Dataset Adapter, join 또는 processing backend는 포함하지 않는다.

## 2. Threat model

| 위협 | 예시 | 방어 |
|---|---|---|
| 정상 field로 위장한 원문 | 긴 category, metadata 내부 문장 | 모든 string을 길이·hash·Unicode 집계로 변환 |
| 중첩 누출 | list/object/tuple/set/custom object | 재귀 검사와 최종 Output Leak Guard |
| 오류 경로 누출 | exception message, traceback, assertion | 고정 error code 반환, 원문으로 예외 생성 금지 |
| 로깅 누출 | debug repr, format argument | Inspector 내부 print/logging 없음 |
| key 기반 누출 | 장문·공백·민감 key | 안전 key regex 외 full SHA-256 surrogate |
| 부분 문자열 누출 | preview, prefix, suffix | 원문 전체와 16자 이상 substring 검사 |
| 비직렬화 output | custom result object | JSON serialization 실패 시 Fail Closed |
| 순환·과도한 중첩 | recursive object graph | cycle error와 max depth 상한 |

## 3. 금지 출력

- string field value와 list/dictionary/custom object 내부 value
- 질문·답변·category·context와 일부 substring
- prefix·suffix·preview·`repr(record)`·`str(record)`
- traceback·assertion·exception message·logging argument의 입력값
- source에서 유래한 임의 문자열과 불완전 hash

실제 입력값은 반환 객체, stdout, stderr, log, exception과 test report에 포함하지 않는다.

## 4. 허용 출력

- 안전한 field path와 key
- 자료형, null·empty·whitespace 여부
- byte/character 길이와 집계 건수
- 최소·최대·평균 길이
- full SHA-256 또는 `null`
- Unicode category별 문자 수
- array 길이와 element type count
- canonical match boolean
- 고정 status·error code와 비가역 key surrogate

## 5. Safe representation

### String

```yaml
path: $.field
type: string
length: 0
empty: false
whitespace_only: false
sha256: null
unicode_category_counts: {}
```

Hash를 활성화하면 `sha256:` prefix와 64자리 lowercase hex 전체를 반환한다. hash prefix 축약이나 원문 복원
목적 사용은 허용하지 않는다.

### Object

```yaml
path: $.object
type: object
keys:
  - field_a
fields: {}
value_output: prohibited
```

안전한 식별자 형식이 아닌 key는 원문 대신 전체 SHA-256 기반 surrogate로 바꾼다.

### Array

```yaml
path: $.items
type: array
length: 0
element_types: {}
items: []
value_output: prohibited
```

`items`에는 값이 아니라 동일한 safe representation만 들어간다.

## 6. Output Leak Guard

`guard_safe_output`은 최종 반환 전에 다음을 검사한다.

1. 결과의 JSON serialization 가능 여부.
2. source string 전체가 결과 serialization에 포함되는지 여부.
3. source의 연속 16자 이상 substring이 포함되는지 여부.
4. 결과의 모든 string leaf가 type·path·full hash·고정 status/error·안전 key allowlist에 속하는지 여부.

Leak 또는 guard 내부 실패 시 원인을 포함한 payload를 반환하지 않는다.

```yaml
status: blocked
error_code: RAW_VALUE_LEAK_DETECTED
value_output: false
```

Guard 결과도 고정 문자열과 boolean만 포함한다.

## 7. Logging 정책

Inspector 구현에는 `print`와 logger 호출이 없다. 입력 object/value를 exception, assertion 또는 format argument로
전달하지 않는다. 예상하지 못한 자료형·custom object·serialization 오류는 다음 고정 code 중 하나로 닫는다.

- `UNSUPPORTED_VALUE_TYPE`
- `SAFE_INSPECTION_FAILED`
- `OUTPUT_GUARD_FAILED`
- `RAW_VALUE_LEAK_DETECTED`
- `UNSAFE_OUTPUT_STRING`
- `CYCLE_DETECTED`
- `MAX_DEPTH_EXCEEDED`

## 8. Synthetic fixture와 테스트 전략

실제 Dataset과 무관한 명시적 synthetic 문자열만 사용한다.

- 짧은·수천 자 장문·여러 줄 문자열
- 합성 한글·영어·숫자·특수문자
- 명백히 가짜인 email·전화번호·주소·JSON 형태 문자열
- nested dictionary/list/tuple/set, bytes, null, empty, whitespace-only
- exception attribute와 `vars()`가 불가능한 custom object

테스트는 반환 JSON, stdout, stderr, caplog와 고정 exception 경계를 검사한다. 실제 AI Hub schema fixture, 질문,
답변, category 값이나 Dataset 경로는 사용하지 않는다.

## 9. 사고 회귀 계약

`test_noncanonical_category_value_is_never_emitted`는 수천 자 synthetic category prose를
`data_category.main` 경로에 입력하고 다음만 확인한다.

- `type:string`
- 전체 길이
- `canonical_match:false`
- `value_output:prohibited`
- 반환·stdout·stderr·log의 원문 부재

Canonical 값도 실제 label을 반환하지 않고 match boolean만 반환한다.

## 10. Fail Closed 동작

| 조건 | 결과 |
|---|---|
| 지원하지 않는 값 | `UNSUPPORTED_VALUE_TYPE` |
| 원문 또는 긴 substring 발견 | `RAW_VALUE_LEAK_DETECTED` |
| 비허용 output string | `UNSAFE_OUTPUT_STRING` |
| output guard 자체 오류 | `OUTPUT_GUARD_FAILED` |
| 예기치 않은 inspector 오류 | `SAFE_INSPECTION_FAILED` |
| 순환 또는 depth 상한 | 고정 구조 오류, 값 출력 금지 |

자동 fallback으로 `str(value)`나 `repr(value)`를 사용하지 않는다.

## 11. 실제 Dataset 적용 전 승인 조건

1. 현재 구현·테스트 commit과 fingerprint 고정.
2. full hash 사용 여부, substring 길이, max depth와 output schema 승인.
3. 실제 payload read 대상 component·split·field와 record 상한 승인.
4. stdout/stderr/log/file sink의 원문 0 계약과 incident 대응 승인.
5. report 저장 위치, atomic publish와 partial artifact 정책 승인.
6. Join Integrity Scan의 source/label access와 key hash 정책 별도 승인.

Synthetic validation은 실제 Dataset 재열람, Join, PII, 중복, 누수 또는 processing 승인이 아니다.

## 12. 현재 상태

```yaml
safe_inspector:
  implementation: completed
  synthetic_validation: completed
  real_dataset_validation: not_approved
AIHUB_71748:
  schema_inspection: completed_with_incident
  join_integrity_scan: not_approved
  payload_reread: not_approved
overall:
  dataset: not_selected
  dataset_processing: not_approved
  sft_training: not_approved
  execution_allowed: false
```

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | 원문 비출력 safe representation, output guard, logging 금지, synthetic-only 사고 회귀와 실제 Dataset 적용 전 승인 조건 구현 |
