# AIHUB-71748 수동 경로 mapping 검토

## 문서 정보

- 문서 상태: `review`
- 마지막 검토일: 2026-07-26
- 선행 문서: [AIHUB-71748 안전 표본 결과](./AIHUB-71748-sampling.md), [수동 mapping 계약](./manual-path-mapping.md)
- 후속 문서·작업: [대용량 JSON 제한 검사](./large-json-inspection.md), [ZIP JSON record 분석](./zip-json-record-sampling.md), RaG mapping 후보 재검토, schema·PII 검토

## 실행 기준

- 수동 mapping dry-run: `manual-dry-8377d08464b6d194`
- 대용량 JSON 검사: `large-json-dry-f6c7eef294d1f5d1`
- Prefix review: `prefix-review-dry-f44600319bd8b473`
- [확정] 모든 실행은 원본 ZIP을 읽기 전용으로 처리했고 실제 entry 추출은 0건이다.
- [확정] 원본 entry 전체 경로, component 원문과 JSON 값은 산출물·문서에 기록하지 않았다.

## Rule별 직접 집계

| Rule | Sanitized prefix | 매칭 | 안전 | 거부 | 크기 초과 | 확장자 불일치 | 경로 실패 | 선택 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `rule-90abbf0f9cec` | `root/외부데이터` | 573 | 1 | 572 | 571 | 1 | 0 | 1 |
| `rule-f83f322018cc` | `root/RaG-데이터` | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

- [확정] Rule ID·source prefix hash·sanitized prefix와 rejection stage를 각 거부 레코드에 기록해 추론 없이 직접 집계할 수 있다.
- [확정] `MAPPING_RULE_NOT_FOUND`는 1,037개이며 모두 JSON이다.
- [확정] 미매칭 sanitized group 중 `root/RaG-데이터`가 119개다. 나머지 918개는 기존 단일 JSON 파일형 집계와 일치한다.

## 거부 stage

| Reason code | Stage | 수 |
|---|---|---:|
| `MAPPING_RULE_NOT_FOUND` | `mapping_lookup` | 1,037 |
| `ENTRY_TOO_LARGE` | `size_validation` | 571 |
| `UNSUPPORTED_EXTENSION` | `extension_validation` | 1 |

Path traversal, output escape와 중복 출력 거부는 각각 0건이다. 일반 sampler의 파일당 5 MiB·전체 50 MiB 기본 제한은 변경하지 않았다.

## RaG prefix 불일치 원인

Prefix review는 RaG sanitized group 119개를 하나의 실제 first-component hash로 집계했다.

| 항목 | 관측 결과 |
|---|---|
| 관측 component hash | `sha256:c1395c4002df0caaef911a7475271f7ddf8018d5dd214b30d9edf301a0b2f4a9` |
| Entry·확장자 | JSON 119개 |
| ASCII·한글 혼합 | 예 |
| 공백 | 1개, Unicode category `Zs` |
| Dash | 없음 |
| Underscore | 없음 |
| NFC | 원형과 동일 |
| NFD | 원형과 다름 |
| Casefold | 원형과 다름 |

현재 rule 후보와 비교하면 관측 component에는 `Zs`가 1개 더 있고 `Pd`가 1개 적다. Exact·NFC·NFD·casefold 비교는 모두 불일치다.

- [확정] 기존 `root/RaG-데이터`는 원문이 아니라 punctuation·공백을 정리한 sanitized preview였다.
- [확정] sanitized preview를 실제 source prefix로 사용한 것이 119개 전부 미매칭된 원인이다.
- [검증 필요] 관측 hash에 대응하는 실제 source prefix는 로컬에서만 검토하고, 공식 package 의미와 함께 사용자가 별도 승인해야 한다.
- [제외] 관측 component 원문을 Git 문서나 분석 JSON에 기록하지 않는다.

## 대용량 JSON 상태

571개는 `large_entry_inspection_candidate`다. 결정론적으로 선택한 5개를 entry당 2 MiB, 전체 10 MiB 이내에서 stream 검사했다.

- 5개 모두 JSON root가 array 후보다.
- 5개 모두 strict UTF-8, BOM 없음, JSON Lines 후보 아님이다.
- 5개 모두 제한 byte에서 잘렸으므로 `parse_completeness: truncated`다.
- Array item key 후보에서 허용 표시 `text`는 5개, `metadata`는 4개 검사에 나타났다.
- 그 외 key는 이름 없이 hash만 기록했다.
- [검증 필요] 제한 prefix 관측은 전체 schema, PII 부재 또는 모든 record의 동일 구조를 확정하지 않는다.

상세 정책과 hash-only 필드는 [대용량 JSON 제한 검사](./large-json-inspection.md)를 따른다.

## 실행·승인 상태

| 항목 | 현재 결과 |
|---|---|
| 수동 mapping 절차 승인 | `approved` |
| 수동 mapping dry-run | 완료, 선택 1·추출 0 |
| 대용량 JSON stream 검사 | 5개 완료·전체 추출 없음 |
| ZIP JSON record inspection | 2개 entry·3,489 record 관측·원문 저장 없음 |
| Prefix review | 1,610개 중앙 디렉터리 집계 완료 |
| 실제 제한 추출 | `not_run` |
| 전체 schema·PII | 미확정 |
| 원본 변경 | 없음 |

Mapping 절차 승인은 데이터 이용·Tokenizer corpus 승인이 아니다.

## Tokenizer와 Gate 상태

- `candidate_status: registered`
- `license_review_status: approved_student_noncommercial`
- `approval.tokenizer: approved_tokenizer_development`, `approval.pretraining/sft/evaluation: pending`
- Gate 3: `planned`

## 다음 검토

1. RaG 관측 component hash와 공식 package 설명을 로컬에서 비교한다.
2. 실제 문자열을 Git에 기록하지 않고 새 rule 후보와 fingerprint를 사용자 승인 대상으로 제시한다.
3. 918개 root-level 후보는 prefix mapping과 다른 명시적 계약이 필요한지 검토한다.
4. 실제 추출 없이 streaming 관측 범위를 늘릴 필요가 있는지 별도 승인한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-26 | [확정] 현재 학생·비상업 라이선스와 tokenizer `under_review` 상태를 동기화함 |
| 2026-07-24 | [확정] 승인 mapping 기반 ZIP JSON record bounded inspection 결과 문서를 연결함 |
| 2026-07-24 | [확정] 관측성 개선 dry-run의 rule별 직접 집계, RaG 공백·dash category 차이와 대용량 JSON 5개 제한 구조 검사 결과를 기록함 |
| 2026-07-24 | [확정] 기존 dry-run 집계로 두 mapping 후보를 제안하고 승인·실행·Gate 상태를 pending/not_run/planned로 기록함 |
