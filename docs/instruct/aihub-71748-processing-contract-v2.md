# AIHUB-71748 Processing 실행 계약 v2

- 문서 상태: `implemented`
- 계약 버전: `processing_contract=2`
- 적용일: 2026-07-30
- 관련 결정: [ADR-004](../decisions/ADR-004-data-governance.md), [ADR-010](../decisions/ADR-010-dohalm-instruct-strategy.md)
- 실제 실행 상태: `execution_allowed=false`

## 반복된 Fail Closed 원인

Run 0001~0006은 실행·검증 단계에서 식별자, checkpoint, Approval capability, runtime gate 또는 squash-merge
lineage 계약의 불일치를 발견해 폐기됐다. Run 0007은 PreflightEvidence 구현이 요구된 v2 schema와 달라 실제
evidence를 만들기 전에 중단했다. Run 0007은 `retired_contract_mismatch_before_start`, evidence 0건이며 재사용하지
않는다. Approval 0007도 생성하지 않았고 재사용하지 않는다.

## Run과 Backend 개발 분리

이번 변경은 실제 Run이 아니라 Backend 계약 개발이다. 외부 Dataset mapping, 실제 Approval, Runtime request와
processed output을 만들지 않았다. Synthetic fixture만 사용해 전체 lifecycle을 검증했다.

## Contract Freeze

```yaml
contract_versions:
  processing_contract: 2
  preflight_evidence_schema: 2
  approval_record_schema: 2
  runtime_execution_request_schema: 1
  processing_result_schema: 1
  registry_schema: 1

contract_freeze:
  frozen: true
  actual_run_started: false
  future_change_requires_contract_revision: true
  future_change_forbids_reusing_active_run: true
```

동결 대상은 Preflight·Approval·Runtime request schema, OutputState, zero-call counters, permission model,
lifecycle, lineage, registry, CLI, execution surface, output allowlist, budget과 processing-result schema다.

## PreflightEvidence v2

Canonical 필드는 identity, execution/governance commit, Manifest·Backend fingerprint, lineage, mapping identity,
source snapshot, registry/output/resource state, 세 budget, zero-call state와 freshness timestamp다.
`schema_version=2`, exact field set, timezone-aware timestamp, 최대 3,600초 freshness, 네 output 경로 부재,
probe residue 0과 모든 zero-call 값 0을 요구한다.

`immutable_git_commit`은 읽기 전용 legacy alias다. v2 직렬화에는 `execution_source_commit`만 기록한다.
v1 evidence는 별도 해석할 수 있지만 실행 근거로 사용하면 `LEGACY_PREFLIGHT_EVIDENCE_NOT_EXECUTABLE`로 차단한다.

## ApprovalRecord v2와 lifecycle

Approval은 `schema_version=2`, execution/governance commit, 세 fingerprint, budget, capability와 lifecycle을
canonical JSON·UTF-8·결정론적 key ordering으로 직렬화한다. checksum은 저장 artifact 무결성을, stable Approval
fingerprint는 lifecycle 전환에 독립적인 identity를 나타낸다.

허용 lifecycle은 `prepared_not_issued`, `issued`, `consumed`, `completed`, `failed`,
`retired_not_issued`, `retired_before_consumption`, `retired_issue_incomplete`다. Capability 세 값은 발급 전부 false,
발급 시 전부 true다. Artifact의 `execution_allowed`는 모든 상태에서 false이며 true이면
`APPROVAL_ARTIFACT_EXECUTION_FLAG_FORBIDDEN`이다.

## RuntimeExecutionRequest v1

Runtime request는 request/run/Approval identity, Approval·Preflight fingerprint, 두 commit, Manifest·Backend
fingerprint, one-shot budget, requester, timezone-aware 발급·만료 시각, nonce와 fingerprint를 포함한다.
`execution_allowed=true`는 메모리 또는 Git 외부 runtime artifact에서만 허용된다. 생성 자체는 Approval을 소비하거나
gate를 활성화하지 않는다. 만료, fingerprint 불일치, Approval/Run 불일치와 재사용은 서로 다른 오류로 차단한다.

Approval 소비는 issued·미소비, capability 세 값 true, 유효한 runtime request, 모든 identity와 fingerprint 일치
직후에만 수행한다. Artifact의 `execution_allowed=false` 상태는 유지된다.

## Registry

Run 상태는 `unused`, `reserved_preflight`, `preflight_passed`, `preflight_failed_closed`, `approval_issued`,
`processing_started`, `processing_completed`, `processing_failed`와 retired 계열로 동결한다. 문서, 코드 상수,
fixture, example과 주석의 문자열은 실제 사용 evidence가 아니다. Canonical registry 또는 runtime/output artifact만
identity를 소비한다.

```yaml
run_0007:
  status: retired_contract_mismatch_before_start
  actual_evidence_count: 0
  reusable: false
approval_0007:
  status: not_created
  reusable: false
```

## Lineage와 execution surface

`execution_source_commit`은 검증된 실행 surface 원본이고 `governance_record_commit`은 계약이 병합된
`origin/develop` commit이다. Direct ancestry는 `DIRECT_ANCESTRY_VALID`, squash merge는 10개 경로·Git blob·두
fingerprint가 모두 같을 때만 `SQUASH_MERGE_EXECUTION_SURFACE_EQUIVALENT`다.

Execution surface는 Manifest 1개와 Preflight validator, reader, processor, output writer, run/Approval/runtime,
post-validation 및 processing CLI 9개를 합친 10개 경로다. 이 변경은 기존 보안 경로 안에서 구현돼 경로 수를
바꾸지 않았다.

## OutputState와 zero-call contract

OutputState는 `final_exists`, `staging_exists`, `failed_exists`, `quarantine_exists`, `parent_probe_passed`,
`parent_probe_residue_count`의 exact field set이다. Metadata-only 성공은 네 경로 false, probe true, residue 0이다.

Runtime counter 단일 구조는 Approval issue/consume, Runtime request/gate, Processing, payload, ZIP/member,
JSON/record, join/policy, writer/checksum/finalization 15개 값을 관리한다. 누락·unknown·음수 값을 허용하지 않는다.

## CLI 계약

- Preflight: `python -m scripts.datasets.preflight_aihub_71748_sft_run`과 `--manifest`, `--mapping`, `--run-id`,
  `--approval-id`, `--execution-source-commit`, `--governance-record-commit`, `--preflight-only`를 사용한다.
- Processing: `python -m scripts.datasets.process_aihub_71748_sft`과 `--manifest`, `--mapping`, `--run-id`,
  `--approval-file`, `--runtime-request`, 두 commit, `--execute`를 사용한다.
- `--immutable-commit`은 읽기 전용 alias다. Repository root에서 module entrypoint를 사용하며 암묵적
  `PYTHONPATH`에 의존하는 direct script 방식은 지원 계약이 아니다.

## Manifest, output과 atomic finalization

Manifest version 1과 기존 runtime/memory/disk/record/output budget을 유지한다. Output allowlist는
`train.jsonl`, `validation.jsonl`, `manifest.yaml`, `statistics.json`, `checksums.sha256`,
`processing-result.yaml`의 정확히 6개다.

Processing result v1은 모든 lineage fingerprint, timestamp, statistics, output count/bytes, checksum, counters와
finalization state를 기록하고 tokenization/training을 false로 유지한다. 성공 시 staging write·검증·checksum·gate
후 atomic rename하며 staging residue가 없어야 한다. 실패 시 final을 만들지 않고 synthetic failed evidence를
보존하며 자동 재시도하지 않는다.

## Synthetic E2E

저작권·PII가 없는 deterministic record 6개(Training 4, Validation 2)를 작은 synthetic ZIP 4개로 만들었다.
실제 reader path를 통해 Approval issue → Runtime request → consume → Processing 1회 → output 6개 → JSONL·split·
statistics → checksum → atomic finalization → Approval completed를 검증한다. 성공 시 issue/request/gate/consume/
processing/payload/writer/checksum/finalization counter는 각각 1이며 ZIP 관련 counter만 synthetic archive 수에 따라
증가한다. 실패 fixture는 failed evidence 보존과 staging residue 0을 검증한다.

## Failure scenarios와 legacy policy

v1 Preflight, 필드 누락, stale evidence, lineage/fingerprint drift, capability 부족, artifact execution flag,
Runtime request expiry·tamper·reuse, Approval 재소비, Processing/payload budget, output allowlist·count·bytes,
checksum·JSONL·atomic-finalization 위반은 모두 Fail Closed다. Legacy Approval과 Preflight는 읽기와 실행을 분리하며
신규 실행에는 사용할 수 없다.

## Runtime evidence와 Git 분리

Git에는 코드, schema, 테스트, synthetic fixture 생성 코드와 문서만 포함한다. 실제 Dataset snapshot, Approval,
Runtime request, processing output, checksum, staging·failed·quarantine artifact는 포함하지 않는다.

## Run 0008 Readiness와 현재 안전 상태

```yaml
processing_contract_v2: frozen
synthetic_e2e: passed
run_0008: preflight_passed
preflight_attempts: 1
preflight_evidence_schema: 2
approval_0008: prepared_not_issued
runtime_execution_request: not_created
actual_dataset_payload_access: 0
actual_approval_issued: 0
actual_processing_calls: 0
processed_dataset: not_created
tokenization: not_approved
sft_backend: not_started
training: not_approved
execution_allowed: false
```

[Run 0008 metadata-only Preflight](./aihub-71748-processing-run-0008-preflight.md)는 동결 계약을 변경하지 않고
정확히 한 번 통과했다. 다음 단계는 최신 `develop`과 evidence freshness의 live 재검증 및 Approval 0008 발급을
위한 별도 승인이다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-30 | 동결 계약 변경 없이 Run 0008 metadata-only Preflight 통과와 미발급 Approval draft 기록 |
| 2026-07-30 | Processing 계약 v2 동결, Run 0007 시작 전 폐기와 Synthetic 4/2 전체 E2E 검증 |
