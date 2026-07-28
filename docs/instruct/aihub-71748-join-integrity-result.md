# AIHUB-71748 SFT Join Integrity 결과

- 문서 상태: `review`
- 마지막 검토일: 2026-07-29
- Dataset ID: `AIHUB-71748`
- 검사 상태: `completed`
- Join 계약: `passed`
- 관련 문서: [SFT 검증 계획](./aihub-71748-sft-validation-plan.md), [Schema Inspection](./aihub-71748-schema-inspection.md), [Safe Dataset Inspector](./safe-dataset-inspector.md), [ADR-004](../decisions/ADR-004-data-governance.md)

## 1. Scope

[확정] 이번 검사는 AIHUB-71748의 `SFTdata`와 `SFTlabel` 사이 `data_id` 관계만 확인했다. Training과
Validation만 포함했으며 General Corpus, RM, PPO 및 질문·응답·category·metadata 값은 검사 대상이 아니다.

## 2. Approval boundary

[확정] 승인 범위는 read-only Join Integrity와 안전 집계, 구현·합성 테스트·문서 게시까지다. Dataset 선택·처리,
PII, content duplicate, near duplicate, leakage, benchmark contamination, 품질 평가, Adapter, SFT backend 및 학습은
승인되지 않았다. `execution_allowed`는 `false`다.

## 3. Components

| Split | Component | Record |
|---|---|---:|
| Training | SFTdata | 10,580 |
| Training | SFTlabel | 10,580 |
| Validation | SFTdata | 1,322 |
| Validation | SFTlabel | 1,322 |

각 Component 합계는 11,902건이며 이전 Schema Inspection 기준과 일치한다.

## 4. Read-only execution

[확정] ZIP entry는 추출 없이 스트리밍으로 열었고 record는 bounded-memory로 한 건씩 해석한 뒤 즉시 폐기했다.
원본·외부 Dataset Root·ZIP·JSON에 대한 쓰기, 복사, 이동, 변환, cache 및 임시 payload 생성은 0건이다.

첫 CLI 직접 파일 호출은 import 진입 전에 실패했으며 archive를 열지 않아 full scan으로 계산하지 않았다. 모듈 진입
검증 후 승인된 payload scan 호출은 한 번만 수행했고, 그 내부에서 primary와 deterministic repeat 두 full scan을
정확히 수행했다. 자동 retry는 없었다.

## 5. Safe Inspector 적용

[확정] 집계 결과는 `guard_safe_output`을 통과해야만 반환하도록 구성했다. 실제 ID·긴 substring·payload 값이
결과에 포함되면 고정 오류 `RAW_VALUE_LEAK_DETECTED`로 Fail Closed한다. 합성 raw ID·exception·stdout·stderr·log
누출 회귀가 통과했다.

## 6. `data_id` 정책

[확정] `data_id`는 원본 decoded string 그대로 프로세스 내부 set/dict key로만 비교했다. trim, case 변환,
Unicode normalization, 숫자 변환 및 hash를 사용하지 않았다. ID·hash·부분 문자열의 출력·직렬화·저장은 0건이다.

| 항목 | Training SFTdata | Training SFTlabel | Validation SFTdata | Validation SFTlabel |
|---|---:|---:|---:|---:|
| string | 10,580 | 10,580 | 1,322 | 1,322 |
| null | 0 | 0 | 0 | 0 |
| empty | 0 | 0 | 0 | 0 |
| whitespace-only | 0 | 0 | 0 | 0 |
| 최소 길이 | 36 | 36 | 36 | 36 |
| 최대 길이 | 36 | 36 | 36 | 36 |

Hash를 사용하지 않았으므로 hash collision 검사는 적용 대상이 아니며 hash 기반 equality도 사용하지 않았다.

## 7. Split 판정

[확정] Split은 archive 상대경로의 정확한 `Training` 또는 `Validation` 경로 요소로만 판정했다. record 내부 값을
사용하지 않았다. unknown·ambiguous split은 발견되지 않았다.

## 8. Component별 record 수

Training 양쪽 10,580건, Validation 양쪽 1,322건으로 기대값과 일치했다. `RECORD_COUNT_DRIFT`는 발생하지 않았다.

## 9. Unique 및 duplicate 집계

| Split | Data unique | Label unique | Data duplicate key | Label duplicate key | Duplicate 영향 record |
|---|---:|---:|---:|---:|---:|
| Training | 10,580 | 10,580 | 0 | 0 | 0 |
| Validation | 1,322 | 1,322 | 0 | 0 | 0 |

## 10. Join 결과

| Split | Matched | One-to-one 비율 | 관계 |
|---|---:|---:|---|
| Training | 10,580 | 1.0 | `one_to_one` |
| Validation | 1,322 | 1.0 | `one_to_one` |

[확정] 제한된 `data_id` Join 계약은 통과했다.

## 11. Orphan 결과

Training과 Validation 모두 SFTdata orphan 0건, SFTlabel orphan 0건이며 duplicate로 관계가 불명확한 key도 0건이다.

## 12. Split collision

SFTdata Training/Validation overlap, SFTlabel Training/Validation overlap, joined overlap은 모두 0건이다. Training
data와 Validation label, Validation data와 Training label 사이 cross-component mismatch도 모두 0건이다.

## 13. Determinism

[확정] 같은 입력에 대한 primary scan과 deterministic repeat의 record·unique·duplicate·matched·orphan·split
overlap·관계 집계가 완전히 일치했다. Full scan 횟수는 정확히 2회이며 추가 실행은 하지 않았다.

## 14. Safety 결과

```yaml
safety:
  raw_id_output: false
  raw_payload_output: false
  stdout_leak: false
  stderr_leak: false
  exception_leak: false
  dataset_root_write: false
  dataset_mutation: false
```

터미널과 문서에는 실제 ID, hash, 질문, 응답, category 값 및 metadata 값이 없다.

## 15. Blocker

Join key 구조 blocker는 발견되지 않았다. 그러나 다음 독립 blocker는 그대로 남는다.

1. PII Scan 미승인·미실행.
2. Content Duplicate 및 Near Duplicate Scan 미승인·미실행.
3. Leakage 및 Benchmark Contamination Scan 미승인·미실행.
4. Dataset 선택·처리 미승인.
5. SFT backend 미구현, SFT 학습 미승인.

## 16. Readiness

```yaml
AIHUB_71748_SFT:
  schema_inspection: completed
  safe_inspector: validated_for_data_id_join_only
  join_integrity_scan: completed
  join_contract: passed
  pii_scan: not_approved
  duplicate_content_scan: not_approved
  leakage_scan: not_approved
  dataset_selection: not_selected
  dataset_processing: not_approved
overall:
  sft_backend: not_started
  sft_training: not_approved
  execution_allowed: false
```

## 17. 다음 승인

[승인 필요] 다음 단계는 별도 PII Scan 계획·범위 승인이다. 이번 Join 결과만으로 Dataset 선택, processing 또는
SFT 실행을 승인할 수 없다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-29 | SFTdata/SFTlabel `data_id` 제한 Join Integrity 두 회 결정론 scan 및 안전 집계 결과 기록 |
