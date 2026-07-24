# ZIP 대용량 JSON record 제한 분석 계약

## 문서 정보

- 문서 상태: `review`
- 마지막 검토일: 2026-07-24
- 선행 문서: [수동 경로 mapping 계약](./manual-path-mapping.md), [대용량 JSON 제한 검사](./large-json-inspection.md)
- 후속 문서: [AIHUB-71748 record 분석 결과](./AIHUB-71748-record-sampling.md), 별도 schema·PII 수동 검토
- 구현 전 필수 여부: 대용량 ZIP JSON record 관측 전 예

## 목적과 비목표

- [확정] 승인된 수동 mapping과 안전 검사를 통과한 5 MiB 초과 JSON entry를 ZIP stream으로만 읽는다.
- [확정] root JSON array의 top-level record 경계를 문자열·escape·중첩 depth 상태로 탐지한다.
- [확정] record 원문이나 문자열 값을 저장하지 않고 key hash, 허용 key 이름, type·길이·schema signature만 기록한다.
- [제외] ZIP 해제, entry 파일 추출, 전체 `json.load()`, corpus 생성과 Tokenizer 학습을 수행하지 않는다.
- [검증 필요] 제한된 read 구간은 전체 파일의 대표 표본이나 실제 schema 확정 근거가 아니다.

## 지원 범위

| 항목 | 상태 |
|---|---|
| Root JSON array | [확정] 지원 |
| Object array item | [확정] 제한 parse·구조 집계 |
| Primitive array item | [확정] type만 기록 |
| Root object 내부 records 탐색 | [제외] 미지원 |
| JSONL·연결 JSON document | [제외] 미지원 |
| 깨진 JSON 복구·주석 JSON | [제외] 미지원 |

상태 코드는 `RECORD_OK`, `RECORD_TOO_LARGE`, `RECORD_PARSE_FAILED`, `RECORD_TRUNCATED`, `ENTRY_READ_LIMIT_REACHED`, `TOTAL_READ_LIMIT_REACHED`, `ROOT_NOT_ARRAY`, `INVALID_UTF8`, `MALFORMED_JSON_STRUCTURE`를 사용한다.

## Streaming parser

1. `ZipFile.open()`으로 선택 entry stream만 연다.
2. UTF-8 incremental decoder가 multibyte chunk 경계를 보존한다.
3. root `[`를 확인하고 문자열·escape·Unicode escape·object/array depth를 추적한다.
4. root depth의 쉼표 또는 닫는 `]`에서 record 경계를 확정한다.
5. 문자열 내부 comma·brace·bracket과 중첩 구조 delimiter는 경계로 사용하지 않는다.
6. record가 상한을 넘으면 buffer를 폐기하고 SHA-256·크기·경계 상태만 계속 추적한다.
7. 상한 내 record만 record 단위 `json.loads()`로 parse하고 callback 이후 원문 객체를 유지하지 않는다.

Trailing comma, 공백 item, 구조 불균형은 `MALFORMED_JSON_STRUCTURE` 또는 record parse 실패로 기록한다.

## 제한과 선택

기본값은 entry 3개, entry당 record 5개, record당 1 MiB, entry당 read 16 MiB, 전체 read 32 MiB다. 일반 안전 sampler의 entry당 5 MiB 제한은 변경하지 않는다.

- [확정] 발견 record는 dataset ID, archive 상대경로, entry 이름 hash, record index와 고정 seed를 SHA-256으로 결합한다.
- [확정] 읽은 범위 안에서 stable rank가 낮은 record만 entry별 제한 수만 유지한다.
- [확정] Python `hash()`를 사용하지 않는다.
- [검증 필요] read 상한 이전 record만 대상으로 하므로 전체 파일 대표 표본이라고 주장하지 않는다.

## 비노출 manifest

외부 `analysis/record-samples/<Dataset ID>/<run-id>/` 아래 다음 JSON만 생성한다.

- `run-summary.json`
- `entry-summary.json`
- `record-manifest.json`
- `schema-summary.json`
- `rejected-records.json`
- `manual-review-required.json`

Archive·entry는 SHA-256 식별자만 기록한다. 허용 schema key만 이름을 표시하고 그 밖의 key와 PII 위험 field 이름은 hash·경고 신호만 기록한다. 문자열 값, preview, 실제 로컬 절대경로와 record 원문 파일은 기록하지 않는다.

## 실행 모드

```powershell
python -m scripts.datasets.sample_zip_json_records `
  --config configs/local-datasets.yaml `
  --dataset AIHUB-71748 `
  --manual-mapping configs/aihub-71748-path-mapping.yaml `
  --max-entries 3 `
  --records-per-entry 5 `
  --max-record-bytes 1048576 `
  --max-read-bytes-per-entry 16777216 `
  --max-total-read-bytes 33554432 `
  --dry-run `
  --json
```

- `--dry-run`: mapping·후보·제한·출력 계획만 확인하며 entry byte를 읽지 않는다.
- 비-dry-run: 제한 byte 안에서 record 구조 manifest만 생성하며 파일을 추출하지 않는다.
- [확정] 전후 inventory metadata digest와 선택 ZIP checksum이 다르면 실패한다.

## 승인 경계

- `candidate_status: registered`
- `license_review_status: pending_terms_review`
- `approval.tokenizer/pretraining/sft/evaluation: pending`
- Gate 3: `planned`

Record 구조 관측은 데이터 이용, PII 부재, corpus 또는 Tokenizer 승인이 아니다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-24 | [확정] bounded JSON array record parser, stable SHA-256 선택, 비노출 schema manifest와 원본 불변 계약을 기록함 |
