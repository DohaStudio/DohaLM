# AIHUB-71748 Processing Run 0008 Metadata-Only Preflight

- 문서 상태: `review`
- 마지막 검토일: 2026-07-30
- 실행 범위: filesystem metadata-only
- Processing 계약: `version 2 (frozen)`
- 실제 Processing: `0`
- Approval 발급·소비: `0`
- `execution_allowed`: `false`

## Scope

Run 0008은 동결된 Processing Contract v2의 실제 로컬 환경 metadata-only Preflight를 공식 module entrypoint로
정확히 한 번 수행했다. ZIP 파일의 이름·크기·mtime과 디렉터리 존재 여부만 조회했고 ZIP entry, JSON, record와
원문은 열지 않았다. 실제 Approval 발급·소비, RuntimeExecutionRequest, Processing과 output 생성은 범위 밖이다.

## Processing Contract v2 Freeze

```yaml
processing_contract: 2
preflight_evidence_schema: 2
approval_record_schema: 2
runtime_execution_request_schema: 1
processing_result_schema: 1
frozen: true
```

계약, schema, counter, lifecycle, CLI, execution surface, Manifest와 budget은 변경하지 않았다.

## Run 0007 Retirement

```yaml
run_0007:
  status: retired_contract_mismatch_before_start
  actual_evidence_count: 0
  reusable: false
approval_0007:
  status: not_created
  reusable: false
```

## Run 0008 Identity

```yaml
run_id: AIHUB-71748-SFT-PROCESSING-20260730-0008
approval_id: AIHUB-71748-SFT-PROCESSING-APPROVAL-20260730-0008
execution_source_commit: e3809de60d579da8e425d6e619878d4fd4e62fba
governance_record_commit: e3809de60d579da8e425d6e619878d4fd4e62fba
run_id_initial_state: unused
approval_id_initial_state: unused
retired_run_count: 7
conflicting_evidence_count: 0
```

Preflight 진입 전 Run·Approval 0008의 canonical registry와 runtime/output artifact가 모두 없음을 확인했다.
문서·코드 상수·fixture·CLI 예시는 실제 사용 evidence로 간주하지 않았다.

## Standard CLI Entry Point

Repository root에서 `python -m scripts.datasets.preflight_aihub_71748_sft_run`을 사용했다. Manifest, ignored local
mapping, 두 identity, 두 commit과 `--preflight-only`를 명시했다. Deprecated `--immutable-commit`, direct script,
임의 `PYTHONPATH`, Processing CLI의 `--execute`는 사용하지 않았다. CLI 진입은 성공했다.

## Execution Surface와 Lineage

Manifest 1개와 backend 9개로 구성된 동결 execution surface 10개를 immutable Git blob으로 검증했다.

```yaml
lineage:
  result_code: DIRECT_ANCESTRY_VALID
  direct_ancestry: true
  squash_merge_mode: false
  governance_reachable_from_origin_develop: true
  execution_surface_file_count: 10
  execution_surface_paths_equal: true
  execution_surface_blobs_equal: true
  manifest_fingerprint_equal: true
  backend_fingerprint_equal: true
  valid: true
manifest_sha256: ca1f99996a459b0f6aa241ee20e2839645fea9a73cf40163169ab3fd9fbf3973
backend_fingerprint: 052922b0341f0710991717190469301b622131518b07585aa4e99772169625c6
```

## Mapping Metadata Validation

```yaml
mapping_identity:
  dataset_id: AIHUB-71748
  component: SFT
  root_type: external
  repository_internal: false
  read_only: true
local_mapping:
  git_ignored: true
  tracked: false
```

실제 local mapping 값과 외부 절대경로는 문서나 runtime evidence에 기록하지 않았다. Raw source와 processed root의
분리 및 외부 read-only source 정책을 검증했다.

## Source Snapshot

```yaml
source_snapshot:
  zip_count: 55
  total_bytes: 17256335769
  filename_aggregate: 7083a10fd74f0826aab9a44cf341777f11413dcf8d3c43e8c72d08a8876b1ec4
  modified_time_aggregate: b887a9d5c1b67f7db3d62c8d57a5360c0f964c0a4c87c7e926d4a11f9a9453b5
```

ZIP entry open과 archive member enumeration은 각각 0건이다. Payload checksum, JSON parse, record count, preview와
압축 해제는 수행하지 않았다.

## OutputState와 Parent Probe

```yaml
output_state:
  final_exists: false
  staging_exists: false
  failed_exists: false
  quarantine_exists: false
  parent_probe_passed: true
  parent_probe_residue_count: 0
```

Processed parent에서만 temporary create → minimal write → flush → fsync → close → delete를 수행했다. Probe 이름과
절대경로는 기록하지 않았고 Run output·staging·failed·quarantine 디렉터리는 만들지 않았다.

## Resource Budget

```yaml
resource_state:
  free_disk_bytes: 1532035944448
  current_rss_bytes: 26402816
  memory_provider_available: true
  runtime_provider_available: true
disk_budget:
  minimum_free_bytes: 4294967296
  staging_multiplier: 2
  safety_margin_ratio: 0.25
memory_budget:
  soft_limit_mib: 1536
  hard_limit_mib: 2048
runtime_budget:
  soft_limit_seconds: 1200
  hard_limit_seconds: 1800
record_budget:
  expected_training: 10580
  expected_validation: 1322
  expected_total: 11902
  maximum_total: 11902
output_budget:
  expected_files: 6
  maximum_files: 6
  maximum_total_bytes: 536870912
```

모든 provider와 동결 budget의 정합성이 통과했다.

## PreflightEvidence v2

```yaml
schema_version: 2
status: completed
fingerprint: 9ef6c7b031d2a1324a49ae0f88bf6ca0978e1703ec61b02dc5b0c901731abfe5
generated_at: 2026-07-29T21:13:50.051940+00:00
expires_at: 2026-07-29T22:13:50.051940+00:00
freshness_seconds: 3600
storage: local_only_git_excluded
```

Canonical JSON round trip과 fingerprint를 검증했다. Runtime evidence에는 실제 절대경로, local mapping 원문,
Dataset 원문, 개별 파일 hash 목록과 secret이 없다.

## ApprovalRecord v2 Draft

```yaml
schema_version: 2
status: prepared_not_issued
fingerprint: 1a8317375b019f39211d3409bd0f30986fd8309f60830454a3ebb6d32c430822
processing_allowed: false
payload_read_allowed: false
output_write_allowed: false
tokenization_allowed: false
sft_backend_allowed: false
training_allowed: false
execution_allowed: false
issued: false
consumed: false
lifecycle_timestamps: null
storage: nested_local_draft_only
```

Draft는 실제 issued Approval artifact가 아니며 Approval checksum이나 실행 capability를 부여하지 않는다.

## Zero-Call State

```yaml
approval_issue_calls: 0
approval_consume_calls: 0
runtime_request_creations: 0
runtime_execution_gate_activations: 0
processing_engine_calls: 0
payload_sessions: 0
zip_entry_opens: 0
archive_member_enumerations: 0
json_parser_calls: 0
record_parser_calls: 0
join_calls: 0
policy_dispatch_calls: 0
output_writer_calls: 0
checksum_calls: 0
atomic_finalization_calls: 0
```

## Preflight Result와 현재 안전 상태

```yaml
run_0008:
  status: preflight_passed
  reusable: false
  preflight_attempts: 1
  actual_evidence_count: 1
approval_0008:
  status: prepared_not_issued
  issued: false
  consumed: false
runtime_execution_request: not_created
processed_dataset: not_created
tokenization: not_approved
sft_backend: not_started
training: not_approved
execution_allowed: false
```

실제 Dataset payload 접근, Processing, Approval 발급·소비, RuntimeExecutionRequest 생성과 output write는 모두
0건이다. Run 0008은 재실행하지 않는다.

## Next Runtime Step

[승인 필요] 다음 작업은 병합된 최신 `develop`에서 execution surface와 evidence freshness를 live 재검증한 뒤
Approval 0008 발급 여부만 결정하는 별도 승인이다. 그 승인 전에는 Approval 발급·소비, RuntimeExecutionRequest,
payload 접근, Processing, Tokenization과 Training을 수행하지 않는다.

## Active Run refresh 구현 보완 상태

[확정] 기존 Contract v2 구현에는 `preflight_passed` active Run을 위한 공식 live refresh 경로가 없었다. 최초
Preflight validator는 신규 identity 전용이므로 Run 0008에 재사용하지 않는다. 보완 구현은 별도
`ApprovalRefreshEvidence` v1, strict canonical registry adapter, governance checkout 검증과 refresh-only CLI를
제공한다.

[확정] 이번 작업에서는 실제 Run 0008 canonical evidence를 읽거나 수정하지 않았고 live refresh도 실행하지
않았다. Approval 0008 artifact와 RuntimeExecutionRequest를 생성하지 않았으며 실제 Dataset payload 접근,
Processing과 output write는 모두 0건이다. 합성 fixture에서만 active refresh 성공·실패 계약을 검증했다.

```yaml
run_0008: preflight_passed
approval_0008: prepared_not_issued
approval_refresh_0008: not_executed_requires_separate_approval
approval_artifact: absent
approval_issue_calls: 0
approval_consume_calls: 0
runtime_execution_request: absent
payload_reads: 0
processing_calls: 0
output_writes: 0
processed_dataset: not_created
execution_allowed: false
```

[승인 필요] Run 0008 유지 또는 폐기 결정, 실제 live refresh, Approval 0008 발급은 각각 후속 governance 승인
범위에서 결정한다. 코드 보완 자체는 그 승인을 대신하지 않는다.

## Approval no-replace 보완

[확정] PR #64 리뷰에서 확인된 `exists()` 검사와 `os.replace()` 사이 경쟁 final overwrite 가능성을 제거했다.
exclusive Approval publish는 POSIX·Windows에서 fsync된 temp의 atomic hard-link no-replace만 사용한다. 경쟁 final이
존재하면 publish가 실패하고 기존 bytes를 유지하며, 미지원 filesystem에서는 fallback 없이 Fail Closed한다.

[확정] deterministic competing-final 검증은 100회 모두 publish 실패·경쟁 final 보존·overwrite 0을 요구한다.
publish 후 temp unlink 또는 directory durability 실패는 성공으로 간주하지 않고 final을 보존해 identity 재사용을
차단한다. 이 검증은 synthetic 임시 identity만 사용했으며 실제 Run 0008 evidence나 Approval artifact를 사용하지
않았다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-30 | Approval no-replace TOCTOU 보완 정책 추가; Run 0008 refresh·Approval 발급 미실행 유지 |
| 2026-07-30 | Active Run refresh 공식 경로 구현 상태 추가; Run 0008 실제 refresh·Approval 발급은 미실행 유지 |
| 2026-07-30 | Run 0008 metadata-only Preflight 1회 통과, local-only evidence와 미발급 Approval v2 draft 기록 |
