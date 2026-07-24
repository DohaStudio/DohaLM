# AIHUB-71748 Corpus Adapter

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `implemented` |
| 마지막 검토일 | 2026-07-24 |
| 선행 문서 | [Corpus Adapter 공통 계약](./corpus-adapter-contract.md), [AIHUB-71748 schema review](./analysis/AIHUB-71748-schema-review.md), [dataset 승인 로그](./dataset-approval-log.md) |
| 후속 문서·작업 | 이용조건·PII·목적별 승인 후 별도 실제 corpus pilot |
| 구현 전 필수 여부 | AIHUB-71748 corpus 변환 전 예 |

- [확정] 구현과 테스트는 실제 AI Hub 원문을 복사하지 않은 synthetic fixture만 사용했다.
- [확정] 실제 AI Hub corpus 생성, 실제 record text read, 실제 preview 생성과 tokenizer 학습은 수행하지 않았다.
- [확정] adapter 구현 성공과 corpus·tokenizer 승인은 별개다. Gate 3은 `planned`를 유지한다.

## 2. 최소 입력 schema

MVP 입력 root는 JSON object이며 `text`는 비어 있지 않은 문자열이어야 한다. `metadata`와 `source`는 선택 필드다. 오직 `text`만 본문으로 사용하고 `metadata`·`source`는 합치거나 출력 record에 복사하지 않는다.

알 수 없는 최상위 필드는 변환을 무조건 실패시키지 않고 `UNKNOWN_FIELD_IGNORED` 경고로 집계한다. PII 유사 field 이름은 `PII_LIKE_FIELD_NAME` 경고를 추가하지만, 이름과 값은 저장하지 않는다. 이는 PII가 없다는 판정이 아니며 `pii_status: review_required`를 바꾸지 않는다.

## 3. 출력과 상태

accepted record는 `record_id`, `dataset_id`, `source_record_hash`, `text_original_hash`, `text_normalized`, 문자·byte 수, schema signature, lineage를 포함한다. source object 전체와 metadata/source 값은 포함하지 않는다.

현재 모든 adapted record 상태는 다음과 같다.

| 구분 | 상태 |
|---|---|
| candidate | `registered` |
| license review | `pending_terms_review` |
| tokenizer | `pending` |
| pretraining | `pending` |
| SFT | `pending` |
| evaluation | `pending` |
| PII | `review_required` |
| usage·split | `blocked_pending_approval` |
| Gate 3 | `planned` |

## 4. 실제 데이터 차단

실제 모드의 dry-run은 config·mapping·ZIP·record content를 열지 않고 승인 상태만 반환한다. 현재 결과는 `actual_dataset_execution: blocked`, `development_corpus_publish: blocked`, `records_read: 0`, `content_bytes_read: 0`, `artifacts_published: 0`이다.

차단 해제에는 이용조건 승인, 목적별 승인, PII clear 또는 명시적 조건부 승인, private preview review 완료, dataset 승인 로그의 tokenizer development 승인이 모두 필요하다.

## 5. 합성 smoke

```powershell
python -m scripts.datasets.adapt_aihub_71748 `
  --input tests/fixtures/data/aihub_71748/valid_records.json `
  --output tests/output/aihub-71748-adapter `
  --synthetic `
  --json
```

합성 모드는 입력을 `tests/fixtures/data/aihub_71748/`, 출력을 `tests/output/` 아래로 제한하고 byte·record 상한을 적용한다. 입력 checksum을 게시 전후 비교하며 기존 출력은 덮어쓰지 않는다.

실제 차단 확인은 다음과 같이 수행하되 content는 읽지 않는다.

```powershell
python -m scripts.datasets.adapt_aihub_71748 `
  --config configs/local-datasets.yaml `
  --dataset AIHUB-71748 `
  --manual-mapping configs/aihub-71748-path-mapping.yaml `
  --dry-run `
  --json
```

## 6. 검증 범위와 한계

- [확정] synthetic 정상·거부·NFC/NFD·newline·unknown·nested metadata·PII 유사 이름·결정론·원본 불변·atomic publish를 자동 검증한다.
- [확정] 실제 schema를 확정하거나 실제 데이터 품질·라이선스·PII를 승인한 결과가 아니다.
- [검증 필요] 실제 승인이 완료된 뒤 bounded pilot으로 관측 schema와 adapter 입력 계약의 일치 여부를 재검토해야 한다.

## 7. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-24 | [확정] synthetic fixture 전용 AIHUB-71748 adapter와 실제 content read 0 차단 경계를 기록함 |
