# AIHUB-71748 Processing Run 0006 Metadata-Only Preflight

- 문서 상태: `review`
- 마지막 검토일: 2026-07-30
- 실행 범위: filesystem metadata-only
- 실제 Processing: `0`
- Approval 발급·소비: `0`
- `execution_allowed`: `false`

## Identity

```yaml
run_id: AIHUB-71748-SFT-PROCESSING-20260730-0006
approval_id: AIHUB-71748-SFT-PROCESSING-APPROVAL-20260730-0006
immutable_commit: 1c8acbde212ee9baf6643b7938da6f4760906d8c
```

Run·Approval ID는 CLI와 validator에 명시적으로 주입했고 형식과 날짜·sequence 일치를 검증했다. Run 0005와
Approval 0005는 각각 `retired_preflight_validator_failure`, `retired_not_issued`로 유지했다.

## Canonical Fingerprints

```yaml
manifest_sha256: ca1f99996a459b0f6aa241ee20e2839645fea9a73cf40163169ab3fd9fbf3973
backend_fingerprint: d873f476664a45453712702bccb2cda58b40a4faa2b747788cd147752428c110
preflight_evidence_fingerprint: a6b0b6c8823eaa79749c77c8cddab8f599d23df6c15b96e17a2323d4471932f7
approval_draft_fingerprint: 2a2764d2479d5342275335a07b09db6e990c1f5aef1f0f667ddda3dfb470c395
```

Evidence 생성 시각은 `2026-07-29T19:09:06.848422+00:00`, 만료 시각은 정확히 3,600초 뒤인
`2026-07-29T20:09:06.848422+00:00`이다. 이 기록은 과거 evidence이며 향후 Approval 발급 근거로 직접
재사용할 수 없다.

## Execution Surface

Manifest 1개와 backend 9개, 총 10개 immutable Git blob을 검증 범위에 포함했다. backend에는 preflight
validator 자체와 실제 processing CLI가 모두 포함된다.

```yaml
file_count: 10
manifest_included: true
validator_included: true
processing_cli_included: true
```

## Source Metadata Snapshot

```yaml
zip_count: 55
total_bytes: 17256335769
filename_aggregate: 7083a10fd74f0826aab9a44cf341777f11413dcf8d3c43e8c72d08a8876b1ec4
modified_time_aggregate: b887a9d5c1b67f7db3d62c8d57a5360c0f964c0a4c87c7e926d4a11f9a9453b5
```

외부 source에서는 ZIP 파일명과 filesystem stat만 읽었다. ZIP entry·member·checksum, JSON·record,
payload는 열거나 계산하지 않았다.

## Output·Resource 검증

final, staging, quarantine 경로는 모두 존재하지 않았다. processed parent에서 create → minimal write → flush →
fsync → delete probe가 통과했고 잔여물은 0건이다. 확인 시 free disk는 `1532110356480` bytes, RSS는
`26198016` bytes였으며 정의된 disk·memory·runtime budget을 충족했다.

## Approval Draft

Approval 0006은 `prepared_not_issued` 초안만 메모리에서 생성·검증했다. 실제 Approval artifact는 생성하지
않았고 발급·소비하지 않았다. processing, payload read, output write, tokenization, SFT backend, training,
execution 권한은 모두 `false`다.

## Zero-Call Contract

```yaml
processing_engine_calls: 0
payload_sessions: 0
zip_entry_opens: 0
archive_member_enumerations: 0
checksum_calls: 0
json_parser_calls: 0
record_parser_calls: 0
join_calls: 0
policy_dispatch_calls: 0
output_writer_calls: 0
atomic_finalization_calls: 0
approval_issue_calls: 0
approval_consume_calls: 0
```

## 결과와 다음 승인

Run 0006 metadata-only Preflight 자체는 통과했지만 Approval 발급 전 permission·schema·squash lineage 계약
불일치가 발견됐다. [후속 계약](./aihub-71748-approval-lineage-contract.md)에 따라 Run 0006은
`retired_approval_contract_failure`, Approval 0006은 `retired_not_issued`로 영구 폐기한다. Approval 발급·소비,
payload 접근, Processing과 output은 모두 0건이며 `execution_allowed=false`다.

Run 0007도 [Processing 계약 v2](./aihub-71748-processing-contract-v2.md)의 PreflightEvidence schema 불일치를
실행 전에 발견해 evidence 0건으로 폐기했다. 실제 다음 Run은 별도 승인될 Run 0008이다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-30 | Run 0007 시작 전 계약 불일치 폐기와 Contract v2 후속 흐름 연결 |
| 2026-07-30 | Approval 발급 전 계약 불일치 Fail Closed와 Run·Approval 0006 영구 폐기 연결 |
