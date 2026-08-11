# ADR-013: 초기 Common AI Contract 소비 경계

- 문서 상태: `draft`
- 마지막 검토일: 2026-08-12
- 결정 상태: `proposed`
- 실행 영향: 없음
- 권위 기준: `DohaStudio/.github@dd75fc88c16e9ae9a04acfafb72756a905f6365b`
- 관련 문서: [Project Definition](../project/overview.md),
  [Current Project Status](../project/current-project-status.md),
  [Phase 1 Data Contract](../data/phase1-data-contract.md),
  [ADR-004](./ADR-004-data-governance.md)

## Context

[확정] DohaLM `develop`은 Dataset ingestion·manifest, training input, evaluation, inference와 Runtime을 자체 계약으로
운영하지만 Common AI Contract package를 소비하지 않는다. `src.data.pipeline`은 DohaLM 고유
`source-manifest.json`을 발행하고 training·evaluation은 그 산출물과 별도 lineage·split manifest를 읽는다.

[확정] Common AI Contract의 단일 권위는
`DohaStudio/.github@dd75fc88c16e9ae9a04acfafb72756a905f6365b`이다. distribution은
`dohastudio-common-ai-contracts` `0.1.0`, public namespace는 `dohastudio_common_ai`, 실행 정책 version은
`1.0.0`이다. 직렬화 객체의 `schema_version`은 package의 compatibility policy가 판정한다.

[확정] [Draft PR #103](https://github.com/DohaStudio/DohaLM/pull/103)은 Learning Candidate에서 Dataset Version,
Training, Evaluation과 Runtime으로 이어지는 미래 제품 구조를 제안한다. 해당 PR과 ADR-012는 모두 미병합 Draft이며
현재 Project Definition이나 구현 요구사항을 변경하지 않는다.

### 현재 blocker

[확정] 현재 DohaLM에는 Common `LearningCandidate`, `DatasetVersion`, `DatasetManifest` 또는
`TrainingEligibility` 객체를 발행하는 producer가 없다. 기존 manifest의 이름이나 일부 field가 비슷하다는 이유만으로
Common 객체로 해석하면 envelope, SemVer, 권리·승인 evidence와 immutable identity의 의미를 바꾸게 된다.

[확정] producer와 domain lifecycle 없이 validator만 먼저 연결하면 실제 payload를 검증하지 않는 빈 loader, 전체 Registry
탐색 wrapper 또는 미래 resource switch만 남는다. 이는 독립적으로 소비할 계약이 없으므로 구현 가능한 consumer 경계가
아니다.

## 확인한 후보

| 후보 | 공식 `$id` | 현재 producer | 현재 consumer boundary | 판정 |
|---|---|---|---|---|
| `learning_candidate` | `https://schemas.dohastudio.org/common-ai/v1/learning-candidate.schema.json` | 없음 | 없음 | Draft PR #103의 learning intake와 review가 선행되어야 함 |
| `dataset_version` | `https://schemas.dohastudio.org/common-ai/v1/dataset-version.schema.json` | 없음 | training input 직전이 가능한 미래 경계이나 승인·freeze producer가 없음 | 선행 Dataset governance 결정 필요 |
| `dataset_manifest` | `https://schemas.dohastudio.org/common-ai/v1/dataset-manifest.schema.json` | 없음 | 현재 manifest reader와 이름만 유사 | Common DatasetVersion과 issued manifest producer가 선행되어야 함 |
| `training_eligibility` | `https://schemas.dohastudio.org/common-ai/v1/training-eligibility.schema.json` | 없음 | training readiness 전이 가능한 미래 경계 | Candidate·rights·review evidence가 선행되어야 함 |

후보는 이번 결정에 직접 필요한 범위만 기록한다. 이 표는 package Registry 또는 전체 resource identity 목록의 사본이 아니다.

## 검토한 선택지

| 선택지 | 장점 | 문제 | 판정 |
|---|---|---|---|
| `learning_candidate`를 첫 resource로 승인 | Draft PR #103의 제안 흐름과 가까움 | 현재 제품 범위에는 producer·review lifecycle·소비 지점이 없음 | 기각 |
| `dataset_version` 또는 `dataset_manifest`를 첫 resource로 승인 | 현재 Dataset·training manifest 경계와 인접 | 기존 payload와 Common 의미가 다르고 승인된 Common producer가 없음 | 기각 |
| package integration만 먼저 승인 | immutable pin과 import 검증을 먼저 준비 가능 | 검증할 payload가 없어 빈 loader 또는 범용 wrapper만 생성 | 기각 |
| 선행 domain/governance 결정 전 consumer 보류 | 추측과 이중 Source of Truth를 방지 | consumer 구현 시작이 지연됨 | 채택 제안 |

## Proposed Decision

다음을 승인 대상으로 제안한다.

```text
initial_common_ai_resource: not_selected
canonical_resource_name: N/A
canonical_resource_id: N/A
consumer_implementation_allowed: false
dependency_pin_allowed: false
required_predecessor: approved_common_object_producer_and_boundary_decision
```

- [제안] 현재 DohaLM의 첫 Common AI Contract resource를 임의 선택하지 않는다.
- [제안] Common 객체를 발행할 domain producer와 lifecycle이 승인되기 전에는 package dependency, loader, adapter 또는
  validator integration을 구현하지 않는다.
- [제안] 후속 결정은 canonical name과 공식 `$id`뿐 아니라 producer, consumer, 정확한 호출 지점과 fail-closed 결과를
  하나의 승인 단위로 고정해야 한다.
- [제안] Draft PR #103의 제품 방향이나 전체 migration plan은 이 ADR로 승인하지 않는다.

## 미래 소비 boundary의 필수 조건

후속 결정에서 resource가 승인되면 최소 소비 boundary는 다음 조건을 모두 만족해야 한다.

1. 승인된 producer가 완성된 immutable Common 객체를 발행한다.
2. DohaLM consumer는 객체를 명시적으로 전달받은 직후, Dataset file·Model·Provider를 열거나 training/evaluation output을
   만들기 전에 public `validate_contract(payload, expected_kind)`를 호출한다.
3. canonical issue가 하나라도 있거나 package/version/resource compatibility가 실패하면 fail-closed로 종료한다.
4. 실패 전후 partial file, staging publication, Dataset mutation과 training/evaluation 실행은 0이어야 한다.
5. validation 전후 payload의 key, value, type와 version은 동일해야 한다.
6. package resource와 `$ref`는 offline으로 해결하고 Runtime network lookup은 0이어야 한다.
7. import는 stdout/stderr, application file, environment, DB, thread, process, Dataset, Model과 Provider 상태를 변경하지 않는다.

이 조건은 특정 resource가 승인됐다는 뜻이 아니며 후속 결정의 acceptance gate다.

## 책임 경계

### Common Contract validation

- authority package의 public API로 envelope, schema, object version과 canonical issue를 판정한다.
- package 내부 path, private module 또는 DohaLM에 복제한 Schema·Registry·version policy를 사용하지 않는다.
- 오류에는 안전한 resource identity, issue code, field path와 정제된 message만 노출한다.

### DohaLM domain validation

- Dataset 사용 목적, local artifact identity, checksum, split, Tokenizer, training/evaluation readiness와 저장 경로를 판정한다.
- Contract validation 성공을 Dataset 승인, training 허용 또는 Runtime 승격으로 재해석하지 않는다.
- 누락 field를 추정하거나 payload를 Common 객체로 자동 변환하지 않는다.

## Dataset·학습 경계

- [확정] 현재 Phase 1 data pipeline과 ADR-004는 유지한다. 이 ADR은 기존 Dataset을 Common DatasetVersion으로 승격하지 않는다.
- [제안] `LearningCandidate`와 승인된 `DatasetVersion`의 도입은 별도 domain/governance 결정으로 수행한다.
- [제안] Training Readiness Gate는 승인된 Common object validation과 DohaLM domain readiness를 모두 통과해야 하며 어느
  한쪽도 다른 쪽을 대체하지 않는다.
- [확정] 이 ADR은 Dataset 접근, Training, Evaluation, Model load 또는 Runtime 연결을 승인하지 않는다.

## Security와 sanitization

- payload 원문, 사용자 입력, consent evidence, credential, 절대경로, local storage path, stack trace와 package 내부 path를
  오류·log·stdout·stderr에 포함하지 않는다.
- Contract validation은 payload를 deep copy로 보완하거나 field·version을 자동 주입하지 않는다.
- package 부재, resource 불일치와 compatibility failure는 정제된 오류로 fail-closed 처리한다.

## 제외 범위

- Common Contract dependency, loader, adapter와 테스트 구현
- Schema·Registry·resource·fixture 또는 version policy 복제
- Dataset governance, LearningCandidate, DatasetVersion과 Training Readiness 구현
- Database, API, Runtime, Provider, Dataset, Model, Artifact, Training과 Evaluation 변경
- Draft PR #103 또는 ADR-012의 승인·수정·병합

## Consequences

- 장점: 현재 계약을 Common 객체로 오인하지 않고 authority를 하나로 유지한다.
- 장점: 후속 consumer PR이 producer와 정확한 boundary 없이 범용 abstraction을 미리 만들지 못한다.
- 비용: 첫 consumer 구현 전 별도의 domain/governance Owner 결정이 필요하다.
- 비용: 기존 공식 구현 순서의 `consumer → Dataset governance`는 실행 가능한 payload가 없어 그대로 적용할 수 없다.
  package integration만을 독립 단계로 두지 않고 producer 결정과 resource-specific consumer를 결합해야 한다.

## 후속 consumer PR acceptance criteria

consumer 구현은 이 ADR의 승인만으로 시작할 수 없다. 별도 승인 결정이 다음을 모두 고정한 뒤에만 시작한다.

- canonical resource name과 authority의 정확한 `$id`
- 현재 존재하는 producer와 완성된 payload 계약
- DohaLM 내부 consumer 함수와 validation 호출 시점
- immutable Git commit dependency와 requested/resolved commit 일치
- package `0.1.0`, 실행 정책 `1.0.0`과 object version compatibility 검증
- public API만 사용한 valid/invalid, deterministic issue, payload immutability와 sanitization test
- offline local `$ref`, Runtime network lookup 0과 import side effect 0 test
- validation 실패 시 partial output, Dataset·Model·Provider 접근과 Training/Evaluation 실행 0 test
- Schema·Registry·resource 전체 목록·fixture·version policy 복제 0과 private import 0 scan

## 승인 Gate

이 ADR은 `draft`다. review와 명시 승인·병합 전에는 현재 보류 결정도 authoritative implementation requirement가 아니다.
승인되더라도 consumer 구현 허가는 `false`이며, 위 acceptance criteria를 채운 후속 resource-specific 결정이 필요하다.

## Revisit conditions

- Common 객체를 발행하는 Dataset governance 또는 learning intake producer가 승인·구현된다.
- 현재 DohaLM 외부에서 전달되는 Common object와 호출 boundary가 승인된다.
- PR #103의 제품 방향과 관련 domain lifecycle이 승인·병합된다.
- authority package의 public API, resource identity 또는 compatibility policy가 변경된다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-12 | [제안] producer 없는 resource 선정을 보류하고 후속 resource-specific consumer Gate를 정의함 |
