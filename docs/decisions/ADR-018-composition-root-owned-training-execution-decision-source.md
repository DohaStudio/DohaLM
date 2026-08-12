# ADR-018: Composition-root-owned Training Execution Decision Source

- 문서 상태: `draft`
- 마지막 검토일: 2026-08-12
- 결정 상태: `proposed`
- 실행 영향: 없음
- 관련 문서: [ADR-014](./ADR-014-dataset-product-governance-boundary.md),
  [ADR-016](./ADR-016-generic-training-execution-approval-boundary.md),
  [ADR-017](./ADR-017-production-training-execution-issuer-trust-anchor.md),
  [Full Pretraining 실행 계획](../training/full-pretraining-execution-plan.md)

## Context

[확정] ADR-016은 외부 user-facing orchestration authority가 하나의 immutable
`TrainingExecutionRequest`에 결속된 opaque authorization evidence를 공급하도록 정하고, ADR-017은 non-CLI composition
root가 등록한 exact `TrainingExecutionIssuerAdapter`를 accountable issuer principal로 정한다. topology와 transport는
same-process typed call이며 adapter protocol은
`decide(request) -> TrainingExecutionIssuerDecision`이다.

[확정] 그러나 현재 저장소에는 business approve/deny를 생산하는 non-CLI orchestration component와 decision supply
lifecycle이 없다. adapter가 eligibility 또는 readiness에서 결정을 자동 추론하면 approval accountability를 위반하고,
filesystem manifest·HMAC·network IAM을 generic source로 승격하면 승인되지 않은 persistence 또는 security product decision이
된다.

[확정] 이 ADR은 adapter가 business policy를 자동 실행하는 방식을 기각하고, composition root가 소유하는 별도
same-process trusted `DecisionSource`를 채택한다. 이 문서는 구현 전 normative contract이며 production source, adapter,
submission API 또는 actual approval을 구현하지 않는다.

## 선례 Matrix

정의되지 않은 항목은 `undefined`로 유지하며 legacy filesystem 방식을 generic source에 자동 적용하지 않는다.

| Contract | Producer | Supply timing | Pending | Decision state | Request binding | Replay | Persistence | Applicable |
|---|---|---|---|---|---|---|---|---|
| Candidate A | 명시적 사용자 승인 | 실행 전 manifest 작성 | manifest field | approved | Dataset·config·Run·Git identity | single-use, retry 금지 | local file·consumption record | binding·single-use만 |
| Candidate B | issuer `undefined` | 실행 전 manifest 작성 | missing 또는 example `pending` | approved | Dataset·config·Run·Git·output | atomic consume, failed Run 재사용 금지 | local file | binding·single-use만 |
| Pilot | `approved_by` 사용자 기록 | 실행 전 manifest 작성 | `not_approved` | approved/not approved | Dataset·tokenizer·config·run evidence | consumed result 재사용 금지 | local file | 상태 분리만 |
| V03 Tokenization | `approver_id`; authentication `undefined` | 별도 request 뒤 approval 발급 | prepared/not issued lifecycle | issued approval | request·Run·Dataset·evidence fingerprint | nonce·TTL·single-use | local filesystem·HMAC artifact | authorization identity·anti-replay만 |
| ADR-016/017 generic boundary | same-process accountable orchestration | bridge의 synchronous adapter invocation | 미정 | approved/denied | exact request fingerprint | process-local exact decision replay | 없음 | 이번 결정의 직접 선행 계약 |

## Decision

### 1. Topology와 accountable producer

[확정] business decision producer는 DohaLM approval boundary 밖의 user-facing orchestration responsibility를 동일 host
process 안에 composition한 trusted orchestration component다. 여기서 `external`은 remote service 또는 network identity가
아니라 책임 경계를 뜻한다.

[확정] non-CLI composition root는 다음 순서로 object graph를 만든다.

```text
trusted orchestration component
        │ submit side
        ▼
composition-root-owned DecisionSource
        ▲ claim side
        │ immutable construction-time reference
TrainingExecutionIssuerAdapter
        │ exact adapter registration
        ▼
trusted issuance bridge
```

[확정] accountable issuer principal은 ADR-017대로 registered exact adapter다. `DecisionSource`와 submission capability는
second IAM principal이 아니라 그 adapter가 신뢰하는 composition-root-owned business-decision dependency다.

### 2. Construction과 binding

[확정] `_compose_production_training_execution_issuer()`만 exact `DecisionSource`, 그 source에 결속된 module-private exact
submission capability와 `TrainingExecutionIssuerAdapter(decision_source)`를 생성하고 adapter를 one-time 등록한다. composition
root는 exact submission capability를 같은 object graph의 trusted orchestration component에만 construction-time으로 결속한다.

[확정] adapter의 source reference와 submission capability의 source reference는 immutable하며 process 종료까지 같은 exact
source를 가리킨다. runtime replacement, setter, unregister/restore, mutable callback 교체와 source swapping은 없다. source는
import side effect 또는 lazy first-request 경로에서 생성하지 않는다.

[확정] 다음 caller-controlled injection은 지원하지 않는다.

- `adapter.decide(request, source=...)`
- `issue_training_execution_approval(..., source=...)`
- caller-supplied callback, provider, factory, mapping 또는 import string
- environment decision flag 또는 public `approve()`·`deny()`·`set_decision()`

### 3. DecisionSource responsibility

[확정] `DecisionSource`는 exact request fingerprint에 결속된 immutable business authorization을 process-local로 보유하고,
adapter의 동기 claim에 대해 하나의 atomic outcome을 제공한다. source는 approval을 발급하거나 private issuance/revoke seam을
호출하지 않고 Dataset eligibility·rights·readiness·config를 재검증하거나 approval policy로 승격하지 않는다.

[확정] adapter가 business approve/deny를 자동 생성하지 않는다. adapter는 source claim 결과를 ADR-017 canonical typed
decision으로 변환하고 evidence shape를 검증하는 boundary다.

### 4. Submission authority와 provenance

[확정] submission owner는 composition root가 같은 source와 함께 생성·결속한 trusted orchestration component다. source가
construction 중 발행한 exact module-private submission capability가 supported provenance다. source는 이 exact capability에 대한
strong reference와 immutable source binding을 보존하며 equal-value reconstruction, 다른 instance와 일반 application caller를
거부한다.

[확정] 이 capability는 새 독립 IAM principal, credential 또는 사용자 인증 결과가 아니다. composition root가 trusted
orchestration component에 exact capability를 결속한 행위가 same-process submission trust다. arbitrary malicious Python,
introspection 또는 process-memory compromise는 threat model 밖이다.

[확정] 후속 구현의 submission seam은 module-private typed operation 하나다. 의미상
`_submit_training_execution_decision_from_trusted_orchestrator(capability, submission)`이며 public package API로 export하지 않는다.
구체적인 Python 배치는 구현 PR에서 이 의미를 바꾸지 않는 범위로만 확정한다.

### 5. Submission input과 authorization identity

[확정] submission은 arbitrary mapping이 아닌 exact immutable typed value이며 ADR-017의 일곱 canonical field를 그대로 가진다.

| Field | Source와 constraint |
|---|---|
| `decision` | trusted orchestration이 공급한 exact enum `approved | denied` |
| `authorization_id` | 한 번의 business approval/denial action이 공급한 opaque non-empty immutable identity |
| `issuer_id` | trusted orchestration evidence metadata; authentication 근거가 아님 |
| `approver_reference` | accountable reference; DohaLM이 사람 identity를 생성·인증하지 않음 |
| `evidence_reference` | raw payload·secret이 없는 opaque reference |
| `request_fingerprint` | exact DohaLM-built request fingerprint |
| `issued_at` | timezone-aware audit timestamp; TTL authority가 아님 |

[확정] `authorization_id` producer는 trusted orchestration component가 표현하는 accountable business decision source다.
DohaLM source와 adapter는 ID를 생성·추정·정규화하지 않으며 random UUID, timestamp, request fingerprint 또는 process counter를
authorization identity로 발명하지 않는다. opaque format의 외부 의미와 전역 durability는 이 process-local 계약의 보장 범위가
아니지만, 같은 process에서 non-empty exact string equality를 replay key로 사용한다.

### 6. State와 synchronous timing

[확정] v1 source에는 persisted `PENDING` state가 없다. source lifecycle은 다음뿐이다.

```text
absent
  └─ trusted submit(approved | denied) → available-unclaimed
       └─ adapter claim → claimed-terminal
```

[확정] `adapter.decide(request)`는 source를 동기적으로 claim하고 즉시 `approved`, `denied` 또는 `unavailable` outcome을 받는다.
비동기 waiting, polling, network, queue와 timeout은 없다. `unavailable`은 stored decision state가 아니라 현재 exact fingerprint에
available-unclaimed authorization이 없다는 claim 결과다.

[확정] `unavailable != denied`다. unavailable은 business denial을 만들지 않고 typed
`TrainingExecutionIssuerDecision`, bridge replay record, private issuance seam call, approval object와 execution을 모두 0으로
유지한다. `src.training.execution_issuer` module이 unavailable control signal의 semantic owner다. source의 absent claim만 exact
concrete module-private `_TrainingExecutionDecisionUnavailable` instance를 생성하며 source registry를 변경하지 않는다.

[확정] adapter는 source가 발생시킨 exact unavailable exception을 catch·wrap·replace하지 않고 같은 instance로 bridge까지
전파한다. trusted bridge는 exact concrete type을 다른 adapter exception보다 먼저 catch해 sanitized
`TRAINING_EXECUTION_DECISION_UNAVAILABLE`로 변환한다. raw internal type·message·stack은 caller에게 노출하지 않는다. `None`,
Optional/union return, sentinel decision, subclass·equal-name reconstruction과 arbitrary exception은 unavailable 표현이 아니며
ADR-017의 `TRAINING_EXECUTION_DECISION_INVALID` 계약을 유지한다.

### 7. Request와 authorization binding

[확정] submission은 exact `request_fingerprint` 하나에 결속된다. source claim은 전달받은 exact
`TrainingExecutionRequest`의 registered provenance와 fingerprint를 adapter boundary가 먼저 검증한 뒤 그 fingerprint만 source에
사용한다. source가 fingerprint를 계산·수정하거나 request field를 읽어 eligibility를 재평가하지 않는다.

[확정] process lifetime 동안 다음 uniqueness invariant를 유지한다.

- 하나의 `authorization_id`는 하나의 request fingerprint와 하나의 decision에만 결속한다.
- 하나의 request fingerprint는 하나의 authorization identity만 가질 수 있다.
- 같은 authorization ID와 다른 fingerprint는 conflict다.
- 같은 fingerprint와 다른 authorization ID 또는 다른 decision도 conflict다.
- claimed record를 삭제하거나 새 submission으로 대체하지 않는다.

### 8. Atomic single-use claim과 decision construction

[확정] source `claim(request_fingerprint)`는 read가 아니라 lock 아래의 atomic
`available-unclaimed -> claimed-terminal` compare-and-set이다. 성공한 claim은 immutable authorization material exact value를
한 번 반환한다. absent lookup은 registry mutation이나 authorization claim 없이 exact private unavailable exception을 발생시킨다.
source는 `TrainingExecutionIssuerDecision`을 생성하지 않는다.

[확정] registered adapter가 성공한 exact claim material로 ADR-017의 exact immutable
`TrainingExecutionIssuerDecision` instance 하나를 생성하여 `adapter.decide(request)`의 direct return value로 bridge에 반환한다.
claim 뒤 object construction 또는 adapter validation이 실패해도 source record는 terminal이고 authorization을 복원하지 않는다.

[확정] approved와 denied 모두 exactly one successful business claim을 허용한다. approved는 bridge의 별도 replay claim 뒤
private issuance seam에 최대 한 번 도달한다. denied는 bridge에서 `TRAINING_EXECUTION_APPROVAL_DENIED`로 끝나며 private seam,
approval object와 registry entry는 0이다. denied authorization도 terminal이며 반복 denial object를 생성하지 않는다.

### 9. 두 replay layer

[확정] 다음 layer를 합치지 않는다.

1. DecisionSource business authorization replay: 동일 business action으로 새 typed decision을 반복 생성하지 못하게
   `(authorization_id, request_fingerprint)`와 request fingerprint ownership을 source lock 아래 terminal 보존한다.
2. ADR-017 typed decision replay: adapter가 direct return한 exact decision과 같은 replay key가 bridge에서 두 번 처리되지 않도록
   별도 provenance/replay registry가 claim한다.

[확정] source claim이 성공한 뒤 bridge가 malformed decision, mismatch 또는 private seam failure로 종료해도 두 layer를
restore하지 않는다. fail closed 결과가 새 authorization의 자동 생성이나 같은 request의 재승인을 의미하지 않는다.

### 10. Submission concurrency

[확정] submit, claim과 replay inspection은 source의 하나의 reentrant lock 아래 linearizable하다.

| Race 또는 현재 상태 | 결과 |
|---|---|
| absent에 최초 valid submit | `available-unclaimed` 생성 성공 |
| identical concurrent duplicate submit | 한 호출만 성공; 나머지는 `TRAINING_EXECUTION_DECISION_SUBMISSION_REPLAYED` |
| 같은 authorization 또는 fingerprint의 conflicting submit | `TRAINING_EXECUTION_DECISION_SUBMISSION_CONFLICT` |
| available 또는 claimed record에 identical resubmit | replay rejection; existing material을 반환하지 않음 |
| available 또는 claimed record에 conflicting resubmit | conflict rejection; 기존 record 불변 |

[확정] duplicate submission을 idempotent success로 반환하지 않는다. 일반 caller, wrong/equal-value capability 또는 malformed typed
submission은 record 0으로 각각 submitter unauthorized 또는 decision invalid가 된다.

### 11. Claim concurrency와 submit/claim race

[확정] 같은 available business decision을 두 thread가 claim하면 정확히 하나만 terminal transition과 material 반환에 성공한다.
패자는 `TRAINING_EXECUTION_DECISION_REPLAYED`를 받는다. 이미 존재했던 terminal record와 단순 absent를 구분하므로 consumed
authorization을 unavailable로 숨기지 않는다.

[확정] claim과 submit의 ordering은 같은 lock의 linearization point로 결정한다.

- claim이 먼저 absent를 관측하면 `TRAINING_EXECUTION_DECISION_UNAVAILABLE`; registry mutation 0이다. 뒤의 submit은 정상 성공할
  수 있다.
- submit이 먼저 `available-unclaimed`를 publish하면 뒤의 claim이 정상 성공한다.
- unavailable 결과는 fingerprint를 예약하거나 future submit을 차단하지 않는다.

[확정] unavailable 뒤 동일 request는 소비되지 않는다. trusted orchestration이 이후 그 fingerprint에 최초 decision을 submit하면
같은 exact request의 다음 `adapter.decide(request)`가 정상 claim할 수 있다. unavailable observation은 source business replay,
bridge typed-decision replay와 approval registry를 변경하지 않는다.

### 12. Reapproval와 execution retry

[확정] 같은 `TrainingExecutionRequest` 또는 같은 request fingerprint에 새 authorization을 제출하지 않는다. 최초 decision이
approved, denied, claimed, adapter-invalid 또는 bridge-failed인지와 관계없이 해당 fingerprint의 business authorization ownership은
process 종료까지 하나다.

[확정] ADR-016에 따라 failed run, retry, resume와 새로운 execution attempt는 새 run identity를 포함한 새
`TrainingExecutionRequest`, 새 request fingerprint와 별도의 새 external authorization을 요구한다. resume는 현재
`execution_mode=fresh` 계약 밖이며 이 ADR이 활성화하지 않는다. source나 adapter는 retry request를 자동 생성하지 않는다.

### 13. Restart와 persistence

[확정] source state, submission capability, available decision, claimed tombstone, adapter registration, typed decision와 approval
authority는 process-local only다. process 종료 뒤 모두 복구하지 않고 serialized evidence·file·DB·object store·durable queue에서
authority를 재구성하지 않는다.

[확정] restart 뒤 source는 empty이고 adapter는 unregistered다. claim되지 않은 submission도 소멸하며 durable business approval로
간주하지 않는다. 새 composition, 새 request와 trusted orchestration의 새 submission이 필요하다. power-loss durability와
cross-process replay 방어는 보장하지 않는다.

### 14. Failure contract

[확정] 후속 구현은 기존 `TrainingError` convention으로 다음 stable meaning을 분리한다. raw evidence, authorization ID,
fingerprint, registry identity, object representation, path와 stack trace는 노출하지 않는다.

| Meaning | Stable code |
|---|---|
| registered adapter 자체 없음 | ADR-017 `TRAINING_EXECUTION_ISSUER_UNAVAILABLE` |
| registered adapter/source는 있으나 decision 없음 | exact private signal을 bridge가 `TRAINING_EXECUTION_DECISION_UNAVAILABLE`로 변환 |
| explicit business denial | ADR-016 `TRAINING_EXECUTION_APPROVAL_DENIED` |
| malformed submission/claim material/typed decision | ADR-017 `TRAINING_EXECUTION_DECISION_INVALID` |
| request fingerprint mismatch | ADR-017 `TRAINING_EXECUTION_APPROVAL_TARGET_MISMATCH` |
| business authorization 또는 typed decision 재사용 | `TRAINING_EXECUTION_DECISION_REPLAYED` |
| conflicting submission | `TRAINING_EXECUTION_DECISION_SUBMISSION_CONFLICT` |
| invalid submission capability | `TRAINING_EXECUTION_DECISION_SUBMITTER_UNAUTHORIZED` |

[확정] `TRAINING_EXECUTION_DECISION_REPLAYED`는 source와 bridge 모두 single-use replay라는 stable 외부 의미로 사용할 수 있지만
각 registry와 내부 transition은 독립적으로 유지한다. conflict와 unavailable은 replay 또는 denied로 합치지 않는다.

### 15. CLI, revoke와 audit

[확정] CLI는 source composition, submission, adapter registration과 approval issuance를 수행하지 않으며 `--execute`는 계속 fail
closed다. 이 ADR은 production revoke envelope 또는 source를 통한 revoke를 정의하지 않는다.

[확정] process-local sanitized decision event/evidence만 허용한다. durable audit persistence를 주장하지 않으며 audit owner,
schema, retention과 access는 별도 architecture decision이다.

## Implementation-readiness

| Concept | Decision | Owner | Persistence | Concurrency | Test obligation |
|---|---|---|---|---|---|
| decision producer | trusted same-process orchestration | composition root object graph | 없음 | exact submission capability | automatic policy 0 |
| DecisionSource | authorization store·atomic claim | composition root | process-local | one lock·linearizable | replacement/restore 0 |
| submission authority | exact module-private capability | trusted orchestration component | 없음 | first valid submit wins | forged/equal instance reject |
| authorization identity | opaque business action ID | trusted orchestration | tombstone until process exit | authorization/request uniqueness | generated UUID 0 |
| request binding | exact request fingerprint | source + adapter | process-local | conflicting binding reject | mismatch reject |
| APPROVED | claim once, adapter constructs typed decision | source claim + adapter | 없음 | exactly one winner | bridge seam at most once |
| DENIED | terminal claim, approval 0 | source claim + adapter/bridge | 없음 | exactly one winner | repeated denial replay reject |
| UNAVAILABLE | source-owned exact private exception; denial 아님 | source→adapter unchanged→bridge conversion | 없음 | no mutation·후속 submit 허용 | decision/replay/approval/execution 0 |
| claim | atomic single-use CAS | DecisionSource | terminal tombstone | linearizable | two-thread one success |
| submission replay | stable rejection | DecisionSource | terminal tombstone | duplicate loses | identical/conflict 분리 |
| concurrent submit | one success or conflict/replay | DecisionSource | process-local | same lock | deterministic race test |
| concurrent claim | exactly one success | DecisionSource | process-local | same lock | loser replay test |
| process restart | authority restoration 0 | composition root | 없음 | N/A | fresh-process fail closed |

[확정] implementation-readiness unresolved count는 **0**이다.

## Implementation Gate

1. 이 ADR의 독립 검증·명시 승인·병합
2. exact source/submission capability/adapter construction-time binding과 replacement 0
3. arbitrary caller submission·source injection·public setter 0
4. exact typed submission과 authorization ID non-generation 검증
5. source-only exact unavailable exception construction, unchanged adapter propagation, bridge stable conversion과
   `None`·wrong type·arbitrary exception invalid 분리 검증
6. one request fingerprint/one authorization과 conflicting resubmission 차단
7. atomic submit/claim, two-thread concurrent submit/claim과 linearizable race 검증
8. source business claim과 ADR-017 bridge replay의 독립 single-use 검증
9. adapter가 claim material로 exact typed decision을 만들고 direct return하는 provenance 검증
10. restart authority 복구 0, persistence·network·CLI·revoke 구현 0
11. production/test 구현 PR의 별도 독립 검증과 승인

이 Gate 이전에는 Production DecisionSource, adapter, submission seam 또는 actual approval issuance를 구현하지 않는다.

## Security boundary

[확정] 보장 범위는 same-process composition ownership, exact submission capability와 adapter, immutable request binding,
authorization single-use, typed decision provenance, lock-protected process-local replay다.

[제외] malicious arbitrary Python, introspection, process memory·host compromise, network authentication, 사람 IAM 정확성, durable
business approval, crash persistence와 cross-process replay는 보장하지 않는다.

## Alternatives

| 대안 | 기각 근거 |
|---|---|
| adapter automatic approve/deny policy | eligibility/readiness를 business authorization으로 잘못 승격하고 accountable producer가 사라짐 |
| caller callback/provider/factory | ADR-017 caller injection 금지와 exact composition trust를 위반함 |
| public setter 또는 CLI submission | arbitrary caller가 business decision을 위조할 수 있음 |
| filesystem/DB/queue pending store | v1 same-process·non-durable 범위를 넘어 persistence product decision을 만듦 |
| unavailable을 denied로 반환 | 미결정과 명시적 거절의 의미 및 audit를 위조함 |
| 같은 request에 새 authorization 허용 | 하나의 execution identity로 반복 capability 발급이 가능해 ADR-016 retry 경계를 위반함 |

## Scope와 non-goals

[확정] 이 ADR의 범위는 composition-root-owned source, trusted submission, authorization/request binding, synchronous outcome,
single-use claim, concurrency, replay, retry와 restart 계약이다.

[제외] production/test code, REST/HTTP/webhook/IPC, DB/file/object store/queue, JWT/HMAC/API key/mTLS/IAM, revoke envelope, durable
audit, CLI activation, Dataset/Artifact read, Model/Provider/Trainer/optimizer/GPU, Training/Evaluation, dependency, Common schema,
Authority와 workflow 변경은 포함하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-12 | [확정] UNAVAILABLE을 source-owned exact private exception→adapter unchanged propagation→bridge stable conversion으로 고정 |
| 2026-08-12 | [확정] composition-root-owned same-process DecisionSource, trusted submission, authorization single-use와 concurrency/restart 계약 초안 작성 |
