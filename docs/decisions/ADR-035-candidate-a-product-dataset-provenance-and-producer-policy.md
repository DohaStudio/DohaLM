# ADR-035: Candidate A Product Dataset 계보와 Producer 정책

- 문서 상태: `approved`
- 마지막 검토일: 2026-09-01
- 결정 상태: `approved`
- 실행 영향: Candidate A Product Dataset rebuild 구현 진입을 승인한다. Dataset artifact 생성·publication,
  production authority provisioning과 Training 실행은 승인하지 않는다.
- 기준 DohaLM commit: `cb6b06c6b1b22f0898c235bc793995293c7e6772`
- 기준 DohaLM tree: `a6c99312a64fe855e720caac2e5591d5c4986266`
- 기준 DohaRights commit: `07599ec26ebc3b97e6257cfd0403815a9e37f19a`
- 선행 결정: [ADR-004](./ADR-004-data-governance.md),
  [ADR-014](./ADR-014-dataset-product-governance-boundary.md),
  [ADR-034](./ADR-034-cross-repository-rights-authority-and-current-evidence-snapshot.md)
- 상세 정책: [Candidate A Product Dataset 계보 정책](../data/candidate-a-product-dataset-provenance-policy.md)
- 승인 근거: 2026-09-01 사용자 `DDORINY`의 Candidate A Product Dataset Provenance Policy + Producer
  Architecture Gate 명시 요청

## Context

[현재] canonical AIHUB-71748 Training source는 25개 archive, 107,226개 record다. 기존 `source_id`는 archive
상대 경로, JSON entry 경로와 array index를 SHA-256으로 결속한다. raw `data_id`는 누락은 없지만 107,224개만
고유하고, 중복 2건은 서로 다른 normalized content를 가리키므로 member identity가 될 수 없다.

[현재] Product Dataset composition 구현은 typed candidate·review·handoff를 소비하지만 canonical candidate producer,
source-level Rights binding, Candidate A 전용 3-way split과 authority input owner가 결정되지 않아 rebuild가 fail closed했다.
이 ADR은 그 다섯 blocker만 해소하며 C1·C2·C3, Host, backend, Training intent, journal, DohaRights와 Model C를
변경하지 않는다.

## Decision summary

```text
CANONICAL_MEMBER_IDENTITY = existing source_id contract
CANONICAL_GROUP_KEY = group:sha256:<SHA-256(NFC(data_file) UTF-8)>
GROUP_KEY_SEMANTICS = canonical source-document/file leakage boundary
PRODUCTION_SPLIT_POLICY = group-preserving SHA-256 bucket split using src/data/splitting.py semantics
PRODUCTION_SPLIT_POLICY_VERSION = aihub-71748-production-split-v1
PRODUCTION_SPLIT_SEED = 17
TRAIN_RATIO = 0.90
VALIDATION_RATIO = 0.05
TEST_RATIO = 0.05
LEARNING_CANDIDATE_GRANULARITY = one candidate per selected canonical source record
LEARNING_CANDIDATE_PRODUCER = DohaLM Dataset Ingestion/Preparation Canonical Candidate Producer
CANDIDATE_RIGHTS_BINDING = candidate source_id -> canonical AIHUB-71748 source Rights Subject current record/token
CANDIDATE_ELIGIBILITY_BINDING = candidate-specific deterministic eligibility projection from exact source membership and approved Candidate A eligibility authority
SCHEMA_MANIFEST_AUTHORITY = pinned DohaStudio Common AI Contracts schema registry/package authority
DATASET_MANIFEST_AUTHORITY = DohaLM Product Dataset Build Manifest Producer
DATASET_ELIGIBILITY_AUTHORITY = DohaLM Dataset Governance Production Eligibility Authority
APPROVAL_EVIDENCE_AUTHORITY = DohaLM Dataset Governance Candidate Review Aggregate Authority
PRODUCT_DATASET_COMPOSITION_PRODUCER = DohaLM Dataset Governance Product Dataset Composition Producer
```

## Canonical member identity

[확정] member identity는 새 scheme이 아니라 기존 `source_id` 계약이다.

```text
source_id = sha256:<lowercase hex of
  SHA-256(archive_relative_path + "\0" + json_entry_path + "\0" + decimal_array_index)>
```

canonical path 문자열은 기존 ingestion 계약의 separator·Unicode 표현을 그대로 사용한다. 입력 archive 순서와 record
iteration 순서는 identity에 영향을 주지 않는다. normalized content가 바뀌어도 동일 source location의 identity는 유지되며,
content 변화는 별도 content fingerprint mismatch로 탐지한다. archive 또는 JSON entry 위치가 바뀌면 새 source member로
식별하는 것이 의도된 fail-closed 동작이다. SHA-256 collision은 authority error로 중단하며 임의 suffix를 붙이지 않는다.

## Leakage group과 split

[확정] canonical logical group value는 `NFC(data_file)`이고 저장·비교 key는
`group:sha256:<SHA-256(logical value UTF-8)>`다. `data_file`은 전체 source에서 누락 0, 93,999개 고유값, 최대
group 7이며 하나의 `data_file`이 여러 `data_source`에 연결된 경우는 0이다. production selection에서는 85,992개
group이고 missing과 multiple-source group은 각각 0이다.

`data_source`와 `data_title`은 각각 최대 group 8,192와 8,193으로 서로 독립적인 source document를 과도하게 묶는다.
`data_source + data_file`은 관측상 `data_file`보다 추가 분리 의미가 없다. 따라서 `data_file`을 canonical source-document/file
leakage boundary로 채택한다.

[확정] production v1은 exact source-document grouping만 보장한다. 승인된 fuzzy algorithm과 threshold가 없으므로 semantic
near-duplicate clustering을 조용히 추가하지 않는다. 이는 알려진 quality gap이며 후속 정책 변경은 새 version과 재승인을 요구한다.

[확정] split은 `src/data/splitting.py`의 deterministic primitive를 재사용한다. group마다 SHA-256
`f"{seed}\n{group_key}"`의 앞 8바이트를 unsigned big-endian 정수로 읽고 `[0, 1)` bucket으로 변환한다. 0.90 미만은
train, 0.95 미만은 validation, 나머지는 test다. Python `hash()`나 입력 순서를 사용하지 않는다.

선택된 production record 97,747건에 대한 read-only simulation 결과는 다음과 같다.

| split | records | groups |
|---|---:|---:|
| train | 88,071 | 77,524 |
| validation | 4,770 | 4,193 |
| test | 4,906 | 4,275 |

cross-split group overlap은 0이고 source 순서를 뒤집은 replay의 allocation은 동일했다. allocation fingerprint는
`sha256:0eee73ff569f1608183805deca1180bb3d8aa909c5fa0dd93d93904691c8308c`다. 이는 policy
evidence이며 이번 작업에서 split artifact를 생성했다는 뜻이 아니다.

## Candidate producer와 review

[확정] LearningCandidate는 historical selector와 승인된 PII exclusion을 통과한 canonical source record 하나를 나타낸다.
group은 split allocation 경계이지 candidate schema의 granularity가 아니다. 기존 Common schema를 변경하지 않는다.

candidate ID는 `candidate:aihub-71748-production-v1:<source_id lowerhex>`이고 content fingerprint는 기존 canonical
normalization 결과의 UTF-8 SHA-256이다. lineage는 archive relative path, JSON entry, array index, `source_id`, historical
selection contract와 source lineage material identity를 결속한다.

Common field는 `source_type=human_authored`, `task=base_pretraining`, `status=approved`로 고정한다. 이 `approved`는
canonical selection·policy evidence로 producer materialization이 허용됐다는 upstream candidate 상태이며, local
`LearningCandidateReviewResult`나 Dataset publication 승인이 아니다. `review_evidence_ids`는 ADR-035 policy evidence와
candidate validation evidence를 참조하고 비울 수 없다.

[확정] producer owner는 `DohaLM Dataset Ingestion/Preparation Canonical Candidate Producer`이며 ProducerIdentity는
`dohalm-dataset-ingestion / 1.0.0`이다. typed port는 canonical source record와 frozen policy/authority identity만 받고
deterministic frozen LearningCandidate를 반환한다. arbitrary candidate ID, review result, Rights result, eligibility boolean과
caller-selected lifecycle state를 받는 generic CRUD는 금지한다.

[확정] `DohaLM Dataset Governance Candidate Review Authority`가 deterministic validation-backed review를 발행한다.
ACCEPTED는 schema, source identity·lineage, content fingerprint, selector membership, group/split policy, current Rights와
current candidate eligibility가 모두 유효할 때만 가능하다. 사람의 승인은 policy·Dataset eligibility와 이후 Dataset
review/publication에 적용한다. record마다 사람이 97,747번 클릭하는 의미를 만들지 않는다.

## Rights와 eligibility binding

[확정] ADR-034의 canonical AIHUB-71748 source Dataset Rights Subject current record/token을 모든 candidate가 공유한다.
candidate lineage의 source identity와 Rights Subject의 Dataset source binding을 exact 검증한다. source-wide permission을
candidate별 97,747개 Rights record로 복제하지 않는다. missing, non-current, ambiguous 또는 scope mismatch는 fail closed한다.

[확정] Common TrainingEligibility가 candidate ID를 포함하므로 eligibility object는 candidate별 deterministic projection이다.
`DohaLM Dataset Governance Candidate Eligibility Producer`만 exact selector membership, shared current source Rights,
approved Candidate A production eligibility evidence, PII·lineage·content checks로 이를 생성한다. Dataset-level approval을
arbitrary boolean로 상속하거나 caller가 eligibility를 주입하지 않는다.

## Authority input ownership

| input | owner와 identity rule |
|---|---|
| schema manifest | pinned `dohastudio-common-ai-contracts` registry/package authority; `schema-manifest:dohastudio-common-ai-contracts:0.1.0:dd75fc88c16e9ae9a04acfafb72756a905f6365b` |
| Dataset manifest | `DohaLM Product Dataset Build Manifest Producer`; `dataset-manifest:aihub-71748-production-v1:<canonical manifest SHA-256 lowerhex>` |
| Dataset eligibility evidence | `DohaLM Dataset Governance Production Eligibility Authority`; `eligibility-evidence:aihub-71748-production-v1:e9087addc427fd508d66740296c6536a76bc9431a427f8a02828d1b117ff20b0` |
| approval evidence | `DohaLM Dataset Governance Candidate Review Aggregate Authority`; `approval-evidence:aihub-71748-production-v1:<canonical accepted-review aggregate SHA-256 lowerhex>` |
| composition producer | `DohaLM Dataset Governance Product Dataset Composition Producer`, ProducerIdentity `dohalm-product-dataset-composition / 1.0.0` |
| `created_by` | stable actor `dohalm-dataset-governance-candidate-a-production-v1`; 개인 이름·runtime UUID·clock 금지 |

authority IDs는 owner가 canonical payload로 발행하거나 deterministic derive한다. random/synthetic UUID, filesystem path와
runtime timestamp는 authority identity가 아니다. eligibility evidence digest는 approved
`aihub-71748-candidate-a-internal-production-eligibility.manifest.yaml` bytes의 SHA-256이다. exact schemas와 persistence
surface 구현은 후속 rebuild implementation 범위다.

## Historical fingerprint clarification

[확정] `sha256:bea1f19b...eb4293` 계열 값은 historical selection을 포함한 상위 canonical source contract
fingerprint다. `sha256:3df6d9a21659d95c87df97926941dabd0fc77ccbfd3d45d223518ecb26e5668e`는
prepared manifest에 내장된 exact `selection_contract` mapping의 checksum이다. 둘은 서로 다른 canonical projection이며
동일해야 하는 값이 아니다. historical `aihub-71748-training-selection-v1`은 candidate inclusion 전단계로 재사용하되,
새 3-way allocation을 대신하지 않는다.

## Consequences and boundaries

- 다섯 provenance blocker는 architecture 수준에서 해소된다.
- rebuild implementation은 이 ADR의 exact identities·policy·ports를 구현할 수 있다.
- C1·C2·C3, Host, backend, Training intent, journal, DohaRights, Model C와 required-check ruleset semantic diff는 0이다.
- production source code, migration, Dataset rebuild artifact, Dataset publication과 Training workload는 이 결정에 포함되지 않는다.
- commercial use, redistribution, model publication과 external deployment 권한은 생성되지 않는다.
