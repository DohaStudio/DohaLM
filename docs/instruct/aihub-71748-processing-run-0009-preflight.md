# AIHUB-71748 Processing Run 0009 Metadata-Only Preflight

- 문서 상태: `review`
- 실행일: 2026-07-30
- 관련 결정: [ADR-004](../decisions/ADR-004-data-governance.md), [ADR-010](../decisions/ADR-010-dohalm-instruct-strategy.md)
- 관련 계약: [Processing Contract v2](./aihub-71748-processing-contract-v2.md), [Approval Lineage Contract](./aihub-71748-approval-lineage-contract.md)
- 실행 상태: `execution_allowed=false`

## 목적과 범위

[확정] Run 0008은 Approval no-replace 보안 수정으로 동결 backend fingerprint가 달라져 live refresh에서
`BACKEND_FINGERPRINT_MISMATCH`로 Fail Closed했다. 기존 Run·Approval·Preflight evidence를 수정하거나 재사용하지
않고 현재 안전한 `develop` commit에서 신규 Run 0009 metadata-only Preflight를 수행했다.

[확정] 저장소의 strict identity 형식에 따라 요청서의 축약 ID 대신 다음 canonical ID를 사용했다.

```yaml
run_id: AIHUB-71748-SFT-PROCESSING-20260730-0009
approval_id: AIHUB-71748-SFT-PROCESSING-APPROVAL-20260730-0009
```

## Run 0008 Retirement

```yaml
run_0008: retired_backend_fingerprint_mismatch
previous_status: preflight_passed
reason_code: BACKEND_FINGERPRINT_MISMATCH
execution_source_commit: e3809de60d579da8e425d6e619878d4fd4e62fba
governance_commit: 841123ea2f0d3f0fccb8cf456edaf8c9faa44014
manifest_fingerprint_equal: true
backend_fingerprint_equal: false
changed_execution_surface:
  - src/data/processing/approval.py
approval_0008: retired_not_issued
approval_artifact: absent
approval_issue_calls: 0
approval_consume_calls: 0
runtime_request: absent
payload_reads: 0
processing_calls: 0
output_writes: 0
reusable: false
execution_allowed: false
```

[확정] Run 0008의 기존 Preflight evidence는 실패 계보의 읽기 전용 근거로 보존한다. Approval 0008 artifact를
만들어 retirement를 표현하지 않으며 Run·Approval identity를 다시 사용하지 않는다.

## Git과 Identity

```yaml
branch_at_execution: docs/aihub-71748-run-0009-preflight
execution_source_commit: 841123ea2f0d3f0fccb8cf456edaf8c9faa44014
governance_record_commit: 841123ea2f0d3f0fccb8cf456edaf8c9faa44014
current_head_at_execution: 841123ea2f0d3f0fccb8cf456edaf8c9faa44014
origin_develop_head: 841123ea2f0d3f0fccb8cf456edaf8c9faa44014
working_tree_at_execution: clean
lineage_result: DIRECT_ANCESTRY_VALID
run_id_unused: true
approval_id_unused: true
conflicting_evidence_count: 0
```

## Execution Surface

```yaml
manifest_sha256: ca1f99996a459b0f6aa241ee20e2839645fea9a73cf40163169ab3fd9fbf3973
backend_fingerprint: ddc26624b86f26e9c6636a753e8126b20dc50afaea5417f7573995db27acbdb8
execution_surface_file_count: 10
execution_surface_blobs_equal: true
manifest_fingerprint_equal: true
backend_fingerprint_equal: true
lineage_valid: true
```

## Source Metadata

```yaml
zip_count: 55
total_bytes: 17256335769
filename_aggregate: 7083a10fd74f0826aab9a44cf341777f11413dcf8d3c43e8c72d08a8876b1ec4
modified_time_aggregate: b887a9d5c1b67f7db3d62c8d57a5360c0f964c0a4c87c7e926d4a11f9a9453b5
```

[확정] 파일명·개수·크기·mtime 기반 metadata만 확인했다. ZIP entry open, archive member enumeration, JSON·record
parse와 payload content read는 모두 0건이다.

## Output과 Resource

```yaml
output_state:
  final_exists: false
  staging_exists: false
  failed_exists: false
  quarantine_exists: false
  parent_probe_passed: true
  parent_probe_residue_count: 0
resource_state:
  free_disk_bytes: 1532027187200
  memory_provider_available: true
  runtime_provider_available: true
```

[확정] parent probe는 processed parent에서만 minimal write·flush·fsync·remove를 수행했고 residue는 0건이다.
Raw Dataset 내부에는 쓰지 않았다.

## Preflight Evidence v2

```yaml
schema_version: 2
status: preflight_passed
fingerprint: 82dde3164ba3e77871e944161f69283f0a021c36909953f2dc2ad3aad524c90a
artifact_file_sha256: 9312389693ecb466d6f1231273d281a2db4428aaa71cb31ad6f4cc080e4113f5
generated_at: 2026-07-29T23:19:26.763093+00:00
expires_at: 2026-07-30T00:19:26.763093+00:00
freshness_seconds: 3600
storage: local_only_git_excluded
```

[확정] exact field set, timezone-aware freshness, canonical fingerprint, identity, lineage, Manifest·Backend fingerprint,
budget과 zero-call state를 project validator로 다시 검증했다. Evidence는 외부 processed root의 canonical
`runtime-evidence/<run-id>/preflight-evidence.json`에만 보존하며 Git에 포함하지 않는다.

## Approval 0009 Draft

```yaml
status: prepared_not_issued
stable_fingerprint: 0a3743106bc0269677ff6d4e3180fa2a3504cae80406a1c9dc6c4d112bc8101c
checksum: not_applicable_not_issued
issued: false
consumed: false
processing_allowed: false
payload_read_allowed: false
output_write_allowed: false
tokenization_allowed: false
sft_backend_allowed: false
training_allowed: false
execution_allowed: false
```

[확정] draft는 Preflight result 내부의 검증용 비발급 record다. 실제 Approval artifact가 아니므로 issuance checksum과
capability를 갖지 않는다. Approval publish·issue·consume은 수행하지 않았다.

## Zero-Call Safety

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

## 검증

```yaml
relevant_regression: 214_passed
changed_scope_ruff: passed
python_compile: passed
yaml_parse: passed
json_parse: passed
markdown_relative_links: passed
markdown_code_fences: passed
git_diff_check: passed
repository_wide_ruff: 79_pre_existing_errors
```

[확정] 관련 회귀에는 Initial Preflight, Approval, Approval Refresh, Git lineage, atomic writer, Runtime request,
Processing Contract, Synthetic E2E, identity 재사용 차단과 retired Run rejection이 포함된다. 저장소 전체 Ruff의
79건은 변경 파일 밖 기존 오류이며 이번 문서 변경에서 새 Python 오류를 추가하지 않았다.

## Approval 0009 공식 Retirement

[확정] PR #67 Squash Merge 뒤 canonical public `retire_approval_file(...)` service를 정확히 한 번 사용했다.
Initial/Refresh evidence는 수정하지 않았으며 retirement evidence는
`processed_root/approvals/AIHUB-71748-SFT-PROCESSING-APPROVAL-20260730-0009.retirement.json`에 보존한다.

```yaml
run_status: retired_runtime_request_governance_mismatch
approval_status: retired_before_consumption
reason_code: RUNTIME_REQUEST_GOVERNANCE_MISMATCH
retired_at: 2026-07-30T03:16:46.462827+00:00
before_file_sha256: 5fe6a22c595dbcf51b1849a83334593acb220588ddf3a1dcb9a9d01aff93f376
after_file_sha256: e70b254cec8ab0dd7b26355a4e762482a03502971cf40284c7f48a6f07115299
before_checksum: 7a0dfc9ff060c81d5d9e955e2032914a29a027f6898e6a3a6738756434e4809a
after_checksum: f6439dd79fbad7805dfe9204aabf7116f09f7e51ddb86aa57f5011f4ec9c2ff2
stable_fingerprint: 50dcf3c34189f7eb974da08488080d9144d6e6df856779e986f9456dd6f6d06d
retirement_evidence_fingerprint: 359e453bbdbde06af30279f4514f21a06e57288cdb3601b5ea545f780b84cc67
consumed: false
execution_allowed: false
reusable: false
```

## 현재 상태와 다음 승인

```yaml
run_0008: retired_backend_fingerprint_mismatch
approval_0008: retired_not_issued
run_0009: retired_runtime_request_governance_mismatch
approval_0009: retired_before_consumption
approval_refresh_0009: validated
runtime_execution_request: absent
processed_dataset: not_created
tokenization: not_approved
sft_backend: not_started
training: not_approved
execution_allowed: false
```

[확정] 후속 별도 승인에서 Live Refresh 검증과 Approval 0009 발급이 완료됐고, PR #67 병합 뒤 공식 public
retirement service로 `retired_before_consumption` 전환했다. Reason code는
`RUNTIME_REQUEST_GOVERNANCE_MISMATCH`이며 consumed=false, execution_allowed=false다. 기존 Initial/Refresh evidence는
변경하지 않았고 RuntimeExecutionRequest·Processing은 없다.

[승인 필요] 다음 신규 identity는 Run 0010 Metadata-Only Preflight의 별도 승인 경계를 따른다. Run 0009와
Approval 0009는 재사용하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-30 | Approval 0009 공식 retirement와 Run 0009 `retired_runtime_request_governance_mismatch` 영구 폐기 |
| 2026-07-30 | Approval 0009 issued·unconsumed 상태와 RuntimeExecutionRequest 미생성 경계 반영 |
| 2026-07-30 | Run 0008 backend fingerprint mismatch 폐기와 Run 0009 metadata-only Preflight 결과 기록 |
