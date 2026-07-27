# AIHUB-71748 Pilot Source Lineage와 Canonical Selection Contract

## 1. 결론

- 문서 상태: `review`
- 결과: `A_historical_tokenizer_corpus_matches_contract`
- Canonical contract: `aihub-71748-training-selection-v1`
- Contract fingerprint: `sha256:bea1f19b1571e062096bd1d9dbd7b2c4144f2e9bf8f578448b190e3a60eb4293`
- [확정] Gate 3 historical corpus 107,226건과 SHA-256 `sha256:0c7119106261e9a8487b5e2e1ba76ba220761a2fdaeb14738e968b91fdbeeb00`을 canonical replay가 재현했다.
- [확정] Pilot v1 selector는 byte quota 초과 예외 후 archive 반복을 종료하지 않아 48건을 추가 선택했다.
- [확정] 48건은 모두 `pilot_only` / `BYTE_QUOTA_EXCEPTION_DID_NOT_STOP_ARCHIVE`이며 unknown은 0건이다.
- [확정] 원문과 실제 record ID는 문서·console·Git에 기록하지 않았다.

## 2. 두 pipeline 비교

| 항목 | Gate 3 Tokenizer corpus | Pilot v1 legacy replay | Canonical 계약 |
|---|---|---|---|
| Archive | Training 원천 `TS_01.*`, RLHF 제외, 25개 | 동일 | 동일 |
| 순서 | archive 상대경로, JSON filename 오름차순 | 동일 | 동일 |
| JSON 구조 | root `data_info` array | 동일 | 동일 |
| Text field | `contents`, 문자열만 | 동일 | 동일 |
| Null/type | 제외 | 동일 | 동일 |
| Empty/whitespace | normalization 오류로 제외 | 동일 | 동일 |
| Unicode/newline | NFC, CRLF/CR→LF | 동일 | 동일 |
| 공백 | 줄 끝 horizontal whitespace 제거, leading 보존 | 동일 | 동일 |
| Dedup | 전역 normalized UTF-8 SHA-256, 첫 record 유지 | 동일 | 동일 |
| Quota | 8,192건 또는 20 MiB, 초과 시 archive 종료 | 초과 후 다음 JSON entry 계속 | 초과 시 archive 종료 |
| Serialization | normalized UTF-8 + LF | dataset JSONL | 목적별 serialization, selection identity 공유 |

## 3. 차이가 발생한 archive

| Archive | Historical/Canonical | Pilot v1 | 차이 |
|---|---:|---:|---:|
| `SL01` | 4,479 | 4,481 | +2 |
| `SL04` | 7,491 | 7,493 | +2 |
| `SL08` | 688 | 690 | +2 |
| `SL09` | 241 | 242 | +1 |
| `SL11` | 286 | 287 | +1 |
| `SL12` | 141 | 146 | +5 |
| `SL14` | 238 | 239 | +1 |
| `WL01` | 6,002 | 6,018 | +16 |
| `WL02` | 3,928 | 3,930 | +2 |
| `WL09` | 572 | 588 | +16 |
| 합계 | 24,068 | 24,116 | +48 |

- [확정] 나머지 15개 archive의 accepted count 차이는 0건이다.
- [확정] 25개 archive의 raw candidate·accepted·duplicate·type/null·normalization/parser 제외 집계와 archive digest는 외부 `lineage-audit/quota-control-flow-v1` manifest에 저장했다.

## 4. Canonical Selection Contract

1. 승인 ZIP inventory에서 `Training/01.원천데이터`의 `TS_01.*` 25개만 허용하고 RLHF·Validation을 제외한다.
2. archive 상대경로와 ZIP 내부 JSON filename을 오름차순 처리한다.
3. JSON root의 `data_info` array만 streaming parser로 처리한다.
4. `contents`가 문자열인 record만 후보로 삼고 null·비문자열·NUL·empty·whitespace-only·parser 오류는 aggregate reason으로 제외한다.
5. CRLF와 CR을 LF로 바꾸고 NFC를 적용하며 각 줄 끝 horizontal whitespace를 제거한다. Leading whitespace는 보존하고 trailing newline은 최대 하나로 정규화한다.
6. normalized UTF-8 SHA-256을 exact duplicate key로 사용하고 전체 archive 순서에서 최초 record만 유지한다.
7. Dedup은 quota 판정 전에 수행한다. archive별 8,192건 또는 serialized 20 MiB를 초과하려는 첫 record에서 해당 archive 처리를 즉시 종료한다.
8. Record identity는 archive 상대경로, JSON entry 경로, array index의 SHA-256이며 공개 문서에는 원 identity를 기록하지 않는다.
9. Selection fingerprint는 ZIP inventory, contract version/config, archive별 count/digest와 source corpus SHA를 결합한다.
10. Tokenizer development와 Pilot Pretraining은 selection·normalization·dedup 계약을 공유한다. 목적별 PII filter·split·serialization·packing과 fingerprint는 별도 version으로 관리한다.

## 5. Artifact 관계

- `operating-16k-v1` corpus와 운영 tokenizer: 승인된 historical immutable artifact.
- `pilot-v1`: selector bug가 포함된 superseded dataset. 기존 Smoke 자원 evidence만 보존한다.
- `pilot-v2`: canonical source 107,226건을 재현한 신규 immutable Pilot dataset.
- 기존 Smoke checkpoint-5: `smoke_only_not_promotable`, pilot-v2 학습 evidence로 사용하지 않는다.

## 6. Readiness 경계

- [확정] `SOURCE_LINEAGE_NOT_VERIFIED`는 해소했다.
- [확정] pilot-v2 전용 5-step Runtime Smoke를 별도 run에서 통과해 상태는 `ready_awaiting_final_execution_approval`이다.
- [제외] 추가 Smoke, 100-step Pilot, Full Pretraining은 별도 사용자 승인 전 실행하지 않는다. 새 checkpoint-5도 승격하지 않는다.
