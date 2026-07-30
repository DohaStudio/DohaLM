# AIHUB-71748 RuntimeExecutionRequest v1 계약

- 문서 상태: `implemented`
- 마지막 검토일: 2026-07-30
- 적용 범위: AIHUB-71748 SFT Dataset Processing
- 관련 계약: [Processing 실행 계약 v2](./aihub-71748-processing-contract-v2.md), [Approval Lineage 계약](./aihub-71748-approval-lineage-contract.md)

## 결정

[확정] 기존 `RuntimeExecutionRequest` schema version 1을 유지한다. 새 필드를 임의로 추가하지 않는다.

- `preflight_evidence_fingerprint`는 Approval 발급에 사용된 최신 Approval Refresh evidence를 가리킨다.
- Initial Preflight fingerprint는 Refresh evidence의 `previous_preflight_evidence_fingerprint`를 통해 연결한다.
- `requested_at`은 request 발급 시각이며 `issued_at`과 같은 의미다.
- Approval에 checksum으로 묶인 runtime·memory·disk·record·output budget을 request가 다시 복제하지 않는다.
- `request_fingerprint`는 request의 안정 identity fingerprint이자 canonical payload integrity checksum이다.

이 매핑으로 v1은 Initial → Refresh → Approval → Request 계보와 예산을 손실 없이 검증한다. v2 migration은
필요하지 않으며 기존 consume validator도 변경하지 않는다.

## Schema와 생명주기

필수 필드는 `schema_version`, `request_id`, `run_id`, `approval_id`, `approval_fingerprint`,
`preflight_evidence_fingerprint`, 두 Git commit, manifest/backend fingerprint, 두 one-shot limit,
`requested_by`, `requested_at`, `expires_at`, `nonce`, `request_fingerprint`다.

request만 `execution_allowed=true`를 가진다. Approval artifact는 계속 `execution_allowed=false`이며 request 발급은
Approval을 소비하지 않는다. immutable request 본문을 바꾸어 consumed 상태를 표현하지 않고, 후속 consume 경로가
Approval lifecycle과 사용된 request fingerprint registry를 별도로 기록한다.

```text
issued Approval + immutable evidence + clean governance checkout
  -> RuntimeExecutionRequest issued
  -> 별도 승인 전까지 unconsumed / runtime gate inactive
  -> 후속 consume 시 one-shot registry에 fingerprint 기록
```

## 발급 서비스와 artifact

공식 entry point는 `issue_runtime_execution_request(...)`다. 직접 dataclass 생성과 직접 파일 쓰기는 공식 발급이
아니다. 서비스는 issued·unconsumed·execution-false Approval, checksum, stable fingerprint, Initial/Refresh chain,
Git lineage, manifest/backend identity, output collision과 기존 request identity를 모두 검증한 뒤에만 발급한다.

canonical 경로는 다음과 같다.

```text
<processed_root>/runtime-evidence/<approval_id>/runtime-execution-request.json
```

writer는 canonical UTF-8 JSON, exclusive temp create, short-write 검사, flush, file fsync, atomic hard-link
no-replace publish를 사용한다. POSIX는 parent directory fsync를 요구한다. Windows는 Python 표준 API에 동일한
directory handle fsync가 없어 file fsync와 no-replace publish를 명시적 durability 경계로 사용한다. 기존 final,
temp collision, unsupported filesystem, publish 또는 sync 실패는 모두 Fail Closed이며 overwrite fallback은 없다.

## Freshness, nonce, one-shot

- request 유효기간은 정확히 1시간이다.
- timezone-aware 시각만 허용하고 미래 발급 시각, 만료 artifact를 차단한다.
- production 발급 시각은 시스템 UTC에서만 얻는다. `now` 주입은 합성 계약에서만 허용해 미래 시각 권한 생성을 막는다.
- 과거 Initial/Refresh evidence는 immutable 계보와 당시 freshness 계약을 검증한다. request 발급 시 Refresh가 다시
  live여야 한다고 요구하지 않는다. Refresh freshness는 Approval 발급 시 소비됐고 request가 새로운 1시간 창을 만든다.
- nonce는 `secrets.token_urlsafe(32)`로 생성하며 URL-safe 43자 이상을 요구한다.
- nonce, request ID와 request fingerprint 재사용을 차단한다.
- 한 Approval에는 canonical request artifact 하나만 허용한다.

## CLI

공식 CLI는 `scripts/datasets/create_aihub_71748_sft_runtime_request.py`다. `--runtime-request-only`는 필수이며
Approval consume, runtime gate 활성화, payload read, Processing을 호출하지 않는다. 입력 경로는 로컬 mapping으로
결정하며 절대경로를 코드에 저장하지 않는다.

CLI 성공 직후 counter 계약은 다음과 같다.

```yaml
runtime_request_creations: 1
runtime_execution_gate_activations: 0
approval_consume_calls: 0
processing_engine_calls: 0
payload_sessions: 0
output_writes: 0
execution_allowed: false
```

## 주요 Fail Closed 코드

`RUNTIME_REQUEST_SCHEMA_INVALID`, `RUNTIME_REQUEST_ID_ALREADY_USED`, `RUNTIME_REQUEST_ALREADY_EXISTS`,
`RUNTIME_REQUEST_TEMPORARY_COLLISION`, `RUNTIME_REQUEST_ATOMIC_WRITE_FAILED`,
`RUNTIME_REQUEST_DIRECTORY_SYNC_FAILED`, `RUNTIME_REQUEST_NO_REPLACE_UNSUPPORTED`,
`RUNTIME_REQUEST_APPROVAL_NOT_ISSUED`, `RUNTIME_REQUEST_APPROVAL_ALREADY_CONSUMED`,
`RUNTIME_REQUEST_APPROVAL_FINGERPRINT_MISMATCH`, `RUNTIME_REQUEST_PREFLIGHT_FINGERPRINT_MISMATCH`,
`RUNTIME_REQUEST_REFRESH_FINGERPRINT_MISMATCH`, `RUNTIME_REQUEST_GIT_LINEAGE_MISMATCH`,
`RUNTIME_REQUEST_STALE`, `RUNTIME_REQUEST_NONCE_INVALID`, `RUNTIME_REQUEST_NONCE_REUSED`를 구분한다.

## Run 0009 안전 상태

[확정] 실제 RuntimeExecutionRequest 0009는 생성하지 않았다. Approval 0009는 공식 retirement service로
`retired_before_consumption` 전환되어 이후 request 발급 대상이 아니다. Initial/Refresh evidence는 변경하지 않았다.

```yaml
approval_0009:
  status: retired_before_consumption
  consumed: false
  execution_allowed: false
runtime_execution_request_0009: not_created
runtime_request_creations: 0
runtime_gate_activations: 0
payload_reads: 0
processing_calls: 0
output_writes: 0
execution_allowed: false
```

[승인 필요] 실제 request가 필요하면 Run 0010 Metadata-Only Preflight부터 새 lineage와 Approval을 구성해야 한다.
폐기된 Run 0009·Approval 0009로 실행을 우회하지 않는다.

## Retirement와 상호 배제

[확정] RuntimeExecutionRequest publish는 Approval lifecycle lock 안에서 Approval이 여전히 issued인지 다시 검증한다.
Retirement service도 같은 lock을 사용하고 기존 request artifact가 있으면 폐기를 거부한다. 따라서 request 발급과
retirement가 동시에 성공할 수 없다. 실제 RuntimeExecutionRequest 0009는 여전히 생성되지 않았다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-30 | Approval 0009 retirement 완료와 RuntimeExecutionRequest 0009 영구 차단 상태 반영 |
| 2026-07-30 | Approval retirement와 RuntimeExecutionRequest publish의 lifecycle lock 상호 배제 추가 |
| 2026-07-30 | v1 의미 매핑, 공식 발급 서비스·atomic no-replace writer·CLI·합성 검증 계약 구현 |
