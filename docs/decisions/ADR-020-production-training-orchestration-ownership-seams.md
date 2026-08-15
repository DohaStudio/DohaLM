# ADR-020: Production Training Orchestration Ownership Seams

- 문서 상태: `draft`
- 마지막 검토일: 2026-08-13
- 결정 상태: `proposed`
- 실행 영향: 없음
- 관련 문서: [ADR-014](./ADR-014-dataset-product-governance-boundary.md),
  [ADR-015](./ADR-015-dataset-version-publication-contract.md),
  [ADR-016](./ADR-016-generic-training-execution-approval-boundary.md),
  [ADR-017](./ADR-017-production-training-execution-issuer-trust-anchor.md),
  [ADR-018](./ADR-018-composition-root-owned-training-execution-decision-source.md),
  [ADR-019](./ADR-019-production-full-pretraining-host-and-trusted-decision-input.md),
  [Full Pretraining 실행 계획](../training/full-pretraining-execution-plan.md),
  [Full Pretraining Readiness](../training/full-pretraining-readiness.md)

## Context

[확정] 이 문서는 ADR-019를 대체하거나 재개방하지 않는 후속 Design ADR이다. ADR-019가 정한 non-CLI,
same-process Production Full Pretraining Host, trusted decision resolver, durable journal, 일곱 decision field와
fail-closed 원칙은 그대로 유지한다.

[확정] 병합된 foundation의 `ProductionTrainingHostIntent`는 DatasetVersion·DatasetManifest·config·readiness의
opaque reference와 기대 fingerprint를 받지만, 실제 Common 객체와 config/readiness evidence를 어떤 construction-bound
port가 resolve하는지 정하지 않는다. 반면 canonical request builder는 exact evaluator-issued
`DatasetTrainingPermission`, config filesystem path, readiness mapping과 Dataset pair identity를 요구한다. caller payload나
path를 그대로 받으면 ADR-019의 authority boundary를 우회하고, Host가 임의 resolver를 만들면 composition root ownership을
우회한다.

[확정] 현재 `run_full_pretraining()`의 권한 순서는 backend precondition 재검증, production approval issuance,
`consume_training_execution_approval()`, `_enter_execution_boundary()`, model·Dataset·output side effect 순이다. 그러나
현재 durable journal transition은 `DECISION_SUBMITTED -> BACKEND_ENTERED -> APPROVAL_CONSUMED`다. 이 순서는 실제
consume/entry 경계와 반대이며 Host가 진실한 phase를 기록할 typed seam도 없다.

[확정] existing request builder의 `_verified_source()`는 request construction 시 current commit/clean state를 확인한다.
backend의 `require_training_execution_request()`는 config checksum, readiness field, Dataset target, run/output과 no-resume를
다시 확인하지만 current source를 다시 inspect하지는 않는다. lifecycle seam은 이 차이를 숨기거나 독자 hash를 만들지 않고,
같은 canonical source/readiness helper를 issuance 직전에 다시 사용해야 한다.

[확정] public callback, caller-provided hook 또는 approval/capability 반환으로 이 관찰 공백을 메우면 backend 내부 권한을
외부로 유출하거나 caller가 lifecycle event를 위조할 수 있다. 반대로 backend 전체를 Host가 재구현하면 canonical
`run_full_pretraining()` validation·issuance·consume 순서를 우회한다.

[제안] 위 두 공백을 `BLOCKED_BY_ORCHESTRATION_OWNERSHIP_CONFLICT`로 정의한다. 이 ADR은 prerequisite resolution
port와 package-private backend lifecycle seam의 소유권·typed 계약을 고정해 그 **설계 공백만** 해소한다. Python,
source, test, CLI, adapter, journal 또는 실제 Training은 이 문서 PR에서 변경하지 않는다.

## 검토한 선택지

| 선택지 | 장점 | 문제 | 판정 |
|---|---|---|---|
| caller가 Common payload·path·readiness mapping을 Host에 직접 전달 | 연결이 단순함 | caller가 authority와 local path를 주입하고 immutable reference 계약을 우회 | 기각 |
| Host가 request마다 resolver를 선택하거나 dynamic import | adapter 교체가 쉬움 | composition-root trust anchor와 construction binding을 우회 | 기각 |
| prerequisite resolver가 approval 또는 request까지 생성 | 한 번에 resolve 가능 | Dataset/config authority와 canonical request/decision authority가 혼합 | 기각 |
| public backend callback으로 consume·entry를 통지 | 기존 body 변경이 작음 | callback 위조·재진입·capability leakage와 public API 확대 | 기각 |
| Host가 backend validation·issuance·consume를 복제 | journal 순서를 직접 제어 | canonical backend 우회와 두 개의 실행 경계 발생 | 기각 |
| construction-bound prerequisite port + package-private lifecycle coordinator | authority source와 lifecycle 관찰을 typed·internal boundary로 제한 | 내부 backend 분해와 journal transition 보완 필요 | 채택 제안 |

## Proposed Decision

### 1. 소유권 원칙

[제안] production composition root만 prerequisite resolver, trusted decision resolver, durable journal, issuer adapter와
package-private backend lifecycle coordinator를 조립한다. Host는 이 exact object graph의 유일한 application owner다.

- caller는 immutable `ProductionTrainingHostIntent`만 제출한다.
- prerequisite resolver는 reference를 authority object로 해석하지만 request, decision, approval 또는 backend result를
  만들지 않는다.
- Host는 intent binding 검증, canonical request 생성, durable claim과 decision resolution/submission을 소유한다.
- existing request builder는 `TrainingExecutionRequest`와 `request_fingerprint`의 유일한 canonical producer다.
- existing production issuer/backend는 approval issuance·consume와 execution entry의 유일한 owner다.
- backend lifecycle coordinator는 Host가 위임한 consume 이후 journal transition을 수행하지만 business decision 또는
  approval authority를 새로 만들지 않는다.

이 역할 중 어느 것도 CLI, inference app, environment variable, caller-selected factory 또는 test double로 production
runtime에서 대체할 수 없다.

### 2. canonical intent fingerprint

[제안] Host는 validated `ProductionTrainingHostIntent`의 아래 정확히 열두 field를 이름순 canonical JSON object로
projection하고 기존 `checksum_value()` 규칙으로 `intent_fingerprint`를 계산한다.

1. `action`
2. `execution_mode`
3. `dataset_version_reference`
4. `dataset_manifest_reference`
5. `expected_dataset_pair_fingerprint`
6. `training_config_reference`
7. `expected_config_fingerprint`
8. `readiness_evidence_reference`
9. `expected_readiness_fingerprint`
10. `run_id`
11. `output_logical_root`
12. `decision_evidence_reference`

caller hash, resolver hash, object identity, timestamp, filesystem path와 iteration order는 substitute가 아니다. 이 fingerprint는
intent-to-resolution binding과 audit correlation이며 approval credential이 아니다. canonical execution identity는 request
builder가 만든 `(run_id, request_fingerprint)`로 계속 유지한다.

### 3. construction-bound prerequisite resolver port

[제안] package-private 논리 port `_TrustedTrainingPrerequisiteResolver`를 둔다. port instance는 production composition
root가 Host construction 시 정확히 한 번 결속하며 request별 교체, setter, service locator, dynamic import와 caller injection을
허용하지 않는다.

논리 signature는 다음과 같다.

```text
resolve(
    intent: ProductionTrainingHostIntent,
    *,
    intent_fingerprint: str,
) -> ResolvedTrainingPrerequisites
```

입력은 exact immutable intent와 Host 계산 fingerprint뿐이다. caller payload, local path, clock, policy boolean,
Dataset mapping, readiness mapping과 approval object를 추가 입력으로 받지 않는다. resolver가 필요한 trusted clock, Common
object store, config/readiness store와 currentness policy는 resolver construction dependency다.

resolver는 reference별 exact immutable authority object를 읽고 다음을 수행한다.

- Common runtime verification과 DatasetVersion·DatasetManifest schema/publication scenario 검증
- upstream objects, `evaluated_at`, expected split와 artifact references를 authority source에서 얻어
  `evaluate_dataset_training_entry()`를 호출하고 exact evaluator-issued permission을 보존
- config/readiness manifest의 authoritative bytes를 resolve하고 `inspect_full_pretraining_readiness()`와 현재 source
  state를 평가
- revoke·supersede·expiry/currentness와 resolver policy를 판정
- path는 repository/storage adapter가 resolve한 internal path로만 만들고 caller path를 사용하지 않음

resolver는 Train Dataset content를 읽거나 model/output을 만들지 않으며 decision evidence를 해석·submit하지 않는다.

### 4. exact immutable resolved prerequisite schema

[제안] `ResolvedTrainingPrerequisites`는 package-private construction을 사용하는 frozen, slotted, redacted immutable
value다. 아래 field set 이외의 extension bag이나 free-form authority field를 허용하지 않는다.

| Resolved field | Exact type | Authoritative producer | Input reference | Validation / binding | Immutable after | Missing / stale / mismatch | Forbidden caller substitute |
|---|---|---|---|---|---|---|---|
| `schema_version` | exact integer `1` | resolver contract | 해당 없음 | exact value/type, subclass 금지 | result construction | invalid result | caller version, extension bag |
| `intent_fingerprint` | `sha256:` + lowercase hex 64 `str` | Host | exact intent 전체 | Host 계산값의 exact echo | Host calculation | resolution binding failure | caller/resolver hash, timestamp |
| `dataset_version_reference` | non-empty `str` | Host intent | same-named intent field | exact echo와 resolved object provenance | intent construction | prerequisite mismatch | raw DatasetVersion mapping, local path |
| `dataset_manifest_reference` | non-empty `str` | Host intent | same-named intent field | exact echo와 resolved object provenance | intent construction | prerequisite mismatch | raw DatasetManifest mapping, legacy manifest |
| `training_config_reference` | non-empty `str` | Host intent | same-named intent field | exact echo와 trusted config source | intent construction | config unavailable/invalid | `config_path`, YAML payload, environment path |
| `readiness_evidence_reference` | non-empty `str` | Host intent | same-named intent field | exact echo와 trusted manifest/report source | intent construction | readiness unavailable/invalid | readiness mapping, approved boolean, local manifest path |
| `config_path` | exact `pathlib.Path` | trusted config adapter | `training_config_reference` | resolved source, safe path, before/after checksum와 parsed config binding | result construction; source는 use-time 재검증 | source change/unavailable은 fail closed | caller path, cwd-relative guess, temp file |
| `config_snapshot` | deep-immutable `Mapping[str, Any]` | `FullPretrainingConfig.from_yaml(config_path).to_dict()`의 trusted canonical snapshot | `training_config_reference` | parsed config와 path checksum, run/output/fresh/no-resume binding | result construction | parse/source mismatch | caller dict, mutable `FullPretrainingConfig` nested dict |
| `manifest_path` | exact `pathlib.Path` | trusted readiness adapter | `readiness_evidence_reference` | approval manifest source와 readiness inspection binding | result construction; source는 use-time 재검증 | source change/unavailable은 fail closed | caller path, CLI manifest option |
| `readiness_report` | deep-immutable `Mapping[str, Any]` | canonical `inspect_full_pretraining_readiness()` | `readiness_evidence_reference` | exact inspection result, source/config/current-state binding | result construction | blocked/stale/source mismatch | caller mapping, approval boolean, copied historical report |
| `dataset_permission` | exact `DatasetTrainingPermission` | `evaluate_dataset_training_entry()` | 두 Dataset reference | exact evaluator-issued registry instance와 target equality | evaluator issuance | missing/denied/forged/stale pair는 fail closed | caller permission, dataclass copy, allowed boolean |
| `dataset_version_id` | non-empty `str` | validated DatasetVersion | `dataset_version_reference` | permission과 resolved version의 exact ID | Common object freeze | mismatch는 fail closed | caller ID, filename, legacy ID |
| `dataset_manifest_id` | non-empty `str` | issued DatasetManifest | `dataset_manifest_reference` | permission과 resolved manifest의 exact ID | manifest issuance | mismatch는 fail closed | caller ID, filename, legacy ID |
| `dataset_pair_fingerprint` | SHA-256 fingerprint `str` | canonical Dataset pair evaluator | 두 Dataset reference | permission, resolved pair와 intent expected 값 모두 일치 | evaluator issuance | mismatch/stale pair는 fail closed | caller hash, single-object checksum |
| `config_fingerprint` | SHA-256 fingerprint `str` | existing `file_checksum(config_path)` | `training_config_reference` | source bytes, snapshot과 intent expected 값 모두 일치 | resolved bytes | change/mismatch는 fail closed | caller hash, mtime, parsed-object hash |
| `readiness_fingerprint` | SHA-256 fingerprint `str` | canonical readiness inspection | `readiness_evidence_reference` | report field와 intent expected 값 모두 일치 | inspection result | stale/mismatch는 fail closed | caller hash, whole-report ad hoc hash |
| `source_commit` | lowercase 40-hex `str` | canonical source inspection/readiness | readiness evidence | report와 current clean source inspection 모두 일치 | inspection result | dirty/unavailable/mismatch는 fail closed | caller SHA, branch name, environment value |
| `run_id` | non-empty `str` | parsed canonical config | `training_config_reference` | resolved output path basename과 intent 값 모두 일치 | config snapshot | mismatch/existing output은 fail closed | caller-generated timestamp/UUID |
| `output_logical_root` | repository-relative logical root `str` | parsed canonical config | `training_config_reference` | config와 intent 값 모두 일치; absolute path 금지 | config snapshot | unsafe/mismatch는 fail closed | caller absolute output/storage root |
| `provenance` | exact `TrustedPrerequisiteProvenance` | trusted resolver adapters | 네 input reference | source identities, policy, evaluated time와 currentness | result construction | missing/stale/revoked/superseded는 fail closed | caller source/policy/current boolean |

`TrustedPrerequisiteProvenance`도 frozen, slotted, redacted value이며 exact field는
`dataset_source_identity: str`, `config_source_identity: str`, `readiness_source_identity: str`,
`resolution_policy_reference: str`, `evaluated_at: timezone-aware ISO-8601 str`, `current: Literal[True]`다. source identity와
policy reference는 bearer credential이 아니며 opaque audit binding이다. missing, stale, revoked, superseded 또는
`current != True`는 resolution failure다.

deep-immutable config/readiness snapshot은 mapping과 모든 nested mapping을 read-only value로, sequence를 tuple로, leaf를
canonical JSON scalar로 제한한다. 기존 builder/backend가 concrete `dict`를 요구하는 지점에서는 Host/backend internal adapter가
즉시 사용되는 fresh private deep copy를 만들고 원본 snapshot과 fingerprint를 다시 확인한다. 이 copy는 caller, audit,
resolver 또는 public return으로 노출하지 않는다.

### 5. Host의 resolved prerequisite 검증

[제안] resolver return은 trust anchor 자체가 아니라 검증 대상이다. Host는 decision resolve나 backend call 전에 다음을
모두 검증한다.

1. exact schema/type, no subclass, redacted representation과 모든 required field 존재
2. intent fingerprint와 네 reference의 exact equality
3. pair/config/readiness fingerprint의 intent expected 값과 exact equality
4. exact evaluator-issued permission provenance, `allowed is True`, empty reason codes와 세 Dataset target field equality
5. 기존 `file_checksum()`, readiness inspection과 source inspection helper로 config snapshot, readiness report field,
   manifest/config/source currentness를 재검증; 독자 checksum/source algorithm 금지
6. config에서 계산한 `run_id`, `output_logical_root`, fresh mode와 no-resume의 intent equality
7. provenance source identity·policy·timezone-aware evaluated time·currentness

하나라도 실패하면 Host는 sanitized prerequisite reason code로 fail-closed하고 request build, decision resolve/submit,
approval issue/consume, backend entry와 Training mutation을 모두 0회로 유지한다. raw path, payload, stack trace와 source
credential은 외부 오류나 durable audit에 기록하지 않는다.

### 6. canonical request build와 durable claim ordering

[제안] prerequisite 검증 후 Host만 기존 `build_training_execution_request()`를 호출한다. 새 builder, copied request,
caller request와 resolver-created request는 금지한다. Host는 returned exact registered instance를 유지하고 다음 equality를
확인한다.

- Dataset IDs/pair fingerprint, config/readiness fingerprint와 resolved values
- `run_id`, `output_logical_root`, `source_commit`, action과 fresh mode가 intent/resolved values
- request builder가 반환한 registered instance와 그 `request_fingerprint`; Host는 별도 request hash algorithm을 만들지 않음

foundation journal의 claim identity는 처음부터 `(run_id, request_fingerprint)`를 요구하므로, 순서는 **resolve and validate
prerequisites -> build exact request -> resolve exact decision -> claim exact identity**다. run ID만 먼저 claim하거나 임시
fingerprint를 넣지 않으며 missing, denied, expired 또는 binding-mismatched decision은 claim 전에 종료한다.
claim 뒤 `RESOLVED`와 `VALIDATED` transition은 이미 완료된 prerequisite/request evidence를 durable state에 확정한다. claim
loser와 run-ID conflict는 decision resolver, submission과 backend에 도달하지 않는다.

### 7. package-private backend lifecycle seam

[제안] public callback이나 public event API 대신 Training package 내부에 package-private
`_HostFullPretrainingBackendLifecycle` coordinator를 둔다. production composition root가 exact durable journal과 Host
identity에 결속해 만들며 caller는 instance, factory, journal 또는 lifecycle event를 전달할 수 없다.

coordinator는 `run_full_pretraining()`의 canonical logic을 복제하지 않는다. 구현 PR S는 기존 함수의 validation,
issuance, consume, entry와 side-effect body를 package-private internal steps로 추출하고 public 함수와 Host coordinator가
동일한 internal steps를 사용하게 한다. production Host path만 exact journal-bound coordinator를 통해 실행한다.

coordinator가 소유하는 순서는 다음과 같다.

1. 기존 backend가 Dataset permission, config, output/disk와 exact registered request를 다시 검증하고, canonical readiness
   inspection과 existing source verifier를 사용해 manifest/readiness fingerprint와 current commit/clean state를 다시 확인한다.
2. 기존 production issuer bridge가 approval을 issue한다.
3. 기존 `consume_training_execution_approval()`이 exact approval을 single-use consume한다.
4. coordinator가 durable CAS로 `DECISION_SUBMITTED -> APPROVAL_CONSUMED`을 기록한다.
5. 기존 `_enter_execution_boundary()`에 도달한다.
6. coordinator가 side effect 전에 `APPROVAL_CONSUMED -> BACKEND_ENTERED`를 durable CAS로 기록한다.
7. 기존 model·Dataset·optimizer·output body를 정확히 한 번 호출한다.
8. known success/failure 또는 outcome unknown을 terminal journal state로 기록한다.

따라서 implementation PR S는 foundation transition graph와 record invariant를 실제 순서인
`DECISION_SUBMITTED -> APPROVAL_CONSUMED -> BACKEND_ENTERED -> terminal`로 보완한다. 이는 ADR-019의 consume-before-side-
effect와 crash 원칙을 구체화하는 후속 정합화이며 decision authority, approval semantics 또는 public backend 호출을
변경하지 않는다. `APPROVAL_CONSUMED` record는 consumed를 뜻하되 `backend_entered=False`이고, `BACKEND_ENTERED`와 그 이후
record만 `backend_entered=True`다. `BACKEND_ENTERED`의 terminal edge는 `COMPLETED`, `FAILED`,
`MANUAL_RECONCILIATION_REQUIRED`만 허용한다.

### 8. exact typed lifecycle result

[제안] coordinator 내부 결과 `_FullPretrainingLifecycleResult`는 frozen, slotted, redacted, package-private value이며 exact
field는 다음뿐이다.

| Field | Exact type / values | 의미 |
|---|---|---|
| `identity` | exact `TrainingOrchestrationIdentity` | exact run/request binding |
| `outcome` | exact enum `SUCCEEDED`, `FAILED`, `OUTCOME_UNKNOWN` | backend lifecycle 판정 |
| `approval_consumed` | exact `bool` | consume 함수가 정상 반환했는지 |
| `backend_entered` | exact `bool` | `_enter_execution_boundary()`에 도달했는지 |
| `terminal_recorded` | exact `bool` | durable terminal CAS 성공 여부 |
| `reason_code` | uppercase sanitized `str` 또는 `None` | raw exception 없는 stable reason |

`SUCCEEDED`는 두 boolean과 `terminal_recorded`가 모두 true이고 reason이 없을 때만 가능하다. `backend_entered=True`는
`approval_consumed=True`를 요구한다. terminal journal write가 실패하면 backend가 성공했더라도 external success를 반환하지
않고 `OUTCOME_UNKNOWN`으로 수동 조정한다.

이 result는 Host 내부 상태 전이·sanitized response에만 사용하고 public backend return, callback payload, event bus 또는
audit payload로 그대로 노출하지 않는다. `TrainingExecutionApproval`, DecisionSource claim, registration/submission
capability, raw backend result, model output, Dataset content, local path, raw exception/traceback은 field 또는 exception에
포함하지 않는다. private lifecycle failure도 이 result와 sanitized reason만 운반하며 caller가 재구성할 수 있는 token을
제공하지 않는다.

## Lifecycle / outcome / retry matrix

| Lifecycle point | Authority owner | Host-observable typed outcome | Journal transition | Retry allowed | Reconciliation required |
|---|---|---|---|---|---|
| prerequisite resolution 전/중 | prerequisite resolver; ordering은 Host | sanitized unavailable/invalid, lifecycle result 없음 | claim 전이면 없음; claim 후 known failure면 `FAILED` | side effect·submission 0이 증명된 transient source read만 same process bounded retry | stale/mismatch는 no; ambiguous source는 yes |
| canonical request build | existing request builder | sanitized invalid, lifecycle result 없음 | 아직 claim 전이므로 없음 | no automatic retry | source mutation 여부가 불명확하면 yes |
| exact request claim | durable journal | acquired/replay/conflict | `CLAIMED` 또는 기존 record | 없음 | 기존 ambiguous record면 yes |
| decision resolve, DENIED/UNAVAILABLE 또는 submission 전 failure | trusted decision resolver/Host | denied/unavailable/failed | `FAILED` | ADR-019에 따라 자동 retry 없음 | authoritative outcome 불명확 시 yes |
| submission 성공, approval issue 전/중 | DecisionSource/issuer/backend | known failure 또는 outcome unknown | `DECISION_SUBMITTED -> FAILED` 또는 manual | 없음 | issuance 여부 불명확 시 yes |
| approval issue 후 consume 전 failure | canonical backend | `FAILED` 또는 `OUTCOME_UNKNOWN`, consumed false | known no-consume이면 `FAILED`; 그 외 manual | 없음; approval 재발급 금지 | consume 여부 불명확 시 yes |
| consume 완료, entry 전 | canonical backend + lifecycle coordinator | consumed true, entered false | `DECISION_SUBMITTED -> APPROVAL_CONSUMED` | 없음 | CAS/crash면 yes |
| execution boundary 도달, body 전 | canonical backend + lifecycle coordinator | consumed true, entered true | `APPROVAL_CONSUMED -> BACKEND_ENTERED` | 없음 | CAS/crash면 yes |
| body explicit success | canonical backend | `SUCCEEDED`, both flags true | `BACKEND_ENTERED -> COMPLETED` | 없음 | terminal CAS 실패 시 yes |
| body explicit known failure | canonical backend | `FAILED`, phase flags exact | `BACKEND_ENTERED -> FAILED` | 없음 | side effect 범위가 알려지지 않으면 yes |
| result 전 exception/process loss | lifecycle coordinator | `OUTCOME_UNKNOWN` | 가능한 경우 manual | 없음 | yes |
| lifecycle result/journal 처리 실패 | lifecycle coordinator/durable journal | `OUTCOME_UNKNOWN`; success 반환 금지 | 가능한 마지막 phase -> manual | 없음 | yes |
| process restart | 새 composition root | 이전 authority 복구 없음 | unresolved active phase는 manual | 없음 | `DECISION_SUBMITTED` 이후는 항상 yes |

위 표에서 허용한 bounded retry는 claim·decision submission·approval issuance 전에 있고 Training side effect 0이 증명된
prerequisite source read에만 한정한다. retry는 같은 construction-bound resolver와 same immutable intent를 사용하며 policy가
정한 횟수만 허용한다. stale, revoked, invalid, mismatch, DENIED와 DECISION_UNAVAILABLE은 success로 retry하지 않는다.

journal adapter가 실패해 manual phase도 기록할 수 없으면 Host는 성공으로 간주하지 않고 sanitized unavailable/outcome-
unknown을 반환한다. process restart 시 `DECISION_SUBMITTED`, `APPROVAL_CONSUMED`, `BACKEND_ENTERED`는 모두 기존 process-
local authority를 복구하지 않으며 manual reconciliation 대상이다. pre-submission attempt도 same run을 자동 재개하지 않는다.

## Visibility / leakage matrix

| 객체 | Caller | Host | Prerequisite resolver | Backend lifecycle | Durable journal/audit |
|---|---:|---:|---:|---:|---:|
| immutable intent/reference | 제출 가능 | 읽기 | resolve 입력 | 불필요 | fingerprint/reference만 |
| resolved Common/config/readiness payload | 금지 | request build 동안 internal | 소유 | 필요한 private copy만 | 금지 |
| internal filesystem path | 금지 | internal | 생산 | 사용 | 금지 |
| exact Dataset permission | 금지 | request-local | 생산 | validation/consume binding | fingerprint/ID만 |
| exact execution request | 금지 | request-local | 금지 | validation/issuance | request fingerprint만 |
| decision record/raw evidence | 금지 | resolver result envelope만 | 금지 | 금지 | opaque reference/fingerprint만 |
| approval/capability | 금지 | 반환·저장 금지 | 금지 | issue/consume 내부만 | 금지 |
| lifecycle result | sanitized status만 | internal | 금지 | 생산 | phase/reason projection만 |
| raw backend result/exception | 금지 | public 반환 금지 | 금지 | internal cleanup만 | 금지 |

### API surface 분류

| Surface | 허용 항목 | 금지 항목 |
|---|---|---|
| Public | ADR-019에서 이미 정의·구현된 Host intent, decision resolver/journal foundation value·port; activation 전 비실행 caller intent surface | prerequisite resolved result, lifecycle event/result, callback/observer, resolver/backend/issuer selector, approval/capability |
| Package-private | prerequisite resolver/result/provenance, immutable snapshot materializer, Host request-build helper, backend lifecycle coordinator/result/failure, existing private issuer submission·consume 연결 | package 밖 export, caller-selected construction, raw object/result/path 반환 |
| Test-only | fake prerequisite/decision resolver, fake journal, bounded fake backend boundary, deterministic failure injection | production registration, real Dataset/model/GPU/output access, test hook의 public export |

모든 surface에서 dynamic import, `eval`/`exec`, environment/CLI boolean approval, caller-selected DecisionSource/issuer/backend,
token/capability/raw decision 반환과 absolute path·storage root·secret·PII·stack trace 노출을 금지한다.

## Failure, cleanup와 partial construction

- resolver나 Host construction 실패는 startup failure이며 partial Host를 publish하지 않는다.
- request failure는 resolved payload, permission, request와 private deep copy reference를 해제하지만 process-lifetime issuer
  registration을 unregister하지 않는다.
- cleanup failure는 approval, consume 또는 success evidence가 아니다. cleanup 중 raw path나 payload를 log하지 않는다.
- approval이 issue됐지만 consume되지 않은 known failure도 approval object를 반환·저장·retry하지 않는다.
- consume 뒤에는 cleanup 성공과 관계없이 자동 retry가 금지된다.
- lifecycle coordinator 재진입, 같은 request 동시 run, duplicate lifecycle binding과 terminal transition은 conflict로
  fail-closed한다.
- journal transition은 exact expected phase CAS이며 lossy upsert, last-write-wins와 phase skip을 허용하지 않는다.

## Audit와 sanitization

[제안] durable record에는 ADR-019 최소 evidence에 더해 intent fingerprint, prerequisite resolver source identities/policy
reference, prerequisite validation result, approval-consumed/backend-entered phase와 sanitized lifecycle reason을 기록할 수 있다.

Dataset/config/readiness raw payload, absolute path, permission/request/approval object, decision payload, capability, credential,
model output, stack trace와 exception message는 기록하지 않는다. `evaluated_at`와 lifecycle timestamps는 audit evidence이며
approval expiry나 caller freshness로 재해석하지 않는다. 이 ADR은 새 durable audit 제품이나 approval-side-effect atomic
transaction을 주장하지 않는다.

## 다음 구현 PR S: 최소 단계

[제안] 이 ADR이 독립 검증·명시 승인·병합된 뒤 단일 implementation PR S는 다음 범위만 수행한다.

1. package-private prerequisite resolver protocol, exact frozen resolved schema와 provenance type
2. future Host가 사용할 canonical intent fingerprint·resolved validation·existing request builder/claim ordering helper 계약
3. existing backend logic과 canonical readiness/source verifier를 공유하는 package-private lifecycle coordinator와 exact
   typed result/failure
4. journal phase ordering을 `APPROVAL_CONSUMED -> BACKEND_ENTERED`로 정합화
5. public export, CLI/inference wiring, caller callback/hook와 capability 반환이 0인지 검증

PR S는 actual Host class/bootstrap, production prerequisite/decision resolver adapter, production journal adapter와 runtime
composition을 구현하지 않는다.

PR S의 required tests는 최소 다음을 포함한다.

- resolver construction binding, duplicate/replacement/injection 차단
- missing/stale/revoked/mismatched reference, provenance, permission, pair/config/readiness/source/run/output 차단
- canonical request builder exact 1회와 copied/forged request 0회
- decision submission 전 prerequisite failure의 issuer/backend/mutation 0회
- exact order: revalidation -> issue -> consume -> consumed CAS -> entry -> entered CAS -> side effect
- consume/entry 전후 exception, journal CAS failure, process-loss simulation의 matrix state와 retry 0회
- lifecycle result invariant, redacted repr/error/audit와 approval/capability/raw path/raw payload 비노출
- source checkout와 build wheel의 private surface·fail-closed parity

모든 test는 fake authority store, fake journal과 bounded fake side-effect boundary를 사용한다. 실제 Dataset content read,
model/optimizer 생성, GPU, checkpoint, output artifact와 Full Pretraining은 0회다.

## 재개 PR B와 PR C

### 재개된 PR B

PR S 병합 뒤 PR B는 non-CLI same-process Host/bootstrap을 구현하고 construction-bound prerequisite resolver, existing
decision resolver/issuer, durable journal과 package-private backend lifecycle coordinator를 하나의 exact object graph로 조립한다.
fake prerequisite/decision resolver, fake journal과 bounded fake backend lifecycle로 ordering·concurrency·replay·crash를
검증한다. production adapter, runtime activation과 실제 Training은 포함하지 않는다.

### PR C

PR C는 별도 독립 검토로 승인된 authority/persistence 선택이 존재할 때만 production prerequisite resolver adapter,
production decision resolver adapter와 durable journal adapter를 구현한다. adapter authenticity/currentness, retention,
restart/manual reconciliation과 sanitized audit를 검증하되 runtime activation과 실제 Training은 포함하지 않는다.

## Production activation Gate

다음이 모두 충족되기 전 production Full Pretraining은 계속 blocked다.

1. ADR-016·017·018·019와 이 ADR이 독립 검증·명시 승인·병합됐다.
2. PR S가 위 ownership, ordering, immutability, failure matrix와 non-leakage test를 통과하고 독립 검증·병합됐다.
3. ADR-019가 요구한 authoritative production prerequisite/decision resolver와 durable journal adapter의 별도 구현·운영
   책임·restart/reconciliation evidence가 승인됐다.
4. source checkout/build wheel parity, exact Dataset pair/config/readiness/source/output/disk/GPU preflight가 새 request에 결속됐다.
5. 실제 실행 범위·비용·중단·복구에 대해 별도 사용자 명시 승인이 있다.

ADR 또는 PR S 병합, approved decision fixture, CLI flag, readiness success와 backend test는 실제 Training 승인으로 해석하지
않는다. 현재 CLI는 issuer/resolver/lifecycle coordinator를 설치하지 않으므로 계속 fail-closed다.

## 해결되는 blocker와 남는 blocker

- [제안] 이 결정은 construction-bound prerequisite resolution의 input/output/authority를 고정해 Host와 caller/resolver의
  ownership conflict를 해소한다.
- [제안] 이 결정은 package-private lifecycle coordinator, consume/entry ordering과 typed result를 고정해 Host와 backend의
  ownership conflict를 해소한다.
- [제안] 따라서 `BLOCKED_BY_ORCHESTRATION_OWNERSHIP_CONFLICT`의 **설계 blocker**는 해소된다.
- [확정] resolver, Host integration, lifecycle coordinator, journal 정합화와 production adapters는 아직 구현되지 않았다.
  실제 production Full Pretraining은 계속 blocked다.

## 제외 범위

- Python/source/test/CLI 구현 또는 기존 symbol 변경
- public callback, public lifecycle event API 또는 backend replacement hook
- prerequisite/decision resolver, Host, journal, issuer adapter 또는 scheduler/database 구현
- JWT/HMAC/API key, network authentication, cross-process transport
- approval/capability durable persistence, restart replay 또는 exactly-once 주장
- actor/workspace/project/job/experiment authority 신설
- Dataset, Model, checkpoint, config, Runtime, Provider mutation
- 실제 Full Pretraining, GPU 작업, artifact 생성, Ready 전환 또는 merge

## Consequences

- 장점: caller reference, authoritative prerequisite, canonical request와 decision/approval ownership이 분리된다.
- 장점: approval consume와 backend entry를 실제 코드 순서대로 기록하면서 public capability나 callback을 만들지 않는다.
- 장점: crash ambiguity를 success나 retry로 과장하지 않고 manual reconciliation으로 차단한다.
- 비용: backend 내부를 shared private steps로 분해하고 journal invariant를 보완해야 한다.
- 비용: production activation 전에 authority store/resolver와 journal adapter의 운영 선택이 여전히 필요하다.

## Revisit conditions

- prerequisite authority가 cross-process/network transport로 바뀐다.
- Common Dataset permission, readiness schema, request builder field set 또는 backend signature가 바뀐다.
- approval consume와 Training side effect를 하나의 durable transaction으로 묶는다.
- public execution API 또는 caller-visible lifecycle event가 필요해진다.
- actor/workspace/project/job/experiment가 authoritative execution identity가 된다.

## 승인 Gate

이 ADR은 `draft`와 `proposed`다. 독립 검증과 명시 승인·병합 전에는 implementation requirement가 아니다. 승인되더라도
PR S와 Production activation Gate를 건너뛸 수 없으며 execution 영향은 없다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-13 | [제안] construction-bound prerequisite resolver와 package-private backend lifecycle ownership seam 초안 등록 |
