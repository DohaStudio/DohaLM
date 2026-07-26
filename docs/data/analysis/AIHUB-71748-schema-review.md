# AIHUB-71748 층화 schema·PII review 결과

## 문서 정보

- 문서 상태: `review`
- 마지막 검토일: 2026-07-26
- 선행 문서: [층화 record review 계약](./stratified-record-review.md), [AIHUB-71748 record 분석](./AIHUB-71748-record-sampling.md)
- 후속 작업: [비공개 최소 preview](./AIHUB-71748-private-review.md)의 기간 제한 사용자 승인
- 구현 전 필수 여부: AIHUB-71748 corpus 승인 전 예

## 실행

| 모드 | Run ID | Content read | 원문 파일 |
|---|---|---:|---:|
| Dry-run | `schema-review-dry-de3bc512336cb5cb` | 0 byte | 0 |
| Inspection | `schema-review-inspect-fde2697421f822e0` | 67,108,864 byte | 0 |

기본 요청 상한은 archive 5개, archive당 entry 2개, entry당 32 MiB, 전체 128 MiB다.

## Dry-run 층화 결과

- 대용량 승인 후보: 571개
- 후보 archive: 1개
- 선택 archive: 1개
- 선택 entry: 2개
- 실제 검사: 0개
- Content read: 0 byte

- [확정] 571개 후보가 한 archive에만 있어 archive 5개 분산을 채울 수 없었다.
- [확정] archive당 entry 상한 2개를 유지했으며 한 archive가 무제한 표본을 차지하지 않았다.

## Inspection 결과

| 항목 | 결과 |
|---|---:|
| 검사 archive / entry | 1 / 2 |
| 총 read | 64 MiB |
| Record 관측 | 141 |
| Record parse | 132 |
| Record 선택 | 10 |
| Preview·원문 저장 | 0 |

두 entry 모두 32 MiB에서 `ENTRY_READ_LIMIT_REACHED`다. 전체 JSON array 종료나 entry 뒤쪽을 확인하지 않았다.

## Entry strata

| 층화 | 결과 |
|---|---:|
| 40–50 MiB | 1 |
| 50 MiB 이상 | 1 |
| Compression ratio 0.25–0.50 | 2 |

선택 가능한 한 archive 내부에서 서로 다른 size bucket을 우선했다.

## Record strata

| Bounded 범위 구간 | 선택 |
|---|---:|
| `early` | 4 |
| `middle` | 4 |
| `late` | 2 |

- [확정] 구간은 각 entry에서 읽은 최대 32 MiB 내부 record index 기준이다.
- [제외] 전체 entry의 실제 중간·뒤쪽 byte를 직접 seek하지 않았다.

## 제한·거부

| 상태 | 수 |
|---|---:|
| `RECORD_TOO_LARGE` | 7 |
| `RECORD_TRUNCATED` | 2 |
| `ENTRY_READ_LIMIT_REACHED` | 2 |

1 MiB 초과 record는 buffer를 폐기하고 경계·checksum만 추적했다.

## Schema·field 후보

- Schema signature 후보: 1개
- Field hash: 5개
- `likely_text`: 1개
- `excluded`: 4개
- 허용 표시 field: `text` 1개

- [검증 필요] 제한 표본에서 하나의 signature가 관측됐지만 전체 schema가 하나라는 의미는 아니다.
- [검증 필요] 허용 목록 밖 field 4개는 이름을 표시하지 않았고 hash로만 관리한다.
- [검증 필요] 실제 text 값과 품질은 확인하지 않았다.

## PII checklist

| 상태 | 항목 수 |
|---|---:|
| `review_required` | 1 |
| `no_field_name_signal` | 5 |
| `not_reviewed` | 3 |

자유서술 `text` 가능성 때문에 사람 검토가 필요하다. 직접 식별자·연락처·주소·계정·건강 관련 field-name 신호는 관측되지 않았지만 PII 부재를 의미하지 않는다. 비식별 설명과 공식 schema 일치 여부도 아직 검토하지 않았다.

## 비노출·원본 불변

- 외부 산출물: JSON 6개
- 로컬 절대경로 패턴: 0
- 원본 entry prefix 패턴: 0
- Record 문자열 값·preview·원문 파일: 0
- 선택 ZIP 전후 SHA-256: 일치
- Inventory metadata digest: 일치
- `source_mutation_detected: false`

## 해석과 승인 경계

- [확정] 전체 데이터 대표성을 보장하지 않는 제한 read 층화 표본이다.
- [확정] 실제 schema·text 품질·PII 부재와 라이선스 승인은 미확정이다.
- [확정] Tokenizer corpus 승인과 별개이며 corpus를 생성하지 않았다.
- `candidate_status: registered`
- `license_review_status: approved_student_noncommercial`
- `approval.tokenizer: approved_tokenizer_development`, `approval.pretraining/sft/evaluation: pending`
- Gate 3: `planned`

## 다음 검토

1. 원문을 Git에 기록하지 않는 비공개 사람 검토 절차와 reviewer 책임을 승인한다.
2. 자유서술 text의 PII 가능성과 비식별 설명을 확인한다.
3. 공식 데이터 설명과 hash-only schema 후보의 일치 여부를 확인한다.
4. 라이선스·PII·목적별 승인 전 corpus와 Tokenizer 학습을 시작하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-26 | [확정] 현재 학생·비상업 라이선스와 tokenizer `under_review` 상태를 동기화함 |
| 2026-07-24 | [확정] 단일 archive의 size-bucket 2개 entry·64 MiB bounded inspection과 schema·PII checklist 결과를 기록함 |
