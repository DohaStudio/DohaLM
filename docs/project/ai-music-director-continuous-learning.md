# AI Music Director와 Product Continuous Learning 경계

- 문서 상태: `review`
- 마지막 검토일: 2026-08-26
- 선행 결정: [ADR-014](../decisions/ADR-014-dataset-product-governance-boundary.md), [ADR-021](../decisions/ADR-021-production-training-adapters-and-durable-journal.md)
- 제안 결정: [ADR-024](../decisions/ADR-024-ai-music-director-product-boundary.md)
- proposal 결정: [ADR-025](../decisions/ADR-025-dataset-version-proposal-authority-contract.md)
- review authority 결정: [ADR-026](../decisions/ADR-026-dataset-review-authority-contract.md)
- publication read 결정: [ADR-031](../decisions/ADR-031-dataset-publication-pair-public-read-contract.md)

## 목적

이 문서는 현재 구현된 Foundation 실행 기반과 아직 제안 단계인 AI Music Director 제품·지속 학습 기능을 분리한다. Common AI Contract를 단일 의미 기준으로 사용하며 새 schema나 병렬 ownership을 만들지 않는다.

## 현재와 계획

| 영역 | 현재 authority·구현 | 계획 상태 |
|---|---|---|
| 프로젝트 정의 | reusable LLM model provider | AI Music Director intelligence provider는 ADR-024 제안 |
| Dataset governance | DohaLM의 immutable DatasetVersion·Manifest publication 구현 | 제품 candidate를 Dataset으로 승격하는 policy는 미구현 |
| Foundation execution | explicit approval, PostgreSQL authority·journal, Host·composition 구현 | 기존 계보 유지 |
| Product/adapter learning | Common LearningCandidate 소비, explicit local review Gate와 Dataset inclusion handoff 구현 | persistence·product DatasetVersion assembly·Training request·Evaluation Gate는 미구현 |
| Reference·Similarity | Common 객체 정의만 authority | DohaLM typed consumer·해석 capability 미구현 |
| Model promotion | 자동 promotion 없음 | Evaluation과 별도 사용자 승인 계약 필요 |

## Authoritative owner matrix

| 책임 | owner | DohaLM 경계 |
|---|---|---|
| Workspace·MusicProject·Asset·AssetVersion·Artifact·Composition·Job persistence와 orchestration | DohaMusic | 제품 intelligence만 제공 |
| `LearningCandidate`, rights·consent evidence | DohaMusic·권리 검토 계층 / Common authority | 직접 생성하지 않음 |
| music/audio generation·stem separation·analysis·mix·audio runtime | DohaAudio | `ReferenceAnalysis`·`FeatureRecord` 소비 후보 |
| singing·voice conversion·vocal correction·analysis·vocal runtime | DohaVocal | typed evidence 소비 후보 |
| DatasetVersion·Manifest publication | DohaLM | 현행 immutable publication 유지 |
| Training·Evaluation·Model lineage | DohaLM / Common authority | Foundation과 product 계보 분리 |
| planning·lyrics·prompt·QA·RevisionPlan | DohaLM | ADR-024 승인 뒤 세부 capability 결정 |

## 객체별 현재성

| 객체·단계 | 현재 상태 | 다음 Gate |
|---|---|---|
| `LearningCandidate` | Common 계약 소비, current evidence review와 Dataset inclusion handoff 구현 | producer/transport와 review·handoff persistence |
| `RightsMetadata` | upstream authoritative evidence; DohaLM producer 아님 | exact consumer boundary |
| `TrainingEligibility` | DohaLM Dataset governance의 candidate 단위 Gate | authoritative producer workflow |
| `DatasetVersion`, `DatasetManifest` | governance·publication 구현 | product candidate 승격 policy |
| `TrainingRun` | Common lineage와 local Foundation execution 존재 | product run identity 분리 |
| `EvaluationRun` | Common lineage; product promotion pipeline 없음 | evaluation contract |
| `ModelVersion` | Common lineage; 자동 runtime promotion 없음 | promotion decision |
| `ReferenceAnalysis`, `FeatureRecord` | DohaLM consumer 없음 | typed capability port |
| `SimilarityReport` | DohaLM consumer 없음; 법적 판단 아님 | evidence interpretation Gate |
| `RevisionPlan` | runtime producer 없음 | product output contract |

## 허용되는 흐름

```text
LearningCandidate creation and review
  -> current RightsMetadata and TrainingEligibility
  -> immutable Dataset inclusion handoff
  -> DatasetVersion draft inclusion
  -> Dataset-level eligibility validation and review
  -> approved DatasetVersion, issued Manifest and freeze
  -> explicit Training approval and durable journal
  -> TrainingRun
  -> EvaluationRun
  -> separate ModelVersion/runtime promotion decision
```

- [확정] 각 화살표는 독립 Gate다.
- [확정] candidate 또는 similarity evidence가 Training approval을 암묵적으로 만들지 않는다.
- [확정] 사용자 수정과 생성 결과는 candidate review 없이 Dataset에 자동 편입되지 않으며, rights·eligibility evidence가 missing·unknown·expired·revoked·invalid이면 fail closed한다.
- [확정] source와 parent lineage는 끝까지 보존한다. Foundation checkpoint와 product/adapter artifact는 별도 identity·lineage record를 사용하되 승인된 명시적 parent/source reference로 연결할 수 있다.
- [확정] Provider끼리 직접 호출하지 않으며 DohaMusic이 Common intent·capability에 따라 orchestration한다.
- [확정] 현재 문서는 물리적 directory 이동이나 schema migration을 지시하지 않는다.

## 구현된 consumer와 review boundary

- [현재] `src.data.learning_candidate_consumer.validate_learning_candidate_for_consumption()`은 pinned Common package로 LearningCandidate·RightsMetadata·TrainingEligibility를 검증하고 immutable consumer view만 반환한다.
- [현재] schema·version·identity·workspace scope, review·consent evidence, source lineage, purpose-matched eligibility와 rights·retention expiry/revocation을 fail closed한다.
- [현재] 입력 payload를 변경하거나 보존하지 않으며 DB persistence, Dataset publication, Training·Evaluation과 promotion을 호출하지 않는다.
- [현재] `src.data.learning_candidate_review.review_learning_candidate()`은 `ValidatedLearningCandidate`만 candidate 입력으로 받고, 명시적 reviewer·reviewed_at·decision과 주입된 current authority port를 사용한다.
- [현재] review 시점의 canonical RightsMetadata·TrainingEligibility를 다시 검증하며 unresolved evidence는 `NEEDS_REVIEW`, 만료·철회·policy-invalid evidence는 `REJECTED`, contract·identity·lineage·scope 위반은 error로 fail closed한다.
- [현재] `ACCEPTED`는 Dataset inclusion review 진입 가능성만 뜻하며 Dataset inclusion/publication, Training request·실행, Evaluation·promotion 권한을 만들지 않는다.
- [현재] `src.data.learning_candidate_dataset_handoff.create_dataset_inclusion_handoff()`는 exact `LearningCandidateReviewResult(decision=ACCEPTED)`만 받고 handoff 시점의 current RightsMetadata·TrainingEligibility를 동일 authority와 Common validator로 다시 확인한다.
- [현재] `DatasetInclusionHandoff`는 candidate·review·evidence·lineage·workspace identity를 보존하는 immutable local lifecycle object이며 별도 Dataset inclusion review의 입력 후보일 뿐이다.
- [현재] handoff 생성은 DatasetVersion을 만들거나 Dataset governance/publication 함수를 호출하지 않으며 Training·Evaluation·promotion, persistence와 API side effect가 없다.
- [현재] `src.data.product_dataset_composition.compose_product_dataset()`은 여러 exact `DatasetInclusionHandoff`와 명시적인 DohaLM Dataset-level authority input을 immutable `ProductDatasetComposition`으로 조립한다.
- [현재] composition은 handoff identity와 current rights·eligibility를 재검증하고, train·validation·test member, group key, workspace, source·review lineage와 Dataset identity를 결정론적으로 결속한다.
- [현재] `build_dataset_version_proposal_mapping()`은 arbitrary caller payload 없이 완전한 Common DatasetVersion `draft` mapping을 side-effect-free하게 만들고 Common validator로 검증한다. 이 호출은 Dataset governance proposal을 생성하지 않는다.
- [현재] Consumer, Candidate Review, Dataset Inclusion Handoff, Product Dataset Composition, DatasetVersion Proposal Authority, Product DatasetVersion Governance Integration, durable PostgreSQL proposal·review authority adapter와 Product Dataset Review Start·Approval·Publication Integration까지 구현됐다. Publication v1의 durable Dataset Approval Authority는 `NOT REQUIRED`이며 Product Training Request, Evaluation·Promotion과 Reference·Similarity는 계획 상태다.

## DatasetVersion proposal authority

- [현재] `adjudicate_dataset_version_proposal()`은 완전한 proposal mapping, timezone-aware `proposed_at`, current evidence authority와 proposal authority를 모두 필수 입력으로 받는다.
- [현재] 순수 `propose_dataset_version()`의 canonical draft payload checksum을 proposal fingerprint로 사용하며 adjudication 시각은 fingerprint에 포함하지 않는다.
- [현재] current RightsMetadata·TrainingEligibility는 생성뿐 아니라 replay 전에도 proposal identity·fingerprint와 결속해 다시 검증한다.
- [현재] proposal authority는 `DatasetVersionIdentity`로 lookup과 put-if-absent를 하나의 atomic operation으로 수행한다. absent는 `CREATED`, 동일 canonical proposal은 기존 object를 `REPLAYED`, 다른 canonical proposal은 overwrite 없는 conflict다.
- [현재] caller가 existing lookup을 생략하거나 read-then-write로 대체할 수 없고, product code에는 persistence 또는 process-global authority cache가 없다.
- [현재] 결과는 계속 `draft/false/false/false`이며 Dataset review·approval, Manifest publication, Training request 또는 실행을 호출하지 않는다.
- [현재] `PostgresDatasetProposalAuthority`는 별도 `dohalm_dataset_governance_v1` schema의 immutable authority row와 restricted function으로 durable create·replay·conflict를 구현한다. Composite identity별 transaction advisory lock 뒤 새 `READ COMMITTED` statement에서 DB primary key를 최종 authority로 판정하며 자동 retry는 없다. runtime composition 등록은 별도 승인 Gate다.
- [현재] PostgreSQL adapter는 `DatasetProposalCurrentEvidenceAuthority`를 소유하지 않으며 caller가 proposal 시점 current evidence Gate를 통과한 뒤에만 명시적으로 주입한다.

## Product DatasetVersion governance integration

- [현재] `propose_product_dataset_version()`은 exact `ProductDatasetComposition`만 받고 기존 `build_dataset_version_proposal_mapping()`과 `adjudicate_dataset_version_proposal()`을 순서대로 호출한다.
- [현재] composition integrity와 Common DatasetVersion validation이 완료된 뒤 proposal 시점의 current RightsMetadata·TrainingEligibility를 검증하고, mandatory atomic authority에서 `CREATED`, `REPLAYED` 또는 conflict를 판정한다.
- [현재] integration은 기존 `DatasetProposalAuthorityResult`를 그대로 반환한다. 새 identity, fingerprint, lifecycle state 또는 arbitrary caller override를 만들지 않는다.
- [현재] create와 replay 결과는 `draft/approved=false/frozen=false/training_allowed=false`를 유지하며 review·approval·publication·Training·Evaluation·promotion을 호출하지 않는다.
- [현재] persistent PostgreSQL adapter는 dependency-injected production implementation으로 제공되지만 자동 runtime activation은 없다. Dataset review·approval·publication과 전체 production Dataset lifecycle 완료를 뜻하지 않는다.

## Dataset Review Authority architecture

- [제안] ADR-026은 DohaLM Dataset Governance를 Dataset Review Authority owner로 두고 immutable proposal authority와 durable review lifecycle authority를 분리한다.
- [제안] review lifecycle은 `DatasetVersionIdentity`와 canonical proposal fingerprint에 결속하며 authoritative proposal read, explicit opaque reviewer, timezone-aware `review_started_at`과 current RightsMetadata·TrainingEligibility Gate를 요구한다.
- [현재] review persistence는 단일 active lifecycle과 atomic `STARTED`·`REPLAYED`·`CONFLICT`, restart durability, corruption fail-closed와 approval이 사용할 authoritative review read를 PostgreSQL restricted boundary로 제공한다.
- [현재] Dataset Proposal Authority public authoritative read는 기존 restricted PostgreSQL function을 통해 구현됐으며 identity·canonical payload·fingerprint·authority metadata를 재검증한다. Product Dataset Review Start Integration은 이 public read, `review_started_at` 기준 current evidence Gate, Review Authority atomic start와 `begin_dataset_review()` 순수 transition을 순서대로 연결한다. proposal row는 계속 immutable `draft`이며 approval·publication·Training side effect와 runtime activation은 없다.
- [현재] Product Dataset Approval Integration은 identity·proposal fingerprint·approval evidence IDs·explicit approval 평가 시각만 받고 authoritative proposal read와 immutable Review Authority read를 검증한 뒤 approval-time current evidence와 기존 순수 `approve_dataset_version()`을 연결한다. caller-created `reviewing` payload를 받지 않으며 proposal·review row를 수정하지 않는다. 결과는 Publication v1의 transient validated input candidate이고 별도 durable Approval Authority·approval replay/conflict는 두지 않는다.
- [현재] `publish_product_dataset_version()`은 매 invocation마다 Product Approval Integration을 다시 실행한 뒤 transient `ApprovedDatasetVersion`만 기존 `publish_dataset_version()`에 전달한다. caller-created approved/frozen/Manifest payload를 받지 않으며, committed frozen DatasetVersion·issued DatasetManifest pair가 유일한 durable Publication 결과다. runtime activation·Training 연결은 없다.
- [제안] Product Dataset Governance Runtime Activation Architecture Gate 판정은 `BLOCKED — PRIOR ARCHITECTURE REQUIRED`다. standalone publication read는 구현됐지만 현재 chain은 service-only이며 production current-evidence authority, governance runtime config·secret/composition owner와 reviewer trust policy 전에는 CLI·API·worker를 활성화하지 않는다. 선행 계약 완료 뒤 첫 재검토 후보는 operator-driven CLI지만 아직 지원·구현 승인이 아니다.
- [제안] [ADR-027](../decisions/ADR-027-dataset-governance-production-prerequisites.md)은 production CurrentEvidence source를 `D. BLOCKED — EVIDENCE SOURCE NOT DEFINED`, config/composition을 `B. NEW DOHALM GOVERNANCE RUNTIME CONFIG REQUIRED`로 판정한다. Common validator는 source가 아니며 새 config도 reviewer trust를 만들지 않는다. 전체 prerequisite는 `STILL BLOCKED`이고 CLI 구현은 시작하지 않는다.
- [제안] [ADR-028](../decisions/ADR-028-current-evidence-source-authority.md)은 접근 가능한 DohaStudio 구현에서 canonical producer를 찾지 못했다. Rights producer·authority와 unique-current projection/cross-source snapshot은 `BLOCKED`, TrainingEligibility는 새 DohaLM Dataset Governance producer·durable authority가 `REQUIRED`다. existing publication pair는 authority revision/snapshot을 결속하지 않으므로 Publication binding Gate 전 port/adapter design과 runtime activation을 시작하지 않는다.
- [제안] [ADR-029](../decisions/ADR-029-rights-metadata-ownership-authority.md)은 Common의 DohaMusic Rights·Consent 방향과 voice consent 구현을 조사했지만 모든 source 유형의 accountable owner, canonical producer, logical Rights chain key, revoke writer와 authenticated read owner를 승인할 근거가 부족하다고 판정한다. Rights Authority contract는 `STILL BLOCKED`이며 다음 단계는 cross-repository·organizational ownership 결정이다.
- [제안] [ADR-030](../decisions/ADR-030-cross-repository-rights-domain-ownership.md)은 여섯 repository를 비교해 DohaMusic을 strongest existing candidate, 새 Rights domain을 leading architecture alternative로 식별했지만 organizational/legal actor·stable source identity·writer·authority/read owner가 승인되지 않아 Option D와 overall `STILL BLOCKED`를 선택한다. DohaLM ownership은 Dataset consumer 경계 위반으로 기각하며 구현은 시작하지 않는다.
- [현재] [ADR-031](../decisions/ADR-031-dataset-publication-pair-public-read-contract.md)의 committed frozen/issued pair standalone read를 exact identity Authority Protocol, explicit-root filesystem adapter, immutable result와 full pair-local verification으로 구현했다. runtime/CLI/API와 current Training permission은 활성화하지 않는다.
- [현재] [Rights Owner Decision Request](../decisions/rights-owner-decision-request.md)는 accepted authentication ADR과 병합 PR을 재검증했다. DohaMusic identity/issuer와 DohaAudio semantic ReviewerAuthority는 부분 승인됐지만 source-wide Rights business owner·identity·writers·authority/read owner는 승인되지 않아 Option D를 유지한다.

## Product continuous learning 구현 상태

| 단계 | 상태 |
|---|---|
| LearningCandidate Consumer | `CURRENT` |
| Candidate Review Gate | `CURRENT` |
| Dataset Inclusion Handoff | `CURRENT` |
| Product Dataset Composition | `CURRENT` |
| Dataset Proposal Authority Contract | `CURRENT` |
| Product DatasetVersion Governance Integration | `CURRENT` |
| Persistent Dataset Proposal Authority Adapter | `CURRENT` |
| Dataset Proposal Authoritative Read | `CURRENT` |
| Dataset Review Authority Architecture | `DRAFT` |
| Dataset Review Authority Python Port | `CURRENT` |
| Persistent Dataset Review Authority | `CURRENT` |
| Dataset Review Start Integration | `CURRENT` |
| Dataset Approval Integration | `CURRENT` |
| Dataset Publication Integration | `CURRENT` |
| Dataset Publication Pair Public Read Contract | `DRAFT — PROPOSED` |
| Dataset Publication Pair Public Read Implementation | `IMPLEMENTED` |
| Production RightsMetadata Producer/Authority | `BLOCKED` |
| Production TrainingEligibility Producer/Authority | `REQUIRED` |
| Production CurrentEvidence Source | `BLOCKED` |
| CurrentEvidence Projection/Snapshot | `BLOCKED` |
| Governance Runtime Config Architecture | `DRAFT` |
| Dataset Governance Runtime Activation | `BLOCKED` |
| Product/Adapter Training Request | `PLANNED` |
| Evaluation | `PLANNED` |
| Promotion | `PLANNED` |
| Reference/Similarity Runtime | `PLANNED` |

## Product Dataset composition field authority

단일 handoff는 Dataset aggregate authority가 아니다. Dataset identity·version·split·group과 Dataset-level evidence는 `ProductDatasetCompositionAuthorityInput`의 명시적 값이며, member identity·content·review·source lineage는 검증된 handoff에서만 파생한다.

| Common DatasetVersion field | authoritative source |
|---|---|
| `object_id`, `dataset_id`, `dataset_version` | explicit Dataset composition authority |
| `created_at`, `created_by`, `producer`, `workspace_id` | explicit Dataset composition authority |
| `schema_manifest_id`, `dataset_manifest_id` | explicit Dataset composition authority; publication은 수행하지 않음 |
| `dataset_eligibility_evidence_id`, `approval_evidence_ids` | explicit Dataset composition authority |
| `usage_purpose`, `task` | 모든 validated handoff에서 동일함을 확인한 뒤 파생 |
| `lineage` | candidate identity·schema version·content fingerprint의 canonical projection |
| `split_manifest`, `candidate_count` | explicit handoff allocation과 validated member 집합 |
| `created_from` | canonical source·parent·handoff lineage fingerprint |
| `content_fingerprint` | canonical candidate content·split·group projection fingerprint |
| `rights_summary` | composition 시점 current evidence가 전부 pass한 결과 |
| `status`, `approved`, `frozen`, `training_allowed` | 고정된 proposal-only 값 `draft/false/false/false` |

필수 Common field의 unresolved source는 0이다. Composition ID는 명시적 Dataset authority, canonical member ordering, handoff·review·source lineage, split·group과 content fingerprint를 결속한다. 입력 순서와 composition 실행 시각은 logical identity나 proposal mapping 의미가 아니며 runtime clock, UUID 또는 silent default를 사용하지 않는다. Safe member binding은 namespaced extension에 보존하므로 source·parent·review lineage가 proposal mapping에서 끊기지 않는다.

`ProductDatasetComposition`은 Common DatasetVersion, Dataset approval, publication, Training readiness 또는 실행 권한이 아니다. Governance proposal·review·approval, publication, persistence, Training, Evaluation과 promotion 호출은 모두 후속 explicit Gate다.

## 후속 결정 순서

1. [제안] ADR-024 제품 방향 승인 여부 결정
2. [계획] cross-repository producer/consumer 및 version mapping 확정
3. [계획] Reference·Similarity typed capability API 결정
4. [계획] product Dataset 승격과 Evaluation 기준 결정
5. [계획] Model promotion·runtime delivery 결정
6. [계획] 명시 승인된 최소 integration 구현

## 역사적 출처

- [확정] PR #103은 2026-08-20 기준 current `develop`과 충돌하는 미병합 초안이다.
- [확정] 당시 repository inventory, `not_started` 표, 별도 schema와 directory migration 제안은 현재 authority가 아니다.
- [확정] 이 문서는 그 초안에서 제품 방향과 Foundation/product learning 분리 원칙만 현행 Common contract와 ADR에 맞춰 이관했다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-26 | Dataset Publication Pair exact-identity public read port·immutable record·explicit-root filesystem adapter와 full pair-local verification 구현 반영; runtime activation은 계속 차단 |
| 2026-08-25 | Rights Owner Decision Request의 explicit approval READY 기준과 authentication 부분 승인·전체 Rights ownership 분리, Option D 유지 반영 |
| 2026-08-25 | ADR-030의 cross-repository Rights ownership Option D·organizational approval `REQUIRED`·overall `STILL BLOCKED` 판정 반영 |
| 2026-08-25 | ADR-029의 RightsMetadata accountable owner·producer·logical key·revoke/read authority `STILL BLOCKED` 판정 반영 |
| 2026-08-25 | ADR-028의 Rights source·projection/snapshot BLOCKED, 새 DohaLM TrainingEligibility producer/authority REQUIRED와 Publication binding blocker 반영 |
| 2026-08-25 | ADR-027 prerequisite Gate의 CurrentEvidence source `BLOCKED`, 새 DohaLM governance config `REQUIRED`, overall `STILL BLOCKED` 판정 반영 |
| 2026-08-25 | Runtime Activation Architecture Gate를 선행 current-evidence/config·secret/reviewer trust/publication read architecture 부족으로 `BLOCKED` 판정하고 CLI를 첫 재검토 후보로 한정 |
| 2026-08-25 | authoritative Proposal·Review와 publication-time current evidence로 transient approval을 재구성하고 기존 atomic publication pair를 발행하는 Product Dataset Publication Integration 구현 반영 |
| 2026-08-25 | Dataset Approval Authority Architecture Gate에서 Publication v1은 `NOT REQUIRED`로 판정하고 fresh approval validation과 frozen/issued pair authority 경계를 반영 |
| 2026-08-25 | authoritative Proposal·Review read와 approval-time current evidence를 기존 pure approval transition에 연결; caller reviewing payload·row mutation·durable Approval Authority·runtime·publication 없음 |
| 2026-08-24 | Product Dataset Review Start Integration의 authoritative proposal read·current evidence replay Gate·atomic review start·순수 reviewing representation 연결 반영; approval·runtime activation 미구현 |
| 2026-08-24 | Dataset Review Authority PostgreSQL persistence·restricted start/read·restart/concurrency/corruption 최소 검증 반영; Product Review Start는 미구현 |
| 2026-08-24 | Dataset Review Authority Python start/read port와 immutable request·record·outcome·fingerprint 계약 반영; persistence와 Product Review Start는 미구현 |
| 2026-08-21 | DatasetVersionIdentity 기반 immutable Dataset Proposal authoritative read와 restricted PostgreSQL 재검증 경계 반영 |
| 2026-08-21 | immutable proposal과 분리된 Dataset Review Authority의 owner·authoritative reads·reviewer/time·current evidence·durable start 의미를 ADR-026 제안으로 등록 |
| 2026-08-21 | DatasetVersionIdentity DB uniqueness, immutable canonical payload와 atomic create·replay·conflict를 제공하는 PostgreSQL proposal authority adapter 반영 |
| 2026-08-21 | Product Dataset composition을 기존 canonical builder와 mandatory Dataset Proposal Authority에 연결하는 draft-only governance integration 반영 |
| 2026-08-21 | DatasetVersion proposal의 mandatory atomic authority, create·replay·conflict와 proposal-time current evidence 재검증 경계 반영 |
| 2026-08-21 | 단일 handoff의 aggregate authority 한계를 해소하는 immutable Product Dataset composition과 side-effect-free Common DatasetVersion draft mapping 경계 반영 |
| 2026-08-21 | ACCEPTED review의 current evidence를 재검증하는 immutable Dataset inclusion handoff와 DatasetVersion/publication 비자동화 경계 반영 |
| 2026-08-20 | ValidatedLearningCandidate 기반 explicit review와 review 시점 current rights·eligibility 재검증 Gate 구현 상태 반영 |
| 2026-08-20 | Common LearningCandidate·RightsMetadata·TrainingEligibility fail-closed consumer boundary 구현 상태와 후속 Gate 분리 |
| 2026-08-20 | PR #103의 제품 방향을 current authority에 맞춰 이관하고 Provider ownership, candidate Gate와 Foundation/product learning을 분리 |
