# AIHUB-71748 SFT Processing Run 0002 Preflight

## 1. 상태

```yaml
run_id: AIHUB-71748-SFT-PROCESSING-20260729-0002
approval_id: AIHUB-71748-SFT-PROCESSING-APPROVAL-20260729-0002
preflight: passed_metadata_only
approval: prepared_not_issued
approval_consumed: false
processing_execution: not_approved
processed_dataset: not_created
execution_allowed: false
```

이 문서는 Processing 실행 승인이 아니다. source payload, ZIP member, JSON record를 읽지 않은 metadata-only
Preflight 결과와 향후 single-use Approval 초안의 계약만 기록한다.

## 2. Immutable Source

Run 0002의 immutable source commit은
`af10abf3ef388f4efd8707489cebef2c22719751`이다. Preflight 시 manifest와 실제 Processing Backend가 이
commit의 Git blob과 동일함을 확인했다.

## 3. Run Identity

- Run ID: `AIHUB-71748-SFT-PROCESSING-20260729-0002`
- Approval ID: `AIHUB-71748-SFT-PROCESSING-APPROVAL-20260729-0002`
- Run 0001: `retired_failed`, 재사용·retry·resume 금지
- Run 0002: 예약됨, 실행 흔적 없음

## 4. Local Mapping

ignored local config의 기존 path mapping을 metadata-only로 해석했다. source root와 output parent는 모두 외부
dataset root 아래로 resolve되며, 절대경로는 추적 설정이나 코드에 기록하지 않았다.

## 5. Source Metadata

```yaml
components:
  - SFTdata
  - SFTlabel
splits:
  - Training
  - Validation
zip_count: 55
total_bytes: 17256335769
zip_member_reads: 0
payload_reads: 0
```

파일명·경로·크기 외 데이터는 읽지 않았다.

## 6. Fingerprints

```yaml
manifest_sha256: ca1f99996a459b0f6aa241ee20e2839645fea9a73cf40163169ab3fd9fbf3973
backend_file_count: 15
backend_fingerprint: 38570ac2a5126f731e9fef5bcd1cb8af2dbba6bdd696a7107503ea4e904db5d7
approval_draft_fingerprint: 06728755644fc953712e2e5206508a7f5ac561715c943385885e87b078dc8b68
```

manifest digest는 immutable Git blob의 SHA-256이다. Backend fingerprint는 immutable commit에서 정렬한
backend 상대경로, NUL, 각 blob SHA-256, LF를 연결해 SHA-256으로 계산했다. Approval draft fingerprint는
canonical JSON 직렬화의 SHA-256이다.

## 7. Output Contract

논리적 output root는 ignored local mapping으로만 resolve한다. 저장소 밖의 정확한 output parent에서 빈 probe
파일의 write, atomic rename, checksum, 즉시 delete와 same-filesystem 조건을 확인했다. Run·staging·quarantine
디렉터리는 만들지 않았다.

허용 output은 다음 여섯 파일뿐이다.

- `train.jsonl`
- `validation.jsonl`
- `manifest.yaml`
- `statistics.json`
- `checksums.sha256`
- `processing-result.yaml`

## 8. Runtime Budget

```yaml
runtime_seconds:
  soft: 1200
  hard: 1800
memory_mib:
  soft: 1536
  hard: 2048
disk_free_required_gib: 4
staging_multiplier: 2
safety_margin: 0.25
record_count:
  expected: 11902
  hard_max: 11902
output_files:
  expected: 6
  hard_max: 6
output_bytes_hard_max: 536870912
measured_free_bytes: 1532137525248
```

시간·메모리 한도는 immutable backend의 기존 hard limit와 일치하도록 보수적으로 고정했다.

## 9. Rule Thresholds

```yaml
pii_threshold: 0
exact_duplicate_threshold: 0
near_duplicate_threshold: 0
leakage_threshold: 0
validation_exclusion: required
unknown_rule: fail_closed
rule_conflict: fail_closed
```

## 10. Approval Draft

추적 초안은
[`configs/data/aihub-71748-processing-run-0002-preflight.yaml`](../../configs/data/aihub-71748-processing-run-0002-preflight.yaml)에
있다. `prepared_not_issued`, `consumed=false`, `execution_allowed=false`이며 실행 권한으로 사용할 수 없다.

## 11. Fail Closed 결과

```yaml
processing_calls: 0
output_writes: 0
approval_consumed: false
processed_dataset_created: false
retry: false
resume: false
overwrite: false
extension: false
training: false
```

identity·fingerprint·source inventory·mapping·output collision·disk budget·승인 상태가 하나라도 다르면 실행 전
중단한다.

## 12. Readiness

```yaml
dataset_selection: CONDITIONALLY_SELECTED
processing_backend: implemented
processing_manifest: approved_not_executed
processing_preflight: passed_metadata_only
single_use_approval: prepared_not_issued
processing_execution: not_approved
processed_dataset: not_created
sft_training: not_approved
execution_allowed: false
```

## 13. Next Approval

다음 단계에는 Run 0002 single-use Approval의 명시적 발급과 실제 Processing 실행에 대한 별도 사용자 승인이
필요하다. 승인 전에는 Approval 발급·소비, Processing Engine 호출, output 생성 모두 금지한다.

## 변경 이력

| 날짜 | 변경 내용 |
| --- | --- |
| 2026-07-29 | Run 0002 metadata-only Preflight 통과와 non-executable Approval 초안 계약 기록 |
