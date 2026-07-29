# AIHUB-71748 Processing Run 0004 Metadata-Only Preflight

## 문서 정보

- 문서 상태: `review`
- 마지막 검토일: 2026-07-29
- 실행 범위: filesystem metadata-only
- 실제 Processing: `0`
- `execution_allowed`: `false`
- 관련 문서: [Run 0003 Backend 계약](./aihub-71748-run-0003-backend-hardening.md), [실제 Processing Backend](./aihub-71748-real-processing-backend.md), [Processing Manifest](./aihub-71748-processing-manifest.md)

## 1. Scope

[확정] Run 0004는 ZIP 파일명과 파일시스템 metadata만 검사했다. ZIP entry 열람, archive member
열거, JSON·record parse, Processing, output 생성, Approval 발급·소비는 수행하지 않았다.

## 2. Run 0001·0002·0003 Retirement

Run 0001은 `retired`, Run 0002는 `retired_failed_closed_before_consumption`, Run 0003은
`retired_failed_closed_before_approval`이다. Approval 0003은 `retired_not_issued`이며 모두 재사용할
수 없다.

## 3. Run 0004 ID

`AIHUB-71748-SFT-PROCESSING-20260729-0004`

## 4. Approval 0004 ID

`AIHUB-71748-SFT-PROCESSING-APPROVAL-20260729-0004`

## 5. Immutable Commit

`5a6a35fd3e8564ffa8fb1c2ef0d8008befd06541`

Feature branch는 위 commit tree에서 생성됐고 metadata-only 실행 시 HEAD 일치, clean worktree,
`origin/develop` 도달 가능성을 검증했다.

## 6. Registry Evidence Classification

문서 선언, 코드 상수, schema 예시, fixture와 CLI help는 사용 evidence에서 제외한다. canonical
registry의 reserved 이상 상태, runtime·failed·completed·consumed evidence와 final·staging·quarantine
artifact만 실제 사용 evidence로 판정한다.

## 7. Run ID Reuse Check

Run 0004의 retired·reserved·runtime·failed·completed·output evidence는 발견되지 않았다. 결과는
`unused`이며 선언 문자열로 인한 오탐은 발생하지 않았다.

## 8. Approval ID Reuse Check

Approval 0004의 issued·consumed·completed·failed·retired·runtime evidence는 발견되지 않았다. 결과는
`unused`다.

## 9. Mapping Validation

ignored local mapping은 `AIHUB-71748`, `SFT`, `external`, `repository_internal: false`,
`read_only: true` 계약과 일치했다. CLI의 resolution source는 `local_config`였고 실제 절대경로는
Git과 이 문서에 기록하지 않았다.

## 10. Source Metadata Snapshot

```yaml
zip_count: 55
total_bytes: 17256335769
filename_aggregate: 7083a10fd74f0826aab9a44cf341777f11413dcf8d3c43e8c72d08a8876b1ec4
modified_time_aggregate: b887a9d5c1b67f7db3d62c8d57a5360c0f964c0a4c87c7e926d4a11f9a9453b5
payload_reads: 0
```

Aggregate는 정렬된 상대 논리 이름과 UTC microsecond 수정시각으로 각각 계산했다. 개별 파일 목록과
payload content는 포함하지 않았다.

## 11. Manifest Fingerprint

immutable Git blob SHA-256은
`ca1f99996a459b0f6aa241ee20e2839645fea9a73cf40163169ab3fd9fbf3973`이다.

## 12. Backend Fingerprint

8개 canonical backend Git blob aggregate SHA-256은
`71b9c800d228c5bd93a8bc8fb78930b04b2e3885090c14e259566a56b282ddc1`이다.

## 13. Preflight Evidence Fingerprint

Canonical JSON evidence 생성 시각은 `2026-07-29T02:58:08.720876+00:00`이며 SHA-256은
`aae1d1d294c4db496d4ed9ccdafd4f769c2e40538b50641955b80c6bec3c295b`이다.

## 14. Output Path State

논리 final, staging, quarantine root는 모두 `absent`였다. raw root와 분리되고 repository 외부이며
기존 Run artifact 충돌은 없었다. 실제 Run 디렉터리는 생성하지 않았다.

## 15. Parent Write Probe

Processed parent에서 create, minimal write, flush, fsync, close, delete를 완료했다. 결과는 `passed`,
잔여 파일은 `0`이다. probe 이름과 경로는 기록하지 않는다.

## 16. Disk Budget

검사 시 free disk는 `1532120518656` bytes였다. 최소 4 GiB, staging multiplier 2,
safety margin 0.25와 최대 output 512 MiB 계약을 충족했다.

## 17. Memory Provider

psutil 또는 Windows fallback 계약을 검증했고 provider는 사용 가능했다. 검사 시 RSS는
`25497600` bytes였다. soft 1536 MiB, hard 2048 MiB 계약은 유지한다.

## 18. Runtime Provider

monotonic clock, phase 기록과 hard-stop provider를 초기화했다. soft 1200초, hard 1800초이며
이번 metadata-only 검사는 Processing peak runtime 측정이 아니다.

## 19. Record Budget

Manifest와 Approval 초안은 Training 10,580, Validation 1,322, total/max 11,902로 일치했다.
payload를 열지 않았으므로 record 수를 재계산하지 않았다.

## 20. Output Budget

Allowlist는 `train.jsonl`, `validation.jsonl`, `manifest.yaml`, `statistics.json`,
`checksums.sha256`, `processing-result.yaml`의 6개이며 최대 536,870,912 bytes다. 실제 output은
생성하지 않았다.

## 21. Approval Draft

Approval 0004 초안 schema와 fingerprint
`92045006d7ac08adc415456326dc4da3f82c1aa242975467a0d78286fb6bd62b`를 검증했다. 상태는
`prepared_not_issued`이고 processing·payload read·output write·tokenization·SFT backend·training
권한은 모두 `false`다. 실제 Approval artifact는 생성하지 않았다.

## 22. Freshness Contract

Evidence의 최대 유효시간은 3,600초다. 문서 병합 후 stale이 되는 것은 허용하지만 실제 Approval 발급
시 immutable commit, fingerprint, source snapshot, output state, registry, disk와 mapping을 live로 다시
검증해야 한다. 이 문서만으로 실행을 승인할 수 없다.

## 23. Zero-Call Guard

```yaml
processing_engine_calls: 0
payload_sessions: 0
zip_entry_opens: 0
json_parser_calls: 0
record_parser_calls: 0
join_calls: 0
policy_dispatch_calls: 0
output_writer_calls: 0
atomic_finalization_calls: 0
approval_issue_calls: 0
approval_consume_calls: 0
```

CLI 경로와 synthetic monkeypatch 검증은 preflight가 Processing 경로로 진입하지 않음을 확인한다.

## 24. Preflight Result

Run 0004 metadata-only Preflight는 `preflight_passed`다. source ZIP 55개와 총 byte, registry,
mapping, immutable fingerprint, output collision, parent probe와 resource 계약이 일치했다.

## 25. Current Status

```yaml
run_0004: preflight_passed
approval_0004: prepared_not_issued
processed_dataset: not_created
tokenization: not_approved
sft_backend: not_started
training: not_approved
execution_allowed: false
```

## 26. Next Required Approval

Approval 0004의 별도 실제 발급과 single-use Processing 실행은 새 live freshness 검증과 사용자의 명시적
승인이 필요하다. 승인 전에는 payload·Processing·output을 사용하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-29 | Run 0004 metadata-only Preflight, canonical evidence와 non-issued Approval 초안 기록 |
