# ADR-027: Product Dataset Governance production prerequisite 경계

- 문서 상태: `draft`
- 마지막 검토일: 2026-08-25
- 결정 상태: `proposed`
- 실행 영향: 없음; CurrentEvidence는 source 미정으로 차단하고 새 DohaLM governance runtime config/composition ownership만 제안
- 관련 결정: [ADR-014](./ADR-014-dataset-product-governance-boundary.md),
  [ADR-015](./ADR-015-dataset-version-publication-contract.md),
  [ADR-025](./ADR-025-dataset-version-proposal-authority-contract.md),
  [ADR-026](./ADR-026-dataset-review-authority-contract.md)
- 관련 문서: [제품 지속 학습 경계](../project/ai-music-director-continuous-learning.md),
  [산출물 및 설정 정책](../governance/artifact-and-configuration-policy.md)

## Context

[현재] Product Dataset Proposal·Review Start·Approval·Publication service chain과 Proposal·Review PostgreSQL authority는
구현됐다. 하지만 모든 lifecycle action이 요구하는 `DatasetProposalCurrentEvidenceAuthority`의 production 구현과 runtime
composition은 없고, Proposal·Review credential과 `publication_root`를 안전하게 소유하는 governance runtime config도 없다.

[현재] Runtime Activation Architecture Gate는 first supported entrypoint를 두지 않고 CLI를 선행 architecture 완료 뒤 첫
재검토 후보로만 남겼다. 이번 결정은 그 선행 조건 중 CurrentEvidence와 config/composition ownership을 함께 검토하며 CLI,
API, worker, migration 또는 Training을 활성화하지 않는다.

## CurrentEvidence inventory

### Dataset-level port와 call sites

- [현재] `DatasetProposalCurrentEvidenceAuthority.evaluate_current_proposal_evidence()`는 canonical
  `DatasetVersionProposal`, proposal fingerprint와 timezone-aware `proposed_at`을 받고
  `DatasetProposalEvidenceDecision`을 반환한다.
- [현재] decision은 `CURRENT`, `MISSING`, `EXPIRED`, `REVOKED`, `INVALID`, `IDENTITY_MISMATCH` 중 하나와 exact
  `DatasetVersionIdentity`, proposal fingerprint, safe authority reference와 positive authority version을 결속한다.
- [현재] Proposal은 atomic compare-and-create 전에 이 port를 호출한다. Review Start는 authoritative Proposal read 뒤,
  Approval은 authoritative Proposal·Review read 뒤 같은 port를 호출한다. Publication은 매 invocation마다 Approval을 다시
  실행하므로 같은 current evidence Gate를 통과한다.
- [현재] production implementation·factory·runtime caller는 0이다. 테스트의 `_CurrentEvidenceAuthority`는 status와 identity를
  합성하는 fake이며 canonical object lookup·selection·revocation·availability architecture의 근거가 아니다.

### Candidate-level canonical evidence

- [현재] `LearningCandidateReviewAuthority`는 `rights_metadata_id`와 `training_eligibility_id`별 current object resolver port를
  정의하지만 구현은 테스트 fake뿐이다.
- [현재] Product composition은 각 member의 candidate ID, RightsMetadata ID, TrainingEligibility ID, producer, workspace,
  usage purpose, task와 consent reference를 immutable `member_bindings`에 보존한다. Dataset-level coordinator가 임의의 latest
  record를 찾을 이유나 권한은 없다.
- [현재] pinned Common package는 RightsMetadata·TrainingEligibility schema와 validation policy를 제공하지만 runtime record,
  current projection, producer workflow, database 또는 revoke endpoint를 소유하지 않는다.

### Source ownership 조사

- [현재] pinned Common authority는 Rights/Provenance/Consent를 DohaMusic·권리 검토 계층 책임으로, TrainingEligibility를
  Dataset governance 책임으로 둔다. DohaLM은 RightsMetadata producer가 아니다.
- [현재] 2026-08-25에 접근 가능한 DohaMusic·DohaAudio·DohaVocal default branch와 pinned
  `DohaStudio/.github@dd75fc88c16e9ae9a04acfafb72756a905f6365b`를 조사했지만 production RightsMetadata 또는
  TrainingEligibility writer, durable current registry, read API와 adapter interface는 확인되지 않았다.
- [현재] DohaLM에도 두 canonical resource의 durable record나 writer는 없다. fixture, caller-provided mapping,
  process-local object와 legacy data evidence는 production authority가 아니다.

## Currentness, revocation과 selection

- [현재] `evaluated_at`은 caller가 제공한 timezone-aware lifecycle 시각이다. hidden wall clock을 사용하지 않는다.
- [현재] RightsMetadata v1은 `created_at`, `reviewed_at`, `rights_status`와 training-scope
  `retention_allowed.expires_at`을 제공한다. `valid_from`·generic `valid_until`·`supersedes` field는 없다.
- [현재] TrainingEligibility v1은 `created_at`, `reviewed_at`, `expires_at`, `decision`, `policy_version`, candidate·rights ID와
  usage purpose를 제공한다. `valid_from`·`supersedes` field는 없다.
- [현재] revocation 상태 표현은 RightsMetadata의 `rights_status=revoked`와 TrainingEligibility의
  `decision=revoked`다. Common specification은 Rights 변경을 append-only로 다루고 새 Eligibility를 발급하도록 요구하지만
  revoke event writer, current projection과 accountable revocation owner는 정의하지 않는다.
- [현재] `(candidate_id, usage_purpose)`에 current/supersession 계약 없이 Eligibility가 여러 개면 순서와 무관하게 fail
  closed한다. Rights에도 `max(created_at)` 또는 latest-wins selection을 적용할 근거가 없다.
- [제안] missing, corrupt, stale, equally authoritative multiple records와 identity·producer·workspace·purpose mismatch는 모두
  fail closed한다. caller fallback, timestamp-based tie-break, stale cache와 process-local fallback은 0이다.

## Evidence integrity와 availability

- [제안] future source adapter는 authoritative lookup, unique-current selection, revocation/current projection과 source
  availability를 소유한다. DohaLM coordinator는 Common validation, exact member binding, producer·workspace·usage purpose·task,
  evaluated-at currentness와 proposal fingerprint binding을 소유한다.
- [제안] Product Proposal·Review·Approval·Publication layer는 raw authority object를 재선택하지 않고 coordinator의 typed
  decision envelope와 identity/fingerprint를 검증한다. raw evidence body는 result·error·log에 노출하지 않는다.
- [제안] source unavailable은 모든 네 operation에서 fail closed한다. cross-invocation cache와 TTL은 승인하지 않는다.
  availability가 복구된 뒤 새 invocation이 current evidence를 다시 읽어야 한다.
- [제안] production source는 restart·multi-worker·concurrent invocation에서 같은 exact ID와 `evaluated_at`에 결정론적인
  current result를 제공해야 한다. process-local mapping은 부적합하다.

## CurrentEvidence decision matrix

| 항목 | DohaLM DB | External Authority | Filesystem Registry | 미정 |
|---|---|---|---|---|
| source ownership | Eligibility 후보만 있고 Rights ownership과 writer 없음 | Rights ownership 방향은 맞지만 read contract 없음 | owner·writer 없음 | 실제 두 source가 모두 미정 |
| currentness | projection/schema 없음 | API·snapshot 의미 없음 | index·selection 의미 없음 | current selector 승인 불가 |
| revocation | revoke writer 없음 | revocation endpoint/event 없음 | update·revoke protocol 없음 | owner 미정 |
| restart | durable 구현 시 가능 | source가 보장하면 가능 | 파일 계약이 있으면 가능 | 현재 증거 없음 |
| multi-worker | DB transaction 계약 필요 | consistency 계약 필요 | lock/snapshot 계약 필요 | 모두 미정 |
| availability | local DB 운영 부담 | network·version·retry 필요 | mount·refresh 실패 필요 | fail-closed만 확정 |
| security | Rights 복제·writer 권한 위험 | authenticated read trust 필요 | ACL·tamper detection 필요 | trust anchor 없음 |
| implementation cost | migration·writer·projection 높음 | interface·adapter 중간 이상 | registry·locking 중간 이상 | 구현 시작 금지 |
| duplication risk | Rights source 복제 위험 높음 | 낮을 수 있으나 source 불명 | stale duplicate 위험 높음 | 판단 보류 |

### CurrentEvidence 판정

- [제안] 최종 판정은 `D. BLOCKED — EVIDENCE SOURCE NOT DEFINED`다.
- [제안] DohaLM DB는 Rights authority를 복제하고도 writer·revocation owner를 만들지 못하므로 채택하지 않는다.
- [제안] External Authority는 ownership 방향과 가깝지만 실제 resource, repository, authenticated interface와 consistency
  contract가 없어 `CROSS-REPOSITORY AUTHORITY REQUIRED`로 확정하지 않는다.
- [제안] Filesystem registry는 current selection·concurrency·revocation owner가 없어 채택하지 않는다.
- [제안] source가 승인되면 DohaLM-owned coordinator implementation이 필요할 가능성이 높지만 coordinator 자체가 source of
  truth를 대신하지 않는다. source decision 전 production adapter·migration·cache 구현은 금지한다.

## Runtime config inventory

- [현재] `src.config`는 model/run YAML, CLI override와 secret masking을 제공하지만 governance field, deployment secret loader와
  runtime composition schema는 없다.
- [현재] `APISettings`는 `.env`와 `DOHALM_` prefix를 사용하는 inference FastAPI settings다. governance DB role, evidence
  source와 publication storage를 소유하지 않는다.
- [현재] Proposal·Review PostgreSQL settings는 각각 immutable·redacted이며 `production` 또는 `isolated_test` transport,
  fixed least-privilege role, TLS와 timeout을 검증한다. 두 settings를 구성하는 loader는 없다.
- [현재] approved Training architecture에는 DohaLM-owned typed composition과 deployment-owned protected secret file injection
  선례가 있지만 Training role·schema·activation contract이므로 governance config로 직접 재사용하지 않는다.
- [현재] repository-wide config policy는 version-controlled non-secret config와 environment 또는 local secret mechanism을
  분리한다. raw secret, private path와 resolved environment dump를 Git·log에 기록하지 않는다.

## Governance runtime config contract

### Required non-secret configuration

- [제안] 새 DohaLM-owned governance runtime config는 environment transport profile, Proposal·Review database endpoint/TLS/timeout,
  CurrentEvidence provider descriptor, publication root reference와 preflight policy를 하나의 immutable typed input으로 소유한다.
- [제안] `environment`는 `production`과 isolated test transport validation을 구분할 뿐 identity, authorization 또는 reviewer
  trust가 아니다. generic dev/test/prod profile hierarchy를 새로 만들지 않는다.
- [제안] Common package `0.1.0`, policy `1.0.0`과 authority commit pin은 build dependency·repository constant다. runtime
  operator override를 허용하지 않고 startup에서 installed package와 schema registry를 검증한다.
- [제안] CurrentEvidence provider별 exact settings는 source authority 결정 뒤 추가한다. class name, module path, plugin 또는
  caller-selected factory는 config 값이 될 수 없다.

### Secret와 credential ownership

- [제안] Security/Secret Provisioning Owner가 deployment-owned protected role-specific secret files를 공급하고 process
  environment에는 그 file location만 주입한다. raw password·raw DSN environment, version-controlled secret, CLI/API argument와
  caller-provided credential은 금지한다.
- [제안] Proposal과 Review credential source는 분리한다. 동일 host·port·database를 사용할 수 있지만 role은 각각
  `dohalm_dataset_proposal_authority`, `dohalm_dataset_review_authority`로 고정하며 하나의 credential·DSN·role로 합치지 않는다.
- [제안] application은 secret file을 생성·수정·출력하지 않는다. missing, relative, unreadable, symlink/reparse substitution,
  검증 불가능한 ACL과 role mismatch는 fail closed한다. exact environment variable name과 secret provider wire format은 source
  implementation Gate에서 고정하며 임의 fallback을 두지 않는다.

### Publication root ownership

- [제안] governance runtime config가 production `publication_root` reference를 소유하고 deployment가 실제 absolute path를
  공급한다. CLI option은 non-secret override가 아니라 inspect용 redacted reference만 받을 수 있다.
- [제안] cwd, repository root, user home, temp와 implicit default를 금지한다. root는 absolute·non-symlink이고 repository 밖의
  deployment-owned storage여야 하며 existing atomic publication adapter의 요구를 preflight해야 한다.

## Config decision matrix

| 항목 | Existing config reuse | New governance config | External deployment-only | 미정 |
|---|---|---|---|---|
| ownership | model/run 또는 inference에 결속 | DohaLM governance boundary가 소유 | repository validation 부재 | owner 미정 유지 |
| secret safety | governance loader 없음 | protected role-secret reference 분리 가능 | provider별 drift 위험 | policy 미적용 |
| testability | schema가 맞지 않음 | immutable config/fake secret provider 가능 | deployment 없이는 검증 어려움 | 낮음 |
| CLI suitability | unrelated override surface | CLI와 독립된 factory input 가능 | CLI가 topology를 알게 됨 | 불가 |
| API future use | inference settings 오염 | 동일 factory를 future host가 재사용 가능 | deployment별 중복 | 불가 |
| publication root | owner 없음 | 단일 explicit owner | external convention마다 다름 | owner 없음 |
| DB role separation | 통합 construction 없음 | Proposal·Review source를 분리 | 배포 실수 검증 경계 없음 | 보장 없음 |
| preflight | governance result 없음 | typed aggregate contract 가능 | app-level semantic mapping 없음 | 불가 |

### Config / Composition 판정

- [제안] 최종 판정은 `B. NEW DOHALM GOVERNANCE RUNTIME CONFIG REQUIRED`다.
- [제안] deployment는 non-secret values와 protected secret references를 공급하지만 schema, validation, role binding,
  composition과 sanitized result ownership은 DohaLM에 남는다. 따라서 external deployment-only config는 채택하지 않는다.
- [제안] future conceptual boundary는 `GovernanceRuntimeConfig → build_dataset_governance_runtime(...) → ports/services`다.
  symbol은 구현 승인이 아니며 CLI, API와 worker가 adapter class나 credential을 선택하지 못하게 하는 dedicated factory를 뜻한다.

## Composition lifetime과 validation

- [제안] future CLI invocation은 config와 secret reference를 한 번 load하고, Common compatibility와 preflight를 한 번 수행한 뒤
  Proposal·Review·CurrentEvidence adapter를 한 번 구성한다. PostgreSQL connection·transaction은 기존처럼 authority invocation마다
  짧게 열고 닫으며 global singleton·pool을 추가하지 않는다. publication storage는 stateless dependency다.
- [제안] startup validation은 config shape, required secret reference 존재, fixed role binding, Common package/policy/schema
  compatibility를 검사한다.
- [제안] read-only preflight는 Proposal·Review DB reachability, expected migration head, current role capability, evidence authority
  availability와 publication root의 atomic publication 적합성을 fail closed로 확인한다. 실제 migration·role grant·root 생성은
  수행하지 않는다.
- [제안] invocation validation은 DB availability를 short-lived connection에서 다시 확인하고 current RightsMetadata,
  TrainingEligibility, authoritative Proposal·Review state와 exact evidence binding을 매 operation마다 재검증한다.
- [제안] typed preflight result가 필요하다. 성공은 `READY` 하나이며 최소 failure taxonomy는 `NOT_CONFIGURED`,
  `DB_UNAVAILABLE`, `MIGRATION_MISMATCH`, `ROLE_INVALID`, `EVIDENCE_AUTHORITY_UNAVAILABLE`, `PUBLICATION_ROOT_INVALID`,
  `CONTRACT_VERSION_MISMATCH`다. failure가 하나라도 있으면 write command를 열지 않는다.
- [제안] config/composition/preflight error와 result에는 password, DSN, secret·absolute path, raw environment, SQL, stack trace와
  raw evidence body를 포함하지 않는다. stable machine-readable code와 redacted component name만 허용한다.

## Remaining dependencies

### Reviewer authority

- [제안] runtime config는 reviewer reference를 운반할 수 있지만 그 값을 trustworthy하게 만들지 않는다. reviewer
  issuer·trust·accountability는 별도 선행 Architecture Gate로 남는다. OS user, Git identity, process user와 CLI current user를
  reviewer로 승격하지 않는다.

### Publication read

- [제안] standalone publication-pair read는 propose CLI의 prerequisite가 아니다. Proposal inspect는 existing authoritative read로
  제공할 수 있다.
- [제안] review-start CLI는 Proposal·Review inspect와 reviewer authority가 필요하지만 publication inspect에 의존하지 않는다.
- [제안] approve/publish operator workflow를 활성화하기 전에는 committed frozen DatasetVersion·issued DatasetManifest pair의
  public read/inspect contract가 필요하다. private replay storage protocol이나 새 aggregate state store로 우회하지 않는다.

## CLI reconsideration readiness

- [제안] proposal CLI 재검토에는 production CurrentEvidence source·selection/revocation contract, approved governance config,
  role-separated secret source, publication root owner와 typed preflight가 모두 필요하다.
- [제안] review-start CLI에는 위 조건과 reviewer trust policy가 추가로 필요하다.
- [제안] approve/publish CLI에는 approval action UX 재검토와 standalone publication read contract가 추가로 필요하다.
- [제안] 이번 Gate 뒤에도 위 첫 조건이 충족되지 않으므로 CLI implementation은 시작하지 않는다.

## Overall decision

- [제안] CurrentEvidence: `D. BLOCKED — EVIDENCE SOURCE NOT DEFINED`
- [제안] Runtime Config / Composition: `B. NEW DOHALM GOVERNANCE RUNTIME CONFIG REQUIRED`
- [제안] 전체 prerequisite 상태: `STILL BLOCKED`
- [제안] Runtime Activation, first supported entrypoint, API, worker와 Training 상태는 변경하지 않는다.

## 기각한 대안

| 대안 | 기각 사유 |
|---|---|
| caller가 Rights/Eligibility payload 제공 | production authority와 current selection을 우회함 |
| proposal extension의 ID 중 latest record 선택 | version·supersession authority 없이 timestamp policy를 발명함 |
| DohaLM DB에 Rights를 즉시 복제 | upstream owner, writer, revoke와 reconciliation 계약이 없음 |
| filesystem JSON registry | concurrent update·revocation·multi-worker snapshot 계약이 없음 |
| existing model/run config 확장 | secret·DB role·publication lifecycle을 training config에 결합함 |
| FastAPI settings 확장 | inference deployment를 governance composition owner로 잘못 승격함 |
| raw DSN/password environment | environment dump·diagnostic과 process exposure 위험 |
| config가 reviewer trust 보증 | configuration과 identity authority를 혼동함 |

## 후속 Gate와 구현 순서

1. RightsMetadata·TrainingEligibility producer, durable source, unique-current selection, revocation/current projection과 read
   interface를 결정하는 CurrentEvidence Source Authority Gate
2. reviewer issuer·trust·accountability Gate
3. standalone publication pair public read contract Gate
4. 위 결정 승인 뒤 governance config/secret loader·composition·read-only preflight contract 구현 PR
5. production CurrentEvidence source adapter와 DohaLM coordinator 구현 PR
6. 별도 Runtime Activation Gate에서 first supported CLI surface 재검토

각 단계는 별도 Ready·사용자 승인·테스트와 fixed-head 검증을 요구한다.

## 제외 범위

- [제외] production source, config, adapter, factory, CLI, API와 worker 구현
- [제외] migration, DB role·grant, secret·publication directory 생성 또는 변경
- [제외] 다른 repository 변경과 근거 없는 cross-repository interface 확정
- [제외] reviewer·approval actor authority와 IAM 구현
- [제외] Training, Evaluation과 promotion 연결

## 미결정 사항

- [검증 필요] RightsMetadata production producer·durable source·revocation owner와 authenticated read interface
- [검증 필요] TrainingEligibility producer workflow·durable source·unique-current projection과 revoke owner
- [검증 필요] 두 source를 한 `evaluated_at`에 결속하는 consistency/snapshot 의미
- [검증 필요] protected secret reference의 exact environment names, provider wire format과 platform ACL validation
- [검증 필요] publication root atomic-usability preflight의 non-publication probe contract
- [검증 필요] reviewer authority와 standalone publication read public port

## 승인 Gate

이 ADR은 `draft`다. 독립 검토, 사용자 명시 승인과 병합 전에는 authoritative implementation requirement가 아니다.
병합되더라도 CurrentEvidence source가 `BLOCKED`이므로 production adapter, runtime config implementation, CLI·API·worker activation과
Training을 승인하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-25 | [제안] CurrentEvidence source를 `BLOCKED`, 새 DohaLM governance config/composition을 `REQUIRED`, 전체 prerequisite를 `STILL BLOCKED`로 판정 |
