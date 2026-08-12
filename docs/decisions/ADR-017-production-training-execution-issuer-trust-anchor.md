# ADR-017: Production Training Execution Issuer Trust Anchor

- 문서 상태: `draft`
- 마지막 검토일: 2026-08-12
- 결정 상태: `proposed`
- 실행 영향: 없음
- 권위 기준: `DohaStudio/.github@dd75fc88c16e9ae9a04acfafb72756a905f6365b`
- 관련 문서: [ADR-014](./ADR-014-dataset-product-governance-boundary.md),
  [ADR-016](./ADR-016-generic-training-execution-approval-boundary.md),
  [Full Pretraining 실행 계획](../training/full-pretraining-execution-plan.md)

## Context

[확정] ADR-016과 현재 구현은 immutable `TrainingExecutionRequest`, exact request fingerprint,
process-local `TrainingExecutionApproval`, single-use consume와 revoke seam을 제공한다. production issuer adapter는 없으며
CLI `--execute`는 fail closed다.

[확정] 기존 Candidate A/B, Pilot과 V03 선례는 exact target binding, deterministic fingerprint, immutable evidence와
single-use lifecycle을 제공하지만 issuer authentication은 모두 `undefined`다. V03의 HMAC·TTL·filesystem lifecycle은
workflow-specific이며 generic Training issuer 인증 근거가 아니다.

[확정] 현재 DohaLM service authentication은 absent이고 repository와 Common Authority에는 Training issuer service
principal, IAM, PKI, credential store 또는 authenticated network channel이 없다. 따라서 GitHub·OS 사용자, hostname,
환경 변수, API key, JWT, HMAC, certificate나 임의 `issuer_id` 문자열을 신뢰 근거로 사용할 수 없다.

## 선례와 후보 비교

정의되지 않은 값은 `undefined`로 유지한다.

| Contract | Principal | Authentication | Decision | Evidence | Integrity | Transport | Replay | Revoke | Audit | 분류 |
|---|---|---|---|---|---|---|---|---|---|---|
| Candidate A | 명시적 사용자 승인 | `undefined` | approved manifest | manifest fields | checksum·Git identity | local file | single-use consume | consumed only | result document | historical-only |
| Candidate B | `undefined` | `undefined` | approval manifest | immutable manifest | checksum·atomic write | local file | consumed/failed 재사용 금지 | `undefined` | result document | workflow-specific |
| Pilot | `approved_by` | `undefined` | manifest field | readiness fingerprint | manifest validation | local file | consumed result 재사용 금지 | `undefined` | result document | historical-only |
| V03 | `approver_id` | `undefined` | issued approval | evidence fingerprint | checksum·nonce·HMAC | local filesystem | TTL·anti-replay lifecycle | retire/expire | lifecycle artifacts | workflow-specific |
| ADR-016 boundary | future trusted adapter | adapter 미구현 | approved/denied | opaque references | exact-instance registry | process-local seam | approval single-use | private seam | persistence 없음 | reusable boundary |

| Mechanism | Existing support | New dependency | Persistence | Cross-process | Integrity | Replay | Operational burden | Fit |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| composition-root registered in-process adapter | private issuance/revoke seam | 아니요 | 아니요 | 아니요 | exact trusted object boundary | process-local | 낮음 | 선택 |
| signed envelope | 아니요 | 예 | key lifecycle 필요 | 예 | signature | durable identity 필요 | 높음 | 기각 |
| HMAC | V03 workflow 전용 | key contract 필요 | key lifecycle 필요 | 가능 | MAC | durable identity 필요 | 높음 | generic 승격 기각 |
| JWT/service token | 아니요 | 예 | issuer/key lifecycle 필요 | 예 | token verifier | claim/store 필요 | 높음 | 기각 |
| mTLS | 아니요 | 예 | PKI 필요 | 예 | authenticated channel | 별도 store 필요 | 높음 | 기각 |

## Decision

### 1. Topology와 accountable issuer principal

[확정] production Training execution issuer topology는 **same-process only**다. 별도 process, service, IPC, HTTP,
message bus 또는 webhook은 이 계약의 topology가 아니다.

[확정] accountable issuer principal은 DohaLM process composition root가 bootstrap 중 명시적으로 설치한 exact
`TrainingExecutionIssuerAdapter` instance다. `issuer_id`, 클래스 이름, module path나 equal-value 객체는 principal이 아니다.

[확정] arbitrary caller, CLI, operator 문자열과 `TrainingExecutionRequest` caller는 issuer가 아니다. external
orchestration이라는 ADR-016 용어는 이 composition-root-owned adapter가 같은 process에서 수행하는 사용자-facing decision
composition 책임을 뜻하며 network service를 암시하지 않는다.

### 2. Trust anchor와 authentication

[확정] trust anchor는 composition root의 one-time exact-instance registration 자체다. 별도 JWT, HMAC, API key,
OAuth, mTLS, certificate 또는 OS/GitHub identity 인증을 추가하지 않는다.

[확정] registration은 process bootstrap에서 issuance 전 정확히 한 번 수행한다. 등록되지 않은 상태, 두 번째 등록,
runtime replacement, unregister/restore, arbitrary callable, public setter와 caller-supplied adapter는 fail closed다. 등록
registry는 module-private이고 exact `is` identity와 process-local lifetime을 사용한다.

[확정] 이 인증 계약은 외부 network identity나 사람 계정을 인증하지 않는다. composition root가 신뢰할 adapter를
선택하는 행위가 application trust decision이며, compromised composition root·adapter·process·host는 보장 범위 밖이다.

### 3. Adapter와 transport boundary

[확정] transport는 in-process typed call뿐이다. production adapter는 typed request view를 받아 자체 orchestration
decision을 검증하고 typed decision을 반환하는 composition boundary다. dict, arbitrary mapping, environment flag, serialized
`TrainingExecutionApproval`, callback injection과 dynamic import string은 supported transport가 아니다.

[확정] 이번 결정은 REST endpoint, webhook, HTTP client, IPC, socket과 network protocol을 만들지 않는다. topology가
변하면 principal, credential, transport integrity와 durable replay를 새 ADR에서 다시 결정해야 한다.

### 4. Request disclosure

[확정] adapter에 제공하는 최소 request view는 ADR-016의 immutable `TrainingExecutionRequest` exact instance와 그
canonical fields다. adapter는 fingerprint를 생성·수정하지 않고 DohaLM request builder가 만든
`request_fingerprint`를 그대로 판단하고 반환 decision에 exact match로 결속한다.

[확정] request에는 raw config bytes, config file path, absolute path, local storage root, Dataset/Artifact payload,
credential, registry identity와 secret이 포함되지 않는다. future field가 이 경계를 위반하면 adapter에 전달하기 전에 별도
privacy/security decision이 필요하다.

### 5. Typed issuer decision과 evidence authority

[확정] typed issuer decision의 canonical semantic fields는 다음과 같다. 신규 persistence schema가 아니라 same-process
adapter-owned immutable value contract다.

| Field | Contract |
|---|---|
| `decision` | exact enum `approved | denied` |
| `authorization_id` | adapter-owned opaque decision identity; non-empty |
| `issuer_id` | audit metadata; authentication 근거가 아님 |
| `approver_reference` | adapter가 검증한 opaque accountable reference; 사람 인증을 DohaLM이 재구현하지 않음 |
| `evidence_reference` | raw payload·secret이 없는 opaque reference |
| `request_fingerprint` | exact DohaLM-built fingerprint |
| `issued_at` | timezone-aware audit timestamp; TTL authority가 아님 |

[확정] evidence authority와 schema owner는 registered adapter다. DohaLM boundary는 exact adapter/decision provenance,
필수 field type·enum·non-empty, request fingerprint, process-local replay state만 검증한다. adapter는 자신의 orchestration
evidence currentness, issuer/approver 의미와 decision integrity를 책임진다. Dataset rights·eligibility·readiness 검증은
기존 evaluator 결과를 재사용하며 중복 구현하지 않는다.

[확정] `issuer_id`, `approver_reference`, `evidence_reference`는 audit/evidence metadata다. 이 문자열만 소지하거나 같은
값을 재구성해도 authority가 생기지 않는다.

### 6. Approved와 denied

[확정] `approved` decision은 registered exact adapter, adapter-owned exact decision instance, exact request instance와
fingerprint, valid evidence fields, 미사용 replay state가 모두 일치할 때만 ADR-016 internal issuance seam으로 전달한다.

[확정] `denied` decision은 `TRAINING_EXECUTION_APPROVAL_DENIED`로 끝난다. `TrainingExecutionApproval` object와 approval
registry entry는 0이며 denied를 approval capability나 revoked state로 변환하지 않는다.

### 7. Decision integrity와 provenance

[확정] decision integrity는 registered trusted adapter boundary가 책임진다. DohaLM은 cryptographic verification을
주장하지 않는다. supported provenance는 adapter-owned object-external registry의 adapter exact identity, decision exact
identity, immutable field snapshot과 request exact binding이다.

[확정] manual constructor, copy, deepcopy, pickle/JSON round-trip, `dataclasses.replace()`, equal-value reconstruction과
field mutation decision은 authority가 없다. hostile Python introspection과 compromised process memory는 범위 밖이다.

### 8. External decision replay와 restart

[확정] adapter는 same process에서 exact decision instance와 `(authorization_id, request_fingerprint)` binding을
process-local registry로 관리한다. 하나의 approved decision은 최대 하나의 `TrainingExecutionApproval` issuance attempt에만
사용할 수 있다. issuance seam 호출이 시작되면 성공·실패와 관계없이 해당 decision은 재사용하지 않는다.

[확정] denied, malformed, request mismatch와 이미 사용된 decision도 새 approval을 만들지 않는다. equal-value 새 decision,
같은 `authorization_id`, 같은 request fingerprint 또는 같은 exact decision 재제출은 `decision replayed`로 fail closed다.

[확정] process restart 뒤 decision registry, adapter registration, decision 또는 approval authority를 복원하지 않는다.
serialized evidence를 읽어 authority를 재구성하지 않으며 새 composition-root registration과 새 orchestration decision이
필요하다. durable cross-process replay 방어는 이 topology에서 주장하지 않는다.

### 9. Expiry

[확정] generic wall-clock TTL을 추가하지 않는다. `issued_at`은 audit evidence이며 expiry 계산에 사용하지 않는다.
decision lifetime은 exact process, exact registered adapter, 최초 issuance attempt, adapter가 currentness를 거부하는 시점 중
가장 이른 시점까지다. time-based expiry가 필요해지면 evidence owner·clock·skew·restart semantics를 별도 결정한다.

### 10. Revocation authority boundary

[확정] production revoke authority는 해당 capability를 발급한 **동일 exact registered adapter instance**다. revoke는
같은 process의 exact issued `TrainingExecutionApproval`만 대상으로 하며 arbitrary caller, 다른 adapter, issuer metadata
문자열과 public revoke API는 authority가 없다.

[확정] ADR-016의 internal revoke seam과 `issued → revoked` lifecycle은 유지한다. consumed capability cancellation,
restore, cross-process revoke와 durable revocation은 지원하지 않는다.

[확정] revoke decision의 exact typed fields, reason/evidence semantics와 adapter-owned anti-replay transition은 별도
resource-specific decision에서 정의한다. 그 결정과 구현이 병합되기 전 production revoke adapter는 unavailable/fail closed다.
이 보류는 production issuance adapter의 same-process trust contract를 약화하거나 public revoke를 허용하지 않는다.

### 11. Audit ownership과 persistence

[확정] registered adapter는 approval/denial/invalid/replay/revoke 요청에 대한 process-local sanitized event/evidence의
owner다. DohaLM은 approval object에 ADR-016의 opaque evidence fields만 보존하며 raw decision/evidence를 로그에 노출하지 않는다.

[확정] durable audit persistence, DB, object store와 cross-process event delivery를 제공하거나 주장하지 않는다. process
종료 후 authoritative audit가 필요하면 owner, schema, retention, access와 failure policy를 별도 architecture decision으로
정한다. durable audit 부재를 execution success evidence로 오인하지 않는다.

### 12. Failure contract

[확정] 후속 구현은 기존 `TrainingError` convention으로 다음 stable meaning을 제공한다. 구체적인 Python constant 배치는
구현 PR에서 정하되 의미를 합치거나 raw detail을 노출하지 않는다.

- `TRAINING_EXECUTION_ISSUER_UNAVAILABLE`
- `TRAINING_EXECUTION_ISSUER_UNAUTHENTICATED`
- `TRAINING_EXECUTION_ISSUER_UNAUTHORIZED`
- `TRAINING_EXECUTION_DECISION_INVALID`
- `TRAINING_EXECUTION_DECISION_REPLAYED`
- 기존 `TRAINING_EXECUTION_APPROVAL_DENIED`
- 기존 `TRAINING_EXECUTION_APPROVAL_TARGET_MISMATCH`
- production revoke unavailable 또는 unauthorized의 별도 stable code는 revoke contract에서 확정

[확정] 오류에는 credential, raw decision/evidence, registry identity, internal endpoint, absolute path, stack trace와
adapter implementation detail을 포함하지 않는다.

### 13. CLI와 execution state

[확정] registered adapter가 없으면 production issuance는 fail closed다. CLI는 composition root로서 adapter를 자동·임의
설치하지 않으므로 `--execute`를 계속 `TRAINING_EXECUTION_APPROVAL_REQUIRED`로 차단한다.

[확정] 이 결정은 production adapter implementation, actual approval issuance, Dataset/Artifact content read, reader,
Model/Provider/Trainer, optimizer, GPU, Training, Evaluation 또는 controlled execution을 승인하지 않는다.

## Threat model

[확정] supported API에서 arbitrary caller의 approved/denied 위조, issuer metadata 위조, request fingerprint 교체,
decision reconstruction·replay, wrong Dataset/config/request 재사용, malformed/missing evidence와 unauthorized revoke를 fail
closed 대상으로 한다.

[제외] compromised composition root, registered adapter, arbitrary malicious Python process, host compromise, process memory
modification, secret exfiltration과 external user authentication의 정확성은 방어한다고 주장하지 않는다.

## Scope

- same-process accountable issuer principal과 composition-root trust anchor
- one-time exact adapter registration과 in-process typed transport
- decision/evidence ownership, exact request binding과 process-local anti-replay
- restart, expiry, revoke authority, audit와 failure boundary

## Non-goals

- production adapter/revoke implementation
- IAM, JWT, HMAC, API key, OAuth, certificate, mTLS 또는 network identity
- REST, webhook, HTTP client, IPC, message bus 또는 scheduler
- credential/audit persistence, DB, object store 또는 secret manager
- Common schema·Authority·dependency·workflow 변경
- CLI activation 또는 actual Training/Evaluation

## Implementation Gate

1. 이 ADR의 독립 검증·명시 승인·병합
2. module-private one-time exact adapter registration과 absent/replacement fail-closed test
3. typed immutable decision과 adapter/decision exact-instance provenance registry
4. exact request fingerprint·permission binding과 approved/denied test
5. decision reconstruction·mutation·duplicate authorization·concurrent replay 차단
6. process restart authority 복원 0과 serialized decision non-authority test
7. private issuance seam만 registered adapter가 호출하고 direct caller issuance 0
8. raw evidence/credential/path 비노출과 sanitized stable error test
9. CLI fail-closed, reader/model/trainer/training/evaluation call 0 유지
10. production revoke 구현 전 별도 exact revoke decision contract 승인·병합
11. 그 이후에만 controlled execution enablement 별도 검토

## Consequences

- network IAM을 발명하지 않고 현재 process-local approval architecture와 일치하는 최소 production trust anchor가 생긴다.
- composition root와 exact adapter instance가 신뢰 경계를 명시적으로 소유한다.
- restart 때마다 새 adapter registration과 orchestration decision이 필요해 durable replay ambiguity를 제거한다.
- cross-process orchestration, durable audit와 production revoke exact envelope는 계속 별도 결정이다.
- 이 ADR만으로 Training execution 또는 CLI activation은 허용되지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-12 | [확정] same-process composition-root registered issuer adapter, in-process typed decision, process-local replay/restart와 audit 경계를 제안 |
