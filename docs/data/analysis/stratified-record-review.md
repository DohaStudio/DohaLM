# 층화 record schema·PII review 계약

## 문서 정보

- 문서 상태: `review`
- 마지막 검토일: 2026-07-24
- 선행 문서: [ZIP JSON record 제한 분석](./zip-json-record-sampling.md), [수동 경로 mapping](./manual-path-mapping.md)
- 후속 문서: [AIHUB-71748 schema review](./AIHUB-71748-schema-review.md), 별도 비공개 수동 검토 승인
- 구현 전 필수 여부: 층화 record schema·PII 검토 전 예

## 목적과 제한

- [확정] 승인 mapping을 통과한 대용량 JSON 후보를 archive·entry 크기·compression ratio 기준으로 분산한다.
- [확정] ZIP deflate entry는 시작부터 승인 byte만 순차 읽으며 임의 위치 seek를 수행하지 않는다.
- [확정] 읽은 bounded 범위에서 발견한 record index를 early·middle·late로 나눠 stable SHA-256 rank로 선택한다.
- [확정] Field 이름 hash, 허용 표시명, type·presence·길이·depth·schema signature와 PII 검토 상태만 기록한다.
- [제외] 전체 ZIP 해제, 전체 JSON 추출·parse, record 원문 저장, corpus 생성과 PII 자동 판정을 수행하지 않는다.
- [검증 필요] 제한 read 표본은 전체 데이터 대표성, 실제 text 품질 또는 PII 부재를 보장하지 않는다.

## Entry 층화

Entry 선택 rank는 seed, dataset ID, archive 상대경로 hash, entry 이름 hash, uncompressed size bucket과 mapping rule ID를 SHA-256으로 결합한다.

| 층화 | 구간 |
|---|---|
| Entry size | 40 MiB 미만 / 40–50 MiB / 50 MiB 이상 |
| Compression ratio | 0.25 미만 / 0.25–0.50 / 0.50 이상 |
| Archive | 서로 다른 archive 우선, archive별 entry 상한 적용 |
| Mapping | 승인된 rule만 포함 |

- [확정] 입력 순서와 Python `hash()`에 의존하지 않는다.
- [확정] 한 archive는 `max-entries-per-archive`, 한 entry는 `records-per-entry`를 넘을 수 없다.
- [검증 필요] 후보가 한 archive에만 있으면 설정한 archive 수를 채우지 않고 실제 분포를 보고한다.

## Record 구간 층화

읽은 범위에서 관측한 `records_seen`을 기준으로 record index 0–33%는 `early`, 33–66%는 `middle`, 66–100%는 `late`로 분류한다. 각 구간에서 stable rank를 적용하고 부족한 quota만 다른 구간의 rank 후보로 보충한다.

- [확정] 이는 bounded prefix 내부 구간이다.
- [제외] 전체 entry의 실제 중간·끝 byte로 seek했다고 표현하지 않는다.
- [검증 필요] read 상한 이후 record 분포와 schema는 미확인이다.

## Field review manifest

각 field는 다음 비노출 정보만 가진다.

- `field_name_hash`, `allowed_display_name`
- `observed_value_types`
- `record_presence_count`, `record_presence_ratio`
- 문자열 길이 최소·최대·평균
- `nested_depth`, `candidate_category`
- `schema_signature_ids`, `strata_presence`
- `manual_review_status`, `manual_review_reason`

분류는 `likely_text`, `possible_text`, `metadata`, `label`, `source`, `pii_review_required`, `excluded`다. 허용 목록 밖 field 이름은 표시하지 않는다.

## PII review checklist

직접 식별자, 연락처, 주소, 계정·사용자 ID, 상담·진단·건강 field 이름 신호와 자유서술·metadata source identifier 가능성을 구분한다. 비식별 설명과 공식 schema 일치 여부는 사람이 검토한다.

상태는 `not_reviewed`, `review_required`, `no_field_name_signal`, `conditionally_clear`, `blocked`를 사용한다.

- [확정] 자동 실행은 `conditionally_clear`를 부여하지 않는다.
- [확정] `no_field_name_signal`은 PII 부재를 의미하지 않는다.
- [확정] 실제 문자열 값을 탐지·출력하지 않는다.

## Preview 차단

- [확정] Preview는 기본 비활성이고 이번 구현에는 생성 기능이 없다.
- [확정] 요청 또는 승인 flag가 들어와도 `blocked_not_implemented`로 거부한다.
- [후순위] 별도 사용자 승인, 외부 ignored 경로, record·문자 상한, redaction, checksum, reviewer와 삭제 기한 계약 후 재검토한다.

## 출력과 실행

외부 `analysis/schema-review/<Dataset ID>/<run-id>/` 아래 다음 JSON 6개만 생성한다.

- `run-summary.json`
- `strata-summary.json`
- `schema-signatures.json`
- `field-review-manifest.json`
- `pii-review-checklist.json`
- `manual-review-required.json`

```powershell
python -m scripts.datasets.review_aihub_records `
  --config configs/local-datasets.yaml `
  --dataset AIHUB-71748 `
  --manual-mapping configs/aihub-71748-path-mapping.yaml `
  --max-archives 5 `
  --max-entries-per-archive 2 `
  --records-per-entry 5 `
  --max-read-bytes-per-entry 33554432 `
  --max-total-read-bytes 134217728 `
  --dry-run `
  --json
```

Dry-run은 content를 읽지 않는다. Inspection도 record 원문 파일을 만들지 않으며 inventory metadata digest와 선택 ZIP checksum을 전후 비교한다.

## 승인 경계

- `candidate_status: registered`
- `license_review_status: pending_terms_review`
- `approval.tokenizer/pretraining/sft/evaluation: pending`
- Gate 3: `planned`

Schema·PII review bundle은 라이선스나 Tokenizer corpus 승인이 아니다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-24 | [확정] archive·entry·bounded record 구간 층화와 비노출 field·PII 수동 검토 계약을 기록함 |
