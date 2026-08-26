# ADR-026: Dataset Review Authority 영속성 계약

- 문서 상태: `draft`
- 결정일: 미결정
- 작성일: 2026-08-21
- 마지막 검토일: 2026-08-26
- 실행 영향: Review Authority Python port·PostgreSQL durable persistence·Product Review Start Integration과
  authoritative review read 기반 Dataset Approval·Publication Integration 구현; Publication v1의 별도 durable Approval
  Authority는 미채택이며 Runtime Activation Architecture Gate는 선행 architecture 부족으로 차단
- 구현 상태: [현재] Review Authority Python port, PostgreSQL persistence, Product Review Start Integration and
  Product Dataset Approval·Publication Integration implemented; approval result remains a transient validated input and the
  committed frozen DatasetVersion·issued DatasetManifest pair is the durable Publication result; no runtime entrypoint is active
- 관련 결정: [ADR-014](./ADR-014-dataset-product-governance-boundary.md),
  [ADR-015](./ADR-015-dataset-version-publication-contract.md),
  [ADR-024](./ADR-024-ai-music-director-product-boundary.md),
  [ADR-025](./ADR-025-dataset-version-proposal-authority-contract.md),
  [ADR-027](./ADR-027-dataset-governance-production-prerequisites.md)

## 배경

- [현재] `begin_dataset_review()`은 immutable `DatasetVersionProposal(status="draft")`을 검증하고 새
  `DatasetVersionProposal(status="reviewing")`을 반환하는 순수 domain transition이다. reviewer, 시작 시각,
  evidence, persistence, replay 또는 concurrency 의미를 소유하지 않는다.
- [현재] `DatasetProposalAuthority`는 `compare_and_create()`와 identity 기반 `read_authoritative_proposal()`을 노출한다.
  PostgreSQL adapter는 restricted read 결과의 identity·payload·fingerprint·authority metadata를 재검증한다.
- [현재] `dohalm_dataset_governance_v1.dataset_version_proposal_authority`는 canonical `draft` proposal을 보존하는
  immutable authority다. `UPDATE`와 `DELETE`는 거부되며 review 상태를 이 row에 기록할 수 없다.
- [현재] immutable typed request·record·STARTED/REPLAYED/CONFLICT result와 authoritative read를 정의하는 Python port는
  구현됐다. durable `reviewing` 상태, restart recovery와 approval이 사용할 PostgreSQL adapter·storage도 구현됐으며
  Product Review Start Integration과 authoritative review read 기반 Approval Integration은 구현됐고 durable approval
  authority·persistence는 아직 없다.
- [확정] ADR-014는 DohaLM Dataset Governance를 DatasetVersion domain owner로 두지만 구체적인 review service와 storage는
  미결정으로 남긴다. ADR-015는 publication, ADR-024는 product learning 경계, ADR-025는 proposal authority만 다룬다.

따라서 Dataset Review Start 구현 전에 proposal과 분리된 review lifecycle authority를 결정해야 한다.

## 결정

### Authority 분리와 owner

- [제안] DohaLM Dataset Governance가 `DatasetReviewAuthority`의 accountable owner다.
- [제안] authority 책임을 다음처럼 분리한다.

| authority | 소유 상태·책임 | 이번 결정의 구현 상태 |
|---|---|---|
| Dataset Proposal Authority | immutable canonical `draft` proposal, create·replay·identity conflict | 기존 구현 유지 |
| Dataset Review Authority | proposal에 결속된 단일 durable `reviewing` lifecycle start와 authoritative read | Python port·PostgreSQL persistence 구현 |
| Dataset Approval | authoritative review와 current evidence를 다시 검증한 transient approved candidate | Product Integration 구현; Publication v1 별도 durable authority 미채택 |
| Dataset Publication Authority | approved Version과 issued Manifest의 publication·freeze | ADR-015 경계 유지 |

- [제안] review 시작은 proposal row를 수정하지 않는다. proposal authority의 stored object는 review 이후에도 canonical
  `draft` snapshot으로 남는다.
- [제안] `begin_dataset_review()`은 순수 transition representation으로 유지한다. durable lifecycle의 성공 여부와 replay 판정은
  Dataset Review Authority만 결정한다.

### Proposal authoritative read

- [제안] proposal read는 기존 Dataset Proposal Authority와 같은 owner·port concern이다. orchestration service가 임의 SQL이나
  caller payload로 proposal을 대체하지 않는다.
- [현재] `read_authoritative_proposal()`은 `DatasetVersionIdentity`로 authoritative proposal을 읽고 최소 다음을
  lossless하게 반환한다.

  - immutable stored `DatasetVersionProposal(status="draft")`
  - exact `DatasetVersionIdentity`
  - canonical proposal fingerprint
  - safe authority reference와 authority revision

- [제안] not-found와 corruption은 구분된 sanitized error로 fail closed한다. caller-provided proposal, process-local cache 또는
  새 proposal 생성으로 fallback하지 않는다.
- [제안] read 결과의 identity, canonical payload, fingerprint와 authority metadata를 다시 검증한 뒤에만 review Gate로 진행한다.

### Review authority identity와 cardinality

- [제안] review lifecycle은 `DatasetVersionIdentity + canonical proposal fingerprint`에 결속된다. fingerprint는 동일 logical
  DatasetVersion identity가 다른 canonical draft를 가리키거나 review record가 다른 proposal에 재사용되는 것을 막는다.
- [제안] 하나의 authoritative DatasetVersion proposal에는 active review-start record가 최대 하나다. 여러 사람의 병렬 검토나
  reviewer handoff는 이 lifecycle-start authority와 다른 후속 concern이다.
- [현재] persistence는 identity와 fingerprint의 composite binding을 DB invariant로 강제하고, 같은
  `DatasetVersionIdentity`에 다른 fingerprint를 가진 두 review lifecycle이 생기지 않도록 별도 uniqueness 또는 동등한
  database-level invariant를 둔다. 애플리케이션 lock만으로 uniqueness를 보장하지 않는다.

### Review Start Request

- [현재] local immutable input은 `DatasetReviewStartRequest`이며 Common canonical schema가 아니다.
- [제안] 최소 field는 다음과 같다.

  - `DatasetVersionIdentity`
  - expected canonical proposal fingerprint
  - explicit opaque·stable reviewer reference
  - explicit timezone-aware `review_started_at`
  - optional safe review-start evidence 또는 request reference

- [제안] reviewer는 blank·malformed 값을 거부하고 `created_by`, producer, OS user 또는 runtime principal에서 추론하지 않는다.
  이 계약은 reviewer reference만 요구하며 IAM·authentication system을 새로 정의하지 않는다.
- [제안] `review_started_at`은 hidden wall clock으로 채우지 않는다. logical authority identity와 retry equivalence에는 포함하지 않고
  최초 성공 record의 immutable audit metadata로 보존한다.
- [제안] optional safe reference가 있으면 opaque identifier만 허용한다. raw note, Dataset content, prompt, token, source path,
  evidence body 또는 credential은 request나 authority record에 저장하지 않는다.

### Current evidence Gate

- [제안] 모든 start 또는 replay invocation은 다음 순서로 fail closed한다.

1. Dataset Proposal Authority에서 authoritative proposal read
2. proposal identity·canonical payload·fingerprint·authority metadata 검증
3. `review_started_at` 기준 current RightsMetadata와 TrainingEligibility 재검증
4. Dataset Review Authority의 atomic start·replay·conflict adjudication
5. 기존 `begin_dataset_review()`을 사용한 immutable `reviewing` representation 반환 또는 동등한 검증

- [제안] Rights 또는 TrainingEligibility가 missing, unresolved, invalid, expired, revoked 또는 identity mismatch이면 review row를
  생성하지 않는다. proposal 시점의 과거 current 판정은 review-start currentness를 대체하지 않는다.
- [제안] replay invocation도 새로운 lifecycle action 요청이므로 current evidence를 다시 통과해야 한다. 이후 evidence가
  non-current가 되면 invocation은 실패하지만 기존 review-start record는 historical fact로 수정·삭제하지 않는다. 별도
  authoritative read는 이 historical record를 계속 반환할 수 있다.

### Atomic STARTED·REPLAYED·CONFLICT

- [현재] Dataset Review Authority는 단순 read-then-insert 대신 `start_review()` 하나로 다음 atomic start adjudication을
  제공한다.

| authoritative state와 요청 | 결과 | mutation |
|---|---|---|
| review 없음 + exact proposal + current evidence | `STARTED` | immutable review-start record 1개 생성 |
| same proposal + same reviewer + same safe logical request | `REPLAYED` | 없음; 기존 record 반환 |
| existing review + different reviewer 또는 conflicting safe request | `CONFLICT` | 없음 |
| proposal 없음·corrupt·fingerprint mismatch | error | review mutation 0 |
| current evidence non-current | error | review authority 호출·mutation 0 |
| review authority unavailable·corrupt | error | fallback 0 |

- [제안] 동일 logical request의 concurrent 호출은 하나만 `STARTED`, 나머지는 `REPLAYED`다.
- [제안] 다른 reviewer의 concurrent 호출은 하나만 `STARTED`이며 loser는 `CONFLICT`다. last-write-wins는 금지한다.
- [제안] same proposal·reviewer·safe request에서 retry가 다른 `review_started_at`을 제공해도 기존 record의 reviewer와 최초
  `review_started_at`을 보존하고 `REPLAYED`한다. timestamp rewrite나 duplicate row를 만들지 않는다.
- [제안] reviewer reassignment, cancellation, review result와 re-open은 별도 lifecycle 결정 없이는 지원하지 않는다.

### Durable record와 authoritative read

- [제안] logical review-start record는 최소 다음을 보존한다.

  - `DatasetVersionIdentity`와 proposal fingerprint
  - lifecycle state `reviewing`
  - reviewer reference와 최초 `review_started_at`
  - optional safe evidence/request reference
  - review authority reference와 schema/authority revision
  - canonical review-record fingerprint
  - 의미 판정에 사용하지 않는 DB audit timestamp

- [제안] record는 기본 immutable이며 reviewer, start time, fingerprint와 state를 rewrite하지 않는다. approval은 같은 row의
  `UPDATE`로 표현하지 않으며, Publication v1에서는 별도 durable Approval Authority도 만들지 않는다.
- [제안] Dataset Review Authority는 identity와 proposal fingerprint로 authoritative record를 읽는 read contract도 제공한다.
  Approval Integration은 caller가 만든 `reviewing` payload가 아니라 이 read 결과를 사용해야 한다.
- [제안] process restart 또는 새 adapter instance 뒤에도 same request는 `REPLAYED`, different reviewer는 `CONFLICT`, current
  authoritative review read는 동일 record를 반환해야 한다.
- [제안] stored identity, proposal fingerprint, reviewer, lifecycle state, canonical record fingerprint 또는 authority metadata가
  서로 맞지 않으면 authority corruption으로 fail closed한다. 자동 repair·overwrite·삭제는 금지한다.

### PostgreSQL 구현 경계

- [현재] durable adapter는 기존 `dohalm_dataset_governance_v1` schema 아래 proposal table과 분리된
  `dataset_version_review_authority` storage identity를 사용한다.
- [제안] 기존 C1 security pattern처럼 owner role, least-privilege runtime authority role, restricted functions, transaction과
  database-level uniqueness를 재사용한다. 새 security model을 발명하지 않는다.
- [제안] proposal authoritative read와 review start/read는 각각 owning authority port를 통해서만 접근하며 product service가
  SQL을 직접 호출하지 않는다.
- [현재] forward-only migration `0005_dataset_review_authority.sql`이 review persistence를 추가하며 migration
  `0001`~`0004`는 수정하지 않는다.

### Error와 data minimization

- [현재] 구현은 repository의 typed error pattern에 맞춰 최소 다음 semantic failure를 안정적으로 구분한다.

  - proposal not found
  - proposal authority unavailable 또는 corrupt
  - proposal fingerprint/identity mismatch
  - current evidence invalid
  - review start conflict
  - review authority missing 또는 unavailable
  - review authority result invalid 또는 stored record corrupt

- [제안] error는 credential, DSN, raw payload, source content, private path, reviewer secret 또는 evidence body를 포함하지 않는다.
- [제안] missing proposal·authority, invalid evidence, database unavailable, corruption과 fingerprint mismatch에 production
  in-memory fallback은 없다.

## State와 side-effect 경계

- [제안] `STARTED`와 `REPLAYED`의 lifecycle state는 `reviewing`이며 `approved=false`, `frozen=false`,
  `training_allowed=false`를 보존한다.
- [제안] review start는 `approve_dataset_version()`, `publish_dataset_version()`, Training request·approval·execution,
  Evaluation 또는 Model promotion을 호출하거나 승인하지 않는다.
- [제안] Dataset Review Authority는 DohaLM local governance lifecycle이며 Common DatasetVersion schema와 Common Contract를
  변경하지 않는다.

## Dataset Approval Authority Architecture Gate

### 판정

- [제안] Publication v1의 별도 durable Dataset Approval Authority는 `NOT REQUIRED`다.
- [현재] `approve_product_dataset_version()`의 `ApprovedDatasetVersion`은 process-local immutable validated value이며
  durable fact나 authoritative lookup 결과가 아니다.
- [현재] `publish_product_dataset_version()`은 caller-created approved payload를 입력으로 받지 않고 authoritative Proposal과
  Review를 다시 읽어 current RightsMetadata·TrainingEligibility와 exact approval evidence binding을 재검증한 뒤 같은
  orchestration attempt에서 `publish_dataset_version()`에 `ApprovedDatasetVersion`을 전달한다.
- [현재] Product service는 기존 `approve_product_dataset_version()`과 `publish_dataset_version()`을 순서대로 재사용한다.
  Manifest/frozen candidate construction, pair fingerprint, staging, no-replace commit, replay·conflict와 atomic visibility는 기존
  Publication boundary가 계속 소유하며 Proposal·Review record는 변경하지 않는다.
- [제안] publication 전에 process가 종료되거나 다른 worker가 이어받으면 이전 approval value를 복구하지 않는다. 새 invocation이
  approval validation을 다시 수행한다.
- [제안] 재시작 후 조회 가능한 authoritative state, idempotent replay와 conflict의 소유자는 ADR-015의 committed frozen
  DatasetVersion·issued DatasetManifest pair다. approved-only 상태는 외부 또는 internal component의 공식 조회 상태가 아니다.

이 판정은 ADR-015의 `ApprovedDatasetVersion` explicit input, pre-publication approval store·lookup 0, frozen/issued pair만
restart-readable authority라는 계약을 유지한다. ADR-015 수정, 새 Approval Authority ADR, port, migration, adapter 또는 role은
필요하지 않다.

### Durability 질문

| 질문 | 답 | 근거·처리 |
|---|---|---|
| approval을 restart 후 재조회해야 하는가 | `NO` | publication 전 실패는 새 invocation에서 authoritative Proposal·Review와 current evidence를 재검증한다. |
| multi-worker가 같은 approval authority를 공유해야 하는가 | `NO` | worker 간 approved-only handoff를 공식 lifecycle로 만들지 않는다. publication worker가 validation을 다시 수행한다. |
| actor·evidence·timestamp를 독립 audit fact로 보존해야 하는가 | `NO` | actor authority가 없고 현재 계약은 evidence ID를 approved payload와 최종 publication pair에 결속한다. |
| approval replay를 독립적으로 판정해야 하는가 | `NO` | publication pair가 동일 canonical bytes의 replay를 판정한다. |
| conflicting approval evidence를 독립 authority가 거부해야 하는가 | `NO` | approval 시 exact declared evidence set mismatch가 실패하고, commit 뒤에는 publication pair fingerprint conflict가 실패한다. |
| publication이 authoritative approval을 읽어야 하는가 | `NO` | ADR-015의 explicit immutable `ApprovedDatasetVersion` 입력을 사용하되 Product Integration에서 그 값을 fresh validation으로 만든다. |
| evidence 변경 뒤 historical approval fact를 보존해야 하는가 | `NO` | unpublished approval은 historical authority가 아니다. published pair는 기존 evidence binding을 immutable lineage로 보존한다. |
| publication 실패·재시도에서 기존 approval fact를 유지해야 하는가 | `NO` | 재시도는 current evidence를 다시 평가하며 committed pair가 있으면 그 pair만 replay한다. |

### 모델 비교와 decision matrix

| 항목 | Authority 없음 | Authority 있음 | 필요성 판단 |
|---|---|---|---|
| restart | 미commit이면 fresh approval validation, commit이면 pair replay | approved-only record 재조회 | 전자가 ADR-015와 일치 |
| multi-worker | publication worker가 fresh validation | worker 간 approval reference 전달 | 공식 approved-only handoff 요구 없음 |
| audit | published pair의 approval evidence binding 보존 | pre-publication actor·time까지 독립 보존 | actor authority·독립 audit 요구 없음 |
| replay | frozen/issued pair replay | approval replay와 publication replay 이중화 | publication replay만 필요 |
| conflict | approval evidence mismatch와 pair fingerprint conflict | 별도 approval identity conflict 추가 | 현행 두 Gate로 충분 |
| publication retry | current evidence 재검증 후 새 attempt | historical approval read 후 current evidence 재검증 | historical read가 안전 Gate를 제거하지 못함 |
| current evidence revocation | 새 attempt가 fail closed | historical approval은 남지만 publication은 다시 fail closed | 결과가 같아 store 이점 없음 |
| immutability | Proposal·Review row와 committed pair 불변 | 새 immutable approval row 추가 | 기존 authority mutation은 양쪽 모두 불필요 |
| operational complexity | 추가 DB lifecycle 없음 | port·migration·adapter·monitoring 필요 | 추가 복잡성 회피 |
| schema/security cost | 없음 | identity·role·restricted function·DML 차단 필요 | 현재 요구에 비례하지 않음 |

### Restart·multi-worker 시나리오

| 시나리오 | Approval Authority 없음 | Approval Authority 있음 | Publication v1 판정 |
|---|---|---|---|
| approval 직후 process crash | process-local value 유실, durable mutation 0 | approval record 유지 | 새 invocation의 fresh validation으로 충분 |
| approval 후 publication 전 restart | Proposal·Review authoritative read부터 다시 수행 | approval read 뒤 publication 진행 | approved-only recovery 요구가 없어 전자 채택 |
| worker A approval / worker B publication | B가 approval validation을 다시 수행 | B가 approval reference를 조회 | cross-worker handoff를 공식 lifecycle로 만들지 않음 |
| concurrent duplicate approval | 각각 side-effect-free candidate 생성, publication에서 단일 pair commit·replay | authority에서 approval replay | durable duplicate가 없어 별도 adjudication 불필요 |
| conflicting approval evidence | proposal에 declared된 exact evidence set과 다르면 approval 실패 | authority conflict | current approval Gate에서 이미 fail closed |
| publication retry | current evidence 재검증; final pair가 있으면 strict replay | approval read와 current evidence 재검증 후 pair replay | 추가 read가 안전성·결과를 개선하지 않음 |

### Actor, evidence와 future reconsideration

- [현재] Product approval input에는 actor가 없고 Common contract에는 별도 `ReviewEvidence` resource가 없다.
  `approval_evidence_ids`는 opaque ID이며 DohaLM은 evidence body authority를 소유하지 않는다.
- [제안] actor나 evidence authority를 임의로 만들지 않는다. published artifact는 승인 시각을 별도 authority audit fact로
  주장하지 않으며, publication 시각·creator metadata를 approval actor로 재해석하지 않는다.
- [제안] 향후 approved-only 상태의 공식 observability, actor accountability, cross-worker approval handoff 또는 publication과
  독립된 approval replay가 제품 요구사항이 되면 새 ADR로 재검토한다. 그때의 최소 identity 후보는
  `DatasetVersionIdentity + proposal fingerprint + review record fingerprint + approval evidence IDs`다. `evaluated_at`과
  actor/reference의 identity·audit 역할은 해당 authority source가 먼저 결정된 뒤 확정한다.

## Product Dataset Governance Runtime Activation Architecture Gate

### Runtime inventory

- [현재] 설치형 entrypoint는 `src.cli.main:main`의 argparse 기반 `dohalm` CLI다. 현재 `environment`, `config`, `paths`,
  legacy Phase 1 `data validate/build`만 제공하며 Product Dataset Proposal·Review·Approval·Publication command는 없다.
- [현재] FastAPI application은 inference용 health·model·chat·streaming surface와 application-lifetime provider registry만
  구성한다. authentication, authorization, trusted principal, reviewer mapping과 governance dependency composition은 없다.
- [현재] Product Dataset Governance chain은 Python service-only다. production runtime, API, CLI, scheduler 또는 worker에서
  호출되지 않는다.
- [현재] product 문서에는 이 chain을 실제로 호출하는 operator, curator, admin backend, ingestion process 또는 training
  consumer가 확정돼 있지 않다. 가능한 actor를 현재 caller나 IAM principal로 승격하지 않는다.
- [현재] PostgreSQL Proposal·Review adapter는 각각 role-scoped immutable settings를 받고 invocation마다 short-lived
  connection·transaction을 열고 닫는다. 이 settings를 environment/profile에서 만들고 두 adapter를 함께 구성하는 production
  factory는 없다.
- [현재] `DatasetProposalCurrentEvidenceAuthority`는 protocol만 존재한다. production RightsMetadata·TrainingEligibility
  authority coordinator나 runtime construction path는 없다.
- [현재] Publication v1은 caller가 명시한 `publication_root`를 받지만 governance runtime용 config owner·loader가 없다.
  hard-coded path, current working directory, repository root 또는 user home에서 production root를 추론할 수 없다.
- [현재] Proposal·Review authoritative read는 public port에 있지만 committed publication pair의 standalone public read port는
  아직 구현되지 않았다. existing replay 검증은 publication attempt 내부의 private storage protocol이다. 후속
  [ADR-031](./ADR-031-dataset-publication-pair-public-read-contract.md)은 exact identity Authority Protocol과 full pair-local
  verification을 `READY FOR IMPLEMENTATION`으로 제안한다.

### Activation model decision matrix

| 항목 | CLI | API | Worker | 미활성 |
|---|---|---|---|---|
| 현재 infrastructure 적합성 | argparse namespace가 있어 `중간` | inference API만 있어 `낮음` | governance worker가 없어 `낮음` | 현행 service-only와 일치 |
| identity safety | explicit opaque reference 전달은 가능하나 trust policy 미정 | authenticated principal이 없어 `낮음` | human actor를 안전하게 만들 수 없어 `낮음` | actor 추론 0 |
| reviewer source | explicit argument 후보, issuer·accountability 미정 | principal mapping 없음 | 자동 생성 금지 | 없음 |
| config readiness | 통합 config/factory 없음 | governance settings 없음 | worker settings 없음 | secret·path 추론 없음 |
| secret handling | CLI argument 노출을 피할 config contract 필요 | deployment secret contract 없음 | worker secret contract 없음 | 새 secret surface 없음 |
| operator usability | read-before-write가 마련되면 `높음` | admin client·IAM 없어서 `낮음` | human review에 부적합 | write workflow 없음 |
| automation | explicit command 단위 retry 가능 | 이론상 높지만 IAM 선행 | 높지만 human Gate 훼손 위험 | 없음 |
| deployment cost | 후보 중 가장 낮음 | server/IAM/route 운영비 높음 | queue·worker lifecycle 비용 높음 | 추가 비용 없음 |
| auditability | explicit input·machine result 계약 필요 | principal/audit middleware 필요 | actor handoff authority 필요 | 새 audit 주장 없음 |
| implementation risk | `중간`, 선행 계약 후 재평가 | `높음` | `높음` | 가장 낮지만 activation 미제공 |

### Security와 operation 분석

- [제안] CLI는 별도 server deployment가 없고 explicit reference·timestamp·evidence를 전달할 수 있어 후보 중 공격 표면과
  운영 비용이 가장 작다. 다만 credential을 command line에 전달하지 않는 secret source, reviewer reference trust와
  machine-readable sanitized result가 먼저 필요하다.
- [제안] API는 현재 inference-only dependency graph에 governance DB role과 filesystem write 권한을 추가하고도 authn/authz가
  없어 accidental publication 위험이 가장 크다. request ID와 existing CORS surface는 principal·audit evidence가 아니다.
- [제안] worker는 queue·handoff·heartbeat·actor provenance·crash recovery를 새로 소유해야 한다. 사람 review가 필요한 현재
  workflow에서는 automation 이점보다 잘못된 actor 생성과 silent retry 위험이 크다.
- [제안] PostgreSQL adapter의 short-lived per-invocation connection은 future CLI lifetime과 양립하지만 startup preflight,
  retry observability와 role별 config construction은 아직 없다. publication pair가 commit되면 existing replay가 crash recovery를
  담당하며 runtime layer가 새 aggregate state store를 만들지 않는다.

### 판정

- [제안] 최종 판정은 `BLOCKED — PRIOR ARCHITECTURE REQUIRED`다.
- [제안] 이번 Gate는 CLI, API, worker 또는 multiple entrypoint activation을 승인하지 않는다. first supported entrypoint는
  아직 없으며 production source·migration·test를 추가하지 않는다.
- [제안] 선행 조건이 충족되면 첫 재검토 후보는 operator-driven CLI다. 기존 argparse namespace, explicit timestamp·opaque
  reference 입력과 단계별 replay/conflict 의미가 현재 workflow에 가장 가깝다. 이는 `CLI ACTIVATION REQUIRED FIRST` 승인이나
  command 구현 승인이 아니다.
- [제안] API는 authn/authz, trusted principal과 reviewer mapping이 생기기 전까지 premature다. inference API의 request ID,
  provider dependency와 existing CORS surface를 governance identity나 권한으로 재해석하지 않는다.
- [제안] worker는 review·approval의 human governance actor를 만들 수 없으므로 지원하지 않는다. Publication 성공을 Training,
  Evaluation 또는 promotion에 자동 연결하지 않는다.
- [현재] Product Approval contract에는 approval actor가 없다. runtime 편의를 위해 actor field나 approval authority를 추가하지
  않으며 accountability 요구가 생기면 별도 Architecture Gate로 되돌린다.

### Required prior architecture

1. production `DatasetProposalCurrentEvidenceAuthority` owner·adapter·lifetime과 failure contract
2. Proposal/Review role credential, environment/profile, publication root와 Common package pin을 묶는 governance runtime config
   contract 및 composition-root owner
3. secret을 CLI argument·log·result에 노출하지 않는 credential source와 role별 least-privilege construction
4. reviewer reference issuer·trust·operator accountability 정책; OS user, Git user와 process owner 자동 추론 금지
5. [ADR-031](./ADR-031-dataset-publication-pair-public-read-contract.md)의 standalone publication pair public read contract
   제안 승인과 별도 구현
6. startup preflight와 invocation validation 분리: config shape·Common version은 startup, DB reachability·migration head·role
   permission·publication root usability는 fail-closed preflight, current evidence는 매 invocation에서 검증
7. semantic error·machine-readable result·exit status 계약; SQL, DSN, password, absolute path, stack trace와 raw evidence body 비노출

### Future CLI scope and test Gate

- [제안] 선행 architecture가 승인된 뒤 별도 PR에서 `dataset proposal-inspect`, `dataset review-inspect`와 승인된 publication
  read가 있다면 `dataset publication-inspect`를 write command보다 먼저 검토한다.
- [제안] write 후보는 `dataset propose`, `dataset review-start`, `dataset approve`, `dataset publish`의 분리된 command다.
  하나의 hidden `propose → review → approve → publish` command나 cross-boundary DB/filesystem transaction은 금지한다.
- [제안] 모든 timestamp, reviewer/request reference, approval evidence ID와 publication metadata는 explicit input이다. hidden
  wall clock, actor, manifest ID, storage path와 default-now를 추가하려면 별도 contract 승인이 필요하다.
- [제안] 후속 테스트는 dependency composition, config validation, startup fail-closed, explicit input forwarding, sanitized error,
  replay/conflict exit status, no hidden default, no direct SQL/storage bypass, service ordering과 Training non-activation을 포함한다.

## 기각한 대안

| 대안 | 기각 사유 |
|---|---|
| proposal row를 `draft → reviewing`으로 UPDATE | ADR-025의 immutable canonical proposal을 파괴하고 proposal/review authority를 결합함 |
| caller가 proposal payload를 전달 | durable authority lookup을 우회하고 stale·conflicting payload를 신뢰하게 됨 |
| process-local review registry | restart·multi-worker·concurrency에서 authoritative replay와 conflict를 보장하지 못함 |
| review read 뒤 별도 insert | concurrent start에서 duplicate 또는 last-write-wins race가 생김 |
| timestamp를 review identity로 사용 | 동일 logical retry가 새 lifecycle이 되고 최초 audit time을 rewrite할 수 있음 |
| reviewer를 creator·OS user에서 파생 | accountability source가 불명확하고 future multi-user identity와 충돌함 |
| review record를 approval까지 mutable row로 확장 | review start와 approval evidence authority를 성급히 결합함 |

## 후속 구현 순서와 Gate

이 ADR이 독립 검토·명시 승인·병합되더라도 구현 완료나 activation을 뜻하지 않는다. 후속 작업은 다음 순서를 권장한다.

1. Dataset Proposal Authority의 authoritative read contract
2. Dataset Review Authority start/read port와 typed request/result — Python contract 구현 완료
3. PostgreSQL review authority migration·restricted functions·adapter — 구현 완료
4. unit·C1/C2 security, corruption, restart와 concurrency 검증 — 단계 4 Gate 구현
5. existing `begin_dataset_review()`을 재사용하는 Product Dataset Review Start Integration — 구현 완료
6. fixed-head 검증과 별도 merge 결정
7. Dataset Approval Integration의 authoritative review read 연결 — 구현 완료; Publication v1 durable Approval Authority는
   Architecture Gate에서 `NOT REQUIRED` 판정
8. Product Dataset Publication Integration의 fresh approval validation과 기존 Publication boundary 연결 — 구현 완료;
   runtime activation·Training은 미구현
9. Product Dataset Governance Runtime Activation Architecture Gate — `BLOCKED — PRIOR ARCHITECTURE REQUIRED`;
   current-evidence production composition·runtime config/secret owner·reviewer trust·publication read contract 선행 필요
10. Production Prerequisites Architecture Gate — CurrentEvidence source는 `BLOCKED`, 새 DohaLM governance runtime
    config/composition은 `REQUIRED`, 전체 prerequisite는 `STILL BLOCKED`
11. Standalone Dataset Publication Pair Public Read Contract Gate — `C. NEW PUBLIC READ PORT REQUIRED`,
    `READY FOR IMPLEMENTATION`; source 구현·runtime activation은 별도 PR/Gate

각 단계는 별도 Ready·검증·승인을 요구한다.

## 제외 범위

- [제외] 이 ADR 작성 범위의 Python review·proposal read code와 PostgreSQL table·function·migration·test 구현
  (후속 단계에서 proposal read, Review Authority Python port와 PostgreSQL persistence가 구현됨)
- [제외] `begin_dataset_review()` 또는 proposal migration `0001`~`0004` 변경
- [제외] proposal row mutation, runtime composition 등록과 API 추가
- [제외] Dataset approval·publication, Training, Evaluation과 promotion
- [제외] Common Contract와 다른 repository 변경
- [제외] IAM·authentication system, reviewer roster·handoff·reassignment workflow 설계

## 미결정 사항

- [현재] port·request·result·adapter symbol은 `DatasetReviewAuthority`, `DatasetReviewStartRequest`,
  `DatasetReviewStartResult`, `PostgresDatasetReviewAuthority`다.
- [현재] PostgreSQL table은 `dataset_version_review_authority`, restricted function은
  `start_dataset_version_review`·`read_dataset_version_review`, role은 `dohalm_dataset_review_owner`와
  `dohalm_dataset_review_authority`, migration은 `0005_dataset_review_authority.sql`이다.
- [현재] optional request reference는 Python과 PostgreSQL에서 같은 safe reference pattern을 사용한다.
- [검증 필요] reviewer reference issuer·roster·reassignment authority
- [제안] Publication v1은 별도 approval persistence를 두지 않고 Product Publication Integration의 fresh approval validation과
  ADR-015 publication transaction 경계를 사용한다. approved-only observability·actor audit 요구가 생기면 별도 ADR로 재검토한다.
- [검증 필요] production current-evidence source·unique-current selection·revocation owner; ADR-027에서 source 미정으로 차단
- [제안] governance runtime config/composition owner는 ADR-027의 새 DohaLM-owned typed contract이며 구현은 미승인
- [제안] ADR-031은 standalone publication read surface를 `REQUIRED`로 판정하고 Dataset Publication module-owned exact identity
  Authority Protocol과 private filesystem adapter 결속을 제안한다. 구현은 별도 PR 전까지 미완료다.

## 승인 Gate

이 ADR은 `draft`다. 독립 검토, 사용자 명시 승인과 병합 전에는 authoritative implementation requirement가 아니다.
현재 구현된 persistence adapter와 Product Dataset Review Start·Approval·Publication Integration의 runtime activation,
durable approval authority, API·CLI·worker 또는 Training은 승인하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-26 | [제안] ADR-031 standalone publication pair public read Gate의 `NEW PUBLIC READ PORT REQUIRED`·`READY FOR IMPLEMENTATION` 판정 연결 |
| 2026-08-25 | [제안] ADR-027 prerequisite Gate의 CurrentEvidence `BLOCKED`, 새 DohaLM governance config `REQUIRED`, 전체 `STILL BLOCKED` 판정 연결 |
| 2026-08-25 | [제안] Runtime Activation Architecture Gate를 `BLOCKED — PRIOR ARCHITECTURE REQUIRED`로 판정하고 CLI를 선행 계약 완료 후 첫 재검토 후보로 한정함 |
| 2026-08-25 | [현재] fresh authoritative Proposal·Review/current evidence와 transient approval을 기존 atomic Publication boundary에 연결하는 Product Dataset Publication Integration 구현; runtime·Training 미구현 |
| 2026-08-25 | [제안] Architecture Gate에서 Publication v1 durable Approval Authority를 `NOT REQUIRED`로 판정하고 fresh approval validation·publication pair authority·재검토 조건을 명시함 |
| 2026-08-25 | [현재] caller-created `reviewing` payload 대신 authoritative proposal·review read와 approval-time current evidence를 사용하는 Product Dataset Approval Integration 구현; durable Approval Authority·runtime·publication 미구현 |
| 2026-08-24 | [현재] authoritative proposal read·current evidence 재검증·atomic review start와 `begin_dataset_review()`을 연결하는 Product Dataset Review Start Integration 구현; approval·runtime activation 미구현 |
| 2026-08-24 | [현재] 단계 4 fingerprint·corruption·concurrency persistence Gate 보강과 구현 후 stale 문구 교정 |
| 2026-08-24 | [현재] 분리된 immutable review table, restricted start/read, PostgreSQL adapter와 최소 restart·concurrency·corruption 검증 구현; Product Review Start·approval·runtime activation은 미구현 |
| 2026-08-24 | [현재] immutable request·record·STARTED/REPLAYED/CONFLICT·authoritative read Python port 구현; PostgreSQL persistence와 Product Review Start는 미구현 |
| 2026-08-21 | [제안] immutable proposal과 분리된 Dataset Review Authority owner·identity·read·STARTED/REPLAYED/CONFLICT·current evidence·restart 계약 등록 |
