# C2 PostgreSQL Training Adapter 구현

- 문서 상태: `review`
- 마지막 검토일: 2026-08-15
- 선행 계약: [ADR-021](../decisions/ADR-021-production-training-adapters-and-durable-journal.md),
  [C1.2/C2 contract alignment](./c1-2-c2-contract-alignment.md)
- 범위: package-private C2 adapter 구현과 isolated contract test

## Adapter와 기존 port 대응

| 구현 | 기존 port | 허용된 PostgreSQL 함수 |
|---|---|---|
| `_PostgresTrainingPrerequisiteResolver` | `_TrustedTrainingPrerequisiteResolver` | `read_c2_training_prerequisite_snapshot` |
| `_PostgresTrainingDecisionResolver` | `TrustedTrainingDecisionResolver` | `read_c2_training_decision_snapshot` |
| `_PostgresTrainingExecutionJournal` | `DurableTrainingOrchestrationJournal` | `claim_c2_training_execution_journal`, `transition_c2_training_execution_journal`, `read_c2_training_execution_journal` |

[확정] 구현은 기존 request/result DTO를 그대로 사용한다. fingerprint, authority ID, correlation,
process boundary와 policy reference를 생성하거나 보정하지 않으며 직접 table SQL을 실행하지 않는다.
함수 결과는 cursor column metadata로 읽고 claim 함수의 실제 반환 이름을 완전한 named map으로
검증한다. positional result ordering과 prefix 추측에 의존하지 않는다.

## Connection과 transaction ownership

| 작업 | login role | isolation/access | connection owner |
|---|---|---|---|
| prerequisite resolve | `dohalm_training_resolver` | `REPEATABLE READ`, `READ ONLY` | 호출별 adapter transaction |
| decision resolve | `dohalm_training_resolver` | `REPEATABLE READ`, `READ ONLY` | 호출별 adapter transaction |
| journal claim/transition | `dohalm_training_journal` | `READ COMMITTED`, `READ WRITE` | 호출별 adapter transaction |
| journal read | `dohalm_training_journal` | `READ COMMITTED`, `READ ONLY` | 호출별 adapter transaction |

[확정] 각 설정은 exact login role의 별도 credential을 요구한다. bootstrap owner, `SET ROLE`, resolver와
journal connection 공유, import/construction 시 connection 생성은 없다. transaction context가 commit 또는
rollback한 뒤 connection을 닫는다. commit acknowledgement가 불명확한 mutation은 자동 재시도하지 않고
manual reconciliation 오류로 반환한다.

## Payload와 materialization

[확정] typed UUID, relationship, fingerprint, current projection, validity와 payload checksum을 먼저 검증한
뒤에만 generic bytes를 parser에 전달한다. DatasetVersion/Manifest와 pair permission input은 canonical JSON,
config와 readiness manifest는 제한된 UTF-8 YAML로 검증한다.

[확정] prerequisite resolver는 OS가 생성한 process-private root 아래 request별 디렉터리를 소유한다.
config/readiness 파일은 exclusive-create, flush/fsync, read-only 전환 후 absolute path로 기존 DTO에 전달한다.
호출자는 경로를 선택할 수 없다. `release(resolved)`가 request materialization만 삭제하고 `close()`가 남은
adapter-owned root를 삭제한다. 후속 C3 composition은 request 종료와 process shutdown에서 이 두 경계를
결속해야 하며, 이 C2 구현은 composition이나 실행을 활성화하지 않는다.

## 오류와 설정

- `21000`은 prerequisite authority relationship conflict다.
- journal `40001`, `23505`, `23514`는 deterministic conflict/invalid transition이다.
- `XX` class는 journal integrity failure다.
- `42501`은 permission denied, `57014`/`55P03`은 timeout이다.
- connection interruption과 commit outcome unknown은 서로 구분하며 mutation을 자동 재실행하지 않는다.
- PostgreSQL message text, locale 문자열, raw SQL parameter, credential 또는 DSN은 domain 오류에 포함하지 않는다.

[확정] configuration은 host/port/database, exact role user/password, connect/statement/idle-transaction timeout,
safe application name과 TLS policy를 명시한다. production은 `verify-full`과 절대 CA path를 요구한다.
`isolated_test`와 명시적 `local_single_user`만 정확한 IPv4 loopback `127.0.0.1`과
`sslmode=disable`을 허용한다. `local_single_user`는
[로컬 단일 사용자 Activation](../training/local-single-user-activation.md)이 소유하며 C1 private fixture나
local profile을 production TLS로 오인하지 않는다. 모든 `repr`은 credential을 redaction한다.

## Technical readiness와 execution decision

[확정] prerequisite resolver는 "이 exact material/configuration을 사용할 수 있는가"만 답한다. DatasetVersion,
Manifest, pair, config와 readiness의 identity, fingerprint, currentness, usage scope 및 기술적 blocker를 검증하며
approver, approval timestamp, acceptance 또는 execution authorization을 요구하지 않는다. canonical readiness report의
유일한 blocker가 `FULL_PRETRAINING_NOT_APPROVED`이면 material은 기술적으로 ready이고 실행은 계속 금지된 상태다.

[확정] decision resolver는 "이 exact run이 지금 실행될 수 있는가"를 별도로 답한다. missing/not-yet-effective/expired
decision은 `TRAINING_EXECUTION_DECISION_UNAVAILABLE`, denied decision은
`TRAINING_EXECUTION_APPROVAL_DENIED`로 fail closed한다. Host는 prerequisite와 approved/current decision을 모두 확인한
뒤에만 journal claim과 backend lifecycle에 진입한다. pending, denied, expired, binding mismatch에서는 claim, transition,
approval consume와 backend invocation이 모두 0이다. backend의 기존 `require_full_pretraining_approval()` 재검증은 유지된다.

이 분리는 `training_readiness_authority.readiness_result = READY`를 technical readiness로 해석하므로 schema, migration,
role 또는 GRANT 변경을 요구하지 않는다.

## 비활성 경계

[확정] 이 구현에는 composition root, executable, environment activation, production credential,
Dataset content 접근 승인, GPU, Training 또는 Evaluation이 없다. C3 composition과 별도 Production Activation
Gate 전에는 실제 backend invocation 권한이 생기지 않는다.

## Dependency와 CI 소유권

[확정] C1 workflow는 `requirements-c1.lock`과 `tests/test_postgres_c1.py`,
`tests/test_postgres_c1_integration.py`의 17개 계약만 소유한다. C1 test는 C2 adapter package를 import하지 않으며
Torch, YAML 또는 synthetic module 주입에 의존하지 않는다.

[확정] C2 workflow는 `requirements-c2.lock`을 `pip --require-hashes`로 설치하고 C2 전용 11개 계약과 명시적인
C1 17개 regression을 실행한다. lock은 Common AI Contracts 0.1.0 release wheel URL과 SHA-256,
`psycopg[binary] 3.3.4`, PyYAML, SentencePiece, PyTorch `2.7.1+cpu`, pytest, Ruff 및 전체 transitive
closure를 exact version과 artifact hash로 고정한다. CPU wheel은 CI import/contract 용도이며 Production CUDA
runtime 또는 Training 활성화를 의미하지 않는다.

[확정] lock 갱신은 Python 3.12에서 다음 명령으로 수행하고, 생성된 diff와 Windows/Linux fresh install을 함께
검증한다.

```text
uv pip compile requirements-c2.in --universal --python-version 3.12 --generate-hashes --only-binary=:all: --emit-index-url --emit-find-links
```

[확정] PyPI는 유일한 package index이고 PyTorch CPU 저장소는 `torch/` wheel 목록만 `--find-links`로 노출한다.
따라서 PyTorch 저장소가 제공하는 unrelated dependency artifact는 resolver 후보가 아니다. universal output에서 platform
wheel hash가 축약된 package는 PyPI release metadata의 Python 3.12 Windows/Linux wheel SHA-256을 대조·보존한 뒤 두
platform의 cache-free `pip --require-hashes` 설치로 검증한다.

[확정] production adapter import는 실제 dependency graph에서 수행한다. fake Torch/YAML module, `sys.modules`
주입, `__spec__` 조작 또는 broad import fallback은 허용하지 않는다. import와 adapter construction은 DB 연결,
GPU 실행, model load 또는 Training을 시작하지 않는다.
