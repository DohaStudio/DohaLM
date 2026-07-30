# AIHUB-71748 Approval Issuance·Squash-Merge Lineage 계약

- 문서 상태: `implemented`
- 마지막 검토일: 2026-07-30
- 작업 유형: `code`, `test`, `documentation`
- 실제 Approval 발급·소비: `0`
- 실제 Dataset payload 접근·Processing·output: `0`
- `execution_allowed`: `false`
- 관련 결정: [ADR-004](../decisions/ADR-004-data-governance.md), [ADR-010](../decisions/ADR-010-dohalm-instruct-strategy.md)

## 1. Run 0006 Fail Closed

[확정] Run `AIHUB-71748-SFT-PROCESSING-20260730-0006`은 Approval 발급 전 기존 permission·schema·lineage
계약 불일치가 발견되어 `retired_approval_contract_failure`로 영구 폐기한다. Approval 0006은 발급·소비되지
않았고 `retired_not_issued`다. 오류 코드는 `APPROVAL_PERMISSION_ESCALATION`이며 모든 실행 counter는 0이다.

## 2. Permission Model 문제

기존 계약은 Approval capability와 현재 runtime 실행 gate를 같은 boolean 집합으로 취급했다. 그 결과 향후
Processing capability를 가진 issued Approval을 만들면서 현재 실행을 비활성화하는 안전한 상태를 표현할 수
없었다.

## 3. Capability와 Runtime Gate 분리

Approval artifact의 `processing_allowed`, `payload_read_allowed`, `output_write_allowed`는 최대 capability다.
`execution_allowed`는 artifact가 그 자체로 실행 권한이 아님을 나타내며 항상 `false`로 저장한다. 실제 실행은
별도 `RuntimeExecutionRequest.execution_allowed=true`와 capability가 모두 검증될 때만 가능하다.

## 4. ApprovalRecord 확장

신규 canonical record는 `governance_record_commit`, `consumed`, `execution_allowed`를 checksum 대상에 포함한다.
필드 누락, 잘못된 boolean, unknown field는 Fail Closed한다. 발급 직후 `status=issued`, `consumed=false`,
`execution_allowed=false`가 필수다.

## 5. PreflightEvidence 확장

Evidence는 `execution_source_commit`과 `governance_record_commit`을 구분한다. 기존
`immutable_git_commit` 의미는 read-only property alias로만 제공하며 신규 canonical serialization에는
`execution_source_commit`을 기록한다.

## 6. Execution Source Commit

실행 surface가 만들어지고 검증된 commit이다. commit object가 실제로 존재해야 하며 고정 surface의 Git blob을
직접 읽어 fingerprint를 계산한다.

## 7. Governance Record Commit

Preflight·Approval·결과 계보가 반영된 commit이다. commit object가 존재하고 `origin/develop`에서 reachable해야
한다. 단순 local branch 이름이나 working tree 내용은 증거로 사용하지 않는다.

## 8. Squash Merge 특성

Squash Merge 후 governance commit은 feature intermediate commit의 descendant가 아닐 수 있다. 이 경우 ancestry
부재만으로 거부하지 않고 고정 execution surface의 경로·blob·Manifest·Backend fingerprint 동등성을 검증한다.

## 9. Execution Surface Equivalence

고정 surface는 Manifest 1개와 validator·reader·processor·writer·run contract·Approval·runtime monitor·
post-validation·processing CLI 9개, 총 10개다. 자동 glob으로 대체하지 않는다. 누락은
`EXECUTION_SURFACE_FILE_MISSING`, blob drift는 fingerprint별 오류 또는 `EXECUTION_SOURCE_TREE_DRIFT`다.

## 10. Lineage Validation

직접 ancestor이며 surface가 같으면 `DIRECT_ANCESTRY_VALID`, ancestor가 아니지만 모든 surface가 같으면
`SQUASH_MERGE_EXECUTION_SURFACE_EQUIVALENT`다. governance가 `origin/develop`에서 도달 불가능하면
`GOVERNANCE_COMMIT_NOT_REACHABLE`로 중단한다.

## 11. Approval Issuance Contract

발급은 capability 세 값이 모두 `true`, lifecycle artifact의 `execution_allowed=false`, `consumed=false`,
tokenization·SFT backend·training 권한이 모두 `false`일 때만 허용한다. issued timestamp와 checksum을 검증한 뒤
exclusive atomic write한다.

## 12. Processing Runtime Contract

실제 처리 호출은 issued·unconsumed Approval과 별도 canonical `RuntimeExecutionRequest`를 함께 요구한다. request는
Run·Approval ID, single-call/session limit, timezone-aware 시각과 자체 fingerprint를 포함한다. capability 부족은
`APPROVAL_CAPABILITY_INSUFFICIENT`, runtime 미승인은 `RUNTIME_EXECUTION_NOT_APPROVED`, identity·fingerprint 충돌은
`RUNTIME_PERMISSION_CONFLICT`다.

## 13. Lifecycle

```text
prepared_not_issued -> issued -> consumed -> completed | failed
prepared_not_issued -> retired_not_issued
issued -> retired_before_consumption
issued_partial -> retired_issue_incomplete
```

`consumed`는 실제 사용 여부이고 `execution_allowed`는 모든 lifecycle 상태에서 `false`다. 소비 transition만
`consumed=true`로 바꾼다.

## 14. Legacy Artifact Policy

신규 보안 필드가 없는 기존 Approval은 `LegacyApprovalRecord`로 read-only 열람할 수 있지만 실행 loader는
`LEGACY_APPROVAL_NOT_EXECUTABLE`로 차단한다. 기존 artifact를 새 schema로 덮어쓰거나 보정하지 않는다.

## 15. Synthetic Validation

capability/runtime 분리, issuance·consume lifecycle, strict serialization, checksum, legacy 차단, direct ancestry,
squash-equivalence, CLI·Manifest·Approval blob drift, missing surface와 governance reachability를 Synthetic fixture로
검증한다. 실제 Dataset·Approval artifact·RuntimeRequest는 사용하지 않는다.

## 16. Run 0007 결과와 후속 계약

```yaml
run_0007: retired_contract_mismatch_before_start
preflight_0007: not_started
approval_0007: not_created_non_reusable
```

[확정] Run 0007은 PreflightEvidence v2 계약 불일치를 실행 전에 발견해 evidence 0건으로 폐기했다. 후속
[Processing 계약 v2](./aihub-71748-processing-contract-v2.md)는 전체 lifecycle을 Synthetic E2E로 동결했다.
새 실제 Run은 이 계약이 develop에 병합된 뒤 새 immutable commit을 정하고 별도 metadata-only Preflight
승인을 받아야 한다. 이번 작업에서 ID를 registry active 상태로 예약하지 않는다.

## 17. Run 0008 Metadata-Only Preflight

[Run 0008 Preflight](./aihub-71748-processing-run-0008-preflight.md)는 동결된 v2 schema와 10-file execution surface를
사용해 `DIRECT_ANCESTRY_VALID`로 통과했다. 실제 Approval은 발급되지 않았으며 Approval v2 draft만
`prepared_not_issued`로 검증했다. Runtime request, capability, payload와 Processing은 모두 0건이다.

## 18. Current Status

```yaml
run_0006: retired_approval_contract_failure
approval_0006: retired_not_issued
approval_permission_model: separated
approval_schema: extended
preflight_governance_commit: supported
squash_merge_lineage: supported
run_0007: retired_contract_mismatch_before_start
approval_0007: not_created_non_reusable
run_0008: retired_backend_fingerprint_mismatch
approval_0008: retired_not_issued
runtime_execution_request_0008: not_created
run_0009: preflight_passed
approval_0009: issued_unconsumed
approval_refresh_0009: validated
runtime_execution_request_0009: not_created
processed_dataset: not_created
tokenization: not_approved
sft_backend: not_started
training: not_approved
execution_allowed: false
```

## 19. Next Approval

[확정] Run 0009 Live Refresh와 Approval 발급은 후속 승인으로 완료됐고 Approval은 issued·unconsumed다.
[승인 필요] [RuntimeExecutionRequest v1 계약](./aihub-71748-runtime-execution-request-v1.md)에 따른 실제 request
발급은 별도 승인 대상이다. 그 전에는 Approval 소비, runtime gate, payload 접근과 Processing을 수행하지 않는다.

## 20. Active Run refresh와 durable issuance

[확정] 신규 Run Preflight와 active Run Approval refresh는 별도 계약이다. refresh는 canonical registry의
`preflight_passed` 상태, 기존 evidence fingerprint, Approval 미발급·미소비, Runtime request 부재와 zero-call
상태를 검증한다. 현재 checkout은 governance commit과 일치해야 하며 과거 execution source와 10-file execution
surface가 blob·Manifest·Backend fingerprint 수준에서 동등해야 한다.

[확정] Approval issuance writer는 exclusive temp create, canonical UTF-8 bytes, flush, file fsync와 atomic
hard-link no-replace publish를 적용한다. `exists()` 확인 후 `os.replace()`하는 exclusive publish는 금지한다.
POSIX·Windows 모두 final이 이미 있거나 publish 순간 경쟁 final이 생성되면 기존 bytes를 유지한 채 실패하며,
동시 발급에서는 정확히 한 호출만 성공한다. hard-link 미지원·cross-filesystem은 fallback 없이 Fail Closed한다.
POSIX는 parent directory를 fsync하고 Windows는 file fsync + hard-link publish의 명시적 durability 경계를 사용한다.

[확정] publish 이전 실패는 final 0건과 temp 정리를 요구한다. publish 후 temp unlink·directory sync 실패는 성공으로
처리하지 않고 incomplete issuance로 분류한다. 이미 publish된 final을 삭제하지 않으며 동일 identity 재발급은
기존 final 존재로 차단하고 수동 조사 후 폐기 정책을 적용한다.

[확정] PR #64 보완 당시에는 실제 Approval 0008을 발급·소비하지 않았고 RuntimeExecutionRequest도 생성하지
않았다. 당시 상태는 `preflight_passed`와 `prepared_not_issued`였으며, 이후 아래 lineage decision에서 Run 0008과
Approval 0008을 폐기했다.

## Run 0008/0009 Lineage Decision

[확정] Run 0008은 execution source `e3809de60d579da8e425d6e619878d4fd4e62fba`와 current governance
`841123ea2f0d3f0fccb8cf456edaf8c9faa44014` 사이 backend fingerprint 불일치로 폐기했다. 보안 수정이 포함된
execution surface를 과거 identity에 소급하지 않으며 Approval 0008은 미발급 상태로 영구 비재사용한다.

[확정] Run 0009는 current governance commit을 새 execution source로 사용해 `DIRECT_ANCESTRY_VALID`를 통과했다.
Preflight 뒤 후속 Live Refresh와 Approval 발급이 완료됐다. Approval artifact는 issued·unconsumed이며
RuntimeExecutionRequest·Processing은 생성하거나 실행하지 않았다.

## Issued Approval retirement

[확정] issued·미소비 Approval은 [Retirement Contract](./aihub-71748-approval-retirement-contract.md)의
`retire_approval_file(...)`을 통해서만 폐기한다. ApprovalRecord v2는 status와 checksum만 전환하고 retirement
timestamp·reason·전후 hash는 별도 canonical evidence로 보존한다. Retirement, consume, finalize와 Runtime request
publish는 동일 Approval lifecycle lock을 사용한다. 실제 Approval 0009 retirement는 아직 실행하지 않았다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-30 | issued·미소비 Approval public retirement service·evidence·lifecycle lock 계약 연결 |
| 2026-07-30 | RuntimeExecutionRequest v1 공식 writer 계보와 Approval 0009 issued·unconsumed 상태 반영 |
| 2026-07-30 | Run 0008 backend fingerprint mismatch 폐기와 Run 0009 신규 immutable lineage 연결 |
| 2026-07-30 | Approval publish를 POSIX·Windows hard-link atomic no-replace로 전환하고 경쟁 final·incomplete 재사용 차단 계약 확정 |
| 2026-07-30 | Active Run Approval refresh 계보와 durable atomic issuance writer 계약 추가(Synthetic only) |
| 2026-07-30 | Run 0008 metadata-only Preflight 통과와 Approval v2 prepared-not-issued draft 연결 |
| 2026-07-30 | Run 0007 시작 전 계약 불일치 폐기와 Processing 계약 v2 Synthetic E2E 연결 |
| 2026-07-30 | Run 0006 폐기, Approval capability/runtime gate·schema·squash lineage 계약 구현 및 Synthetic 검증 |
