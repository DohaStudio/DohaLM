# DohaLM v0.3 Tokenization publish 실패 보존 계약

- 문서 상태: `review`
- 최종 검토일: 2026-08-05
- 학습 상태: `not_started`
- 실행 권한: `false`

## 범위

이 문서는 `DOHALM-V0.3-TOKENIZATION-20260802-0001`에서 확인된 publish-stage 관측성
손실과 후속 fail-closed 계약을 정의한다. Tokenization 포맷, Dataset, Tokenizer,
max sequence length, Sampler 정책은 변경하지 않는다.

## 확인된 원인과 미확정 범위

기존 wrapper는 전체 작업에 600초 timeout을 적용했으나 worker는 종료되지 않고 약 15분간
계속 실행됐다. wrapper가 먼저 종료되어 worker의 마지막 publish 예외와 exit code가 보존되지
않았다. 따라서 확인된 장애 분류는 `WRAPPER_TIMEOUT_OBSERVABILITY_LOSS`이다.

동일 output parent에서 수행한 read-only filesystem 조사와 별도 synthetic probe로 다음 원인은
배제했다.

- cross-device atomic publish
- no-replace rename 미지원
- directory fsync 미지원
- output parent 권한 부족
- disk 또는 inode 부족

기존 실행의 내부 publish 예외는 기록이 없어 `UNRESOLVED`로 유지한다. 추정으로 세부 원인을
확정하지 않는다.

2026-08-05 읽기 전용 재검증에서는 Git 외부 tokenization parent만 존재하고 기존 Run ID의 final,
명시적·hidden staging, `.failed`, identity와 emergency artifact는 확인되지 않았다. Dataset package checksum은
유효하지만 tokenization checksum inventory·manifest·output fingerprint는 없다. 따라서 기존 메모리 내 결과나
임시 파일을 복구하는 경로는 사용할 수 없다.

원인 분류는 다음처럼 분리한다.

- 외부 장애: `environment failure` — wrapper timeout과 관측성 손실
- 내부 publish root cause: `unknown`
- 복구 blocker: `incomplete evidence`

Approval·Runtime request 발급·소비는 당시 v0.3 Tokenization entrypoint에 연결되지 않아 상태를 증명할 artifact가
없다. config의 `tokenization_allowed: true`는 single-use 실행 승인 evidence를 대신하지 않는다.

## Worker와 supervisor

전체 Tokenization에는 고정 overall timeout을 두지 않는다. worker는 atomic
`stage-state.json`을 갱신하고 supervisor는 heartbeat와 publish 단계만 감시한다.

```yaml
worker_heartbeat_timeout_seconds: 600
publish_stage_timeout_seconds: 300
failure_publish_timeout_seconds: 300
```

`stage-state.json`에는 Run ID, PID, 단계, 상태, 처리 레코드 수, 작성 파일 수와 시각만
기록한다. 원문, token sequence, label 배열은 기록하지 않는다. stdout/stderr는 pipe가 아닌
worker 전용 파일로 수집하여 wrapper 종료나 pipe close가 worker를 고립시키지 않게 한다.

## Publish 단계와 오류 코드

| 단계 | 오류 코드 |
|---|---|
| staging 생성 | `TOKENIZATION_STAGING_CREATE_FAILED` |
| artifact 작성 | `TOKENIZATION_ARTIFACT_WRITE_FAILED` |
| file fsync | `TOKENIZATION_FILE_FSYNC_FAILED` |
| checksum inventory | `TOKENIZATION_CHECKSUM_FAILED` |
| staging reload | `TOKENIZATION_STAGING_RELOAD_FAILED` |
| final collision | `TOKENIZATION_FINAL_COLLISION` |
| atomic no-replace | `TOKENIZATION_ATOMIC_PUBLISH_FAILED` |
| parent directory fsync | `TOKENIZATION_DIRECTORY_FSYNC_FAILED` |
| final reload | `TOKENIZATION_FINAL_RELOAD_FAILED` |
| final checksum | `TOKENIZATION_FINAL_CHECKSUM_FAILED` |
| staging cleanup | `TOKENIZATION_STAGING_CLEANUP_FAILED` |

일반 오류 하나로 합치지 않으며 성공 final은 reload와 checksum 검증 후에만 성공으로 보고한다.

## Terminal failure artifact

실패 시 성공 final과 동시에 존재할 수 없는
`DOHALM-V0.3-TOKENIZATION-20260802-0001.failed`를 atomic no-replace로 게시한다.

- `stage-state.json`
- `failure-result.yaml`
- `environment.json`
- `artifact-inventory.json`
- `checksums.sha256`

inventory는 부분 파일의 상대경로, 크기, SHA-256만 포함한다. Arrow 내용과 token sequence는
복사하지 않는다. failure 게시 자체가 실패하거나 timeout되면 별도 emergency record를 남기고
성공으로 보고하지 않는다.

## Run identity 정책

final, staging, failed가 모두 없다는 사실만으로 Run ID를 재사용할 수 없다. 이전 publish 시도가
관측되었으면 `previous_publish_attempt_recorded: true`이며 `identity_reusable: false`이다.
새 Run ID는 자동 생성하지 않고 별도 사용자 승인을 받는다.

## 안전 상태

```yaml
tokenization_retry: not_executed
sampler_simulation: blocked_until_verified_tokenization
qlora_training: not_approved
training_started: false
backward_calls: 0
optimizer_steps: 0
execution_allowed: false
```

후속 코드 변경의 충분성, 재개 경로와 새 identity Gate는
[v0.3 학습 재개 Readiness](./dohalm-v0.3-training-readiness.md)를 따른다.
새 identity·Approval·Runtime request·worker lifecycle과 publish eligibility marker 계약은
[V03-1·V03-2 Recovery Contract](./dohalm-v0.3-recovery-contract.md)를 따른다. 이 후속 설계는 기존 내부 실패 원인을
해결했다고 소급 판정하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | 새 canonical execution의 Recovery Contract를 연결하고 기존 내부 원인 `unknown` 보존 |
| 2026-08-05 | Dataset checksum은 유효하지만 tokenization final·staging·failed가 모두 없음을 재검증하고 원인을 environment/unknown/incomplete evidence로 분리 |
