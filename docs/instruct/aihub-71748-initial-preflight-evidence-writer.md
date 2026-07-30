# AIHUB-71748 Initial Preflight Evidence Writer

- 문서 상태: `implemented_synthetic_validated`
- 적용 계약: [Processing 실행 계약 v2](./aihub-71748-processing-contract-v2.md)
- 범위: Initial Preflight Evidence v2의 저장과 재검증
- 실행 권한: `false`

## 목적과 범위

공식 Initial Preflight CLI가 생성한 기존 `PreflightEvidence` schema v2 결과를
`runtime-evidence/<run-id>/preflight-evidence.json`에 한 번만 게시한다. schema, fingerprint,
freshness, registry, output, zero-call 계약은 변경하지 않는다. writer는 Dataset payload, ZIP entry,
record parser, Processing, Approval issue·consume 또는 RuntimeExecutionRequest를 호출하지 않는다.

## Atomic no-replace 계약

writer는 embedded evidence와 Approval draft를 검증하고 canonical UTF-8 JSON을 같은 디렉터리의 exclusive
temporary file에 기록한다. short write 검사, flush, file fsync 뒤 hard-link no-replace로 final을 게시하고
temporary link를 제거한다. POSIX에서는 parent directory도 fsync한다. Windows에서는 표준 Python API의 directory
handle 제약을 명시적으로 인정하고 file fsync, atomic hard-link publish, temp unlink를 보장한다.

기존 final, publish 중 경쟁 final, temp 충돌은 덮어쓰지 않는다. hard-link no-replace를 보장하지 못하는 filesystem은
fallback 없이 Fail Closed한다. publish 이후 temp 정리나 directory sync가 실패하면 final을 삭제하지 않고 incomplete로
보고하며, 남은 final 또는 runtime artifact가 같은 Run identity 재사용을 차단한다.

## Parent와 identity

빈 `runtime-evidence/<run-id>/` 디렉터리만 존재하는 것은 Run 사용 증거가 아니다. 그 디렉터리에 canonical evidence나
다른 runtime artifact가 하나라도 존재하면 `RUN_ID_ALREADY_USED`다. Processing final·staging·failed·quarantine 및
Approval artifact의 기존 차단 규칙은 그대로 유지한다. CLI의 `--output-evidence`는 resolved processed root 아래의
canonical 경로와 정확히 일치해야 한다.

## CLI 순서

```text
identity → Git lineage → source metadata → unused registry → manifest/output
→ parent probe → resource → evidence/draft validation → atomic publish → reload validation
```

저장 후 canonical file bytes의 SHA-256과 evidence fingerprint를 다시 확인한다. CLI 실패 시 자동 retry하지 않는다.

## Synthetic 검증 범위

- 정상 canonical 저장과 reload
- 기존 final·경쟁 final 보존
- 동시 publisher 1개만 성공
- parent 생성, temp, short write, flush, fsync, publish, directory sync 실패
- unsupported filesystem fallback 금지
- 빈 evidence parent 허용과 artifact 존재 시 identity 차단

Synthetic 테스트는 실제 Run 완료가 아니며 실제 processed root나 Run 0010 identity를 사용하지 않는다.

## Run 0010 구현 병합 전 상태

```yaml
run_0010: not_created
initial_evidence_0010: absent
approval_0010: not_created
approval_refresh_0010: not_executed
runtime_request_0010: absent
processing: not_started
execution_allowed: false
```
