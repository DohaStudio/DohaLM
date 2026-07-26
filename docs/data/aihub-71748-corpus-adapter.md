# AIHUB-71748 Corpus Adapter

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `implemented` |
| 마지막 검토일 | 2026-07-26 |
| 선행 문서 | [Corpus Adapter 공통 계약](./corpus-adapter-contract.md), [AIHUB-71748 schema review](./analysis/AIHUB-71748-schema-review.md), [dataset 승인 로그](./dataset-approval-log.md) |
| 후속 문서·작업 | Gate 7 별도 승인 검토; 현재 Adapter 범위는 tokenizer development 완료로 종료 |
| 구현 전 필수 여부 | AIHUB-71748 corpus 변환 전 예 |

- [확정] 구현과 테스트는 실제 AI Hub 원문을 복사하지 않은 synthetic fixture만 사용했다.
- [확정] 기존 `src/data/adapters/aihub_71748.py`와 `scripts/datasets/adapt_aihub_71748.py`는 회귀 검증을 위해 synthetic fixture 전용으로 유지한다.
- [확정] 2026-07-26 사용자 승인에 따라 별도 전용 진입점이 Training의 `data_info[].contents`만 제한 처리한다. Validation·RLHF·라벨링·metadata는 입력하지 않는다.
- [확정] corpus·후보 생성은 tokenizer development에만 승인됐고 모델 학습 승인이 아니다. 2026-07-26 사용자 최종 승인으로 Gate 3은 `passed`, 제한 Adapter 작업은 `completed`이며 Gate 7은 `planned`를 유지한다.

## 2. 합성 Adapter 입력 schema

MVP 입력 root는 JSON object이며 `text`는 비어 있지 않은 문자열이어야 한다. `metadata`와 `source`는 선택 필드다. 오직 `text`만 본문으로 사용하고 `metadata`·`source`는 합치거나 출력 record에 복사하지 않는다.

알 수 없는 최상위 필드는 변환을 무조건 실패시키지 않고 `UNKNOWN_FIELD_IGNORED` 경고로 집계한다. PII 유사 field 이름은 `PII_LIKE_FIELD_NAME` 경고를 추가하지만, 이름과 값은 저장하지 않는다. 이는 PII가 없다는 판정이 아니며 `pii_status: review_required`를 바꾸지 않는다.

## 3. 출력과 상태

accepted record는 `record_id`, `dataset_id`, `source_record_hash`, `text_original_hash`, `text_normalized`, 문자·byte 수, schema signature, lineage를 포함한다. source object 전체와 metadata/source 값은 포함하지 않는다.

합성 Adapter와 실제 tokenizer 전용 파이프라인의 상태는 다음과 같다.

| 구분 | 상태 |
|---|---|
| candidate | `registered` |
| license review | `approved_student_noncommercial` |
| tokenizer | `approved_tokenizer_development` |
| pretraining | `pending` |
| SFT | `pending` |
| evaluation | `pending` |
| PII | `not_cleared_restricted_tokenizer_development_approval` |
| usage·split | tokenizer development만 허용 |
| Adapter | `completed_tokenizer_development_only` |
| Gate 3 | `passed` |
| Gate 7 | `planned` |

## 4. 실제 데이터의 제한 활성화

기존 synthetic CLI의 실제 모드 dry-run은 계속 차단 상태를 반환한다. 실제 tokenizer development는 `scripts.datasets.build_aihub_71748_tokenizer_corpus`만 사용하며 package manifest의 목적 승인과 Adapter 제한 상태를 먼저 확인한다.

전용 진입점은 `Training/01.원천데이터/TS_01.*` 25개만 허용하고 각 archive checksum을 기존 inventory와 다시 비교한다. 출력은 로컬 설정의 외부 root 아래에만 원자적으로 게시하며 acquisition evidence·provider version 미확정 때문에 일반 `source_manifest_eligible`은 `false`로 유지한다.

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
| 2026-07-26 | [확정] 운영 tokenizer 최종 승인에 따라 제한 Adapter 범위를 `completed`, Gate 3을 `passed`로 기록하고 Gate 7·모델 학습 미승인 경계를 유지함 |
| 2026-07-26 | [확정] 사용자 승인에 따라 Training `data_info[].contents` 전용 제한 pipeline을 분리하고 Validation·RLHF·metadata·모델 학습 차단을 유지함 |
| 2026-07-24 | [확정] synthetic fixture 전용 AIHUB-71748 adapter와 실제 content read 0 차단 경계를 기록함 |
