# AIHUB-71748 ZIP JSON record 제한 분석 결과

## 문서 정보

- 문서 상태: `review`
- 마지막 검토일: 2026-07-24
- 선행 문서: [ZIP JSON record 분석 계약](./zip-json-record-sampling.md), [AIHUB-71748 mapping 검토](./AIHUB-71748-path-mapping.md)
- 후속 작업: 별도 schema·PII 검토 범위 승인
- 구현 전 필수 여부: AIHUB-71748 record 구조 관측 결과 검토 시 예

## 실행 범위

| 구분 | Run ID | Entry 내용 읽기 | 파일 추출 |
|---|---|---:|---:|
| Dry-run | `record-dry-49fb375e2506f467` | 0 byte | 0 |
| 읽기 전용 inspection | `record-inspect-9dc6597bffe74d47` | 최대 32 MiB | 0 |

- [확정] 후보는 승인 mapping과 기존 안전 검사를 통과한 5 MiB 초과 JSON 571개다.
- [확정] 최대 entry 3개, entry당 record 5개, record 1 MiB, entry read 16 MiB, 전체 read 32 MiB 제한을 적용했다.
- [확정] 일반 sampler의 5 MiB entry 제한은 변경하지 않았다.

## Dry-run 결과

| 항목 | 결과 |
|---|---:|
| 후보 entry | 571 |
| 계획 entry | 3 |
| 검사 entry | 0 |
| 읽은 byte | 0 |
| record parse·선택 | 0 / 0 |
| 원본 변경 | 없음 |

Dry-run은 ZIP 중앙 디렉터리와 mapping·출력 계획만 확인했다.

## 읽기 전용 inspection 결과

| 항목 | 결과 |
|---|---:|
| 선택 entry | 3 |
| 실제 검사 entry | 2 |
| 총 read | 33,554,432 byte |
| Record 관측 | 3,489 |
| Record parse 성공 | 3,486 |
| Stable-rank 선택 | 10 |
| Record 거부 | 3 |
| 파일·record 원문 저장 | 0 |

세 번째 entry는 전체 32 MiB 상한 도달로 검사하지 않았다. 검사한 두 entry 모두 `ENTRY_READ_LIMIT_REACHED`이며 전체 array 종료까지 읽지 않았다.

## 실패와 제한 도달

| 상태 | 수 | 의미 |
|---|---:|---|
| `RECORD_TOO_LARGE` | 1 | 1 MiB 초과로 buffer를 폐기하고 경계만 추적 |
| `RECORD_TRUNCATED` | 2 | entry read 상한 시 진행 중 record |
| `ENTRY_READ_LIMIT_REACHED` | 2 | 두 검사 entry가 각각 16 MiB에서 중단 |
| `RECORD_PARSE_FAILED` | 0 | 제한 범위에서 record 단위 parse 실패 없음 |

거부 manifest에는 record index·크기·checksum·hash 식별자와 상태만 있으며 원문은 없다.

## 관측 schema 후보

선택한 10개 record에서 허용 표시 key는 다음과 같다.

| Key | 출현 record 수 |
|---|---:|
| `text` | 10 |
| `metadata` | 5 |
| `source` | 5 |

- Schema signature 후보: 2개
- Text field 후보 hash 그룹: 1개
- PII field-name warning: 0개
- [검증 필요] PII field-name 미탐지는 PII 값 부재를 의미하지 않는다.
- [검증 필요] 10개 record와 앞쪽 32 MiB 관측은 전체 schema 또는 분포를 확정하지 않는다.

## 비노출과 원본 불변

- [확정] 외부 산출물은 JSON manifest 6개뿐이며 record 파일은 없다.
- [확정] 산출물의 로컬 절대경로, 원본 entry 전체 경로와 원문 prefix 패턴 탐지 결과는 0건이다.
- [확정] record 문자열 값과 preview는 기록하지 않았다.
- [확정] 선택 ZIP의 전후 SHA-256과 전체 inventory metadata digest가 일치했다.
- `source_mutation_detected: false`

## 해석 제한과 승인 상태

- [확정] 이번 결과는 구조 후보 관측이며 corpus 생성이 아니다.
- [확정] 실제 schema 확정, PII 부재 확인과 Tokenizer corpus 승인을 의미하지 않는다.
- `candidate_status: registered`
- `license_review_status: pending_terms_review`
- `approval.tokenizer/pretraining/sft/evaluation: pending`
- Gate 3: `planned`

## 다음 검토

1. 전체 파일 대표성을 주장하지 않고 entry·record 층화 범위를 별도 승인한다.
2. 실제 값 비노출 조건을 유지한 schema·PII 수동 검토 방식을 정한다.
3. 라이선스와 목적별 승인 전 corpus 생성·Tokenizer 학습을 진행하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-24 | [확정] dry-run 무내용 read와 32 MiB bounded inspection의 3,489 record 관측·원본 불변·비노출 결과를 기록함 |
