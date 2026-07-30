# AIHUB-71748 Approval Refresh Evidence Writer

- 문서 상태: `implemented_synthetic_validated`
- 적용 계약: [Processing 실행 계약 v2](./aihub-71748-processing-contract-v2.md)
- schema: `ApprovalRefreshEvidence v1` 유지
- 실행 권한: `false`

## 목적과 범위

공식 Approval Refresh CLI가 검증한 결과를
`runtime-evidence/<run-id>/approval-refresh-evidence.json`에 한 번만 게시한다. validation phase,
fingerprint, exact field set, 1시간 freshness, registry/runtime/output/resource와 이전 Initial Evidence fingerprint
계약은 변경하지 않는다. writer와 CLI는 Approval issue·consume, RuntimeExecutionRequest, Dataset payload 및
Processing을 호출하지 않는다.

## Atomic no-replace 계약

public writer는 embedded `ApprovalRefreshEvidence`와 Approval draft를 검증하고 canonical UTF-8 JSON을 같은
디렉터리의 exclusive temporary file에 기록한다. short write, flush와 file fsync 후 hard-link atomic no-replace로
final을 게시하고 temporary link를 제거한다. POSIX에서는 parent directory도 fsync한다. Windows에서는 표준 Python
API의 directory handle 제약을 명시하고 file fsync, atomic hard-link publish와 temp unlink를 보장한다.

기존 final과 경쟁 final을 덮어쓰지 않으며 동시 publisher 중 하나만 성공한다. foreign temp는 삭제하지 않는다.
hard-link no-replace가 불가능한 filesystem에서는 fallback 없이 Fail Closed한다. publish 이후 temp 정리,
directory sync 또는 reload 검증이 실패하면 final을 삭제하지 않고 incomplete로 보고하며 같은 canonical 경로의
재게시를 차단한다.

## Canonical CLI 경로

`--output-evidence`는 resolved processed root 아래의 canonical Refresh Evidence 경로와 정확히 일치해야 한다.
Initial Evidence, Approval artifact 또는 임의 경로는 `APPROVAL_REFRESH_EVIDENCE_PATH_INVALID`로 차단한다.
저장 후 canonical bytes의 SHA-256, exact field set, evidence fingerprint와 Approval draft를 reload해 재검증한다.

## Synthetic 검증 범위

- 정상 저장·reload와 temp residue 0
- existing·competing final 보존 및 concurrent 단일 성공
- parent, temp, short write, flush, file fsync, publish, directory sync와 reload 실패
- unsupported filesystem fallback 금지
- fingerprint 및 canonical path 불일치 차단

Synthetic fixture와 repository 외부 임시 경로만 사용하며 실제 Run identity나 processed root에 artifact를 만들지 않는다.

## 구현 병합 전 runtime 상태

```yaml
run_0010: preflight_passed
approval_0010: prepared_not_issued
approval_refresh_0010: not_created
run_0011: not_created
approval_0011: not_created
runtime_request: absent
processing: not_started
execution_allowed: false
```
