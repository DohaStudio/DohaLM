# Production Training Intent Authority Foundation

- 문서 상태: `review`
- 마지막 검토일: 2026-09-01
- 기준 결정: [ADR-032](../decisions/ADR-032-production-training-intent-authority.md)

## 구현 경계

이 foundation은 production Training 요청을 실행하지 않고 다음 경계까지만 구현한다.

```text
current dedicated submitter authority
  -> immutable intent submission
  -> submitter-scoped idempotency
  -> exact Dataset/config/readiness binding
  -> TrainingExecutionRequest v1 projection
  -> append-only decision binding
  -> validate-only boundary
  -> STOP
```

`ProductionFullPretrainingHost.run()`, backend, GPU, checkpoint, artifact, execution journal claim과 public entrypoint는 호출하거나 추가하지 않는다.

## 구성 요소

| 구성 요소 | 책임 |
|---|---|
| `production_intent_authority.py` | frozen domain model, canonical fingerprint, construction-bound submitter selection, exact request projection, validate-only fail-closed 검증 |
| `postgres_training_intent_authority.py` | producer/writer/resolver role로 제한된 PostgreSQL function adapter와 안정적인 오류 분류 |
| migration `0006` | dedicated submitter authority, immutable submission, immutable decision binding, restricted function과 GRANT |
| C1/C2 persistence coverage | C1 migration·restore와 C2-owned shared PostgreSQL fixture에서 exact/conflicting concurrent replay, cross-submitter scope, decision bind, immutable DML와 journal 비변경 검증 |

## 영속성 및 권한

- submitter는 기존 identity/event/current projection을 재사용하는 `intent_submitter` family다.
- intent 생성 시각과 binding 시각은 PostgreSQL `transaction_timestamp()`가 발급한다.
- `(submitter_authority_id, client_request_id)`는 idempotency identity이고 `requested_run_id`는 전역 unique다.
- submission과 decision binding은 UPDATE/DELETE trigger로 불변이며 public/runtime/journal role에 직접 DML 권한을 주지 않는다.
- intent writer는 restricted submit function만 실행할 수 있고 resolver는 restricted read function만 실행할 수 있다.
- execution journal schema와 row는 이 foundation에서 변경하지 않는다.

## Canonical projection

Python과 PostgreSQL은 UTF-8, lexicographic key order, compact separators, trailing LF의 같은 SHA-256 입력을 사용한다. PostgreSQL `jsonb` 내부 key order에 의존하지 않고 canonical text를 명시적으로 구성한다. Durable intent에서 기존 `TrainingExecutionRequest v1`의 11개 필드를 투영하며 별도 approval payload를 만들지 않는다.

## 검증 및 활성화 금지

validate-only는 intent, submitter, Dataset version/manifest/pair, config, readiness, decision, issuer와 approver currentness, request fingerprint와 source commit을 한 repeatable-read snapshot에서 검증한다. 승인 성공도 typed validated representation만 반환한다.

현재 상태:

- Architecture approved: `YES`
- Foundation implementation: `IN REVIEW`; merge 후 `YES`
- Actual Training activation: `NO`
- Application entrypoint: `NO`
- Host/backend invocation: `0`
- Ruleset mutation: `0`
