# ADR-016: Generic Training Execution Approval 경계

- 문서 상태: `draft`
- 마지막 검토일: 2026-08-12
- 결정 상태: `proposed`
- 실행 영향: 없음
- 권위 기준: `DohaStudio/.github@dd75fc88c16e9ae9a04acfafb72756a905f6365b`
- 관련 문서: [ADR-014](./ADR-014-dataset-product-governance-boundary.md),
  [ADR-015](./ADR-015-dataset-version-publication-contract.md),
  [Dataset publication 구현 계획](../data/dataset-publication-implementation-plan.md),
  [Full Pretraining 실행 계획](../training/full-pretraining-execution-plan.md)

## Context

[확정] 병합된 Dataset 경계는 frozen `DatasetVersion`과 issued `DatasetManifest`를 검증한 뒤
`DatasetTrainingPermission`을 발급하고, full-pretraining entry에서 exact permission instance와 Dataset target을 먼저
검사한다. 이 permission은 Dataset pair의 training-entry prerequisite만 의미하며 특정 config·run·실행을 승인하지 않는다.

[확정] 현재 `run_full_pretraining()` 순서는 Dataset permission, 기존 readiness, config load, output·disk inspection,
seed, Dataset reader, Model·Trainer, Training·Evaluation이다. CLI는 Common pair 조회와 permission construction 계약이 없어
`--execute`를 계속 차단한다.

[확정] historical Candidate A/B, Pilot과 V03 계약은 모두 명시적 승인과 실행 identity를 분리하고 비용 있는 실행을
single-use로 제한한다. 그러나 action, artifact lifecycle과 consumption point가 서로 달라 generic contract로 직접 재사용할
수 없다. Common Authority에도 Training Execution Approval schema는 없다.

[확정] ADR-014가 사용자 UI·workflow와 사용자 승인을 외부 consumer domain 책임으로 둔 경계에 따라 DohaLM은 사람·계정
인증, IAM 또는 승인 UI를 소유하지 않는다. 따라서 DohaLM이 `approved_by` 문자열, 환경 변수, OS 사용자 또는 GitHub 계정을
근거로 실행 권한을 추정해서는 안 된다.

## 선례 분류

정의되지 않은 항목은 `undefined`로 유지한다.

| Contract | Approved action | Dataset binding | Config binding | Run binding | Issuer | Provenance | Expiry | Revocation | Replay |
|---|---|---|---|---|---|---|---|---|---|
| Candidate A historical full-pretraining | Candidate A 10M full-pretraining | Dataset·split·tokenizer fingerprints | config·model·initialization fingerprints | Run ID·Git commit·output | 명시적 사용자 승인 기록 | manifest field·consumption record; issuer authentication `undefined` | `undefined` | consumed 상태 | single-use, retry 금지 |
| Candidate B | Candidate B 25M full-pretraining | Dataset·split·packing fingerprints | resolved config·model·initialization | Run ID·Git/upstream·output | issuer identity `undefined` | immutable manifest·atomic consumption | timestamp 또는 config/commit/run 변경 무효화 | consumed/failed run 재사용 금지 | single-use |
| Pilot | smoke 또는 100-step Pilot | Dataset·tokenizer·readiness fingerprints | config fingerprint | run identity 일부 | `approved_by` 사용자 기록 | manifest validation; issuer authentication `undefined` | `undefined` | `undefined` | consumed result 재사용 금지 |
| V03 Tokenization | fresh tokenization request | V03 Dataset·evidence fingerprints | tokenization/backend/dependency fingerprints | reserved Run·request ID | `approver_id`; authentication `undefined` | persisted approval/request checksum·nonce·lifecycle | explicit TTL | retire/expire artifact | single-use·anti-replay |

[제안] 재사용 가능한 공통 요소는 exact action/target binding, deterministic fingerprint, explicit issuer boundary,
single-use, fail-closed consumption이다. Candidate별 budget, V03 TTL·HMAC·filesystem lifecycle, optimizer-step-1 consumption은 각
workflow 전용이며 generic contract로 승격하지 않는다.

## Decision

### 1. 승인 action과 Permission 분리

[제안] `TrainingExecutionApproval`은 하나의 immutable `TrainingExecutionRequest`가 나타내는
`full_pretraining` execution boundary 진입을 정확히 한 번 승인한다. Dataset 자체, Dataset publication, GPU 일반 사용,
job submission, resume/retry, Evaluation 또는 후속 Training을 승인하지 않는다.

[제안] `DatasetTrainingPermission`과 `TrainingExecutionApproval`은 별개의 필수 gate다. permission이 allowed여도 approval을
자동 발급하거나 execution approved로 승격하지 않는다.

### 2. Execution request identity

[제안] request의 canonical projection은 다음 값만 포함한다.

| Field | Source | Decision |
|---|---|---|
| `schema_version` | consumer contract | `1` 고정 |
| `action` | execution entry | `full_pretraining` 고정 |
| `dataset_version_id` | Activation target | permission target과 exact match |
| `dataset_manifest_id` | Activation target | permission target과 exact match |
| `dataset_pair_fingerprint` | Activation target | `sha256:` fingerprint exact match |
| `config_fingerprint` | existing `file_checksum(config_path)` | exact config bytes identity |
| `readiness_fingerprint` | approved readiness report | readiness evidence exact match |
| `run_id` | existing resolved output root basename | 새 Job system 없이 현재 run identity 재사용 |
| `output_logical_root` | config-declared logical output | 절대·private path가 아닌 logical identity |
| `source_commit` | readiness가 검사한 immutable Git HEAD | 40자리 commit과 clean tree 재검증 |
| `execution_mode` | caller | `fresh`만 허용; resume/retry 제외 |

[제안] `request_fingerprint`는 위 projection을 고정 key로 구성해 기존 `checksum_value()`로 계산한다. mapping-order나 호출자
객체 identity를 포함하지 않는다. seed, model, budget, dataset/tokenizer paths는 exact config bytes에 이미 포함되므로 별도
중복 field로 두지 않는다. config parser가 향후 semantic canonical representation을 제공하기 전까지 기존
`file_checksum(config_path)`가 authority다.

### 3. Run과 request 관계

[제안] 현재 `output_root.name`을 `run_id`로 사용하고 config의 logical output root를 함께 묶는다. generic Job, scheduler,
queue 또는 별도 Run registry를 만들지 않는다. 같은 request fingerprint라도 새 실행은 새 run identity와 새 approval을
요구한다.

### 4. Accountable issuer와 evidence

[제안] accountable issuer는 DohaLM 외부의 사용자-facing orchestration approval authority다. 이 owner는 사용자·운영자의
명시적 실행 결정을 인증하고 다음 최소 evidence를 제공한다.

- opaque `authorization_id`
- opaque `issuer_id`와 `approver_reference`
- raw secret·사용자 payload를 포함하지 않는 `evidence_reference`
- exact `request_fingerprint`
- `decision=approved`
- caller-provided timezone-aware `issued_at`

[제안] DohaLM은 이 identity를 생성·추정·인증하지 않는다. production issuer adapter는 외부 authority의 evidence를 검증한
뒤에만 내부 issuance seam을 호출하는 trusted composition boundary다. 이 ADR은 IAM, 서명, 외부 transport 또는 adapter
구현을 선택하지 않는다. production adapter가 별도 승인·구성되기 전에는 실제 `TrainingExecutionApproval` 발급이 항상
fail closed다.

[제안] 다음 구현 PR은 public `approve=True`, `approved_by` 문자열, default issuer, environment flag, public marker setter
또는 임의 callable을 issuer로 받는 API를 제공해서는 안 된다. synthetic test issuer는 test scope 밖에서 import·사용할 수
없는 명시적 test seam이어야 한다.

### 5. Approval evidence와 중복 검증 금지

[제안] issuance prerequisite는 evaluator-issued exact `DatasetTrainingPermission`, 승인된 readiness report,
`TrainingExecutionRequest`, 그리고 trusted issuer adapter가 검증한 외부 authorization evidence다. Approval은 Common
Dataset schema, rights, eligibility, split, artifact reference 또는 readiness 정책을 다시 구현하지 않고 각 결과의 exact
identity/fingerprint만 결속한다.

### 6. Provenance와 lifecycle

[제안] `TrainingExecutionRequest`와 `TrainingExecutionApproval`은 현재 process에서만 유효한 immutable object다. pickled,
JSON round-trip, copied, deep-copied, `dataclasses.replace()` 또는 equal-value reconstruction 객체는 authority를 갖지 않는다.

[제안] supported API boundary의 provenance는 issuer/evaluator-owned object-external exact-identity registry로 증명한다.
caller-controlled field, opaque token attribute나 equality를 provenance로 사용하지 않는다. registry는 weak reference와 exact
`is` identity를 사용하고 state를 `issued | consumed | revoked`로 관리한다. hostile arbitrary Python introspection 또는
cryptographic cross-process trust는 이 경계의 보장이 아니다.

[제안] approval 자체를 persistence authority로 저장하지 않는다. 외부 durable evidence는 opaque reference로만 남으며,
process 종료·object GC·consume·revoke 시 local authority가 끝난다. cross-process approval이 필요해지면 별도 security/product
decision이 필요하다.

### 7. Expiry와 revocation

[제안] local approval에 임의 wall-clock TTL을 만들지 않는다. exact immutable request에 결속되고 process-local이므로
유효 기간은 issuance부터 최초 consume, explicit revoke, GC 또는 process 종료 중 가장 이른 시점까지다. `issued_at`은 audit
evidence지만 local TTL 계산에 사용하지 않는다.

[제안] trusted issuer adapter는 issuance 직전에 외부 evidence가 current인지 검증한다. 실행 전 외부 승인 취소는 adapter가
내부 revoke seam을 호출해 registry state를 `revoked`로 바꾼다. public caller-facing revoke/restore API와 consumed approval
복원은 금지한다. durable cross-process revocation registry는 이번 범위가 아니다.

### 8. Replay와 atomic consumption

[제안] approval은 execution-attempt-bound single-use다. consume은 같은 process의 registry lock 아래 compare-and-set으로
`issued → consumed` 한 번만 허용한다. 동일 object 재호출, copy, 다른 thread의 경쟁, 같은 request의 새 object, failed run,
retry와 resume는 모두 새 request와 새 external authorization을 요구한다.

### 9. Consumption point와 call ordering

[제안] 구현 순서는 다음과 같다.

```text
DatasetTrainingPermission exact-instance/target 검증
→ existing readiness 검증
→ config inspection과 config/request fingerprint 구성
→ TrainingExecutionRequest exact identity 검증
→ TrainingExecutionApproval exact target 검증·atomic consume
→ seed
→ Dataset reader
→ Model / Trainer
→ Training / Evaluation
```

[제안] config/readiness/request 계산은 inspection-only다. approval consume 전 Dataset/Artifact content read, seed mutation,
reader construction, Model/Provider, Trainer, optimizer, GPU, Training과 Evaluation은 모두 0이어야 한다. 승인 후 초기화 실패도
approval을 복원하지 않는다.

### 10. Failure와 error contract

[제안] 최소 stable code는 다음 의미를 제공해야 한다. 구체적인 Python symbol은 구현 PR에서 저장소 관례에 맞춰 확정한다.

- `TRAINING_EXECUTION_REQUEST_INVALID`
- `TRAINING_EXECUTION_APPROVAL_REQUIRED`
- `TRAINING_EXECUTION_APPROVAL_INVALID`
- `TRAINING_EXECUTION_APPROVAL_DENIED`
- `TRAINING_EXECUTION_APPROVAL_TARGET_MISMATCH`
- `TRAINING_EXECUTION_APPROVAL_REVOKED`
- `TRAINING_EXECUTION_APPROVAL_CONSUMED`

[제안] 오류는 code와 sanitized message만 노출한다. raw permission/readiness/config, 절대 경로, registry identity, 외부 evidence,
사용자 identity, secret/token과 stack trace를 포함하지 않는다.

### 11. CLI와 실제 실행 상태

[제안] 이 ADR과 후속 boundary 구현만으로 CLI를 활성화하지 않는다. Common pair lookup, permission evaluation, configured
production issuer adapter, request/approval issuance와 전체 synthetic Gate가 별도로 승인·병합되기 전 `--execute`는 계속
fail closed다.

[제안] 이 ADR은 실제 Training/Evaluation, Dataset read, GPU 사용, job submission, approval issuance 또는 controlled dry-run을
승인하지 않는다.

## Scope

- generic full-pretraining execution request·approval 의미와 identity
- external accountable issuer와 DohaLM trusted adapter 경계
- process-local immutable provenance·single-use lifecycle
- fail-closed ordering, error와 implementation/test Gate

## Non-goals

- production issuer adapter, IAM, UI, API, signature/HMAC 또는 external transport 구현
- DatasetTrainingPermission·Common schema·Authority 변경
- approval artifact persistence, DB, object store, scheduler, queue 또는 Job system
- CLI activation, actual reader/model/trainer/GPU/Training/Evaluation
- Candidate A/B, Pilot 또는 V03 contract migration

## Implementation readiness

| Concept | Decision | Source/Evidence | Implementation owner | Test obligation |
|---|---|---|---|---|
| approved action | exact fresh `full_pretraining` request 1회 | current backend·single-use precedents | `src/training` future boundary | action mismatch·replay |
| DatasetVersion binding | exact ID | Activation target | future boundary | mismatch downstream 0 |
| Manifest binding | exact ID | Activation target | future boundary | mismatch downstream 0 |
| pair fingerprint | exact `sha256:` | Activation target | future boundary | stale pair 차단 |
| config identity | `file_checksum(config_path)` | current readiness/backend | request builder | byte drift 차단 |
| run/job identity | run ID + logical output; no Job system | current `output_root.name` | request builder | reuse/collision 차단 |
| request fingerprint | `checksum_value()` fixed projection | existing checksum helper | request builder | deterministic vectors |
| issuer | external orchestration approval authority | ADR-014 external user workflow owner | future production adapter | adapter absent fail closed |
| evidence | opaque authorization/issuer/approver/evidence refs + request fp + issued_at | historical explicit approval, privacy boundary | future adapter | raw/secret leakage 0 |
| provenance | object-external weak exact-identity registry | PR #114 repaired precedent | future boundary | constructor/copy/pickle/replace 차단 |
| lifecycle | process-local `issued→consumed` or `issued→revoked` | current same-process entry | future boundary | GC/concurrency/state matrix |
| expiry | consume/revoke/GC/process end; no wall-clock TTL | exact request + no generic TTL authority | future boundary | arbitrary TTL 0 |
| revocation | trusted adapter-owned pre-consume registry transition | external issuer accountability | future adapter/boundary | revoked downstream 0 |

## Implementation Gate

1. ADR 독립 검증과 명시적 승인·병합
2. pure immutable request projection과 deterministic fingerprint vectors
3. process-local approval registry·consume/revoke state machine의 synthetic-only 구현
4. production issuer adapter 부재 시 issuance 0과 CLI fail-closed 유지
5. permission → readiness → request → approval → execution sentinel ordering 독립 검증
6. 별도 production issuer adapter/security contract 결정
7. 그 이후에만 controlled execution-enablement 검토

## Test and evidence Gate

[제안] 후속 구현은 absent, denied, direct constructor, field manipulation, copy/deepcopy, pickle, replace, equality, wrong Dataset,
wrong config/readiness/run/source, revoked, duplicate/concurrent consume를 모두 차단해야 한다. 모든 blocked path에서 reader, Model,
Provider, Trainer, optimizer, GPU, Training과 Evaluation 호출은 0이어야 한다.

[제안] valid synthetic path는 approval을 정확히 한 번 consume하고 execution sentinel까지만 도달한다. actual Dataset reader,
Model, Trainer, Training과 Evaluation은 해당 구현 PR에서도 실행하지 않는다.

## Security boundary

[확정] 이 결정은 supported DohaLM API에서 external accountable issuer, trusted adapter와 exact local capability를 분리한다.
arbitrary malicious Python code, compromised process, external issuer compromise 또는 cryptographic authorization을 방어한다고
표현하지 않는다. 이 범위를 넘는 요구는 별도 product/security 결정이다.

## Consequences

- Dataset eligibility와 execution authorization이 독립 gate로 유지된다.
- config·run·source drift와 approval replay를 execution 전에 차단할 계약이 생긴다.
- production issuer adapter가 없으므로 이 ADR 병합만으로 실제 approval을 발급하거나 Training을 실행할 수 없다.
- cross-process approval이 필요해지면 persistence·signature·revocation 설계를 새로 결정해야 한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-12 | [제안] Common Dataset 기반 generic full-pretraining request·external issuer·process-local single-use approval 경계 초안 등록 |
