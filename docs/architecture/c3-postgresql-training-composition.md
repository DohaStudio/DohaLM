# C3 PostgreSQL Training Composition

- 문서 상태: `review`
- 마지막 검토일: 2026-08-16
- 선행 계약: [ADR-021](../decisions/ADR-021-production-training-adapters-and-durable-journal.md),
  [C1.2/C2 contract alignment](./c1-2-c2-contract-alignment.md),
  [C2 PostgreSQL adapters](./c2-postgresql-training-adapters.md)
- 범위: package-private non-CLI composition과 non-activating preflight

## Dependency graph

[확정] C3의 exact composition symbol은
`src.training.production_composition._compose_postgres_training_host`다. 새 Host,
parallel composition root, service locator, executable 또는 CLI를 만들지 않는다.

```text
trusted immutable C3 configuration
  ├─ resolver role connection factory
  │   ├─ _PostgresTrainingPrerequisiteResolver
  │   └─ _PostgresTrainingDecisionResolver
  └─ journal role connection factory
      └─ _PostgresTrainingExecutionJournal
                    ↓ explicit injection
          existing ProductionFullPretrainingHost
```

| 구성 요소 | provider 선택 | lifecycle owner |
|---|---|---|
| prerequisite resolver | C3 trusted configuration | C3 composition root |
| decision resolver | C3 trusted configuration | C3 composition root |
| execution journal | C3 trusted configuration | C3 composition root |
| resolver/journal factory | 고정 role mapping | C3 composition root |
| Host | 기존 package-private bootstrap | 기존 Host와 C3 root |

## Configuration과 provider selection

[확정] 기본 provider는 `disabled`이며 PostgreSQL을 암묵적으로 선택하지 않는다.
PostgreSQL 구성은 environment, host/port/database, 서로 다른 resolver/journal credential,
timeout, application/process identity, decision authority UUID, prerequisite/decision policy와
activation authority/evidence reference를 모두 요구한다. raw DSN, environment-selected class, dynamic
import와 caller-selected adapter는 없다.

[확정] production profile은 `verify-full`과 존재하는 absolute non-symlink CA file을 요구한다.
`isolated_test`와 명시적 `local_single_user`만 정확한 IPv4 loopback `127.0.0.1`과 TLS disable을
허용한다. `local_single_user`의 durable Docker, credential, Dataset mapping과 executable ownership은
[로컬 단일 사용자 Activation](../training/local-single-user-activation.md)에 있다. configuration, root, activation decision의
`repr`과 모든 composition error는 credential, host, CA path와 raw database exception을 redaction한다.

## Activation boundary와 Host wiring

[확정] configuration은 activation authority가 아니다. C3 root는 non-mutating preflight 완료 뒤
provider, activation authority/evidence reference와 process boundary가 정확히 일치하는 explicit typed
activation decision이 있을 때만 기존 Host bootstrap을 호출한다. C3는 production decision을
발급·읽기·승인하거나 repository 설정에 저장하지 않는다. test의 synthetic decision은 disposable
contract fixture일 뿐 production approval이 아니다.

[확정] Host에는 PostgreSQL prerequisite resolver, decision resolver와 journal exact instance를
constructor boundary에서 주입한다. Host는 config/environment/DSN을 읽거나 adapter를 만들지 않는다.
process boundary와 두 policy reference는 composition configuration에서 한 번 고정되며 adapter가
보정하지 않는다.

[확정] 이 PR은 intent intake, executable, scheduler와 public Host accessor를 제공하지 않는다.
따라서 C3 graph가 synthetic fixture에서 constructible해도 Production Activation과 Training execution은
계속 false다. 실제 intake와 backend invocation은 별도 Production Activation Gate 대상이다.

## Lifecycle과 preflight

[확정] module import와 graph construction은 connection, registration, request, journal mutation과 backend
side effect가 0이다. preflight 시에만 C2 adapter가 short-lived connection으로 prerequisite/decision의
missing probe와 journal read를 수행한다. claim, transition, authority write와 direct table SQL은 없다.

[확정] resolver와 journal factory는 credential, role과 transaction ownership을 공유하지 않는다.
composition은 `NEW → STARTING → ACTIVE`와 `STARTING → FAILED → SHUTDOWN`,
`ACTIVE → SHUTTING_DOWN → SHUTDOWN`의 단일 explicit state machine과 revocable lease를 소유한다.
preflight connection은 `STARTING`, Host 실행과 runtime connection은 `ACTIVE`에서만 lease를 획득한다.
Host 진입과 resolver/journal connection factory 양쪽에서 lease를 검사하므로 Host-only TOCTOU guard에
의존하지 않는다.

[확정] shutdown은 lease를 가장 먼저 revoke해 새 Host 실행과 connection을 차단한다. revoke 전에 lease를
획득한 작업만 완료될 때까지 drain한 뒤, 해당 Host identity와 capability가 소유한 Host/issuer global
registration을 compare-and-clear한다. 이전 composition의 중복 shutdown은 더 새로운 registration을 제거하지
않는다. 이어 두 factory의 credential-bearing delegate, configuration, adapter와 Host의 composition strong
reference를 제거하고 prerequisite materialization root를 닫는다. Python 문자열의 물리적 zeroization은
주장하지 않는다.

[확정] configuration/factory/adapter/preflight/bootstrap/registration 실패는 lease를 `FAILED`로 revoke하고
같은 cleanup 경계를 거쳐 `SHUTDOWN`으로 끝난다. 실패한 composition과 shutdown된 retained Host는 재사용할
수 없고 startup을 다시 호출할 수 없다. cleanup 오류는 원래 실패를 덮지 않으며 별도의 redacted cleanup
오류로만 분류한다. shutdown은 동시 호출에도 idempotent하다. C2 factory는 호출별 connection을 열고
transaction 종료 후 닫으므로 보존할 pool은 없다.

## Error contract

| 분류 | stable composition code |
|---|---|
| provider disabled | `TRAINING_COMPOSITION_PROVIDER_DISABLED` |
| activation absent/mismatch | `TRAINING_COMPOSITION_ACTIVATION_NOT_AUTHORIZED` |
| config/TLS/role conflict | `TRAINING_COMPOSITION_CONFIGURATION_INVALID` |
| permission denied | `TRAINING_COMPOSITION_PERMISSION_DENIED` |
| timeout | `TRAINING_COMPOSITION_TIMEOUT` |
| dependency unavailable | `TRAINING_COMPOSITION_DEPENDENCY_UNAVAILABLE` |
| other preflight failure | `TRAINING_COMPOSITION_PREFLIGHT_FAILED` |
| revoked/failed lifecycle | `TRAINING_COMPOSITION_LIFECYCLE_REVOKED` |
| cleanup failure | `TRAINING_COMPOSITION_CLEANUP_FAILED` |

[확정] error에는 raw SQL, parameter, DSN, credential, host, CA path, exception representation과 stack
trace를 포함하지 않는다. configuration 오류를 database integrity failure로 바꾸지 않는다.

## 비활성 경계

[확정] C3는 migration/schema/function/trigger/role/GRANT, 기존 port/DTO와 C2 adapter semantics를
변경하지 않는다. production credential/data/DB, Dataset content, Model, GPU, Training/Evaluation에
접근하지 않는다. 다음 단계는 C3 독립 검증·병합 후 별도의 Production Activation Gate다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-16 | [확정] production TLS를 유지하면서 explicit `local_single_user` loopback profile 소비 경계 연결 |
| 2026-08-16 | [확정] explicit lifecycle state, Host/factory shared lease, compare-and-clear registration과 credential reference cleanup 보완 |
| 2026-08-16 | [확정] C3 package-private composition, provider/activation guard, lifecycle와 preflight 구현 계약 기록 |
