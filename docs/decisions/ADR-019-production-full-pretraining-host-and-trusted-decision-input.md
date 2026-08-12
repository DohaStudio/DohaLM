# ADR-019: Production Full Pretraining Host와 Trusted Decision Input

- 문서 상태: `draft`
- 마지막 검토일: 2026-08-13
- 결정 상태: `proposed`
- 실행 영향: 없음
- 관련 문서: [ADR-014](./ADR-014-dataset-product-governance-boundary.md),
  [ADR-015](./ADR-015-dataset-version-publication-contract.md),
  [ADR-016](./ADR-016-generic-training-execution-approval-boundary.md),
  [ADR-017](./ADR-017-production-training-execution-issuer-trust-anchor.md),
  [ADR-018](./ADR-018-composition-root-owned-training-execution-decision-source.md),
  [Full Pretraining 실행 계획](../training/full-pretraining-execution-plan.md),
  [Full Pretraining Readiness](../training/full-pretraining-readiness.md),
  [실험 관리](../training/experiment-management.md)

## Context

[확정] 현재 production execution backend는 `src.training.full_pretraining.run_full_pretraining()`이지만 non-test
호출자는 없다. `scripts/training/run_full_pretraining.py`의 `--execute`는
`TRAINING_EXECUTION_APPROVAL_REQUIRED`로 종료하는 inspection CLI이며 production composition root가 아니다.
inference `create_app()`과 일반 `dohalm` CLI도 Training object graph를 소유하지 않는다.

[확정] ADR-017·018의 production issuer 구성 함수, trusted decision submission 함수와 DecisionSource는 구현돼
있지만 test 밖에서 조립되지 않는다. 따라서 등록된 trusted adapter가 없어 production issuance는 fail-closed다. 이것이
`BLOCKED_BY_MISSING_PRODUCTION_ENTRYPOINT`의 현재 원인이다.

[확정] decision submission의 필드는 `decision`, `authorization_id`, `issuer_id`, `approver_reference`,
`evidence_reference`, `request_fingerprint`, `issued_at`의 정확히 일곱 개다. 현재 코드는 타입·형식·request binding은
검증하지만 누가 각 값을 생산하고 어떤 evidence를 신뢰하는지, orchestration caller가 무엇을 제출할 수 있는지는 정하지
않는다. 이것이 `BLOCKED_BY_MISSING_DECISION_INPUT_CONTRACT`의 현재 원인이다.

[확정] 현재 Training domain에서 구현된 실행 identity는 `TrainingExecutionRequest.run_id`와
`request_fingerprint`다. Common Dataset envelope의 선택적 `workspace_id`·`job_id`는 Training 권위가 아니며,
actor·owner·project·experiment authority와 durable orchestration identity는 아직 구현되지 않았다.

## 검토한 선택지

| 선택지 | 장점 | 문제 | 판정 |
|---|---|---|---|
| inspection CLI가 production issuer를 임의 구성 | 코드가 작음 | local caller가 trust anchor와 approval을 함께 만들 수 있고 ADR-017을 위반 | 기각 |
| inference service 또는 backend가 composition root를 겸함 | 기존 process 재사용 | inference lifecycle과 Training 권한·자원·실패 경계 혼합 | 기각 |
| 외부 API/JWT/HMAC 기반 issuer | 분산 호출 가능 | ADR-017의 same-process topology를 바꾸며 현재 인증·transport 계약이 없음 | 기각 |
| 비-CLI same-process Production Full Pretraining Host | 기존 trust anchor·typed call을 보존하고 단일 lifecycle owner를 둠 | 별도 host와 authoritative resolver 구현 필요 | 채택 제안 |

## Proposed Decision

### 1. Production Full Pretraining Host

[제안] 논리 역할 `Production Full Pretraining Host`를 production full-pretraining object graph의 유일한
non-CLI application boundary로 둔다. 구체적인 executable 이름, scheduler 제품, database 또는 deployment 제품은 이
결정의 일부가 아니다.

Host는 다음을 단독 소유한다.

- process bootstrap 시 DecisionSource·issuer adapter·registration capability를 정확히 한 번 구성하는 책임
- construction time에 결속된 trusted orchestration resolver와 durable orchestration journal
- immutable DatasetVersion·issued DatasetManifest, upstream evidence, config, readiness와 source state의 해석
- `DatasetTrainingPermission` 평가와 canonical `TrainingExecutionRequest` 구성
- authoritative decision evidence를 일곱 필드 submission으로 변환하고 private trusted call을 수행하는 책임
- backend 호출과 결과·불확실 상태를 journal에 기록하는 request lifecycle

Host는 CLI, inference app, Training backend, issuer adapter factory 또는 decision producer와 동일한 역할이 아니다.
backend는 Host의 trust anchor를 설치할 수 없고 caller는 Host 내부 dependency를 교체할 수 없다.

### 2. 호출자와 trust boundary

[제안] Host의 production 호출자는 process 조립 시 결속된 trusted orchestration port 하나뿐이다. transport는
same-process typed call이며 별도 JWT, HMAC, API key 또는 외부 network identity 인증을 주장하지 않는다. 신뢰의 근거는
production composition root가 resolver·journal·Host를 함께 등록한 사실이다.

호출자가 전달할 수 있는 것은 다음 immutable intent와 reference뿐이다.

- 고정 action `full_pretraining`과 고정 execution mode `fresh`
- DatasetVersion·DatasetManifest reference와 기대 pair fingerprint
- config reference와 기대 config fingerprint
- readiness evidence reference와 기대 readiness fingerprint
- 의도한 `run_id`와 logical output root
- authoritative decision evidence reference

Host는 reference가 가리키는 권위 객체를 construction-bound resolver로 다시 읽고 기대 fingerprint와 일치시킨다.
caller가 보낸 payload, filesystem path, actor 문자열 또는 boolean을 권위 evidence로 사용하지 않는다. source commit과
clean state는 Host가 승인된 readiness/source 경계에서 다시 계산·검증한다.

현재 actor·owner·workspace·project·job·experiment authority는 입력 계약에 추가하지 않는다. 이 값이 production 정책에
필수가 되면 별도 ADR과 versioned input contract가 먼저 필요하다. 현재 orchestration 중복 판정의 canonical identity는
Host가 request 구성 후 얻는 `(run_id, request_fingerprint)`다.

현재 request에는 별도 `created_at`이나 expiry field가 없다. Host는 caller timestamp를 만들거나 freshness 근거로 쓰지
않는다. decision freshness는 authoritative resolver policy와 `issued_at`의 timezone-aware 형식으로만 판정하고 generic
TTL을 추정하지 않는다.

호출자는 다음을 주입할 수 없다.

- DecisionSource, issuer adapter, registration/submission capability 또는 approval capability
- `TrainingExecutionApproval`이나 private issuance token
- caller가 직접 만든 일곱 decision field 또는 `approved=True` 같은 축약값
- Common object를 흉내 낸 mapping, legacy manifest, 환경 변수 또는 임시 파일
- resolver, journal, clock, source-state verifier 또는 backend 구현

production wiring은 정적·명시적 composition만 허용한다. dynamic import, `eval`/`exec`, caller-selected module·adapter
path와 environment approval bypass는 금지한다.

### 3. trusted decision evidence

[제안] construction-bound trusted orchestration resolver는 opaque `evidence_reference`로 immutable decision record와
resolver provenance context를 반환한다. resolver는 record source의 authenticity, 현재 상태, revoke·supersede 여부와
policy version을 판정한다. 구체적인 IAM·database·service 제품은 후속 production adapter 구현에서 선택한다.

resolver provenance context의 source identity와 policy reference는 audit·currentness 판정용 envelope이며 아래 일곱
submission field에 추가되는 새 decision field가 아니다. Host는 record를 수정하거나 누락값을 채우지 않는다.

### 4. 일곱 decision field authority matrix

| Field | Type / allowed values | Authoritative producer | Source evidence | Host validation | Bound identity / scope | Immutable after | Missing / stale / mismatch result | Forbidden substitutes |
|---|---|---|---|---|---|---|---|---|
| `decision` | exact enum `approved` 또는 `denied` | accountable business decision producer | resolver가 인증한 immutable decision record | exact enum, current·not-revoked, 같은 authorization·request binding | `authorization_id`와 `request_fingerprint` | decision finalization | missing·malformed·stale·revoked는 `TRAINING_EXECUTION_DECISION_INVALID`; denied는 `TRAINING_EXECUTION_APPROVAL_DENIED` | boolean, readiness·eligibility 결과, env flag, Host 기본값 |
| `authorization_id` | non-empty `str` | authoritative business decision system | immutable decision action identity | canonical non-empty value, resolver provenance와 record binding, journal의 uniqueness | exact decision action과 request | decision finalization | missing·malformed는 invalid; 동일 ID 재사용은 replay 또는 conflict | UUID·timestamp의 현장 생성, request fingerprint, process counter |
| `issuer_id` | non-empty `str` | trusted decision evidence producer | immutable producer identity in the record | resolver policy가 인정한 producer identity이며 record와 결속됐는지 검증 | exact decision record | decision finalization | missing·unknown·stale producer는 invalid | adapter class/module 이름, OS user, GitHub user, env string; 이 값 단독 인증 |
| `approver_reference` | non-empty `str` | accountable user-facing orchestration authority | resolver가 인증한 opaque actor/accountability reference | non-empty, record·authorization binding; Host는 actor를 재해석하지 않음 | exact authorization | decision finalization | missing·unauthenticated·stale reference는 invalid | raw PII, caller input, `approved_by`, local username |
| `evidence_reference` | non-empty `str` | authoritative evidence store/decision record producer | immutable opaque record reference | resolver가 authenticity·integrity·currentness와 authorization/request/policy binding을 확인 | exact decision record와 policy version | record publication | missing·unresolvable·stale·revoked·mismatch는 invalid | raw evidence payload, local path, temp file, URL query secret, env value |
| `request_fingerprint` | `sha256:` + 소문자 hex 64자 | **Host의 canonical `build_training_execution_request()`**; decision record는 exact echo만 함 | 완성된 immutable request와 decision record의 echo | 형식과 Host 계산값의 byte-exact equality | Dataset pair, config, readiness, run/output, source commit, mode를 포함한 request 전체 | request construction | missing·malformed는 invalid; 다른 request는 `TRAINING_EXECUTION_APPROVAL_TARGET_MISMATCH`; stale record는 invalid | caller 문자열, legacy checksum, 부분 payload hash, authorization ID |
| `issued_at` | timezone-aware ISO-8601 non-empty `str` | authoritative business decision producer | immutable decision-finalization timestamp | timezone-aware parse와 resolver의 currentness policy 통과; generic TTL은 추정하지 않음 | exact decision finalization | decision finalization | missing·naive·malformed·policy상 stale은 invalid | Host current clock, file mtime, request 생성 시각, caller timestamp |

`issuer_id`와 `approver_reference`는 accountability evidence이지 bearer credential이 아니다. 일곱 값이 모두 형식상
유효해도 trusted resolver가 record authenticity와 currentness를 증명하지 못하면 submission은 생성하지 않는다.

## Lifecycle와 ordering

### Process bootstrap

1. production composition root가 trusted resolver와 durable journal implementation을 선택하고 Host에 construction-time
   binding한다.
2. Host가 private production composition 경계로 DecisionSource와 issuer adapter를 만든다.
3. adapter와 exact source binding을 process 전체에서 정확히 한 번 등록한다.
4. 등록 성공 후에만 Host가 request를 받는다.

초기화 실패는 startup failure다. 부분 등록을 허용하지 않으며 duplicate initialization은 동일 dependency를 사용했더라도
idempotent success로 바꾸지 않고 conflict로 fail-closed한다. runtime replacement·unregister·caller-selected adapter는
없다. process 종료가 registration lifetime의 끝이다.

DecisionSource·adapter 구성은 ADR-017·018의 process-lifetime registration이므로 개별 request의 decision 조회보다 먼저
일어난다. 아래 request lifecycle은 이미 등록된 exact object graph 안에서 수행되며 caller가 request마다 source나 issuer를
새로 만드는 순서가 아니다.

### Request lifecycle

1. Host가 typed intent/reference의 허용 field, action과 mode를 검증한다.
2. journal에서 `run_id` claim과 기존 lifecycle을 확인한다.
3. authoritative DatasetVersion·issued DatasetManifest·upstream evidence를 resolve하고 Common/domain validation과
   `DatasetTrainingPermission` 평가를 수행한다.
4. config bytes·readiness·source commit/clean state·output logical root를 resolve하고 검증한다.
5. public builder로 canonical `TrainingExecutionRequest`와 `request_fingerprint`를 만든 뒤
   `(run_id, request_fingerprint)` claim을 확정한다.
6. trusted resolver로 decision evidence를 resolve하고 authority matrix 전체를 검증한다.
7. exact private submission capability로 DecisionSource에 한 번 submit한다.
8. Host가 permission·request와 production-issued approval path를 사용해 `run_full_pretraining()`을 호출한다. backend가
   자체 precondition을 재검증하고 request를 요구하며 issuer bridge를 호출해 approval을 single-use consume한다.
9. Host는 backend 진입·완료·실패 또는 outcome-unknown을 journal에 기록한다.

각 단계 실패 시 이후 단계 호출 수는 0이다. 특히 step 6 이전에는 decision submission·approval issuance·backend 호출이
0이고, step 8의 approval consume 이전에는 model·optimizer 생성, seed 설정, Dataset iterator, checkpoint와 output
mutation이 0이어야 한다. 실패 audit 기록은 허용하지만 Training artifact mutation으로 간주하지 않는다.

성공·거부·실패 후 Host는 request-local resolved object와 capability reference를 외부로 반환하지 않고 해제한다. process
registration은 request cleanup 대상이 아니며 process lifetime 동안 유지된다. 중단 또는 crash 후 cleanup 성공을 승인
증거로 간주하지 않고 durable journal의 마지막 확정 phase를 따른다.

## Decision semantics

- `APPROVED`: 일곱 field, authoritative provenance, currentness와 exact request binding이 모두 유효할 때만 issuer가
  single-use approval capability를 만들 수 있다. 유효한 APPROVED도 backend precondition이나 consume 성공을 보장하지
  않는다.
- `DENIED`: authoritative business/policy decision의 명시적 거부다. backend 호출과 Training mutation은 0이고 자동
  retry나 local APPROVED 전환은 없다.
- `UNAVAILABLE`: resolver 부재·일시 실패·판정 불능 또는 등록 issuer 부재다. DENIED와 구분하되 backend 호출은 0이며
  legacy decision, environment 또는 Host default로 fallback하지 않는다.
- `INVALID` / `MISMATCHED` / `FORGED`: type·provenance·freshness·request binding 중 하나라도 실패한 상태다. 외부 오류는
  sanitized reason code만 노출하고 backend와 Training mutation은 0이다.

## Retry, replay, conflict, concurrency와 crash

- 같은 `(run_id, request_fingerprint)`의 동시 요청은 durable journal의 single winner만 진행한다. loser는 정제된 기존
  상태만 관찰하며 decision을 재-submit하거나 backend를 재호출하지 않는다.
- 같은 `run_id`와 다른 fingerprint는 terminal conflict다. authorization을 다른 request에 재사용하는 것도 terminal
  target mismatch 또는 conflict다.
- identical decision resubmission도 success로 바꾸지 않는다. Host가 journal에서 먼저 차단하며 DecisionSource까지
  도달하면 기존 ADR-018의 replay 오류가 authoritative하다.
- decision denial·invalid·unavailable·replay·conflict는 자동 retry하지 않는다. 새 orchestration은 새 `run_id`, 새
  request와 새 authorization을 필요로 한다.
- process restart 후 이전 DecisionSource, adapter capability, decision claim과 approval authority는 복구하지 않는다.
  resolver record가 남아 있어도 새 process에서 기존 approval을 재생하지 않는다.
- crash가 decision submission 전이면 이전 lifecycle을 abandoned로 확정한 뒤 새 orchestration만 허용한다.
- crash가 submission 후 approval consume 전이면 process-local decision 상태가 소실되므로 기존 authorization을 재사용하지
  않고 outcome-unknown으로 수동 조정한다.
- crash가 approval consume 후 backend completion 확인 전이면 실행이 시작됐을 수 있다. 정확히 한 번 실행을 주장하지
  않으며 자동 재호출을 금지하고 `MANUAL_RECONCILIATION_REQUIRED` 상태로 둔다.

[제안] 위 crash 의미를 강제하려면 production activation 전에 durable orchestration journal이 필요하다. journal은 최소
`run_id`, request/authorization/evidence fingerprint, lifecycle phase, backend-entered 여부, terminal outcome을 원자적으로
claim·기록해야 한다. process-local approval consume와 Training side effect를 하나의 durable transaction으로 묶는다는
주장은 하지 않는다. 따라서 ambiguous crash에서 exactly-once 대신 fail-closed manual reconciliation을 선택한다.

journal은 ADR-018 DecisionSource의 persistence가 아니며 decision·adapter·approval capability를 저장하거나 restart 뒤
복원하지 않는다. durable record의 용도는 이전 attempt를 자동 재실행하지 않고 conflict 또는 manual reconciliation으로
차단하는 데 한정한다.

## Audit와 sanitization

production Host의 durable journal/audit record는 다음 최소 evidence를 보존한다.

- Host lifecycle/version과 opaque orchestration correlation
- `run_id`, request·Dataset pair·config·readiness fingerprint
- `authorization_id`, `issuer_id`, opaque approver/evidence reference와 resolver policy reference
- bootstrap·resolve·validate·submit·backend-entered·consumed·terminal phase와 정제된 reason code
- 각 phase timestamp, process restart 경계와 manual reconciliation 여부

capability, approval object, raw decision/evidence payload, raw PII, credential, token, local absolute path, config 내용,
Dataset 내용과 stack trace는 기록하지 않는다. 이번 ADR은 특정 durable audit 제품이나 이미 존재하는 persistence를 주장하지
않는다.

## 구현 순서와 Gate

### 첫 구현 PR: input·port 계약

ADR 병합 후 첫 PR은 다음 최소 범위다.

- immutable Host intent/reference type과 strict validation
- trusted decision resolver port와 resolver provenance type
- durable orchestration journal port와 lifecycle/error vocabulary
- authority matrix의 valid·missing·stale·mismatch·forbidden injection unit test
- fake resolver·fake journal만 사용하며 issuer composition, backend, CLI와 실제 Training 연결은 0

### 두 번째 구현 PR: same-process Host 조립

- non-CLI Host와 exact-once process bootstrap
- 기존 private composition/submission 경계와 request builder 연결
- fake authoritative resolver·journal·backend를 사용한 ordering, duplicate init, concurrency, replay와 crash-window test
- inspection CLI와 inference app의 issuer 설치 0 검증

### 세 번째 구현 PR: production adapters

- 별도 검토로 선택한 authoritative decision resolver와 durable journal adapter
- authenticity/currentness/revoke·supersede 정책, retention·운영 복구와 sanitization evidence
- restart·concurrency·partial failure 독립 검증
- 실제 backend 대신 bounded fake 또는 no-op boundary만 사용

### Production activation Gate

다음이 모두 충족되기 전 `run_full_pretraining()`의 실제 side effect 경로를 활성화하지 않는다.

1. 이 ADR과 선행 ADR-016·017·018이 독립 검증·명시 승인·병합됐다.
2. 위 세 구현 단계가 독립 검증·병합됐고 production resolver·journal의 기술 선택과 운영 책임자가 승인됐다.
3. authority matrix, construction binding, duplicate init, denial/invalid/unavailable, replay/conflict, restart/crash와 audit
   sanitization test가 통과했다.
4. source checkout과 build wheel이 같은 Host/input contract, private capability 비노출과 fail-closed 결과를 보이는 parity
   evidence가 있다.
5. exact Dataset pair·config·readiness·source commit·output root와 disk/GPU preflight evidence가 새 request에 결속됐다.
6. 실제 실행 범위·비용·중단·복구 계획에 대한 별도 사용자 명시 승인이 있다.

각 구현 PR은 input immutability, caller injection 0, partial registration/mutation 0과 APPROVED fake backend 정확히 1회,
DENIED·UNAVAILABLE·invalid·mismatch fake backend 0회 evidence를 범위에 맞게 제출한다. 실제 GPU Training은 모두 0이다.

이 ADR의 승인이나 세 구현 PR의 병합은 실제 Training 승인으로 해석하지 않는다.

## 해결되는 blocker와 남는 blocker

- [제안] 이 결정은 non-CLI production lifecycle owner와 bootstrap 경계를 지정해
  `BLOCKED_BY_MISSING_PRODUCTION_ENTRYPOINT`의 **설계 공백**을 해소한다.
- [제안] 이 결정은 trusted logical input, 금지 injection과 일곱 field authority를 지정해
  `BLOCKED_BY_MISSING_DECISION_INPUT_CONTRACT`의 **설계 공백**을 해소한다.
- [확정] production Host, resolver, durable journal과 activation evidence는 아직 구현되지 않았다. 따라서 실제
  Full Pretraining은 계속 blocked이며 등록 adapter가 없는 현재 CLI도 fail-closed다.

## 제외 범위

- Python/source/test/CLI 구현 또는 기존 symbol 변경
- issuer adapter·DecisionSource·resolver·journal·service·scheduler·database 구현
- JWT/HMAC/API key, cross-process topology 또는 network authentication
- actor/workspace/project/job/experiment authority의 신설
- durable audit·exact revoke protocol의 구체 제품 결정
- Dataset, Model, checkpoint, config, Runtime, Provider mutation
- 실제 Full Pretraining, GPU 작업, artifact 생성, Ready 전환 또는 merge

## Consequences

- 장점: production entrypoint의 소유자와 decision producer를 분리하고 caller capability injection을 차단한다.
- 장점: 현재 일곱 필드와 request binding을 바꾸지 않고 authoritative evidence의 출처·currentness를 검증할 수 있다.
- 장점: retry·restart·crash의 모호성을 success나 exactly-once로 과장하지 않는다.
- 비용: Host activation 전에 production resolver와 durable journal 구현·운영 결정이 추가로 필요하다.
- 비용: actor·project·experiment 단위 정책이 필요해지면 versioned 후속 결정이 필요하다.

## Revisit conditions

- topology가 cross-process 또는 network transport로 바뀐다.
- decision field, authorization lifecycle, revoke 또는 generic TTL 계약이 바뀐다.
- durable transaction이 approval consume와 Training side effect까지 원자적으로 묶이게 된다.
- actor·workspace·project·job·experiment가 authoritative execution identity가 된다.
- Training backend, Dataset permission 또는 request fingerprint field set이 바뀐다.

## 승인 Gate

이 ADR은 `draft`와 `proposed`다. 독립 검증과 명시 승인·병합 전에는 implementation requirement가 아니다. 승인되더라도
구현 순서와 Production activation Gate를 건너뛸 수 없으며 execution 영향은 없다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-13 | [제안] non-CLI Production Full Pretraining Host, trusted input와 일곱 decision field authority 계약 초안 등록 |
