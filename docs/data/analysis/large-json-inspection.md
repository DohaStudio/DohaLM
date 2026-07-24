# 대용량 JSON 제한 Streaming 구조 검사

## 문서 정보

- 문서 상태: `review`
- 마지막 검토일: 2026-07-24
- 선행 문서: [수동 경로 mapping 계약](./manual-path-mapping.md), [AIHUB-71748 mapping 검토](./AIHUB-71748-path-mapping.md)
- 후속 작업: 사용자 구조 검토, schema·PII 검사 범위 결정

## 목적과 비목표

- [확정] 일반 sampler의 5 MiB 제한을 넘는 JSON을 추출하지 않고 제한된 prefix byte에서 구조 후보만 확인한다.
- [확정] 전체 ZIP 해제, 전체 `json.load()`, 원문 값 저장과 학습 corpus 생성은 수행하지 않는다.
- [확정] 이 결과는 실제 전체 schema나 데이터 품질을 확정하지 않는다.

## 실행 계약

```powershell
python -m scripts.datasets.inspect_large_json_entries `
  --config configs/local-datasets.yaml `
  --dataset AIHUB-71748 `
  --manual-mapping configs/aihub-71748-path-mapping.yaml `
  --max-entries 5 `
  --max-read-bytes 2097152 `
  --max-total-read-bytes 10485760 `
  --dry-run
```

기본값은 entry 5개, entry당 2 MiB, 전체 10 MiB다. `--dry-run`만 지원하며 출력은 외부 `analysis/large-json-inspection/<Dataset ID>/<Run ID>/`에 둔다.

## Streaming 정책

- `zipfile.ZipFile.open()`으로 선택 entry를 직접 stream read한다.
- Read 요청은 최대 64 KiB chunk이며 entry·전체 byte 상한에서 중단한다.
- Incremental strict UTF-8 decoder와 string escape·brace/bracket depth를 추적하는 제한 lexical scanner를 사용한다.
- 전체 `json.load()`와 외부 streaming dependency를 사용하지 않는다.
- 내용 byte와 문자열 값을 디스크·로그·JSON에 저장하지 않는다.

## 기록 필드

- 상태: `large_entry_inspection_candidate`, `large_entry_stream_inspected`, `large_entry_manual_review_required`
- Archive 상대경로 hash, entry 이름 hash, Rule ID와 source prefix hash
- 압축·비압축 크기와 실제 읽은 byte
- Root type·첫 구조 token·UTF-8·BOM·JSON Lines 후보
- Parse completeness·truncated·depth·unterminated string 상태
- Top-level 및 array item key hash
- 허용 일반 key의 sanitized 이름: `text`, `content`, `instruction`, `response`, `role`, `label`, `metadata`

허용 목록 밖 key는 이름을 기록하지 않고 SHA-256만 기록한다.

## AIHUB-71748 실행 결과

- Run ID: `large-json-dry-f6c7eef294d1f5d1`
- 대용량 후보: 571개
- 결정론적 선택·검사: 5개
- 실제 읽은 byte: 10,485,760
- 비압축 크기 범위: 36,359,456~49,684,060 bytes
- Root type 후보: array 5개
- Strict UTF-8: 5개
- BOM: 0개
- JSON Lines 후보: 0개
- Truncated: 5개
- `text`: 5개 검사에서 관측
- `metadata`: 4개 검사에서 관측
- 전체 파일 추출: 0개
- 원본 변경: 0건

[검증 필요] 모든 결과는 각 entry의 첫 2 MiB에 한정된다. 뒤쪽 record, 전체 key 집합, PII와 schema 일관성은 확인하지 않았다.

## 크기 정책

- [확정] 일반 sampler 기본 5 MiB를 유지한다.
- [확정] 대용량 검사는 별도 상태와 별도 외부 산출물로 관리한다.
- [제외] 일반 sampler의 기본 상한을 64 MiB 등으로 자동 상향하지 않는다.

## 승인 경계

- 이 검사는 mapping 절차 승인 범위의 읽기 전용 구조 관측이다.
- 데이터 이용조건·PII·Tokenizer·사전학습·SFT·평가 승인을 변경하지 않는다.
- Gate 3은 `planned`다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-24 | [확정] 표준 라이브러리 제한 streaming 검사 계약과 AIHUB-71748 대용량 JSON 5개 관측 결과를 기록함 |
