# AIHUB-71748 Approval Retirement Contract

- 문서 상태: `review`
- 마지막 검토일: 2026-07-30
- 적용 범위: issued·미소비 AIHUB-71748 SFT Processing Approval
- 관련 계약: [Approval Lineage](./aihub-71748-approval-lineage-contract.md), [Processing Contract v2](./aihub-71748-processing-contract-v2.md), [RuntimeExecutionRequest v1](./aihub-71748-runtime-execution-request-v1.md)

## 목적

[확정] `retire_approval_file(...)`은 canonical Approval artifact를 읽고 무결성·identity·상태를 검증한 뒤
`issued -> retired_before_consumption` 전환을 안전하게 영속화한다. Synthetic 검증과 PR #67 병합 뒤 별도 사용자
승인으로 실제 Approval 0009에 정확히 한 번 적용했다.

## Schema 결정

[확정] `ApprovalRecord` schema v2의 exact field set은 변경하지 않는다. Retirement timestamp와 사유는 sibling artifact
`<approval-stem>.retirement.json`의 `ApprovalRetirementEvidence` v1에 기록한다. Evidence는 전후 파일 SHA-256과
checksum, stable fingerprint, 전후 status, `retired_at`, `reason_code`, 자체 fingerprint를 포함한다.

Stable fingerprint는 lifecycle 상태와 timestamp를 제외하므로 retirement 전후 동일하다. Approval checksum은 status
변경을 포함하므로 새로 계산한다.

## 허용 전환과 차단

허용 조건은 다음과 같다.

```yaml
status: issued
consumed: false
execution_allowed: false
runtime_execution_request: absent
```

`prepared_not_issued`, `consumed`, `completed`, `failed`, 모든 retired 상태, checksum·fingerprint·identity 불일치,
unknown schema, 기존 RuntimeExecutionRequest는 Fail Closed다. Retired Approval은 RuntimeExecutionRequest 발급과
Approval consume에 다시 사용할 수 없다.

## Lock·CAS·atomic rewrite

[확정] Approval별 `.lifecycle.lock`을 exclusive create하여 retirement, consume, finalize와 RuntimeExecutionRequest
publish를 직렬화한다. Lock에는 PID와 무작위 nonce를 기록하며 기존 lock은 자동 제거하지 않는다. Stale lock은
수동 조사 대상으로 남기고 자동 우회하지 않는다.

Retirement는 다음 순서를 따른다.

1. lock 획득
2. 기존 file SHA-256·checksum·stable fingerprint·identity·status 검증
3. Approval과 evidence temp를 exclusive create하고 short write·flush·file fsync 검증
4. 교체 직전 기존 bytes와 RuntimeExecutionRequest 부재 재검증
5. Approval atomic replace
6. evidence atomic no-replace publish
7. 지원 플랫폼에서 parent directory fsync
8. 공식 loader로 Approval과 evidence 재검증
9. 소유한 temp와 lock만 정리

경쟁자가 artifact를 바꾸면 `APPROVAL_RETIREMENT_ARTIFACT_CHANGED`로 종료하고 경쟁 artifact를 덮어쓰지 않는다.
동시 retirement는 한 호출만 성공한다. 소유권이 없는 lock·temp 충돌 artifact는 삭제하지 않는다.

Replace 이후 evidence publish나 directory sync가 실패하면 성공으로 보고하지 않는다. Approval이 이미 retired로
전환됐을 수 있으므로 `APPROVAL_RETIREMENT_INCOMPLETE` 또는 `APPROVAL_RETIREMENT_DIRECTORY_SYNC_FAILED`로 보고하고
자동 retry를 금지한다.

## 오류 계약

- `APPROVAL_RETIREMENT_ARTIFACT_NOT_FOUND`: 대상 artifact 없음
- `APPROVAL_RETIREMENT_IDENTITY_MISMATCH`: Approval ID 또는 Run ID 불일치
- `APPROVAL_RETIREMENT_CHECKSUM_MISMATCH`: checksum 불일치
- `APPROVAL_RETIREMENT_FINGERPRINT_MISMATCH`: stable fingerprint 불일치
- `APPROVAL_RETIREMENT_ALREADY_CONSUMED`: 이미 소비·완료된 Approval
- `APPROVAL_RETIREMENT_STATUS_INVALID`: 허용되지 않은 lifecycle 또는 runtime request 존재
- `APPROVAL_RETIREMENT_LOCK_COLLISION`: lifecycle lock 경쟁
- `APPROVAL_RETIREMENT_TEMPORARY_COLLISION`: temp/probe 충돌
- `APPROVAL_RETIREMENT_ATOMIC_WRITE_FAILED`: short write·flush·file fsync·replace 실패
- `APPROVAL_RETIREMENT_DIRECTORY_SYNC_FAILED`: 교체 후 directory fsync 실패
- `APPROVAL_RETIREMENT_UNSUPPORTED`: 안전한 no-replace 보장이 없는 플랫폼
- `APPROVAL_RETIREMENT_INCOMPLETE`: 교체 후 evidence·unlock·재검증 실패

## Counter와 CLI

Retirement는 기존 execution counter를 증가시키지 않는다.

```yaml
approval_issue_calls: unchanged
approval_consume_calls: unchanged
runtime_request_creations: unchanged
runtime_execution_gate_activations: unchanged
processing_engine_calls: unchanged
```

공식 CLI는 `python -m scripts.datasets.retire_aihub_71748_sft_approval`이며 `--retirement-only`를 요구한다.
사용자 지정 retirement timestamp는 받지 않고 시스템 UTC를 사용한다. CLI는 Approval issue·consume,
RuntimeExecutionRequest, Preflight, Processing을 호출하지 않는다.

## 검증과 실제 안전 상태

[확정] Synthetic test로 정상 전환, 상태·identity·무결성 차단, 기존 RuntimeExecutionRequest 차단, 경쟁 변경 보존,
동시 retirement 단일 성공, lock/temp 충돌, short write·flush·file fsync·replace·directory sync·unlock 실패,
unsupported platform과 CLI zero-call 계약을 검증했다. 실제 폐기 실행에서는 public service만 사용했으며
RuntimeExecutionRequest·consume·Processing counter는 모두 0으로 유지됐다.

```yaml
approval_0009: retired_before_consumption
approval_retirement_0009: completed
retirement_reason: RUNTIME_REQUEST_GOVERNANCE_MISMATCH
runtime_execution_request_0009: absent
run_0010: not_created
processing_calls: 0
execution_allowed: false
```

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-30 | PR #67 병합 후 Approval 0009 공식 retirement 완료; Run 0010 미생성 유지 |
| 2026-07-30 | schema v2를 유지하는 public retirement service·evidence·lock/CAS·CLI 계약 초안 작성 |
