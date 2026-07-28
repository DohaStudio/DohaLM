# DohaLM Instruct Readiness

- 문서 상태: `review`
- 마지막 검토일: 2026-07-28
- 설계 상태: `design_completed`
- 실행 상태: `execution_not_approved`
- `execution_allowed`: `false`

## Checklist

| 영역 | 상태 | 현재 evidence | 실행 전 blocker |
|---|---|---|---|
| Parent | `approved_experimental` | Candidate B, ADR-009 | immutable checkpoint 복사·identity manifest |
| Lineage | `designed` | ADR-010·Instruct 전략 | model/run/version ID 확정 |
| Dataset | `not_selected` | dataset 전략 | license·PII·목적·split·누수 승인 |
| Schema | `designed_not_implemented` | instruction schema | validator·mapping·실제 record 검증 |
| Prompt | `designed_not_serialized` | placeholder templates | delimiter·mask·EOS·truncation fingerprint |
| Evaluation | `framework_designed` | instruction evaluation | dataset·rubric·numeric threshold 승인 |
| Safety | `framework_designed` | instruction safety | policy·red-team·severe failure 승인 |
| Tool calling | `design_only` | tool strategy | registry·permission·validator·sandbox |
| Backend | `not_started` | 없음 | 별도 backend 설계·CPU fail-closed 검증 |
| Training config | `not_created` | 없음 | budget·optimizer·scheduler·batch·seed 승인 |
| Runtime | `not_inspected` | 없음 | GPU·disk·output·monitor preflight |
| Approval | `not_issued` | 없음 | immutable commit·single-use execution approval |
| Training | `not_approved` | 금지 | 모든 blocker 해소 후 별도 사용자 승인 |
| Publication | `not_approved` | 금지 | license·model card·safety·artifact 승인 |

## Fail Closed 조건

Parent checksum 불일치, dataset·license·PII 미승인, schema/template/evaluation identity 미확정, leakage,
working tree dirty, output 미검증, runtime 예산 미확정 또는 single-use approval 부재 시 optimizer step 0에서
중단해야 한다. 자동 retry·resume·budget extension·publication은 허용하지 않는다.

## Ready 판정

```text
project: dohalm-instruct-tiny-v1
design_status: design_completed
readiness_package: documentation_complete
execution_allowed: false
backend: not_started
dataset: not_selected
training: not_approved
evaluation_execution: not_approved
publication: not_approved
```

[확정] 이 상태는 “학습 준비 완료”가 아니라 설계 문서 묶음이 작성됐음을 뜻한다. 다음 단계도 바로 학습이
아니라 dataset 후보·license·PII와 template/evaluation numeric 계약의 별도 검토다.

## 다음 승인 후보

1. Instruction dataset 후보 조사·read-only metadata 검토
2. Schema validator와 prompt serialization 설계 승인
3. Evaluation dataset·rubric·numeric threshold 승인
4. Backend 구현·CPU fail-closed 검증 승인
5. 최종 runtime·single-use SFT 실행 승인

각 항목은 독립 승인이고 1~4가 5를 자동 승인하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | Instruct 설계 readiness checklist·blocker·fail-closed 상태 작성 |
