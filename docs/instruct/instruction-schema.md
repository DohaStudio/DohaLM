# Instruction Dataset Schema

- 문서 상태: `review`
- 마지막 검토일: 2026-07-28
- Schema 상태: `design_completed_not_implemented`
- 실제 record 생성: `forbidden`

## Logical record

| Field | Type | Required | 용도 | 학습 입력 여부 |
|---|---|---|---|---|
| `instruction` | string | 예 | 수행할 지시 | 예 |
| `input` | string 또는 null | 예 | 선택적 작업 context | 값이 있을 때 예 |
| `output` | string | 예 | 목표 응답 | label only |
| `system` | string 또는 null | 아니요 | 승인된 상위 행동 경계 | 승인 template에서만 |
| `metadata` | object | 예 | 비학습 계보·감사 정보 | 아니요 |
| `language` | enum | 예 | 주 언어·혼합 언어 | 아니요 |
| `license` | object | 예 | source·사용·파생 조건 | 아니요 |
| `source` | object | 예 | dataset·record 계보 | 아니요 |
| `quality` | object | 예 | 검토·score·검증 상태 | 아니요 |
| `safety` | object | 예 | PII·유해성·권한 risk | 아니요 |
| `category` | enum | 예 | 평가·분할 category | 아니요 |
| `difficulty` | enum | 예 | 난이도 bucket | 아니요 |
| `version` | string | 예 | schema·record version | 아니요 |

## Metadata 계약

`metadata`에는 record ID, group ID, split, schema version, created/validated provenance와 content fingerprint를
둔다. `license`에는 license ID·검토 상태·SFT 허용·redistribution 상태를, `source`에는 dataset ID·version·
source record reference를 둔다. 실제 owner나 이용조건을 추정하지 않는다.

`quality`와 `safety`의 enum·threshold는 실제 dataset 검토 후 승인한다. 원문 PII 값을 metadata에 복제하지
않고 검출 category·review status·비가역 fingerprint만 기록한다.

## Validation

- Required field, type, enum과 version 검증
- Empty/whitespace-only instruction·output 차단
- Metadata가 serialized prompt에 들어가지 않는지 검증
- Output만 label로 학습하고 instruction/input/system label은 mask하는 계약 검증
- JSON·tool category의 output schema 검증
- 동일 group의 split 교차와 benchmark overlap 차단
- record·manifest fingerprint의 canonical serialization 검증

## 금지

실제 text 예시, PII, URL 원문, token ID, dataset record와 학습 가능한 문장을 이 문서에 넣지 않는다.
Schema 승인은 dataset 선택·SFT 사용·redistribution 승인이 아니다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | Instruction logical record와 비학습 metadata·validation 경계 설계 |
