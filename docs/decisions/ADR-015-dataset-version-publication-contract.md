# ADR-015: Common DatasetVersion·DatasetManifest publication 계약

- 문서 상태: `draft`
- 마지막 검토일: 2026-08-12
- 결정 상태: `proposed`
- 실행 영향: 없음
- 권위 기준: `DohaStudio/.github@dd75fc88c16e9ae9a04acfafb72756a905f6365b`
- 권위 tree: `217ed885d2555d753c785cd00df1c836a52095c3`
- package: `dohastudio-common-ai-contracts==0.1.0`
- namespace: `dohastudio_common_ai`
- 실행 policy: `1.0.0`
- 관련 문서: [ADR-004](./ADR-004-data-governance.md),
  [ADR-013](./ADR-013-initial-common-ai-contract-consumer-boundary.md),
  [ADR-014](./ADR-014-dataset-product-governance-boundary.md),
  [Dataset Registry](../data/dataset-registry.md)

## Context와 문제 정의

[확정] ADR-014는 DohaLM이 미래 Dataset governance와 Dataset publication을 소유하고, 공식 lifecycle을
`Approved → Manifest Issued → Freeze`로 처리하도록 경계를 정했다. 다만 canonical resource, package public API,
validation 순서와 publication transaction의 구체적인 설계는 후속 resource-specific ADR로 남겼다.

[확정] authority의 `DatasetVersion`은 Dataset identity, 집합 eligibility, approval, split와 freeze의 논리 권위이고,
`DatasetManifest`는 그 Version에 ID·checksum으로 결속된 발행 후 immutable reproduction evidence다. frozen
`DatasetVersion`은 issued `DatasetManifest` 없이는 authority validator의 Dataset Gate를 통과할 수 없다.

[확정] 현재 DohaLM의 `src.data.pipeline.build_pipeline()`은 legacy corpus를 처리하고
`AtomicArtifactDirectory` staging에서 `source-manifest.json`을 만든 뒤 원자적으로 디렉터리를 게시한다. 이 구현은
Common `DatasetVersion` 또는 `DatasetManifest`를 생성·검증·발행하지 않는다. 설정과 문서의 `dataset_version` 문자열,
기존 registry entry, readiness·approval evidence도 Common 객체가 아니다.

[확정] 현재 dependency와 source에는 `dohastudio-common-ai-contracts` 또는 `dohastudio_common_ai`가 없다. 따라서 이
ADR은 구현을 완료하거나 dependency를 추가하지 않고, 후속 구현이 진입하기 전에 필요한 resource와 transaction 계약만
결정한다.

## Authority 조사 결과

아래 표의 schema와 public symbol은 pinned authority의 실제 파일과 export를 기준으로 한다.

| 조사 명칭 | canonical schema·`$id` | package public 접근 | 이번 결정 |
|---|---|---|---|
| `LearningCandidate` | `learning-candidate.schema.json` · `https://schemas.dohastudio.org/common-ai/v1/learning-candidate.schema.json` | `get_schema("learning_candidate")`, `validate_contract(payload, "learning_candidate")` | 인접 입력, 미채택 |
| `RightsEvidence` | 별도 schema·`$id` 없음. canonical resource는 `rights-metadata.schema.json` · `https://schemas.dohastudio.org/common-ai/v1/rights-metadata.schema.json` | `get_schema("rights_metadata")`, `validate_contract(payload, "rights_metadata")` | 명칭 치환 금지, 미채택 |
| `ConsentEvidence` | 별도 schema·`$id`·export 없음. `RightsMetadata.consent_evidence_refs`만 존재 | 별도 symbol 없음 | 비공개 evidence reference, 미채택 |
| `ReviewEvidence` | 별도 schema·`$id`·export 없음. `LearningCandidate.review_evidence_ids`와 approval evidence ID만 존재 | 별도 symbol 없음 | evidence ID, 미채택 |
| `TrainingEligibility` | `training-eligibility.schema.json` · `https://schemas.dohastudio.org/common-ai/v1/training-eligibility.schema.json` | `get_schema("training_eligibility")`, `validate_contract(payload, "training_eligibility")` | Dataset 집합 Gate 입력, 미채택 |
| `DatasetVersion` | `dataset-version.schema.json` · `https://schemas.dohastudio.org/common-ai/v1/dataset-version.schema.json` | `get_schema("dataset_version")`, `validate_contract(payload, "dataset_version")` | 채택 |
| `DatasetManifest` | `dataset-manifest.schema.json` · `https://schemas.dohastudio.org/common-ai/v1/dataset-manifest.schema.json` | `get_schema("dataset_manifest")`, `validate_contract(payload, "dataset_manifest")` | 채택 |

모든 resource의 공통 envelope와 `$ref`는 package의 `build_registry()`가 구성하는 offline registry에서 해결한다.
`$id`는 identifier이며 network endpoint가 아니다. `validate_scenario()`는 DatasetVersion·DatasetManifest identity 결속,
candidate별 current eligibility와 rights, split·group 누수 및 manifest lineage를 함께 검증하는 public API다.

### Version compatibility

- [제안] consumer는 package `0.1.0`, policy `1.0.0`과 authority Git commit·tree를 immutable하게 pin한다.
- [제안] 직렬화 객체는 `schema_version` major `1`만 허용한다. patch는 compatible이다.
- [제안] 이후 `1.x` minor는 새 값이 namespaced `extensions`에만 있을 때 authority policy가 허용하는 범위에서 수용한다.
- [제안] unknown major, unknown core field, unknown enum, deprecated version, unknown resource와 unresolved `$ref`는 fail closed다.
- [제안] package version, policy version과 객체 `schema_version`은 서로 다른 version 축이며 대체하지 않는다.

### 채택 resource의 필수성과 불변성

`DatasetVersion`은 envelope 외에 `dataset_id`, `dataset_version`, `status`, `usage_purpose`, `task`, `lineage`,
`created_from`, `candidate_count`, `split_manifest`, `schema_manifest_id`, `rights_summary`,
`dataset_eligibility_evidence_id`, `approval_evidence_ids`, `approved`, `frozen`, `training_allowed`,
`dataset_manifest_id`, `content_fingerprint`가 필수다. frozen 상태는 approved·frozen·training_allowed가 모두 true이고,
issued Manifest와 identity가 일치해야 한다. frozen payload는 제자리 수정하지 않는다.

`DatasetManifest`는 envelope 외에 `dataset_manifest_id`, `manifest_status`, `manifest_format_version`,
`source_dataset_version_id`, `source_dataset_version_checksum`, `dataset_id`, `dataset_version`, `dataset_domain`,
`source`, `license_status`, `training_allowed`, `commercial_usage_status`, `redistribution_allowed`, `item_count`,
`manifest_checksum`, `object_file_artifact_refs`, `content_checksum_set_id`, `split_id`, `deletion_status`가 필수다.
issued Manifest는 terminal immutable record이며 replacement는 새 ID와 선형 `supersedes` lineage를 사용한다.

두 schema는 각각 `common-envelope.schema.json`과 그 `$defs`만 직접 `$ref`한다. DatasetVersion과 DatasetManifest의
상호 관계는 embedded `$ref`가 아니라 stable ID·checksum과 `validate_scenario()`의 cross-object invariant로 강제한다.

## Decision

### 최소 coherent resource set

[제안] 첫 DohaLM Common resource set으로 `DatasetVersion`과 `DatasetManifest`를 함께 채택한다. DatasetVersion approval,
Manifest issuance와 freeze가 하나의 publication transaction이고, frozen Version의 `dataset_manifest_id`와 Manifest의
`source_dataset_version_id`·`source_dataset_version_checksum`을 분리해 발행할 수 없기 때문이다.

[제안] `LearningCandidate`, `RightsMetadata`와 `TrainingEligibility`는 Dataset 집합 validation에 필요한 upstream
reference/evidence다. 이번 ADR은 그 객체의 producer·review lifecycle이나 별도 소비 구현을 채택하지 않는다. 특히 authority에
없는 `RightsEvidence`, `ConsentEvidence`, `ReviewEvidence` resource·symbol을 만들지 않는다.

### Producer boundary

[제안] future DohaLM Dataset Governance boundary는 승인 전 `DatasetVersion` proposal, 집합 eligibility 검증과 approval
evidence 결속을 책임진다. future DohaLM Dataset Publication boundary는 approved DatasetVersion을 입력으로
DatasetManifest draft를 구성하고 issuance·freeze transaction을 책임진다.

[검증 필요] 두 boundary의 실제 module·class·function과 persistence 기술은 아직 존재하거나 승인되지 않았다. 구현 이름을
이 ADR에서 발명하지 않으며 후속 구현 계획에서 실제 경로를 제안하고 검증한다. `.github`는 schema·resource
semantics·version·compatibility authority일 뿐 product workflow 또는 Runtime data producer가 아니다.

### Consumer boundary

[제안] future DohaLM training-entry boundary는 외부에 공개된 frozen DatasetVersion과 issued DatasetManifest pair를
명시적으로 전달받는 첫 consumer다. pair의 Common validation과 DohaLM domain validation을 모두 통과하기 전에는 Dataset
artifact, Model, Provider를 열거나 Training/Evaluation을 실행할 수 없다.

[검증 필요] consumer의 실제 module·function과 current/replacement 조회 저장 기술은 후속 구현 설계에서 정한다. 현재
`src.training.full_pretraining.inspect_full_pretraining_readiness()`, `require_full_pretraining_approval()`과
`src.data.tokenized_dataset.TokenizedJsonlDataset`은 legacy domain readiness·Dataset reader이며 Common consumer로
승격하거나 이름만 재사용하지 않는다.

### Public package API

후속 구현은 namespace root의 public API만 사용한다.

```text
get_schema("dataset_version")
get_schema("dataset_manifest")
validate_contract(dataset_version_payload, "dataset_version")
validate_contract(dataset_manifest_payload, "dataset_manifest")
validate_scenario(publication_scenario)
contract_policy_version()
build_registry()
```

package 내부 module·filesystem path, authority schema 복사본, 전체 resource switch, private Registry와 Runtime network lookup을
사용하지 않는다. 정확한 dependency source와 requested/resolved Git commit 결속 방식은 후속 구현 진입 시 결정하며 이
ADR은 dependency 변경을 수행하지 않는다.

## Validation 순서와 fail-closed 계약

1. [제안] immutable input identity, authority/package/policy pin과 expected resource kind를 확인한다.
2. [제안] Dataset artifact를 열거나 staging을 만들기 전에 in-memory DatasetVersion proposal에
   `validate_contract(..., "dataset_version")`를 적용한다.
3. [제안] canonical issue가 0건일 때만 DohaLM domain validation으로 candidate 집합, 목적별 current
   TrainingEligibility·RightsMetadata, approval evidence, checksum, split/group 누수, schema·Tokenizer compatibility를
   검증한다.
4. [제안] domain validation까지 통과하면 DatasetVersion을 `approved` 상태로 결정하되 외부 공개나 Training 허용으로
   해석하지 않는다.
5. [제안] approved Version의 immutable identity와 artifact/checksum set에서 DatasetManifest draft와 frozen Version
   candidate를 staging에 구성하고 각각 `validate_contract()`한다.
6. [제안] `evaluated_at`, required upstream objects, issued Manifest candidate와 frozen Version candidate를 포함한
   `validate_scenario()`로 Dataset Gate와 Version/Manifest identity를 검증한다.
7. [제안] Common issue가 0건인 뒤 DohaLM domain validator가 실제 artifact bytes·checksum set, item count,
   split identity, local storage constraints와 publication target collision을 재검증한다.
8. [제안] 어느 validation이든 실패하면 더 뒤 단계는 실행하지 않고 정제된 오류로 fail closed한다. Common schema·version
   failure가 domain validation보다 우선하며, domain failure는 Common 성공을 승인이나 허용으로 승격하지 않는다.

validation 전후 payload key, value, type, version과 identity는 동일해야 한다. default 보완, alias, key rename,
type/version 변환과 evidence 추정을 금지한다.

## Lifecycle과 atomic publication transaction

공식 상태 순서는 다음과 같다.

```text
DatasetVersion Approved → DatasetManifest Issued → DatasetVersion Freeze
```

[제안] 상태 전이의 논리 순서는 유지하되 Manifest issuance와 freeze의 외부 공개는 하나의 atomic publication unit이다.
staging 내부에서 issued Manifest와 frozen Version candidate를 순서대로 완성·검증할 수 있지만 둘 중 하나도 commit 전에
consumer가 관찰할 수 없다. `freeze-before-manifest`를 재도입하지 않는다.

[제안] publication commit point는 검증을 마친 issued DatasetManifest와 frozen DatasetVersion pair 및 결속된 artifact
reference가 하나의 immutable publication identity 아래에서 외부 조회에 동시에 나타나는 단일 no-replace commit이다.
구체적인 filesystem·DB·object-store primitive는 미결정이며, 단일 원자성을 제공하지 못하는 기술은 이 Gate를 통과하지 못한다.

### Failure와 retry

- staging cleanup: 완료되어야 함
- externally visible partial Version·Manifest·artifact: 0
- published Dataset mutation: 0
- Model·Provider access: 0
- Training·Evaluation execution: 0
- 동일 ID overwrite·fallback: 0

[제안] retry는 동일 immutable input, authority/package/policy pin, DatasetVersion ID, DatasetManifest ID와 content
fingerprint/checksum set이 모두 같을 때만 idempotent success 또는 동일 결과 재확인을 허용한다. 같은 identity에 다른 bytes,
lineage, split, evidence 또는 fingerprint가 있으면 conflict로 실패하고 새 Version/Manifest identity가 필요하다.

## Revoke, supersede와 expiry

- [제안] rights·consent·review·eligibility expiry 또는 revocation은 기존 Version·Manifest를 수정·삭제하지 않는다.
- [제안] current eligibility를 새 평가 시각으로 다시 판정하고 영향 event를 append-only로 기록한다.
- [제안] frozen Dataset 변경은 새 DatasetVersion과 새 DatasetManifest를 발행하고 Version `supersedes` lineage를 연결한다.
- [제안] 동일 source Version의 Manifest evidence 정정은 새 Manifest ID와 하나의 선형 `supersedes` chain을 사용한다.
- [제안] replacement publication도 동일 Common/domain validation과 atomic commit Gate를 다시 통과한다.
- [제안] 이미 생성된 Run·Model lineage는 historical evidence로 보존하며 이 ADR은 rollback·Runtime 정책을 승인하지 않는다.

## Legacy와 Common의 비승격 경계

[확정] 기존 corpus, `source-manifest.json`, registry entry와 `dataset_version` 문자열은 Common 객체가 아니다. 아래 방식으로
자동 승격하지 않는다.

- wrapping 또는 alias
- default·필수 field 삽입
- key rename·삭제·추가
- type 또는 version 변환
- rights·consent·review·eligibility evidence 추정

[제안] legacy 자료를 Common lifecycle에 넣으려면 authority가 허용하는 source taxonomy, 검증된 evidence와 새 immutable
lineage를 갖춘 별도 migration/ingestion ADR이 먼저 승인·병합돼야 한다. 그 전까지 legacy pipeline과 Common publication은
서로 다른 Source of Truth다.

## 현재 구현, 설계 후보와 미래 범위

| 구분 | 실제 경로·symbol | 판정 |
|---|---|---|
| legacy Dataset 처리·manifest 생성 | `src.data.pipeline.validate_pipeline()`, `build_pipeline()`, `_run()` | `EXISTING_IMPLEMENTATION`; Common producer 아님 |
| legacy atomic directory publication | `src.data.artifacts.AtomicArtifactDirectory`, `_rename_directory_no_replace()` | `EXISTING_IMPLEMENTATION`; 재사용 여부 미결정 |
| legacy Dataset config identity | `src.data.config.DataConfig.dataset_version` | `EXISTING_IMPLEMENTATION`; Common DatasetVersion 아님 |
| tokenized Dataset reader | `src.data.tokenized_dataset.TokenizedJsonlDataset` | `EXISTING_IMPLEMENTATION`; Common validation 없음 |
| training readiness | `src.training.full_pretraining.inspect_full_pretraining_readiness()`, `require_full_pretraining_approval()` | `EXISTING_IMPLEMENTATION`; domain Gate이며 Common Gate 아님 |
| Common Dataset Governance producer | abstract Dataset governance boundary | `DESIGN_CANDIDATE`; module·function·storage 미결정 |
| Common Dataset Publication producer | abstract Dataset publication boundary | `DESIGN_CANDIDATE`; transaction primitive 미결정 |
| frozen Version·issued Manifest consumer | abstract training-entry boundary | `DESIGN_CANDIDATE`; module·function 미결정 |
| LearningCandidate·RightsMetadata·TrainingEligibility producer | ADR-014의 cross-repository future boundary | `OUT_OF_SCOPE_FUTURE`; 이번 ADR에서 구현·운영 의무 확정 안 함 |
| legacy migration/ingestion | 별도 authority·migration 결정 필요 | `OUT_OF_SCOPE_FUTURE` |

## Acceptance criteria

### 이 Design ADR의 acceptance

- exact authority commit·tree, package·policy와 두 `$id`가 기록돼 있다.
- DatasetVersion·DatasetManifest를 하나의 coherent resource set으로 선택한 이유가 있다.
- 인접 resource와 authority에 존재하지 않는 evidence resource를 구분한다.
- producer·consumer, Common/domain validation, lifecycle, atomic publication과 failure 결과가 결정돼 있다.
- legacy 자동 승격, 구현·consumer 활성화와 Training/Evaluation을 승인하지 않는다.
- ADR-014의 3단계 Gate와 index가 동기화돼 있다.

### ADR 병합 후 구현 진입 Gate

이 ADR이 독립 검증·명시 승인·병합된 뒤 별도 구현 작업은 다음을 먼저 고정해야 한다.

1. 실제 producer·consumer module·function과 호출 흐름
2. immutable dependency requested/resolved commit과 package integrity
3. current eligibility·rights·review와 append-only event 조회 계약
4. DatasetVersion/Manifest identity·fingerprint의 canonical 계산 규칙
5. single atomic commit을 보장하는 staging·persistence primitive와 crash recovery
6. sanitized deterministic error와 observability boundary
7. synthetic valid/invalid, expiry/revocation, collision, cleanup과 idempotent retry test 계획

위 Gate 전에는 dependency, loader, adapter, producer, consumer 또는 transaction을 구현하지 않는다.

### 구현 후 검증·consumer 활성화 Gate

구현 완료 뒤에도 다음 evidence를 독립 검증하고 별도 승인하기 전에는 consumer를 활성화하지 않는다.

1. public package API와 exact expected kind만 사용하고 private path·schema 복제 0
2. offline `$ref` resolution과 Runtime network lookup 0
3. Common → domain 순서, payload mutation 0과 fail-closed compatibility test
4. DatasetVersion approval → Manifest issuance → freeze와 single external commit 검증
5. crash/failure별 staging cleanup, partial publication 0과 no-replace test
6. immutable identity/fingerprint collision과 idempotent retry test
7. revoke·supersede·expiry append-only 처리와 current 판정 test
8. legacy wrapping·alias·default·key/type/version 변환과 evidence 추정 0
9. validation 실패 시 Dataset mutation, Model·Provider 접근, Training·Evaluation 실행 0
10. consumer 활성화에 대한 별도 명시 승인

consumer 활성화는 Dataset 승인, Training Readiness 또는 Training 실행 허용을 자동 의미하지 않는다.

## 명시적 미결정과 제외

- [검증 필요] 실제 producer·consumer module·class·function 이름
- [검증 필요] persistence, event transport, lock·CAS와 atomic commit primitive
- [검증 필요] canonical identity·fingerprint serialization 규칙과 storage key
- [검증 필요] reviewer roster, 법률 escalation, 운영 SLA와 retention 실행 기술
- [검증 필요] dependency source·artifact hash와 rollback pin 절차
- [제외] Python·schema·fixture·dependency·workflow 변경
- [제외] Common 객체 생성·발행, Dataset 접근·변환, Model·Provider 접근과 Training/Evaluation 실행
- [제외] DohaMusic 또는 다른 저장소의 현재 module·function·운영 의무 확정
- [제외] PR #103·ADR-012의 미래 제품 구조를 authority로 사용

## Alternatives

| 대안 | 기각 사유 |
|---|---|
| DatasetVersion만 선택 | freeze에 issued Manifest와 identity 결속이 필요해 publication을 완결할 수 없음 |
| DatasetManifest만 선택 | Manifest는 approval·lifecycle 권위가 아니며 source DatasetVersion 없이 발행할 수 없음 |
| LearningCandidate부터 채택 | 최초 producer가 DohaLM이 아니고 cross-repository 구현·review evidence가 미승인임 |
| TrainingEligibility를 같은 ADR에서 생산 | candidate 단위 판정과 Dataset publication은 독립 책임이며 scope가 과도하게 결합됨 |
| 기존 `source-manifest.json` 변환 | Common envelope·rights·approval·lifecycle을 추정해 이중 Source of Truth를 만듦 |
| Manifest를 먼저 외부 공개한 뒤 freeze | partial publication과 공식 atomic unit 계약을 위반함 |
| freeze-before-manifest | authority의 공식 lifecycle을 역전함 |

## Consequences와 후속 계획

- 장점: 첫 Common resource가 실제 Dataset ownership과 현재 training 경계에 인접하며 Version/Manifest 권위를 분리한다.
- 장점: Common schema validation과 DohaLM artifact/domain validation을 서로 대체하지 않는다.
- 장점: 실패 시 외부 partial output과 Dataset·Model·Training side effect를 0으로 고정한다.
- 비용: producer·persistence·transaction·consumer 구현과 검증이 별도 작업으로 남는다.
- 위험: 현재 저장 기술이 Version·Manifest pair의 single atomic commit을 제공하는지는 검증되지 않았다.
- rollback: 이 proposed ADR은 실행 mutation이 없어 문서 branch/PR을 폐기하면 된다. 병합 뒤 설계 변경은 후속 ADR로
  대체하고 구현 pin은 별도 승인 전 추가하지 않는다.

다음 단계는 이 Draft PR의 독립 검증과 필요한 보완이다. 같은 head를 재검증하고 Ready·squash merge한 뒤에만 별도의
implementation 작업을 시작할 수 있다.

## 승인 Gate

이 ADR은 `draft`·`proposed`다. 독립 검증, 명시 승인과 병합 전에는 authoritative implementation requirement가 아니다.
병합되더라도 구현 완료, consumer 활성화, Dataset publication 또는 Training/Evaluation을 승인하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-12 | [제안] DatasetVersion·DatasetManifest canonical set, validation 순서와 atomic publication transaction 설계 |
