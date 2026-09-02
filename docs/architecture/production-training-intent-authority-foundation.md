# Production Training Intent Authority Foundation

- 문서 상태: `review`
- 마지막 검토일: 2026-09-01
- 기준 결정: [ADR-032](../decisions/ADR-032-production-training-intent-authority.md)

## 구현 경계

이 foundation과 후속 application wiring은 production Training 요청을 실행하지 않고, 승인된 authority를 생성하고 실행 경계를 연결하는 다음 단계까지 구현한다.

```text
current dedicated submitter authority
  -> immutable intent submission
  -> submitter-scoped idempotency
  -> exact Dataset/config/readiness binding
  -> TrainingExecutionRequest v1 projection
  -> append-only decision binding
  -> family-specific authority provisioning ports
  -> Product Dataset publication authority bridge
  -> validate-only boundary
  -> non-CLI application entrypoint
  -> read-only C3 composition resolution
  -> immutable activation plan + transient dry-run evidence
  -> explicit activate() -> existing C3/Host boundary
```

`activate()`는 검증된 intent ID와 observed source commit만 받아 currentness를 다시 확인한 뒤 기존 C3 composition과 `ProductionFullPretrainingHost.run()`에 위임한다. backend나 journal을 직접 호출하지 않는다. 이 구현 PR에서는 production credential/authority를 만들지 않고 `activate()`도 실제 호출하지 않으므로 backend, GPU, checkpoint, artifact와 execution journal mutation은 모두 0이다. application entrypoint는 transport-independent Python service이며 CLI, HTTP, websocket과 external queue를 추가하지 않는다.

## 구성 요소

| 구성 요소 | 책임 |
|---|---|
| `production_intent_authority.py` | frozen domain model, canonical fingerprint, construction-bound submitter selection, exact request projection, validate-only fail-closed 검증 |
| `postgres_training_intent_authority.py` | producer/writer/resolver role로 제한된 PostgreSQL function adapter와 안정적인 오류 분류 |
| migration `0006` | dedicated submitter authority, immutable submission, immutable decision binding, restricted function과 GRANT |
| migration `0007` | issuer·approver·config·readiness·decision과 Dataset version/manifest/pair 원자 등록을 위한 family-specific `SECURITY DEFINER` 함수 및 producer-only `EXECUTE` |
| migration `0010` | 기존 v1 pair payload를 보존하면서 C3 입력을 완결한 v2 pair authority를 발행하고, 공통 append-only lifecycle event로 v1을 supersede하는 producer-only replacement 함수 |
| `production_authority_provisioning.py` | raw SQL 없는 typed command/result port, submitter/issuer/approver UUID 분리와 staged provisioning package |
| `postgres_production_authority_provisioning.py` | producer role만 허용하는 restricted-function adapter; generic privileged CRUD 및 table DML 없음 |
| `product_dataset_authority_registration.py` / `dataset_publication_authority_bridge.py` | Dataset-owned pure material builder가 frozen/issued publication과 non-commercial eligibility를 stable identity로 동결하고 Training bridge가 PostgreSQL Dataset authority 3종에 원자 등록 |
| C1/C2 persistence coverage | C1 migration·restore와 C2-owned shared PostgreSQL fixture에서 exact/conflicting concurrent replay, cross-submitter scope, decision bind, immutable DML와 journal 비변경 검증 |
| `production_training_application.py` | durable intent ID와 observed source commit만 받는 frozen non-CLI command, exact activation plan/fingerprint, transient `READY_FOR_ACTIVATION` evidence와 explicit `activate()` |
| C3 `prepare_activation` / `activate` | actual intent의 prerequisite/decision/current source/output/continuation 및 journal collision을 재검증하고, 같은 prepared readiness만 기존 Host에 전달 |

## 영속성 및 권한

- submitter는 기존 identity/event/current projection을 재사용하는 `intent_submitter` family다.
- intent 생성 시각과 binding 시각은 PostgreSQL `transaction_timestamp()`가 발급한다.
- `(submitter_authority_id, client_request_id)`는 idempotency identity이고 `requested_run_id`는 전역 unique다.
- submission과 decision binding은 UPDATE/DELETE trigger로 불변이며 public/runtime/journal role에 직접 DML 권한을 주지 않는다.
- intent writer는 restricted submit function만 실행할 수 있고 resolver는 restricted read function만 실행할 수 있다.
- execution journal schema와 row는 이 foundation에서 변경하지 않는다.
- provisioning adapter에는 generic CRUD가 없고 모든 쓰기는 고정 `search_path`의 family-specific 함수로만 수행한다. Dataset version/manifest/pair는 단일 함수·단일 transaction이며 동일 입력은 replay되고 다른 payload는 전체 rollback된다.
- Dataset pair v2는 `upstream_objects`, `artifact_references`, `evaluated_at`, `expected_split_id`를 기존 authoritative publication evidence에서 동결한다. DatasetVersion·DatasetManifest canonical pair fingerprint는 content identity이므로 그대로 유지하고, v2 authority identity는 canonical payload SHA-256으로 별도 결속한다. 기존 v1 payload는 UPDATE·DELETE하지 않으며 v2 current 전환은 append-only `superseded` event로만 표현한다.

## Canonical projection

Python과 PostgreSQL은 UTF-8, lexicographic key order, compact separators, trailing LF의 같은 SHA-256 입력을 사용한다. PostgreSQL `jsonb` 내부 key order에 의존하지 않고 canonical text를 명시적으로 구성한다. Durable intent에서 기존 `TrainingExecutionRequest v1`의 11개 필드를 투영하며 별도 approval payload를 만들지 않는다.

## 검증 및 활성화 금지

validate-only는 intent, submitter, Dataset version/manifest/pair, config, readiness, decision, issuer와 approver currentness, request fingerprint와 source commit을 한 repeatable-read snapshot에서 검증한다. 승인 성공도 typed validated representation만 반환한다.

application entrypoint는 이 결과를 복제하지 않고 그대로 재사용한다. construction-bound C3 factory는 actual intent의 prerequisite와 decision을 다시 읽고, requested run journal collision, output availability와 fresh/R3 continuation을 검증한다. 결과 plan은 frozen projection이며 dry-run evidence는 activation 직전에 currentness를 다시 확인해야 하는 시점성 증거다. `dry_run()`은 계속 read-only이고, `activate()`만 same-readiness C3/Host 경계를 호출한다.

현재 상태:

- Architecture approved: `YES`
- Foundation implementation: `YES`
- Actual Training activation: `NO`
- Application entrypoint: `ACTIVE`
- Activation dry-run: `ACTIVE`
- Authority provisioning ports: `ACTIVE`
- Dataset publication authority bridge: `ACTIVE`
- Application `activate()`: `ACTIVE`
- This implementation PR Host/backend invocation: `0`
- Ruleset mutation: `0`

다음 단계는 별도 `Production Training Provisioning + Approved Intent + First Real Run`이며, 그 Gate에서 실제 credential·authority·intent를 생성하고 exact `activate()`를 명시 승인하기 전까지 actual Training activation은 계속 금지한다.
