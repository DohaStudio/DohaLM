# AIHUB-71748 Processing Run 0005 Preflight Failure Lineage

- 문서 상태: `review`
- 마지막 검토일: 2026-07-30
- Run 상태: `retired_preflight_validator_failure`
- Approval 상태: `retired_not_issued`
- `execution_allowed`: `false`

## 실패 요약

Run `AIHUB-71748-SFT-PROCESSING-20260730-0005`는 metadata-only Preflight의 최종 evidence
검증에서 중단됐다. validator가 호출자가 명시한 Run·Approval ID 대신 과거 0004 모듈 상수를 비교하여
`RUN_ID_ALREADY_USED`로 잘못 분류한 것이 원인이다.

Approval `AIHUB-71748-SFT-PROCESSING-APPROVAL-20260730-0005`는 발급되지 않았고 소비되지 않았다.
Processing engine, archive member 열람, JSON·record parse, payload read, output write는 모두 0건이다.

## 보존 정책

Run 0005와 Approval 0005는 재사용하지 않는다. 상태는 각각
`retired_preflight_validator_failure`, `retired_not_issued`로 영구 보존한다. 이 실패는 ID 형식·sequence 또는
실제 reuse 실패가 아니며 validator identity injection 결함과 구분한다.

## 후속 조치

[Run 0006 Preflight](./aihub-71748-processing-run-0006-preflight.md)는 명시적 Run·Approval ID 주입,
독립 mismatch 오류, execution surface 확대와 synthetic 회귀 검증을 포함한 새 immutable commit에서 수행했다.
Run 0006도 이후 Approval 계약 불일치로 폐기됐으며 [후속 계약](./aihub-71748-approval-lineage-contract.md)이
구현됐다. Run 0007은 [Processing 계약 v2](./aihub-71748-processing-contract-v2.md) 불일치를 시작 전에 발견해
evidence 0건으로 폐기됐다.
capability와 runtime gate, squash lineage를 분리한다.
