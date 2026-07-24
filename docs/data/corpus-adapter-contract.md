# DohaLM Corpus Adapter 공통 계약

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `implemented` |
| 마지막 검토일 | 2026-07-24 |
| 선행 문서 | [Phase 1 데이터 계약](./phase1-data-contract.md), [데이터 전처리](./preprocessing.md), [데이터 품질 체크리스트](./data-quality-checklist.md), [ADR-004](../decisions/ADR-004-data-governance.md) |
| 후속 문서·작업 | dataset별 adapter, 승인된 corpus의 Phase 1 pipeline 연결 |
| 구현 전 필수 여부 | dataset별 adapter 구현 전 예 |

- [확정] Corpus Adapter는 외부 dataset의 record를 제한된 공통 중간 record로 바꾸는 경계다. adapter 성공은 라이선스·PII·목적별 사용 승인이나 Phase 1 corpus 게시를 의미하지 않는다.
- [확정] 현재 구현 검증 범위는 합성 fixture뿐이다. 실제 외부 원문을 corpus로 생성하지 않았다.

## 2. 입력·추출 계약

- [확정] adapter는 record 단위 JSON 값을 받아 dataset별 schema를 검증한다.
- [확정] 본문 필드로 승인된 값만 `text_normalized`에 넣는다. object 전체 문자열화, key 삽입, metadata·source·label·role 결합은 금지한다.
- [확정] 알 수 없는 필드는 기본적으로 값과 이름을 저장하지 않는다. 구조 통계에는 key 이름의 SHA-256과 value type만 반영할 수 있다.
- [확정] 입력 원문 object와 거부된 text는 산출물에 저장하지 않는다.

## 3. 정규화 계약

순서는 UTF-8 유효성 검사 → NUL 차단 → CRLF/CR의 LF 변환 → Unicode NFC → 각 줄 끝의 불필요한 공백 제거다. 연속 공백은 보존하며 NFKC는 적용하지 않는다. 세부 기준은 [Phase 1 데이터 계약](./phase1-data-contract.md)을 따른다.

출력은 `text_original_hash`, `text_normalized`, `normalization_applied`, 문자 수와 UTF-8 byte 수를 포함한다. manifest에는 원문 text를 넣지 않는다.

## 4. ID·schema·lineage

- [확정] `record_id`는 dataset ID, source record hash, schema signature, normalized text hash, adapter version의 canonical JSON SHA-256이다. Python `hash()`는 사용하지 않는다.
- [확정] schema signature는 root·정렬된 key 구조·value type·중첩 구조·adapter schema version만 fingerprint한다. `text`, `metadata`, `source` 이외 key는 이름도 hash만 사용한다.
- [확정] accepted record 계보에는 source record hash, adapter version, normalization version, schema signature, output record hash를 둔다.
- [확정] 시각은 artifact fingerprint에서 제외한다. 절대 로컬 경로는 record·manifest·schema summary에 기록하지 않는다.

## 5. Rejection과 사용 차단

구조·text 위반은 `rejections.jsonl`에 reason code와 단계, source record hash만 기록한다. `ROOT_NOT_OBJECT`, `TEXT_FIELD_MISSING`, `TEXT_NOT_STRING`, `TEXT_EMPTY`, `TEXT_WHITESPACE_ONLY`, `TEXT_CONTAINS_NUL`, `TEXT_TOO_SHORT`, `TEXT_TOO_LONG`, `INVALID_UNICODE`, `UNSUPPORTED_SCHEMA`를 공통 최소 코드로 사용한다.

라이선스·승인·PII 미충족은 구조 변환 실패와 구분한다. 변환 가능한 record도 `adapter_status: adapted`, `usage_status: blocked_pending_approval`과 `LICENSE_NOT_APPROVED`, `APPROVAL_NOT_APPROVED`, `PII_REVIEW_REQUIRED`를 기록할 수 있다.

## 6. Batch·산출물 계약

- [확정] 단일 record와 one-pass iterable을 지원하고 accepted/rejected JSONL을 record 단위로 기록한다.
- [확정] 입력 순서는 JSONL 순서에만 영향을 주며 record ID와 정렬 기반 입력·출력 fingerprint에는 영향을 주지 않는다.
- [확정] 기본 text 길이는 1~100,000자이며 상한 초과를 정규화 전에 우선 차단한다.
- [확정] `accepted.jsonl`, `rejections.jsonl`, `adapter-manifest.json`, `schema-summary.json` 네 파일을 sibling staging에서 작성한 뒤 원자적으로 게시한다. 기존 출력은 덮어쓰지 않는다.
- [확정] 입력 파일을 처리 전후 SHA-256으로 비교하며 mutation이면 게시하지 않는다.

## 7. 실제 데이터 승인 Gate

실제 dataset adapter 실행과 개발 corpus 게시는 license `approved`, 목적별 approval `approved`, PII `clear` 또는 명시적 조건부 승인, 필요한 비공개 review 완료가 모두 확인돼야 한다. 조건이 하나라도 미충족이면 fail closed하고 content read와 artifact publish를 수행하지 않는다.

## 8. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-24 | [확정] 합성 fixture 기반 공통 adapter·결정론·비노출·원자적 산출물·승인 차단 계약을 구현 상태로 기록함 |
