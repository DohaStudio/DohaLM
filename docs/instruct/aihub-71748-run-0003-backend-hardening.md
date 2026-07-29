# AIHUB-71748 Processing Run 0003 Backend 계약 보완

- 문서 상태: `review`
- 마지막 검토일: 2026-07-29
- 작업 유형: `code`, `test`, `documentation`
- 실제 Dataset payload 접근: `0`
- 실제 Processing 호출: `0`
- 실제 Approval 발급·소비: `0`
- `execution_allowed`: `false`
- 관련 문서: [Run 0002 Preflight](./aihub-71748-processing-run-0002-preflight.md), [실제 Processing Backend](./aihub-71748-real-processing-backend.md), [Processing Manifest](./aihub-71748-processing-manifest.md)

## 1. Run 0002 Fail Closed

`AIHUB-71748-SFT-PROCESSING-20260729-0002`는 `retired_failed_closed_before_consumption`으로
영구 보존한다. Approval 0002는 발급·소비되지 않았고 `retired_not_issued`이다. Processing 호출,
payload read, output write는 모두 0이며 두 ID는 재사용할 수 없다.

## 2. 발견된 Backend 결함

Run 0002에서 확인된 결함은 과거 immutable commit 하드코딩, 불완전한 Approval identity와 timestamp,
Processing 호출과 payload session 구분 부재, 실제 RSS·disk·output budget 측정 부재, 상세 통계와
post-write 검증 부족이었다. 이번 변경은 이 계약을 구현하고 synthetic fixture로만 검증한다.

## 3. Immutable Commit 계약

실행 기준 commit은 CLI `--immutable-commit` 또는 Approval의 `immutable_git_commit`으로 명시해야 한다.
현재 HEAD 자동 승격은 금지한다. exact HEAD, clean worktree, develop ancestry를 검증하며 누락·불일치는
`IMMUTABLE_COMMIT_REQUIRED`, `IMMUTABLE_SOURCE_COMMIT_MISMATCH`, `WORKTREE_NOT_CLEAN`,
`SOURCE_COMMIT_NOT_REACHABLE`로 Fail Closed한다.

Manifest는 immutable Git blob SHA-256으로 검증한다. Backend fingerprint는 고정 상대경로 목록을
정렬하고 각 Git blob SHA-256을 canonical aggregate한 값이다. 개별 hash 목록은 Approval이나 결과에
저장하지 않는다.

## 4. Approval Schema

Approval은 Dataset·Component, Run ID, immutable commit, Manifest version·SHA-256, Backend fingerprint,
Preflight evidence fingerprint, 승인자와 timezone-aware 시각, 단일 실행 상한, runtime·memory·disk·record·
output budget, 모든 권한을 포함한다. Tokenization, SFT Backend와 Training은 항상 `false`다.

## 5. Approval Lifecycle

허용 전이는 다음과 같다.

```text
prepared_not_issued -> issued -> consumed -> completed | failed
prepared_not_issued -> retired
issued -> retired_before_consumption
```

terminal 상태나 retired Approval은 재발급·재소비할 수 없다. 시각은 timezone-aware ISO-8601이며
`approved_at <= issued_at <= consumed_at <= completed_at|failed_at` 순서를 강제한다.

## 6. Preflight Evidence Fingerprint

Run·Approval ID, immutable commit, Manifest·Backend fingerprint, mapping identity, source ZIP count·총 byte,
output·staging·quarantine 상태, free disk, 모든 budget과 `generated_at`을 canonical JSON으로 직렬화해
SHA-256을 만든다. fingerprint 불일치, 30분 초과 stale evidence, output 충돌, source metadata 변경은
Approval 이전에 차단한다.

## 7. Processing Call Counter

Processing Engine 진입 직전에 `processing_calls`를 증가시키며 maximum은 1이다. 두 번째 진입은
`PROCESSING_CALL_LIMIT_EXCEEDED`로 중단한다. Approval 소비 후 진입 실패도 사용 사실을 숨기지 않는다.

## 8. Payload Session Counter

하나의 Processing Engine 호출 안에서 모든 archive stream을 감싸는 전체 reader context를 하나의
payload session으로 센다. maximum은 1이며 중첩, 두 번째 open, 미종료를 각각 Fail Closed한다.
개별 ZIP 수를 session 수로 집계하지 않는다.

## 9. Memory Guardrail

RSS는 `psutil`을 우선 사용하고 OS API를 fallback으로 사용한다. 측정 불가 시 Fail Closed한다.
soft limit은 1,536 MiB, hard limit은 2,048 MiB다. current·peak RSS와 soft trigger를 aggregate로
기록하며 hard 초과 시 finalization을 금지한다.

## 10. Runtime Guardrail

`time.monotonic()` elapsed time을 major phase와 output write 중에 측정한다. soft limit은 1,200초,
hard limit은 1,800초다. soft 초과는 상태에 기록하고 hard 초과는 즉시 Fail Closed한다.

## 11. Disk Guardrail

실행 전과 write·checksum·finalization phase에서 free disk를 재측정한다. minimum free 4 GiB,
staging multiplier 2, safety margin ratio 0.25를 적용한다. 측정 실패, 시작 전 부족, write 중 부족을
구분해 차단한다. provider 주입으로 synthetic 검증할 수 있다.

## 12. Output Budget

허용 파일은 `train.jsonl`, `validation.jsonl`, `manifest.yaml`, `statistics.json`, `checksums.sha256`,
`processing-result.yaml` 여섯 개뿐이다. symlink, 임시·숨김·추가 파일을 금지하며 최대 파일 수 6,
최대 총 byte 536,870,912를 write 중·checksum 후·rename 전후에 검증한다.

## 13. Detailed Statistics

통계는 run, input, source, join, schema, pii, exact duplicate, near duplicate, leakage, actions, output,
runtime, validation aggregate를 포함한다. input split 합계, output split 합계, action 총합, 제외 합계가
서로 일치해야 하며 `unresolved`는 0이어야 한다. record ID·text·pair·개별 hash는 저장하지 않는다.

## 14. JSONL Post-validation

write 후 별도 streaming reader로 두 JSONL 전체를 UTF-8로 읽는다. 각 line은 정확히 `instruction`,
`input`, `output`, `system` 네 field를 가지며 instruction·output은 non-empty string이어야 한다.
추가 field, malformed JSON, type·count 불일치를 차단한다.

## 15. Split Validation

Training과 Validation은 별도 파일이어야 하며 통계 count와 일치해야 한다. 운영 실행에서는 Training
최소 10,000, Validation 최소 1,000을 요구한다. cross-split exact QA와 normalized QA는 0이어야 하며
pair 목록은 저장하지 않는다.

## 16. Checksum Revalidation

`checksums.sha256`은 나머지 다섯 output의 canonical 상대경로와 SHA-256만 포함한다. 생성 후 별도
함수로 다시 계산하며 누락·추가·중복·내부경로·비정상 digest와 file tamper를 차단한다.

## 17. Source Immutability

처리 전후 ZIP count, 총 byte, 상대 파일명 aggregate, 수정시각 aggregate를 metadata-only로 비교한다.
파일 추가·삭제·metadata 변경은 각각 Fail Closed한다. payload checksum 재계산이나 ZIP entry open은
이 검사에 포함하지 않는다.

## 18. Atomic Finalization Gate

Approval 소비, Processing call 1, payload session 1·종료, 통계·record·exclusion·JSONL·split·checksum·
source·disk·output 검증, hard limit 미초과, unresolved·malformed·join failure 0이 모두 참일 때만 staging을
final root로 atomic rename한다. 하나라도 실패하면 final root를 만들지 않고 partial output을 폐기한다.

## 19. Synthetic Validation

실제 Dataset 문장을 사용하지 않는 synthetic ZIP fixture로 reader, join, rule, writer, post-validation,
checksum, source snapshot과 Approval lifecycle의 성공 흐름을 검증했다. 또한 identity·fingerprint·timestamp·
counter·memory·runtime·disk·output·statistics·JSONL·split·checksum·source·final gate 실패를 검증했다.

## 20. Run 0003 Readiness

```yaml
run_id: AIHUB-71748-SFT-PROCESSING-20260729-0003
approval_id: AIHUB-71748-SFT-PROCESSING-APPROVAL-20260729-0003
backend_hardening: implemented
synthetic_end_to_end: passed
preflight: not_preflighted
approval: not_prepared
processing_allowed: false
```

Run 0003은 이번 작업에서 registry에 예약하거나 Approval을 만들지 않는다.

## 21. Current Status

```yaml
run_0001: retired
run_0002: retired_failed_closed_before_consumption
backend_hardening: implemented
approval_contract: implemented
runtime_guardrails: implemented
post_validation: implemented
synthetic_end_to_end: passed
run_0003: not_preflighted
processed_dataset: not_created
tokenization: not_approved
sft_backend: not_started
training: not_approved
execution_allowed: false
```

## 22. Next Approval

다음 작업은 병합된 immutable commit을 명시한 Run 0003 metadata-only Preflight다. 해당 별도 승인이
있기 전까지 실제 ZIP entry·payload·JSON record를 읽거나 Approval 0003을 준비·발급·소비하거나
Processing·Tokenization·SFT Training을 실행하지 않는다.
