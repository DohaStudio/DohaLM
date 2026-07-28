# SFT Processing Manifest Schema

- 문서 상태: `review`
- 마지막 검토일: 2026-07-29
- Schema version: `sft-processing-manifest-v1`
- AIHUB-71748 Manifest: `completed_non_executable`
- 실제 처리 실행: `not_approved`

## 목적

이 문서는 [Processing Backend](./processing-backend.md)가 검증하는 메모리 내 Manifest schema를 정의한다.
현재 구현은 serializer나 runtime file writer를 제공하지 않는다. AIHUB-71748의 canonical 비소비 계약은
[`configs/data/aihub-71748-sft-processing-v1.yaml`](../../configs/data/aihub-71748-sft-processing-v1.yaml)에
작성됐으며 Approval이 비어 있어 실행할 수 없다.

## 최상위 Schema

| Field | Type | 필수 | 계약 |
|---|---|---:|---|
| `input_dataset` | object | 예 | Synthetic identity만 허용 |
| `dataset_version` | string | 예 | `input_dataset.dataset_version`과 동일 |
| `rule_set` | tuple | 예 | 등록 Rule 전체를 중복 없이 포함 |
| `processing_order` | tuple | 예 | 승인된 고정 순서와 정확히 동일 |
| `statistics` | tuple | 예 | 승인된 aggregate field와 정확히 동일 |
| `output_schema` | tuple | 예 | 최종 SFT field와 정확히 동일 |
| `approval` | object | 예 | Synthetic validation 전용 승인 |
| `manifest_version` | string | 예 | `sft-processing-manifest-v1` |

## Input Dataset Identity

| Field | 계약 |
|---|---|
| `dataset_id` | `SYNTHETIC-` prefix 필수 |
| `dataset_version` | 비어 있지 않은 Synthetic version |
| `component` | `SFT` |
| `synthetic` | `true` |

기존 Synthetic record 실행 validator는 실제 `AIHUB-71748` identity를 계속 거부한다. 별도
`validate_aihub_71748_processing_manifest`는 실제 Dataset을 읽지 않고 AIHUB-71748 계약 Mapping만 검증한다.

## Rule Set과 처리 순서

Rule 선언은 `name`과 `enabled`만 가진다. 모든 기본 Rule은 비활성이다. Rule set은 다음 순서를 정확히
사용한다.

```yaml
processing_order:
  - schema_transform
  - pii
  - exact_duplicate
  - canonical_selection
  - near_duplicate
  - leakage
  - validation_exclusion
```

## Output Schema

```yaml
output_schema:
  - instruction
  - input
  - output
  - system
  - metadata
```

현재 Backend는 이미 이 논리 schema로 정규화된 Synthetic Record만 받는다. 실제 AIHUB field mapping과
변환 실행은 별도 Processing 승인 대상이다.

## Statistics Schema

```yaml
statistics:
  - input_count
  - processed_count
  - retained_count
  - excluded_count
  - rule_impacts
  - validation_status
```

## Approval Schema

| Field | 허용값 |
|---|---|
| `approval_id` | `SYNTHETIC-` prefix |
| `synthetic_validation_allowed` | `true` |
| `processing_allowed` | `false` |
| `training_allowed` | `false` |
| `execution_allowed` | `false` |

Approval이 없거나 실제 처리·학습·실행 권한이 하나라도 `true`면 Fail Closed다.

## Invalid Manifest

Version, identity, Rule 집합·순서, 통계 field, 출력 schema 또는 Approval 계약의 불일치는 모두 예외로
종료한다. 자동 보정, 기본 승인, 미등록 Rule 무시, 부분 처리 fallback은 없다.

## 현재 상태

```yaml
schema_implementation: completed
synthetic_validation: passed
aihub_71748_manifest: completed_non_executable
processing_execution: not_approved
processed_dataset: not_created
training: not_approved
execution_allowed: false
```

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-29 | AIHUB-71748 canonical 비소비 Manifest와 별도 Fail Closed validator 연결 |
