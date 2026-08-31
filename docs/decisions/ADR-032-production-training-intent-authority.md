# ADR-032: Production Training Intent Authority

- 문서 상태: `approved`
- 마지막 검토일: 2026-09-01
- 결정 상태: `approved`
- 실행 영향: architecture contract 승인; foundation 구현 진입 허용, production Training activation 미승인
- 승인 근거: 사용자 `DDORINY` 명시 architecture approval (2026-09-01),
  [PR #187 Approval Status Transition](https://github.com/DohaStudio/DohaLM/pull/187)
- 관련 문서: [ADR-016](./ADR-016-generic-training-execution-approval-boundary.md),
  [ADR-017](./ADR-017-production-training-execution-issuer-trust-anchor.md),
  [ADR-018](./ADR-018-composition-root-owned-training-execution-decision-source.md),
  [ADR-019](./ADR-019-production-full-pretraining-host-and-trusted-decision-input.md),
  [ADR-020](./ADR-020-production-training-orchestration-ownership-seams.md),
  [ADR-021](./ADR-021-production-training-adapters-and-durable-journal.md),
  [C3 PostgreSQL Training Composition](../architecture/c3-postgresql-training-composition.md),
  [테스트 전략](../quality/test-strategy.md)

## Context

[확정] 현재 production Training architecture에는 PostgreSQL 기반 config, readiness, Dataset version·manifest·pair,
execution decision, issuer와 approver authority가 있다. 각 authority는 immutable payload와
`training_authority_event`/`training_authority_current`의 current·revoked·superseded lifecycle을 사용한다.
ADR-021은 이 authority snapshot과 execution journal·reservation·CAS를 승인했고 C1/C2/C3 구현은 해당 계약을 따른다.

[확정] 현재 execution journal은 `run_id`, request·intent fingerprint, claim reservation, execution phase,
backend 진입, terminal outcome과 manual reconciliation을 소유한다. `ProductionTrainingHostIntent`는 caller가 전달하는
frozen execution-facing value일 뿐 durable intake record나 실행 권위가 아니다. C3 composition은 intent intake,
executable, scheduler와 public Host accessor를 제공하지 않는다.

[확정] 다음 production intake authority는 아직 없다.

- accountable production intent submitter principal
- durable immutable intent submission과 authoritative read
- submitter-scoped idempotency와 deterministic replay/conflict
- immutable intent와 execution decision 사이의 durable binding
- future non-CLI application entrypoint가 소비할 validated intent record

[확정] execution journal을 intent intake store로 재사용하면 “누가 무엇을 요청했는가”와 “실행이 어떻게 진행됐는가”가
한 lifecycle에 섞인다. denied 또는 never-claimed intent를 execution claim처럼 표현하게 되고 journal phase가 submission
상태로 확장된다. 이 ADR은 intent authority와 execution journal을 분리한다.

## Decision summary

[확정] v1은 다음 architecture를 채택한다.

```text
trusted local configuration
  -> current dedicated intent submitter authority
  -> immutable durable intent submission
  -> validated TrainingExecutionRequest v1 projection
  -> current execution decision
  -> append-only intent/decision binding
  -> validate-only application boundary
  -> STOP
```

[확정] 이 ADR은 `DEDICATED_SUBMITTER_AUTHORITY`, `intent_id != run_id`, submitter-scoped idempotency와
`SUBMIT -> VALIDATE PROJECTION -> DECIDE -> APPEND-ONLY BIND`를 선택한다. 이 문서가 `approved`가 되기 전에는
schema, migration, port, adapter 또는 application service 구현을 시작하지 않는다.

## Dedicated submitter authority

[확정] production intent submitter는 기존 issuer·approver와 다른 dedicated PostgreSQL authority family다. conceptual
subject family는 `intent_submitter`다. trusted local configuration은 current local operator authority UUID 하나를 선택하지만,
configuration 문자열이나 caller가 전달한 display value 자체는 authority가 아니다.

[확정] submitter authority는 기존 authority identity/event/current projection pattern을 재사용한다.

- stable UUID identity와 immutable payload를 가진다.
- authority producer가 provision하고 lifecycle event를 기록한다.
- `current`인 exact authority만 새 submission을 만들 수 있다.
- `revoked`, `superseded`, `expired` 또는 missing authority는 fail closed다.
- submission 뒤 submitter가 stale해져도 historical intent를 삭제하거나 rewrite하지 않는다.
- validate-only와 future execution boundary는 submitter currentness를 다시 확인한다.

[제외] caller-provided arbitrary string, existing execution issuer 재사용, OS account projection과 public user registration은
submitter authority가 아니다.

### Local single-user boundary

[확정] 현재 production target은 single-user local/on-prem durable runtime이다. v1 deployment는 dedicated family에 current
local operator 하나만 provision하고 configuration은 그 UUID 하나만 선택한다. OAuth, multi-tenant IAM, cloud directory,
workspace/project/job authority, queue scheduler와 Kubernetes orchestration은 만들지 않는다.

## Intent와 run identity

[확정] `intent_id`와 `run_id`는 별도 identity다. v1 cardinality는 `1 intent -> 1 requested run`이며 각 submission은
`requested_run_id` 하나를 freeze한다.

- denied intent는 run을 실행하지 않아도 authoritative submission으로 남는다.
- submitted intent는 never claimed일 수 있다.
- intent는 request authority identity이고 run은 execution identity다.
- `requested_run_id`는 v1 intent 전체에서 unique해 다른 intent에 재사용하지 않는다.
- 동일 intent를 재승인하거나 재실행하지 않는다. 새 시도는 새 intent, 새 requested run과 새 decision을 요구한다.
- future 1:N scheduling은 이 ADR 범위가 아니다.

## Responsibility와 lifecycle

| Owner | Owns | Must not own |
|---|---|---|
| Intent Authority | submitter, submission identity, immutable references, idempotency, fingerprint, creation time, decision binding | execution claim, backend phase, terminal execution outcome |
| Execution Journal | run claim, reservation, execution phase, backend entry, outcome, reconciliation | caller submission authority, submitter lifecycle, intake idempotency |

[확정] intent lifecycle은 immutable submission과 최대 하나의 decision binding에서 다음 상태로 derive한다.

- `SUBMITTED`: decision binding이 없다.
- `DECISION_BOUND_APPROVED`: immutable binding의 decision value가 `approved`다.
- `DECISION_BOUND_DENIED`: immutable binding의 decision value가 `denied`다.

decision의 이후 currentness 상실은 binding history를 rewrite하지 않고 validate-only를 실패시킨다. `CLAIMED`, `RUNNING`,
`COMPLETED`, `FAILED`와 reconciliation은 execution journal state이며 intent lifecycle에 추가하지 않는다.

## Immutable intent record

[확정] v1 immutable intent submission은 최소 다음 conceptual fields를 가진다.

| Field | Contract |
|---|---|
| `schema_version` | exact integer `1` |
| `intent_id` | trusted adapter가 발급하는 UUID; caller authority가 아님 |
| `submitter_authority_id` | current `intent_submitter` authority UUID |
| `client_request_id` | submitter-scoped idempotency identifier |
| `action` | exact `full_pretraining` |
| `requested_run_id` | v1에서 unique한 execution identity |
| `execution_mode` | `fresh` 또는 `r3_one_epoch_continuation` |
| Dataset binding | version·manifest·pair authority UUID와 exact pair fingerprint |
| config binding | config authority UUID와 exact payload/config fingerprint |
| readiness binding | readiness authority UUID와 exact readiness fingerprint |
| `source_commit` | exact lowercase 40-character commit SHA |
| `output_logical_root` | validated relative logical output root |
| continuation binding | mode-specific predecessor run/checkpoint/step/target material |
| `intent_fingerprint` | versioned canonical submission fingerprint |
| `created_at` | database-authoritative `timestamptz` |

[확정] Common DatasetVersion·DatasetManifest logical IDs는 immutable authority rows에서 deterministic하게 resolve한다.
raw filesystem path, mutable config path, raw `ready=true`와 caller timestamp는 authority field가 아니다.

### Timestamp

[확정] creation time은 PostgreSQL `transaction_timestamp()`가 발급한다. column type은 `timestamptz`이며 external typed
record는 UTC canonical timestamp를 반환한다. caller timestamp는 저장·비교 authority로 사용하지 않는다.

## Canonical fingerprint

[확정] intent fingerprint는 repository `canonical_json_bytes()` precedent와 호환되는 다음 v1 contract를 사용한다.

- algorithm: SHA-256, `sha256:<64 lowercase hex>`
- encoding: UTF-8
- serialization: JSON object, lexicographically sorted keys, compact `,`/`:` separators, non-finite number 거부
- terminator: trailing LF exactly one
- version: canonical projection에 `schema_version=1`과 `action=full_pretraining` 포함

[확정] fingerprint input은 submitter authority, requested run, execution mode, Dataset exact binding, config exact binding,
readiness exact binding, source commit, output logical root와 continuation binding이다. `intent_id`, `client_request_id`,
`created_at`, display metadata와 post-submit decision identity는 fingerprint에서 제외한다.

fingerprint는 uniqueness identity가 아니다. 같은 semantic request라도 다른 `client_request_id`, 새 intent와 새 run으로 별도
submission을 만들 수 있다.

## Idempotency와 transaction

[확정] idempotency identity는 `(submitter_authority_id, client_request_id)`다. `client_request_id`는 retry correlation이며
submitter 권위나 intent identity가 아니다.

| Case | Result |
|---|---|
| new scoped key | 새 immutable intent 한 건 생성 |
| same key + same fingerprint | 기존 exact typed record 반환 |
| same key + different fingerprint | deterministic conflict; row·binding mutation 0 |

[확정] PostgreSQL unique constraint와 restricted submission function이 concurrent insert를 serialize한다. exact loser는 winning
row를 읽어 반환하고 conflicting loser는 stable conflict로 실패한다. UPDATE, overwrite, delete와 fingerprint unique constraint는
사용하지 않는다. 이 contract는 retry-safe intake이며 exactly-once execution을 주장하지 않는다.

## Exact authority bindings

### Dataset

[확정] intent는 DatasetVersion authority UUID, DatasetManifest authority UUID, Dataset pair authority UUID와 exact pair
fingerprint를 freeze한다. pair가 exact version/manifest를 참조하는지 authoritative resolver가 검증한다. raw Dataset path나
caller-supplied manifest payload는 authority가 아니다.

### Config

[확정] intent는 training config authority UUID와 exact payload/config fingerprint를 freeze한다. mutable config path와 caller
mapping은 authority가 아니다.

### Readiness

[확정] intent는 readiness authority UUID와 exact readiness fingerprint를 freeze한다. readiness는 Dataset pair와 config
fingerprint에 exact하게 결속돼야 하며 boolean readiness를 허용하지 않는다.

### Source와 output

[확정] intent는 expected source commit을 freeze한다. clean worktree는 durable intent field가 아니라 validate-only와 future
execution preflight가 실제 source state에서 다시 확인할 fact다. output logical root도 fingerprint에 포함하지만 artifact
registry, checkpoint publication authority 또는 model publication root로 해석하지 않는다.

## Fresh와 continuation

[확정] `fresh` mode의 predecessor run, checkpoint, source step과 target binding은 모두 NULL이어야 한다. 하나라도 있으면
submission invalid다.

[확정] `r3_one_epoch_continuation`은 current approved R3 one-epoch contract의 predecessor run, checkpoint reference,
source step과 target cumulative step binding을 모두 요구한다. 이 값은 immutable config authority와 exact하게 일치해야 한다.
arbitrary resume는 추가하지 않는다. continuation intent도 새 intent, 새 run과 새 decision을 요구하며 predecessor approval을
재사용하지 않는다. checkpoint reference는 이 ADR에서 artifact authority가 되지 않는다.

## Validation timing

| Boundary | Required validation |
|---|---|
| submission | typed structure, authority row existence, submitter currentness, canonical fingerprint, mode fields, idempotency |
| request projection | full Dataset/config/readiness resolution과 exact binding, source/output structure, deterministic request fingerprint |
| decision bind | decision currentness, exact request fingerprint, issuer/approver binding, existing binding 0 |
| validate-only / future execution | submitter, Dataset, config, readiness와 decision currentness 재검증; actual source commit·clean state와 output availability |

[확정] submission-time existence는 future validity를 보장하지 않는다. 모든 stale-after-submit 상태는 fail closed이며 intent나
decision binding을 자동 교체하지 않는다.

## Approval flow와 request projection

[확정] approval flow는 Model C다.

```text
SUBMIT
  -> VALIDATE CANONICAL EXECUTION-REQUEST PROJECTION
  -> DECIDE
  -> APPEND-ONLY BIND
```

[확정] raw caller request나 unvalidated intent fingerprint에 approval을 붙이지 않는다. validated intent에서 existing
`TrainingExecutionRequest v1`의 다음 11-field canonical projection을 deterministic하게 만든다.

1. `schema_version`
2. `action`
3. `dataset_version_id`
4. `dataset_manifest_id`
5. `dataset_pair_fingerprint`
6. `config_fingerprint`
7. `readiness_fingerprint`
8. `run_id`
9. `output_logical_root`
10. `source_commit`
11. `execution_mode`

request fingerprint도 같은 canonical JSON/SHA-256 contract를 사용한다. decision authority의 `request_fingerprint`는 이 exact
projection과 같아야 한다. post-submit decision evidence reference는 request fingerprint input이 아니며 decision binding 뒤
execution-facing Host intent에 projection된다.

## Append-only decision binding

[확정] submission row는 decision을 넣기 위해 UPDATE하지 않는다. 별도 immutable `intent_decision_binding` concept가
`intent_id`, decision authority identity, exact request fingerprint, durable decision evidence reference와 database binding
timestamp를 기록한다.

- v1 intent 하나에는 binding을 최대 한 건만 허용한다.
- 하나의 decision authority record도 최대 한 intent에만 bind한다.
- bind 시 decision과 issuer/approver가 current이고 request fingerprint가 exact해야 한다.
- approved와 denied 모두 immutable binding으로 남는다.
- denied, revoked 또는 stale decision을 새 decision으로 교체하지 않는다. 새 시도는 새 intent와 run을 사용한다.
- binding UPDATE와 DELETE는 금지한다.

[확정] durable storage에는 decision identity와 audit-safe evidence만 둔다. process-local single-use
`TrainingExecutionApproval`, submission capability와 issuer capability는 serialize하거나 restart 뒤 복원하지 않는다.

## Conceptual authority port

[확정] future application-facing port는 다음 최소 operations만 제공한다.

```text
submit(submission) -> IntentRecord
get(intent_id) -> IntentRecord | None
get_by_idempotency(submitter_authority_id, client_request_id) -> IntentRecord | None
bind_decision(binding) -> IntentDecisionBinding
get_decision_binding(intent_id) -> IntentDecisionBinding | None
```

read result는 typed, frozen, versioned value다. raw DB row/dict를 authority contract로 노출하지 않는다. generic CRUD,
submission update/delete, decision-binding update/delete, list-all과 caller-selected adapter는 제공하지 않는다.

## PostgreSQL schema와 GRANT model

[확정] 별도 schema objects가 필요하다. execution journal column 확장은 기각한다. implementation은 repository naming
convention을 검증하되 다음 세 책임을 분리한다.

1. dedicated intent submitter authority payload family
2. immutable intent submission table
3. immutable intent decision binding table

[확정] conceptual constraints는 다음과 같다.

- `intent_id` primary key
- `(submitter_authority_id, client_request_id)` unique
- `requested_run_id` unique in v1
- intent/decision binding one-to-one
- authority UUID foreign keys와 delete restrict
- fingerprint는 non-unique
- submission과 binding immutable UPDATE/DELETE triggers

| Role | Allowed | Forbidden |
|---|---|---|
| DB object owner | schema/table/function ownership과 migration | LOGIN, runtime request |
| authority producer | submitter payload provision, publish/revoke/supersede event, restricted decision bind | intent submission impersonation, execution |
| intent writer | restricted submit function execution | direct table INSERT, UPDATE, DELETE, authority provision, decision creation |
| resolver/application | restricted typed read/validation functions | direct DML, authority mutation |
| execution journal | existing claim/read/transition functions | intent/submitter table mutation |
| PUBLIC | 없음 | schema/table/function access |

[확정] runtime roles에는 direct table UPDATE/DELETE를 부여하지 않는다. intent writer credential은 caller principal이 아니며
submitted UUID가 trusted configuration이 선택한 current operator와 exact한지 restricted function이 검증해야 한다.

## Failure and security contract

[확정] architecture-level stable failure categories는 다음을 구분한다. exact exception symbol과 sanitized message는 foundation
implementation PR에서 repository convention에 맞춰 고정한다.

- unauthorized, missing 또는 non-current submitter
- idempotency conflict
- invalid Dataset binding
- invalid config binding
- invalid readiness binding
- decision/request mismatch 또는 duplicate binding
- source commit mismatch

[확정] intent, error, log와 durable binding에 password, DSN, API/GitHub token, credential, raw Dataset/config/readiness payload,
local absolute path와 process-local capability를 저장하거나 노출하지 않는다. caller는 submitter, issuer, approver, adapter,
database role과 authority escalation을 임의 주입할 수 없다.

## Future application entrypoint

[확정] future entrypoint의 허용 flow는 다음과 같다.

```text
caller
  -> trusted configuration이 선택한 current submitter authority
  -> durable intent authority
  -> validated request projection
  -> current decision binding
  -> validate-only application service
  -> separately approved C3/Host wiring
```

[확정] `raw caller -> ProductionFullPretrainingHost.run()`은 금지한다. 이 ADR은 application entrypoint, C3 startup, Host
invocation 또는 backend execution을 구현하거나 승인하지 않는다.

## Alternatives rejected

| Alternative | Rejection reason |
|---|---|
| configured local operator string only | durable currentness, revoke/supersede와 accountable identity가 없음 |
| existing execution issuer reuse | intent submitter와 decision issuer 책임·credential을 결합함 |
| OS/local account projection | platform coupling, durable identity와 test reproducibility 부족 |
| execution journal reuse | intent submission과 execution lifecycle·reconciliation 책임을 혼합함 |
| fingerprint-only idempotency | 동일 semantic request의 별도 authorized submission을 막음 |
| mutable submission row에 decision 추가 | immutable intake audit와 concurrent state 의미를 약화함 |

## Consequences

[확정] 장점은 accountable submitter, durable immutable intake, retry-safe submission, exact approval target, stale authority
fail-closed와 future non-CLI entrypoint foundation이다. denied/never-executed intent와 actual run state도 정직하게 분리된다.

[확정] 비용은 새 authority family와 migration, role-separated restricted functions, intent에서 request/Host projection으로의
추가 validation, 별도 decision-binding lifecycle이다. intent persistence와 Training side effect는 하나의 transaction이 아니며
exactly-once execution은 계속 주장하지 않는다.

## Relationship to previous ADRs

[확정] ADR-032는 ADR-021을 폐기하거나 execution journal contract를 변경하지 않는다. ADR-021이 승인한 authority
event/current pattern과 PostgreSQL least-privilege precedent를 재사용하고 journal 앞의 상위 intake boundary를 추가한다.

[확정] ADR-016~020은 계속 `draft`/`proposed` historical design이다. 이 ADR은 이들의 request-bound approval,
same-process capability, Host ownership과 intent/execution separation 방향을 refine하지만 supersede하거나 상태를 변경하지 않는다.
충돌 시 approved ADR-021과 향후 명시 승인된 ADR-032가 우선하며 실제 activation은 별도 Gate에 남는다.

## Out of scope and activation prohibition

[제외] 다음은 이 ADR과 후속 foundation 구현 범위가 아니다.

- actual Training activation 또는 full-pretraining workload
- C3 startup, Host/backend invocation, GPU, model construction과 checkpoint/artifact 생성
- HTTP API, public CLI activation command와 scheduler
- cancellation, withdrawal과 execution preemption
- artifact/checkpoint registry와 model publication root
- generic multi-user IAM, OAuth, cloud directory와 workspace/project/job authority
- arbitrary resume와 future intent-to-run 1:N
- execution journal redesign과 exactly-once execution
- Dataset publication, config/readiness authority와 decision authority mutation

**This ADR does not authorize production Training activation.**

## Implementation and approval Gate

[확정] 이 ADR PR은 documentation only다. migration, schema, Python port, PostgreSQL adapter, application service, test,
workflow, dependency, ruleset와 production data를 변경하지 않는다.

| ADR PR mutation | Count |
|---|---:|
| migration | 0 |
| schema | 0 |
| production code | 0 |
| tests | 0 |
| workflow/dependency/ruleset | 0 |
| Host/backend/Training activation | 0 |

[확정] Draft PR 또는 Ready 전환만으로 architecture approval이 되지는 않는다. 사용자 `DDORINY`가 2026-09-01 이
architecture content를 명시 승인했고, 이 status transition은 document와 decision을 `approved`로 동기화한다.
`Production Training Intent / Approval Authority Foundation` 구현 진입만 허용하며, foundation 구현이 별도 검증·병합되더라도
application entrypoint와 actual Training activation은 각각 후속 Gate를 요구한다.

Foundation implementation authorization은 `YES`이고 actual Training activation은 `NO`다.

### Foundation implementation mapping

[구현] `src/training/production_intent_authority.py`는 frozen intent model, canonical fingerprint,
construction-bound local submitter 선택, 기존 `TrainingExecutionRequest v1` exact projection과 validate-only STOP을 구현한다.
`src/training/postgres_training_intent_authority.py`와 forward-only migration `0006_training_intent_authority.sql`은
기존 identity/event/current pattern을 재사용한 submitter family, immutable submission, restricted writer/read surface와
append-only decision binding을 구현한다. 구현 PR이 병합되기 전 문서 상태는 `approved`를 유지하며,
application entrypoint와 actual Training activation은 계속 금지한다.

## Revisit conditions

- production scope가 multi-user, cross-process 또는 network-authenticated topology로 바뀐다.
- 한 intent가 여러 run을 생성해야 한다.
- cancellation, withdrawal 또는 re-approval이 필요하다.
- approval request projection이나 existing `TrainingExecutionRequest` field set이 바뀐다.
- artifact/checkpoint authority가 intent lifecycle과 결속돼야 한다.
- approval capability 또는 execution side effect와 durable intent를 원자적으로 묶는 새 transaction model이 생긴다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-09-01 | [구현] dedicated submitter authority, immutable intent/idempotency, exact request projection, append-only decision binding과 validate-only STOP foundation을 구현 review에 반영; Host/backend/Training activation 0 유지 |
| 2026-09-01 | [확정] 사용자 `DDORINY` 명시 architecture approval로 `draft/proposed`에서 `approved/approved`로 전환하고 foundation 구현 진입만 허용; actual Training activation은 계속 금지 |
| 2026-09-01 | [제안] dedicated submitter authority, immutable intent/idempotency, validated request projection과 append-only decision binding architecture 초안 작성 |
