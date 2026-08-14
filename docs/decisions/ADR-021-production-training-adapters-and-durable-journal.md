# ADR-021: Production Training Adapters와 Durable Journal Authority

- 문서 상태: `approved`
- 마지막 검토일: 2026-08-13
- 결정 상태: `approved`
- 실행 영향: architecture contract 승인; C1/C2/C3 미구현, production activation 미승인
- 승인 근거: [PR #126](https://github.com/DohaStudio/DohaLM/pull/126), squash merge
  `dc999571117bcc6349bf948f3f1e85661aef626a` (2026-08-13)
- 관련 문서: [ADR-015](./ADR-015-dataset-version-publication-contract.md),
  [ADR-016](./ADR-016-generic-training-execution-approval-boundary.md),
  [ADR-017](./ADR-017-production-training-execution-issuer-trust-anchor.md),
  [ADR-018](./ADR-018-composition-root-owned-training-execution-decision-source.md),
  [ADR-019](./ADR-019-production-full-pretraining-host-and-trusted-decision-input.md),
  [ADR-020](./ADR-020-production-training-orchestration-ownership-seams.md),
  [ADR-022](./ADR-022-c1-ephemeral-postgresql-test-image-security-policy.md),
  [Dataset publication 구현 계획](../data/dataset-publication-implementation-plan.md),
  [Full Pretraining 실행 계획](../training/full-pretraining-execution-plan.md)

## Context

[확정] ADR-019·020과 병합된 Production Host는 same-process composition root가 prerequisite resolver, decision
resolver/source, issuer adapter와 durable journal을 불변 결속하도록 한다. 그러나 현재 저장소에는 production config,
readiness evidence, Dataset pair와 business decision을 조회할 authoritative repository가 없고, journal port를 영속화할
승인된 제품·schema·transaction 계약도 없다. non-CLI production process, credential 주입과 restart ownership 역시
정해지지 않았다.

[확정] ADR-015의 publication은 로컬 디렉터리 안에서 canonical DatasetVersion·DatasetManifest 두 JSON을 publish하는
primitive다. 이는 production authority catalog, multi-process lock, backup 또는 power-loss durability 계약이 아니다.
ADR-017·018의 DecisionSource와 issuer registry는 process-local이며 process restart 뒤 decision authority나 capability를
복구하지 않는다. 이들을 production adapter로 포장하는 것만으로 durable authority가 되지 않는다.

[확정] 따라서 future production persistence/adapter 구현은 Definition of Ready의 입력·출력, 설정, persistence와 recovery 조건을 충족하지
않는다. 제품·경로·schema·환경변수·secret provider를 구현자가 임의 선택하지 않도록 이 ADR에서 선택지를 비교하고 하나의
승인 계약을 정의한다. 이 ADR의 승인은 Python, dependency, migration, credential, production data와 runtime activation을
변경하지 않는다.

[확정] C1 ephemeral PostgreSQL test image의 취약점 허용 기준은 이 ADR에서 결정하지 않았다. `Critical 0 / High 0`,
특정 `gosu` rebuild 대기, official-image-only 또는 대체 image 금지는 [ADR-022](./ADR-022-c1-ephemeral-postgresql-test-image-security-policy.md)의
별도 proposed Decision Gate이며 이 ADR의 승인 요구사항으로 소급하지 않는다.

## 검토한 선택지

### Authority와 persistence 제품

| 선택지 | 장점 | 문제 | 판정 |
|---|---|---|---|
| ADR-015 local publication 디렉터리와 JSON journal | dependency가 작음 | cross-process CAS, transaction, fsync·power-loss, schema migration과 backup 계약이 없음 | 기각 |
| process별 SQLite database | 단일 파일·local test가 쉬움 | process/service ownership, network filesystem 금지, writer contention과 운영 backup 경계가 배포 topology에 결속됨 | 기각 |
| prerequisite별 별도 저장소 + journal database | 각 도메인 독립 운영 가능 | 한 request snapshot의 currentness와 decision/journal claim 사이 원자 경계가 없고 분산 복구가 필요 | 기각 |
| supported PostgreSQL authority catalog + 외부 immutable artifact reference | row-level CAS, constraint, transaction, recovery와 운영 도구가 명확함 | 운영 database와 driver·migration·backup 책임이 추가됨 | 채택 |
| object storage를 모든 authority와 journal로 사용 | immutable payload 보관에 적합 | conditional update와 journal transaction 의미가 provider마다 달라짐 | metadata/journal에는 기각; Dataset content 위치는 후속 범위 |

### Credential 공급

| 선택지 | 장점 | 문제 | 판정 |
|---|---|---|---|
| DSN 원문 environment variable | 배포가 단순함 | process listing·diagnostic·error 환경 dump에 secret 노출 위험 | 기각 |
| caller 또는 CLI가 DSN/path 전달 | test가 쉬움 | caller가 production composition과 authority를 선택함 | 기각 |
| deployment-owned protected DSN file의 절대 경로만 environment로 전달 | secret rotation과 application config 분리 | mount·ACL 운영 책임 필요 | 채택 |
| 특정 cloud secret SDK | rotation 기능이 풍부함 | deployment provider가 선택되지 않았고 새 dependency가 필요 | 현재 기각; topology 변경 시 재검토 |

## Decision

### 1. authority topology와 소유권

[확정] production metadata authority와 durable journal은 단일 PostgreSQL database, 고정 schema
`dohalm_training_v1`에 둔다. product version policy는 **PostgreSQL 16 이상이며 upstream이 지원하고 DohaLM compatibility
matrix가 명시적으로 승인한 major의 최신 supported minor**다. 최초 Schema/Dependency PR C1의 validation baseline과 초기
allowlist는 `16.x`/`{16}`이지만 16-only 기능을 주장하지 않는다. 다른 supported major는 driver·migration·concurrency·backup/
restore contract suite를 통과해 matrix가 갱신된 뒤 사용할 수 있다. unsupported/EOL major, matrix 밖 major와 승인 minor보다
낮은 보안 minor는 fail closed한다. major upgrade는 별도 migration·restore·recovery 독립 검증 Gate다. schema version은 exact
integer `1`이다. Dataset 원문·model·checkpoint·output은 database에 저장하지 않는다.

[확정] Production Training Deployment Owner와 Security/Secret Provisioning Owner가 database deployment와 secret mount를
각각 소유한다. future non-CLI production composition boundary만 연결을 만들고 아래 adapter를 정확히 한 번 구성한다.

- `_PostgresTrainingPrerequisiteResolver`
- `_PostgresTrainingDecisionResolver`
- existing same-process `TrainingExecutionDecisionSource`와 `ProductionTrainingExecutionIssuerAdapter`
- `_PostgresTrainingExecutionJournal`
- `ProductionFullPretrainingHost`

위 adapter symbol은 후속 Adapter PR C2의 package-private 목표이며 이 ADR PR에서 생성하지 않는다. composition executable의
exact symbol은 Composition PR C3에서 확정한다. caller, CLI, request, plugin, dynamic import, service locator와
environment-selected class는 adapter나 connection을 선택할 수 없다.

### 2. reference 문법과 공통 record envelope

[확정] Host foundation의 기존 `[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}` 검증을 유지하면서 production reference를 아래 exact
ASCII 형식으로 제한한다. `<id>`는 lowercase UUID textual form이고 namespace와 id의 조합은 immutable하다.

```text
config:<id>
readiness:<id>
dataset-version:<id>
dataset-manifest:<id>
dataset-pair:<id>
decision:<id>
```

`authorization_id`, `issuer_id`, `approver_reference`, `prerequisite_resolution_policy_reference`와
`decision_policy_reference`는 whitespace 없는 위 Host reference grammar의 opaque scalar다. 두 policy reference는 서로 다른
producer와 lifecycle을 가지며 한 컬럼이나 fallback으로 혼용하지 않는다. `evidence_reference`는 exact
`decision:<authority_id>`다. scalar를 소지하거나 재구성해도 authority는 없다.

[확정] 모든 immutable authority family row는 `training_authority_identity`의 UUID surrogate identity를 공유한다. 외부
domain reference는 UUID PK를 대체하지 않는 immutable UNIQUE alternate key다. DB timestamp를 canonical ISO 8601로
직렬화할 때 UTC offset `+00:00`을 포함한다. `payload_sha256`은 `sha256:` + lowercase hex 64이며 payload의
repository-defined canonical bytes에 기존 `checksum_value()`와 동일한 SHA-256 표현을 적용한 값이다.

`training_authority_identity`의 exact schema는 다음과 같다.

| field | exact PostgreSQL type / constraint |
|---|---|
| `authority_id` | `uuid PRIMARY KEY`, no default; producer가 생성한 UUID |
| `subject_family` | `text NOT NULL CHECK` exact `config`, `readiness`, `dataset_version`, `dataset_manifest`, `dataset_pair`, `decision`, `issuer`, `approver` |
| `domain_key` | `varchar(256) NOT NULL`, Host reference grammar, whitespace-only 금지 |
| `created_at` | `timestamptz NOT NULL DEFAULT transaction_timestamp()` |

`UNIQUE(subject_family, domain_key)`이며 세 identity field는 insert 뒤 UPDATE·DELETE할 수 없다. 각 family table은
`authority_id uuid PRIMARY KEY`와 같은 `subject_family` 상수를 보존하고
`FOREIGN KEY (authority_id, subject_family) REFERENCES training_authority_identity(authority_id, subject_family) ON DELETE
RESTRICT`를 사용한다. 이를 위해 identity table은 `UNIQUE(authority_id, subject_family)`도 갖는다. polymorphic application
predicate나 opaque key만으로 family binding을 대체하지 않는다.

| field | exact type / constraint | 의미 |
|---|---|---|
| `authority_id` | UUID primary key/FK | `training_authority_identity.authority_id` |
| `schema_version` | `smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1)` | record envelope version |
| `payload_bytes` | `bytea NOT NULL CHECK (octet_length(payload_bytes) > 0)`, NO DEFAULT | immutable source bytes |
| `payload_sha256` | `char(71) NOT NULL`, NO DEFAULT, `CHECK (payload_sha256 ~ '^sha256:[0-9a-f]{64}$')` | exact source-byte identity |
| `created_at` | `timestamptz NOT NULL DEFAULT transaction_timestamp()` | DB가 기록한 생성 시각 |
| `valid_from` | `timestamptz NOT NULL`, NO DEFAULT, `CHECK (created_at <= valid_from)` | 효력 시작 |
| `valid_until` | `timestamptz NULL DEFAULT NULL`, `CHECK (valid_until IS NULL OR valid_from < valid_until)` | null이면 별도 expiry 없음 |
| `source_commit` | `char(40) NOT NULL`, NO DEFAULT, `CHECK (source_commit ~ '^[0-9a-f]{40}$')` | producer source provenance |

위 column은 SQL inheritance 없이 config, readiness, DatasetVersion, DatasetManifest, pair, decision, issuer와 approver의
각 family table DDL에 동일하게 반복한다. nullable family 예외는 없다. CHECK가 NULL을 허용하는 PostgreSQL 의미에 의존하지
않고 `schema_version`, `payload_bytes`, `payload_sha256`과 `source_commit`을 별도 `NOT NULL`로 강제한다.

다음 56개 정의는 위 공통 envelope의 **normative C1 family expansion**이다. 설명용 참조, PostgreSQL inheritance,
`LIKE`, generated DDL 또는 암묵적 macro가 아니며 migration은 각 named family table에 해당 7개 column을 그대로 선언한다.
8개 family 모두 `valid_until`만 nullable이고 다른 nullable 예외는 없다. 아래 정의와 각 절의 family-specific identity,
alternate key, payload binding, FK, uniqueness, currentness와 supersession constraint를 함께 적용한다.

| Authority family table | Envelope column | Exact PostgreSQL definition repeated in that family DDL |
|---|---|---|
| `training_config_authority` | `schema_version` | `smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1)` |
| `training_config_authority` | `payload_bytes` | `bytea NOT NULL CHECK (octet_length(payload_bytes) > 0)`, NO DEFAULT |
| `training_config_authority` | `payload_sha256` | `char(71) NOT NULL`, NO DEFAULT, `CHECK (payload_sha256 ~ '^sha256:[0-9a-f]{64}$')` |
| `training_config_authority` | `created_at` | `timestamptz NOT NULL DEFAULT transaction_timestamp()` |
| `training_config_authority` | `valid_from` | `timestamptz NOT NULL`, NO DEFAULT, `CHECK (created_at <= valid_from)` |
| `training_config_authority` | `valid_until` | `timestamptz NULL DEFAULT NULL`, `CHECK (valid_until IS NULL OR valid_from < valid_until)` |
| `training_config_authority` | `source_commit` | `char(40) NOT NULL`, NO DEFAULT, `CHECK (source_commit ~ '^[0-9a-f]{40}$')` |
| `training_readiness_authority` | `schema_version` | `smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1)` |
| `training_readiness_authority` | `payload_bytes` | `bytea NOT NULL CHECK (octet_length(payload_bytes) > 0)`, NO DEFAULT |
| `training_readiness_authority` | `payload_sha256` | `char(71) NOT NULL`, NO DEFAULT, `CHECK (payload_sha256 ~ '^sha256:[0-9a-f]{64}$')` |
| `training_readiness_authority` | `created_at` | `timestamptz NOT NULL DEFAULT transaction_timestamp()` |
| `training_readiness_authority` | `valid_from` | `timestamptz NOT NULL`, NO DEFAULT, `CHECK (created_at <= valid_from)` |
| `training_readiness_authority` | `valid_until` | `timestamptz NULL DEFAULT NULL`, `CHECK (valid_until IS NULL OR valid_from < valid_until)` |
| `training_readiness_authority` | `source_commit` | `char(40) NOT NULL`, NO DEFAULT, `CHECK (source_commit ~ '^[0-9a-f]{40}$')` |
| `dataset_version_authority` | `schema_version` | `smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1)` |
| `dataset_version_authority` | `payload_bytes` | `bytea NOT NULL CHECK (octet_length(payload_bytes) > 0)`, NO DEFAULT |
| `dataset_version_authority` | `payload_sha256` | `char(71) NOT NULL`, NO DEFAULT, `CHECK (payload_sha256 ~ '^sha256:[0-9a-f]{64}$')` |
| `dataset_version_authority` | `created_at` | `timestamptz NOT NULL DEFAULT transaction_timestamp()` |
| `dataset_version_authority` | `valid_from` | `timestamptz NOT NULL`, NO DEFAULT, `CHECK (created_at <= valid_from)` |
| `dataset_version_authority` | `valid_until` | `timestamptz NULL DEFAULT NULL`, `CHECK (valid_until IS NULL OR valid_from < valid_until)` |
| `dataset_version_authority` | `source_commit` | `char(40) NOT NULL`, NO DEFAULT, `CHECK (source_commit ~ '^[0-9a-f]{40}$')` |
| `dataset_manifest_authority` | `schema_version` | `smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1)` |
| `dataset_manifest_authority` | `payload_bytes` | `bytea NOT NULL CHECK (octet_length(payload_bytes) > 0)`, NO DEFAULT |
| `dataset_manifest_authority` | `payload_sha256` | `char(71) NOT NULL`, NO DEFAULT, `CHECK (payload_sha256 ~ '^sha256:[0-9a-f]{64}$')` |
| `dataset_manifest_authority` | `created_at` | `timestamptz NOT NULL DEFAULT transaction_timestamp()` |
| `dataset_manifest_authority` | `valid_from` | `timestamptz NOT NULL`, NO DEFAULT, `CHECK (created_at <= valid_from)` |
| `dataset_manifest_authority` | `valid_until` | `timestamptz NULL DEFAULT NULL`, `CHECK (valid_until IS NULL OR valid_from < valid_until)` |
| `dataset_manifest_authority` | `source_commit` | `char(40) NOT NULL`, NO DEFAULT, `CHECK (source_commit ~ '^[0-9a-f]{40}$')` |
| `dataset_pair_authority` | `schema_version` | `smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1)` |
| `dataset_pair_authority` | `payload_bytes` | `bytea NOT NULL CHECK (octet_length(payload_bytes) > 0)`, NO DEFAULT |
| `dataset_pair_authority` | `payload_sha256` | `char(71) NOT NULL`, NO DEFAULT, `CHECK (payload_sha256 ~ '^sha256:[0-9a-f]{64}$')` |
| `dataset_pair_authority` | `created_at` | `timestamptz NOT NULL DEFAULT transaction_timestamp()` |
| `dataset_pair_authority` | `valid_from` | `timestamptz NOT NULL`, NO DEFAULT, `CHECK (created_at <= valid_from)` |
| `dataset_pair_authority` | `valid_until` | `timestamptz NULL DEFAULT NULL`, `CHECK (valid_until IS NULL OR valid_from < valid_until)` |
| `dataset_pair_authority` | `source_commit` | `char(40) NOT NULL`, NO DEFAULT, `CHECK (source_commit ~ '^[0-9a-f]{40}$')` |
| `training_execution_decision_authority` | `schema_version` | `smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1)` |
| `training_execution_decision_authority` | `payload_bytes` | `bytea NOT NULL CHECK (octet_length(payload_bytes) > 0)`, NO DEFAULT |
| `training_execution_decision_authority` | `payload_sha256` | `char(71) NOT NULL`, NO DEFAULT, `CHECK (payload_sha256 ~ '^sha256:[0-9a-f]{64}$')` |
| `training_execution_decision_authority` | `created_at` | `timestamptz NOT NULL DEFAULT transaction_timestamp()` |
| `training_execution_decision_authority` | `valid_from` | `timestamptz NOT NULL`, NO DEFAULT, `CHECK (created_at <= valid_from)` |
| `training_execution_decision_authority` | `valid_until` | `timestamptz NULL DEFAULT NULL`, `CHECK (valid_until IS NULL OR valid_from < valid_until)` |
| `training_execution_decision_authority` | `source_commit` | `char(40) NOT NULL`, NO DEFAULT, `CHECK (source_commit ~ '^[0-9a-f]{40}$')` |
| `training_issuer_registry` | `schema_version` | `smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1)` |
| `training_issuer_registry` | `payload_bytes` | `bytea NOT NULL CHECK (octet_length(payload_bytes) > 0)`, NO DEFAULT |
| `training_issuer_registry` | `payload_sha256` | `char(71) NOT NULL`, NO DEFAULT, `CHECK (payload_sha256 ~ '^sha256:[0-9a-f]{64}$')` |
| `training_issuer_registry` | `created_at` | `timestamptz NOT NULL DEFAULT transaction_timestamp()` |
| `training_issuer_registry` | `valid_from` | `timestamptz NOT NULL`, NO DEFAULT, `CHECK (created_at <= valid_from)` |
| `training_issuer_registry` | `valid_until` | `timestamptz NULL DEFAULT NULL`, `CHECK (valid_until IS NULL OR valid_from < valid_until)` |
| `training_issuer_registry` | `source_commit` | `char(40) NOT NULL`, NO DEFAULT, `CHECK (source_commit ~ '^[0-9a-f]{40}$')` |
| `training_approver_registry` | `schema_version` | `smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1)` |
| `training_approver_registry` | `payload_bytes` | `bytea NOT NULL CHECK (octet_length(payload_bytes) > 0)`, NO DEFAULT |
| `training_approver_registry` | `payload_sha256` | `char(71) NOT NULL`, NO DEFAULT, `CHECK (payload_sha256 ~ '^sha256:[0-9a-f]{64}$')` |
| `training_approver_registry` | `created_at` | `timestamptz NOT NULL DEFAULT transaction_timestamp()` |
| `training_approver_registry` | `valid_from` | `timestamptz NOT NULL`, NO DEFAULT, `CHECK (created_at <= valid_from)` |
| `training_approver_registry` | `valid_until` | `timestamptz NULL DEFAULT NULL`, `CHECK (valid_until IS NULL OR valid_from < valid_until)` |
| `training_approver_registry` | `source_commit` | `char(40) NOT NULL`, NO DEFAULT, `CHECK (source_commit ~ '^[0-9a-f]{40}$')` |

`payload_sha256`은 existing `sha256_bytes(payload_bytes)`와 exact 동일하다. JSON resource는 먼저 existing
`canonical_json_bytes()`로 만들며 UTF-8, key 이름순, compact separator, trailing LF 하나와 non-finite rejection을 그대로
사용한다. YAML source는 byte-for-byte identity를 보존한다.

insert 뒤 identity, domain key, validity, `payload_bytes`, fingerprint와 provenance는 UPDATE·DELETE할 수 없다. raw secret,
DSN, absolute path, capability, approval과 PII payload를 저장하지 않는다. revoke/supersede는 immutable row를 수정하지 않고
아래 공통 append-only `training_authority_event`에만 기록한다.

| field | exact type / constraint |
|---|---|
| `event_id` | `uuid PRIMARY KEY`, no default; producer-generated |
| `authority_id` | `uuid NOT NULL` |
| `subject_family` | 위 identity와 같은 closed `text NOT NULL` set |
| `subject_version` | `bigint NOT NULL CHECK (subject_version >= 1)` |
| `event_kind` | `text NOT NULL CHECK` exact `published`, `activated`, `revoked`, `superseded` |
| `superseded_by_authority_id` | `uuid NULL`; `superseded`에서만 NOT NULL, self-reference 금지 |
| `effective_at` | `timestamptz NOT NULL` |
| `recorded_at` | `timestamptz NOT NULL DEFAULT transaction_timestamp()` |
| `producer_role` | `varchar(128) NOT NULL CHECK (producer_role = 'training_authority_producer')` |
| `correlation_reference` | `varchar(256) NOT NULL`, opaque Host-reference grammar |
| `evidence_reference` | `varchar(256) NOT NULL`, opaque Host-reference grammar |
| `event_fingerprint` | `char(71) NOT NULL`, canonical event projection의 fingerprint pattern |

`FOREIGN KEY (authority_id, subject_family)`은 identity table의 같은 pair를 `ON DELETE RESTRICT`로 참조한다.
`superseded_by_authority_id`가 non-null이면
`FOREIGN KEY (superseded_by_authority_id, subject_family) REFERENCES training_authority_identity(authority_id,
subject_family) ON DELETE RESTRICT`가 같은 family를 관계적으로 강제한다. `UNIQUE(authority_id, subject_version)`이
same-version duplicate/different-payload conflict를 차단한다. event fingerprint는 event ID와 `recorded_at`을 제외한 모든
event field의 canonical projection을 결속한다. event row는 INSERT-only이고 UPDATE·DELETE 권한은 어느 runtime role에도 없다.

`producer_role`은 PostgreSQL login role name이나 display name이 아닌 durable domain identifier다. v1 closed set은 exact
`training_authority_producer` 하나다. C1 migration은 restricted event writer function의 EXECUTE를 별도 least-privilege DB
login role에만 GRANT하고 그 function이 caller input 없이 위 literal을 기록하게 한다. 이 GRANT mapping의 owner는 Production
Training Deployment Owner이고 accountable role은 Training Authority Producer Owner다. caller, Host, CLI, API와 intent는 값을
전달할 수 없으며 unknown identifier는 CHECK에서 fail closed한다. equality CHECK의 유일한 literal은 27자 lowercase ASCII
`[a-z_]+` slug이므로 길이·grammar·closed-set을 하나의 constraint로 동시에 고정한다.

| Persisted identifier | Accountable role | May write event families | Forbidden families/actions | DB role mapping owner |
|---|---|---|---|---|
| `training_authority_producer` | Training Authority Producer Owner | config, readiness, DatasetVersion, DatasetManifest, pair, decision, issuer, approver의 published/activated/revoked/superseded event | journal/reconciliation row, migration·backup·secret/process event, UPDATE/DELETE, caller-selected family/key | Production Training Deployment Owner의 C1 GRANT |

Migration, Backup/Restore, Reconciliation, Process, Deployment와 Secret Provisioning Owner는 runtime authority event producer가
아니므로 v1 persisted identifier set에 포함하지 않는다. reconciliation closure는 별도 append-only table의 approver role
field이며 `training_authority_event.producer_role`을 재사용하지 않는다.

`training_authority_current`의 exact schema는 다음과 같다.

| field | exact PostgreSQL type / constraint |
|---|---|
| `authority_id` | `uuid PRIMARY KEY REFERENCES training_authority_identity(authority_id) ON DELETE RESTRICT` |
| `subject_family` | closed `text NOT NULL`; identity와 composite FK |
| `stream_head_event_id` | `uuid NOT NULL REFERENCES training_authority_event(event_id) ON DELETE RESTRICT` |
| `current_event_id` | `uuid NULL REFERENCES training_authority_event(event_id) ON DELETE RESTRICT`; 아직 효력 있는 event가 없을 때만 NULL |
| `current_subject_version` | `bigint NOT NULL CHECK (current_subject_version >= 1)`; recorded stream head version |
| `state` | `text NOT NULL CHECK` exact `scheduled`, `current`, `expired`, `revoked`, `superseded` |
| `state_effective_at` | `timestamptz NOT NULL`; 아래 state별 단일 산식 |
| `superseded_by_authority_id` | `uuid NULL`; `superseded`에서만 NOT NULL; identity의 `(authority_id, subject_family)`에 composite FK |
| `valid_from` | `timestamptz NOT NULL`; immutable family row와 exact equality |
| `valid_until` | `timestamptz NULL`; immutable family row와 exact equality |
| `projection_version` | `bigint NOT NULL CHECK (projection_version >= 1)`; stream head version과 exact equality |
| `projected_at` | `timestamptz NOT NULL DEFAULT transaction_timestamp()` |

`unavailable`과 `invalid`은 projection state가 아니라 resolver control outcome이다. `scheduled`는 authority row가 존재하지만
DB clock `as_of`에 효력이 시작되지 않았다는 source state다. projection의 event ID는 반드시 같은 `authority_id`의 event여야
하며 restricted writer function이 이를 검증한다. `state='scheduled'`이면 `current_event_id`와
`superseded_by_authority_id`가 NULL이고, 그 외 state는 `current_event_id`가 NOT NULL이다. superseded target은
`state='superseded'`일 때만 NOT NULL이다. `state_effective_at`은 모든 state에서 NOT NULL이다.

subject version은 **recorded order authority**이며 effective time과 별개다. 첫 event는 version 1 `published`이고 이후 insert는
expected stream-head version + 1만 허용한다. recorded-order legal graph는
`published -> activated | revoked | superseded`, `activated -> revoked | superseded`뿐이며 revoked/superseded 뒤 successor는
없다. `expired`는 event kind가 아니라 immutable `valid_until <= as_of`에서 파생되는 terminal source state다. family의 `valid_from`이
publication 즉시 current를 허용하면 version 1 `published`를 effective-state 계산에서 `current`로 해석할 수 있지만 별도
`activated` event를 합성하지 않는다.

effective-state order는 `(effective_at ASC, subject_version ASC)`이다. 동일 effective time에는 더 큰 subject version이
후속이다. future event를 append하면 stream head/projection version은 전진하지만 `effective_at > transaction_timestamp()`인
event로 `current_event_id`나 current state를 즉시 덮지 않는다. delayed past-effective event는 전체 effective-order graph를
재검증한 뒤 그 순서의 deterministic state를 projection한다. overlap, impossible transition 또는 terminal 뒤 event는 insert
transaction 자체를 거부한다. retroactive event는 이미 소비된 approval/capability를 복원하거나 backend를 재실행하지 않는다.
`effective_at >= valid_until`인 새 event와 이미 DB clock상 expired인 subject의 새 event는 거부한다.

projection은 DB `transaction_timestamp()`을 `as_of`로 사용하고 다음 precedence와 산식으로만 계산한다. state-start event는
`published` 또는 그 다음 `activated`이며 `start_at = greatest(valid_from, event.effective_at)`이다. effective-order상 가장
뒤의 eligible state-start event가 winning start event다. terminal event는 그 authority stream의 `revoked` 또는 `superseded`다.

| Projection state | Winning event/source | `state_effective_at` formula | Required event/field | Null allowed | Rebuild rule |
|---|---|---|---|---|---|
| `scheduled` | 아직 `start_at <= as_of`인 state-start event가 없음 | eligible future state-start event들의 `min(start_at)` | future published/activated event와 `valid_from` | no | earliest future start를 보존; future terminal은 current를 조기 덮지 않음 |
| `current` | `start_at <= as_of`인 effective-order상 마지막 published/activated event | `greatest(valid_from, winning_event.effective_at)` | winning event | no | 더 늦은 effective terminal과 expiry가 없을 때만 |
| `expired` | effective terminal event 없이 `valid_until <= as_of` | immutable row `valid_until` | non-null `valid_until` | no | expiry는 event를 합성하지 않음 |
| `revoked` | `effective_at <= as_of`인 winning revoked event | `winning_event.effective_at` | revoked event | no | writer가 `effective_at < valid_until`을 강제한 eligible explicit terminal이 expiry보다 우선 |
| `superseded` | `effective_at <= as_of`인 winning superseded event | `winning_event.effective_at` | superseded event와 target | no | writer가 `effective_at < valid_until`을 강제한 eligible explicit terminal이 expiry보다 우선 |

writer는 terminal event의 `effective_at`이 computed first `start_at`보다 이르지 않도록 강제한다. 같은 effective time의 두
terminal event는 subject version tie-breaker로 두 번째가 terminal successor가 되므로 전체 transaction을 conflict로 거부한다.
terminal이 `valid_until` 이상인 persisted history, state와 위 산식의 timestamp가 일치하지 않는 row 또는 scheduled row에
eligible future start가 없는 경우는 corrupt/impossible이다.

event insert와 expected-version projection CAS는 하나의 transaction이다. 시간이 future boundary를 통과한 경우 Producer
role의 restricted refresh function만 event stream을 DB `transaction_timestamp()` 기준으로 재계산해 같은 stream-head CAS로
projection을 갱신한다. resolver는 use-time read-only transaction에서 같은 계산으로 projection을 검증하며 stale projection은
fail closed하고 직접 repair하지 않는다. 동일 event stream의 rebuild 결과는 항상 같아야 한다. version gap, event/projection
불일치, impossible successor, checksum/FK/schema 손상은 해당 subject와 process preflight를 fail closed한다.

supersession event의 `authority_id`는 **기존 subject**, `superseded_by_authority_id`는 **replacement subject**다. 두 subject는
위 composite FK로 같은 family이고 각각 family-specific immutable row가 존재해야 한다. writer는 source가 event effective
time에 current이고 revoked/expired/superseded가 아니며 target이 같은 시각에 published/current-eligible인지 확인한다.
self-supersession, cross-family target, terminal source, target의 missing/corrupt projection과 recursive
`superseded_by_authority_id` chain에서 source로 돌아오는 cycle을 거부한다. source stream expected-version lock과 target
projection row lock을 한 transaction에서 획득한다. 같은 source/effective time의 concurrent supersession은 하나의 event만
CAS에 성공하고 나머지는 conflict이며 idempotent success나 alternate target 선택이 아니다.

adapter는 unknown field, duplicate key, type coercion, checksum mismatch, future schema, not-yet-effective, expired, revoked와
superseded record를 거부한다. prerequisite read는 명시적 `REPEATABLE READ` transaction 하나에서 수행하며 caller timestamp나
payload를 신뢰하지 않는다.

### 2.1 Authority family와 database role

| Record family | Stable key/reference | Immutable payload/binding | Event/current key | CAS | Producer role | Reader role |
|---|---|---|---|---|---|---|
| config | UUID / `config:<id>` | exact YAML, config kind/schema | family+UUID | projection version | Training Authority Producer | Production Training Resolver |
| readiness | UUID / `readiness:<id>` | manifest, pair/config/source/evaluated binding | family+UUID | projection version | Training Authority Producer | Production Training Resolver |
| DatasetVersion | UUID / `dataset-version:<id>` | Common canonical JSON/object ID | family+UUID | projection version | Training Authority Producer | Production Training Resolver |
| DatasetManifest | UUID / `dataset-manifest:<id>` | Common canonical JSON/object ID | family+UUID | projection version | Training Authority Producer | Production Training Resolver |
| Dataset pair | UUID / `dataset-pair:<id>` | two IDs, pair fingerprint, scenario | family+UUID | projection version | Training Authority Producer | Production Training Resolver |
| business decision | UUID / `decision:<id>` | exact seven fields and validity | family+UUID | projection version | Training Authority Producer | Production Training Decision Resolver |
| issuer registry | UUID PK + immutable UNIQUE `issuer_id` | identity, adapter kind, active interval | issuer+UUID | projection version | Training Authority Producer | Production Training Decision Resolver |
| approver registry | UUID PK + immutable UNIQUE `approver_reference` | identity, active interval | approver+UUID | projection version | Training Authority Producer | Production Training Decision Resolver |
| currentness event | event UUID | subject/version/effect/evidence | family+subject | expected version | Training Authority Producer | both resolvers |

Producer DB role만 immutable row와 event를 INSERT하고 projection CAS를 실행한다. Resolver DB role은 authority/projection
read-only, Journal DB role은 restricted journal claim/transition function만 실행한다. Host/caller/CLI/runtime role은 authority

issuer table은 `authority_id uuid PRIMARY KEY`와 `issuer_id varchar(256) NOT NULL UNIQUE`, approver table은
`authority_id uuid PRIMARY KEY`와 `approver_reference varchar(256) NOT NULL UNIQUE`를 사용한다. rename/key mutation은 없다.
decision relation은 `issuer_authority_id`+`issuer_id`, `approver_authority_id`+`approver_reference`를 integrity-only binding으로
보유하고 각 registry의 `UNIQUE(authority_id, issuer_id)`와 `UNIQUE(authority_id, approver_reference)`에 composite FK를 둔다.
이 binding column은 일곱-field decision
projection을 늘리는 외부 field가 아니다. UUID와 opaque key가 서로 다른 row를 가리키는 decision insert는 거부한다.
row/event/projection을 직접 생성·변경·삭제할 수 없고 unrestricted table UPDATE 권한을 갖지 않는다.

### 3. Config authority

[확정] `training_config_authority`는 공통 envelope 외에 `config_kind = 'full_pretraining'`과
`config_schema_version = 1`을 갖는다. `payload_bytes`는 UTF-8, BOM 없음, duplicate YAML key 없음인 exact YAML source다.
fingerprint는 existing `file_checksum(config_path)`와 같아지도록 exact bytes에 `sha256_bytes()`를 적용한다. schema는 existing
`FullPretrainingConfig.from_yaml()`이 exact type·required field·value를 검증하고 `to_dict()`가 만드는 snapshot으로 고정한다.
unknown field, YAML alias/custom tag, environment substitution과 type coercion은 허용하지 않는다.

[확정] adapter는 DB bytes를 process마다 새로 만든 private directory의 `config.yaml`에 exclusive create하고 flush/fsync한 뒤
absolute `Path`를 만든다. directory는 caller가 지정할 수 없고 OS temporary-directory API로 생성하며 symlink/reparse point,
pre-existing file, `..`, backslash와 final-handle containment 불일치를 차단한다. materialized file은 read-only로 바꾸고 resolve와
backend revalidation 사이 checksum·parsed snapshot을 다시 확인한 뒤 request 종료 시 삭제한다. reference, expected fingerprint,
`source_commit` 중 하나라도 현재 clean checkout과 다르면 fail closed한다. DB source bytes가 authority이며 temporary path는
authority나 audit identity가 아니다.

### 4. Readiness evidence authority

[확정] `training_readiness_authority`는 existing Full Pretraining approval manifest의 exact UTF-8 YAML bytes를 공통 envelope에
저장하고 다음 typed columns를 추가한다.

| field | constraint |
|---|---|
| `dataset_pair_fingerprint` | fingerprint pattern |
| `config_fingerprint` | fingerprint pattern |
| `source_commit` | 공통 envelope와 동일 값 |
| `evaluated_at` | timestamptz, non-null |
| `valid_until` | timestamptz, non-null, `evaluated_at < valid_until` |
| `readiness_result` | exact `READY` |

producer는 별도 승인된 readiness workflow이며 Host/caller/adapter가 evidence를 생성하거나 보정하지 않는다. adapter는 config와
같은 process-private 규칙으로 `manifest.yaml`을 materialize하고 existing `_load_manifest()` 및
`inspect_full_pretraining_readiness(config_path, manifest_path)`를 실행한다. 저장된 typed columns, 새 report의
`readiness_fingerprint`, DB clock 기준 expiry, Dataset pair, config와 current clean source checkout이 모두 일치해야 한다.
`READY` 이외 record는 보존할 수 있지만 production resolver 결과가 될 수 없다.

### 5. Dataset authority와 permission 생산

[확정] `dataset_version_authority`와 `dataset_manifest_authority`는 ADR-015와 pinned Common package가 검증한 각 canonical JSON
bytes를 공통 envelope로 저장한다. 각 row의 `common_object_id`는 payload의 `object_id`와 exact 일치하며 unique다.
`dataset_pair_authority`는 UUID primary key와 `dataset-pair:<id>` reference를 갖는 immutable join record다. 다음 tuple은
별도 unique binding이다.

```text
(dataset_version_authority_id, dataset_manifest_authority_id,
 pair_fingerprint, publication_scenario)
```

두 authority ID는 foreign key, pair fingerprint는 fingerprint pattern, `publication_scenario`는 ADR-015가 승인한 non-empty
closed value여야 한다. `created_at`은 공통 envelope provenance이며 identity key가 아니다.

두 Host reference는 같은 join row를 가리켜야 하며 expected pair fingerprint와 일치해야 한다. adapter는 한 snapshot에서 두
payload를 읽고 Common runtime verification, ADR-015 pair validation과 current authority event를 확인한다. 이어 authority에
저장된 upstream provenance·split·artifact reference만으로 existing `evaluate_dataset_training_entry()`를 호출해 exact
`DatasetTrainingPermission`을 만든다. permission을 DB에 직렬화·복원하지 않으며 caller가 payload, local path 또는 permission을
공급할 수 없다. raw Dataset content와 artifact accessibility 검사는 C2가 아니라 별도 Activation preflight 범위다.

### 6. Business decision authority

[확정] 별도 승인 workflow가 `training_execution_decision_authority`에 decision을 append한다. Host, adapter, issuer와 caller는
business decision을 생성하거나 기본값으로 대체하지 않는다. record는 공통 envelope와 아래 exact seven-field projection을
갖는다.

| field | constraint / authority |
|---|---|
| `decision` | semantic `APPROVED` 또는 `DENIED`; 저장값은 actual enum과 동일한 `approved | denied` |
| `authorization_id` | opaque reference grammar, globally unique; approval workflow |
| `issuer_id` | `training_issuer_registry.issuer_id`; registry |
| `approver_reference` | non-empty opaque reference; approval workflow |
| `evidence_reference` | exact `decision:<id>`; decision row identity |
| `request_fingerprint` | canonical request builder fingerprint; workflow exact echo |
| `issued_at` | canonical aware timestamp; DB transaction time |

decision row는 non-null `valid_from`, `valid_until`과 `valid_from <= issued_at < valid_until`을 요구한다. request fingerprint는
existing canonical request builder 결과를 exact echo하며 source가 별도 hash를 만들지 않는다. `authorization_id`는 unique,
issuer/approver는 registry의 referential predicate, evidence는 exact decision row identity여야 한다. `DENIED`도 동일한
authoritative provenance와 currentness를 가진다.

`prerequisite_resolution_policy_reference`의 producer는 ADR-020 `TrustedPrerequisiteProvenance.resolution_policy_reference`를
발행한 construction-bound prerequisite resolver다. prerequisite resolve가 성공하면 request build와 journal claim 전에 이미
알려지며 caller가 제공하지 않는다. `decision_policy_reference`의 producer는 actual
`TrustedDecisionResolution.provenance.policy_reference`를 발행한 construction-bound decision resolver다. 이 값은 journal
claim 뒤 decision resolve에서 처음 알려지고, authorization/evidence fingerprint 및 decision provenance와 함께
`decision_submitted` transition에서 기록한다. Host/C2 adapter는 provenance의 exact 값을 전달할 뿐 생성·정규화하지 않는다.
missing/malformed/mismatch/stale prerequisite policy는 `TRAINING_HOST_PREREQUISITE_INVALID` 또는 source 접근 불가 시
`TRAINING_HOST_PREREQUISITE_UNAVAILABLE`, decision policy는 `TRAINING_EXECUTION_DECISION_INVALID`로 fail closed한다.
placeholder, synthetic policy와 한 policy를 다른 policy의 fallback으로 쓰는 행위는 금지한다.
두 policy reference는 resolver provenance/journal evidence이며 ADR-017·019의 external decision submission 일곱 field를
추가하거나 변경하지 않는다.

`training_issuer_registry`와 `training_approver_registry`의 identity row는 각각 opaque identity, `active_from`,
`active_until`, `schema_version`을 가진 immutable row다. issuer registry의 `adapter_kind` v1 값은
`same_process_training_execution_issuer`다. identity row에 mutable `revoked_at`을 두지 않으며 revoke/supersede는 공통
authority event/projection만 사용한다. resolver는 use-time 직전 DB clock 기준 두 registry active interval, decision
effective/expiry, revoke/supersede, evidence와 exact request binding을 다시 검증한다.

[확정] `UNAVAILABLE`은 persisted enum/value/row가 아니다. canonical request fingerprint에 claim 가능한 current decision
record가 없거나 authoritative record를 안전하게 얻지 못하는 control outcome이다. missing, not-yet-effective, expired,
revoked와 inaccessible record는 sanitized `TRAINING_EXECUTION_DECISION_UNAVAILABLE`로 끝난다. malformed scalar,
checksum/FK/schema/event/projection corruption과 request mismatch는 `TRAINING_EXECUTION_DECISION_INVALID`로 끝난다.
UNAVAILABLE row, placeholder authorization과 synthetic DENIED를 생성하지 않으며 DecisionSource submit/claim, bridge replay
record, approval과 backend entry는 0이다. ADR-018의 private unavailable control exception과 실제 approved/denied enum을
변경하지 않는다.

[확정] resolved seven-field value는 기존 same-process DecisionSource에 exact 한 번 submit되고 process-local claim 뒤 issuer
adapter로 전달된다. restart 뒤 DB decision을 다시 읽는 것은 새 orchestration attempt와 새 canonical request decision을
필요로 하며 이전 process의 claim, approval 또는 capability를 복원하지 않는다.

### 7. Durable journal schema와 concurrency

[확정] `training_execution_journal`은 current lifecycle projection이다. 아래 표의 `NO DEFAULT`는 restricted claim/transition
function이 값을 명시해야 한다는 뜻이다. fingerprint CHECK는 exact `sha256:` + lowercase hex 64, opaque reference CHECK는
Host grammar와 whitespace-only 금지를 뜻한다.

| column | exact PostgreSQL type / nullability / default | first write | later update | key/check와 보존 의미 |
|---|---|---|---|---|
| `run_id` | `varchar(256) NOT NULL`, NO DEFAULT | claim | 금지 | `PRIMARY KEY`, Host reference pattern; 실행 identity |
| `request_fingerprint` | `char(71) NOT NULL`, NO DEFAULT | claim | 금지 | fingerprint CHECK, `UNIQUE(run_id, request_fingerprint)` |
| `intent_fingerprint` | `char(71) NOT NULL`, NO DEFAULT | claim | 금지 | fingerprint CHECK |
| `host_schema_version` | `smallint NOT NULL DEFAULT 1` | claim | 금지 | `CHECK (= 1)` |
| `host_lifecycle_version` | `smallint NOT NULL DEFAULT 1` | claim | 금지 | `CHECK (= 1)` |
| `orchestration_correlation_id` | `varchar(256) NOT NULL`, NO DEFAULT | claim | 금지 | opaque reference CHECK, `UNIQUE` |
| `dataset_version_id` | `varchar(256) NOT NULL`, NO DEFAULT | claim | 금지 | non-empty Common object ID |
| `dataset_manifest_id` | `varchar(256) NOT NULL`, NO DEFAULT | claim | 금지 | non-empty Common object ID |
| `dataset_pair_fingerprint` | `char(71) NOT NULL`, NO DEFAULT | claim | 금지 | fingerprint CHECK |
| `config_fingerprint` | `char(71) NOT NULL`, NO DEFAULT | claim | 금지 | fingerprint CHECK |
| `readiness_fingerprint` | `char(71) NOT NULL`, NO DEFAULT | claim | 금지 | fingerprint CHECK |
| `source_commit` | `char(40) NOT NULL`, NO DEFAULT | claim | 금지 | lowercase Git SHA-1 CHECK |
| `prerequisite_resolution_policy_reference` | `varchar(256) NOT NULL`, NO DEFAULT | claim | 금지 | prerequisite provenance exact echo, opaque reference CHECK |
| `authorization_id` | `varchar(256) NULL`, DEFAULT NULL | `decision_submitted` | 이후 금지 | opaque reference CHECK; decision bundle all-or-none |
| `issuer_id` | `varchar(256) NULL`, DEFAULT NULL | `decision_submitted` | 이후 금지 | issuer registry FK; bundle all-or-none |
| `approver_reference` | `varchar(256) NULL`, DEFAULT NULL | `decision_submitted` | 이후 금지 | approver registry FK; bundle all-or-none |
| `evidence_reference` | `varchar(256) NULL`, DEFAULT NULL | `decision_submitted` | 이후 금지 | exact `decision:<uuid>` CHECK/FK; bundle all-or-none |
| `authorization_fingerprint` | `char(71) NULL`, DEFAULT NULL | `decision_submitted` | 이후 금지 | fingerprint CHECK; bundle all-or-none |
| `decision_evidence_fingerprint` | `char(71) NULL`, DEFAULT NULL | `decision_submitted` | 이후 금지 | fingerprint CHECK; bundle all-or-none |
| `decision_policy_reference` | `varchar(256) NULL`, DEFAULT NULL | `decision_submitted` | 이후 금지 | decision provenance exact echo, opaque reference CHECK; bundle all-or-none |
| `phase` | `text NOT NULL DEFAULT 'claimed'` | claim | restricted transition만 | closed actual `TrainingOrchestrationPhase` CHECK |
| `journal_version` | `bigint NOT NULL DEFAULT 1` | claim | 매 legal transition | `CHECK (>= 1)`, exact +1 |
| `backend_entered` | `boolean NOT NULL DEFAULT false` | claim | entry/terminal transition | phase/event invariant |
| `reconciliation_required` | `boolean NOT NULL DEFAULT false` | claim | manual transition | `phase = 'manual_reconciliation_required'`와 exact 동치 |
| `reconciliation_reason_code` | `varchar(128) NULL`, DEFAULT NULL | manual transition | 금지 | uppercase reason CHECK; manual에서만 NOT NULL |
| `process_boundary_id` | `varchar(256) NOT NULL`, NO DEFAULT | claim | 각 transition에서 current process 값으로 갱신 | opaque process-start identity; user/host/credential 아님 |
| `created_at` | `timestamptz NOT NULL DEFAULT transaction_timestamp()` | claim | 금지 | 최초 DB transaction clock |
| `updated_at` | `timestamptz NOT NULL DEFAULT transaction_timestamp()` | claim | 각 transition | 해당 transition의 DB transaction clock |

identity/binding columns와 `created_at`은 claim 뒤 immutable하다. decision bundle 일곱 field(`authorization_id`, `issuer_id`,
`approver_reference`, `evidence_reference`, 두 fingerprint, `decision_policy_reference`)는 모두 NULL이거나 모두 NOT NULL인
row CHECK를 갖고, NULL→NOT NULL은 `decision_submitted` restricted transition 한 번뿐이다. 이후 NULL 복귀·교체는 금지한다.
`process_boundary_id`, lifecycle projection, version과 `updated_at`만 legal transition에서 갱신할 수 있다. 두 timestamp는
timezone-aware PostgreSQL value이고 caller/app clock을 받지 않는다. table은 자동 삭제하지 않으며 retention은 9절을 따른다.
같은 live attempt의 normal transition은 claim event의 process boundary를 유지한다. restart된 새 process는 active lifecycle을
정상 phase로 계속 진행하지 않고 새 boundary를 기록한 manual-reconciliation transition만 요청할 수 있다.

phase row CHECK와 restricted transition invariant는 다음과 같다. `failed`와 manual phase는 어느 predecessor에서 왔는지에 따라
decision bundle/backend flag를 보존하므로 history-dependent 조건은 phase-event와 restricted function이 강제한다.

| Phase | decision bundle | `backend_entered` | reconciliation | journal/event reason | Terminal |
|---|---|---:|---:|---|---:|
| `claimed` | 모두 NULL | false | false | NULL | no |
| `resolved` | 모두 NULL | false | false | NULL | no |
| `validated` | 모두 NULL | false | false | NULL | no |
| `decision_submitted` | 모두 NOT NULL | false | false | NULL | no |
| `approval_consumed` | 모두 NOT NULL | false | false | NULL | no |
| `backend_entered` | 모두 NOT NULL | true | false | NULL | no |
| `completed` | 모두 NOT NULL | true | false | NULL | yes |
| `failed` | predecessor의 bundle/flag 보존 | predecessor의 값 | false | journal NULL / event NOT NULL | yes |
| `manual_reconciliation_required` | predecessor의 bundle/flag 보존 | predecessor의 값 | true | journal/event 모두 NOT NULL | yes |

`succeeded`는 실제 enum이 아니므로 저장하지 않고 성공 terminal은 `completed`다. DB row CHECK는 bundle all-or-none,
normal-phase reason NULL, terminal/manual boolean 관계와 명백한 flag 조합을 강제한다. predecessor 보존, phase regression/skip,
terminal overwrite와 exact +1은 cross-row 조건이므로 아래 restricted function만 강제한다. unrestricted UPDATE 권한은 없다.
구체적으로 `claimed|resolved|validated`는 decision bundle 전체 NULL,
`decision_submitted|approval_consumed|backend_entered|completed`는 전체 NOT NULL이다.
`backend_entered|completed`는 `backend_entered=true`, 그 전 normal phase는 false다.
`reconciliation_required = (phase='manual_reconciliation_required')`이고
`reconciliation_reason_code IS NOT NULL`도 같은 predicate와 exact 동치다. `failed`/manual의 predecessor bundle과
backend flag 보존은 restricted function이 직전 event와 비교한다.

#### Append-only phase event exact schema

| column | exact PostgreSQL type / nullability / default | constraint와 의미 |
|---|---|---|
| `event_id` | `uuid NOT NULL`, NO DEFAULT | `PRIMARY KEY`; function-generated UUID |
| `run_id` | `varchar(256) NOT NULL`, NO DEFAULT | journal `run_id`에 `ON DELETE RESTRICT` FK |
| `request_fingerprint` | `char(71) NOT NULL`, NO DEFAULT | fingerprint CHECK; journal과 composite FK |
| `journal_version` | `bigint NOT NULL`, NO DEFAULT | `CHECK (>= 1)`, `UNIQUE(run_id, journal_version)` |
| `from_phase` | `text NULL`, DEFAULT NULL | version 1 claim event에서만 NULL; 그 외 closed phase NOT NULL |
| `to_phase` | `text NOT NULL`, NO DEFAULT | closed actual phase CHECK |
| `process_boundary_id` | `varchar(256) NOT NULL`, NO DEFAULT | transition을 수행한 opaque process-start identity |
| `reason_code` | `varchar(128) NULL`, DEFAULT NULL | uppercase CHECK; `failed`/manual destination에서만 NOT NULL |
| `event_at` | `timestamptz NOT NULL DEFAULT transaction_timestamp()` | phase가 실제로 durable해진 DB transaction time |
| `recorded_at` | `timestamptz NOT NULL DEFAULT transaction_timestamp()` | event insert DB time; v1에서는 `event_at = recorded_at` CHECK |

`FOREIGN KEY (run_id, request_fingerprint)`는 journal의 같은 UNIQUE pair를 `ON DELETE RESTRICT`로 참조한다. claim function은
journal version 1과 `(from_phase=NULL, to_phase='claimed', journal_version=1)` event를 같은 transaction에 insert한다. 이후
transition function은 journal의 current version N/phase를 lock/CAS하고 `(from_phase=current phase, to_phase=next phase,
journal_version=N+1)` event를 insert한 뒤 journal을 같은 N+1로 갱신한다. 마지막 event의 destination/version/request
fingerprint/process boundary는 commit되는 journal projection과 exact 일치해야 한다.

event row CHECK는 정확히 version 1이면 `from_phase IS NULL`, `to_phase='claimed'`, `reason_code IS NULL`을 요구하고,
version > 1이면 `from_phase IS NOT NULL`을 요구한다. `to_phase IN ('failed','manual_reconciliation_required')`와
`reason_code IS NOT NULL`은 exact 동치이고 다른 destination에서는 reason이 NULL이다. `event_at = recorded_at`이며 두 값은
caller 입력을 받지 않는다.

일반 CHECK만으로 event contiguity를 주장하지 않는다. restricted claim/transition function이 previous event N의 존재,
N+1, legal edge, same request와 same transaction projection을 검증한다. unique conflict, gap, duplicate/different payload,
projection mismatch는 transaction rollback과 sanitized conflict다. event role은 INSERT만 가능하고 UPDATE·DELETE 권한이 없다.
terminal event 뒤 successor도 없다.

#### ADR-019 durable evidence mapping

| ADR-019 evidence | Journal column/event | Type/nullability | First write | Immutable/update rule |
|---|---|---|---|---|
| Host lifecycle/schema | `host_lifecycle_version`, `host_schema_version` | `smallint NOT NULL = 1` | claim | immutable |
| orchestration correlation | `orchestration_correlation_id` | `varchar(256) NOT NULL UNIQUE` | claim | immutable |
| run/request/intent | `run_id`, request/intent fingerprints | NOT NULL exact grammar | claim | immutable |
| Dataset pair | two IDs + `dataset_pair_fingerprint` | NOT NULL exact ID/fingerprint | claim | immutable |
| config/readiness | two fingerprint columns | `char(71) NOT NULL` | claim | immutable |
| source provenance | `source_commit` | `char(40) NOT NULL` | claim | immutable |
| prerequisite policy provenance | `prerequisite_resolution_policy_reference` | `varchar(256) NOT NULL` | claim | resolver exact echo, immutable |
| decision provenance | seven-field journal bundle including `decision_policy_reference` | 모두 NULL until submit, 이후 모두 NOT NULL | decision submission | bundle one-time write |
| bootstrap/claim | journal `claimed`, phase event version 1 | closed phase/event, NOT NULL except `from_phase` | claim | append-only |
| resolve/validate/submit/consume/entry/terminal | `phase`, `journal_version`, one event per transition | current projection + append-only events | each transition | expected-phase/version CAS |
| each phase timestamp | phase event `event_at`/`recorded_at` | `timestamptz NOT NULL` | each transition | immutable |
| process/restart boundary | journal/event `process_boundary_id` | `varchar(256) NOT NULL` | claim and every transition | event immutable; projection advances |
| backend entry | `backend_entered` + phase event | `boolean NOT NULL` | claim, becomes true at entry | never true→false |
| terminal outcome/reason | terminal phase + reason | closed phase; failed/manual reason NOT NULL | terminal | terminal immutable |
| manual reconciliation | phase/boolean/reason + event | exact phase equivalence | manual transition | terminal immutable |

따라서 ADR-019의 `bootstrap` durable evidence는 ADR-021의 `claimed` projection과 version 1 claim event에 정확히 대응한다.
main journal phase/version은 항상 마지막 event와 일치하고 phase별 timestamp와 restart boundary는 event history가 보존한다.

approval/capability/token, DecisionSource·adapter object, raw config/readiness/Dataset/decision payload, raw exception/stack trace,
absolute path, DSN과 credential은 두 journal table에 저장하지 않는다.

[확정] claim은 `run_id` primary key를 actual `ON CONFLICT` arbiter로 사용한다. `INSERT ... ON CONFLICT DO NOTHING
RETURNING`이 row를 반환하면 acquired다. 반환하지 않으면 같은 `READ COMMITTED` transaction에서 primary key로 existing row를
읽고 immutable binding을 비교한다. 같은 run/fingerprint의 terminal result만 read-only terminal replay이며, 다른 fingerprint,
active/manual row 또는 binding mismatch는 deterministic conflict다.

transition은 restricted DB function 안에서
`UPDATE ... WHERE run_id = ? AND request_fingerprint = ? AND phase = ? AND journal_version = ? RETURNING ...` CAS와 phase event insert를
한 transaction으로 수행한다. 이 predicate의 `phase`와 `journal_version`은 caller가 읽은 exact expected phase와 expected
version이다.
affected row 0은 re-read하여 terminal conflict, stale phase/version 또는 unavailable로 mapping한다.
unrestricted direct UPDATE 권한, lossy upsert, last-write-wins, advisory/filesystem/in-memory lock을 권한 근거로 쓰지 않는다.

[확정] legal phase graph는 ADR-019·020의
`claimed -> resolved -> validated -> decision_submitted -> approval_consumed -> backend_entered -> completed`가 success path다.
`claimed`부터 `backend_entered`까지 각 non-terminal phase는 `failed` 또는 `manual_reconciliation_required`로만 terminal 전이할
수 있다. 실제 foundation enum의 legal graph와 동일하다.
terminal overwrite, phase skip, backward transition과 deletion은 DB constraint와 restricted transition function으로 차단한다.
immutable binding update, phase event gap, impossible flag 조합도 거부한다. `approval_consumed`는
`backend_entered=false`, `backend_entered`·`completed`는 true이고 `reconciliation_required=true` iff manual phase다. consumed 또는
entered 결과가 불명확하면 automatic retry 없이 `MANUAL_RECONCILIATION_REQUIRED`를 새 version으로 기록한다. 이 phase는
terminal이며 Training Reconciliation Approver가 closure evidence를 검토해 새 run과 새 decision을 허용하기 전 재실행할 수 없다.

### 8. transaction, restart와 corruption

[확정] authority snapshot read와 journal CAS는 같은 database를 쓰지만 approval consume와 Training side effect를 하나의 DB
transaction으로 묶었다고 주장하지 않는다. process loss 위치에 따라 다음처럼 처리한다.

- `decision_submitted` 이하: 기존 process-local authority는 복구하지 않고 record를 active conflict로 유지한다.
- `approval_consumed` 또는 `backend_entered`: startup reconciliation이 자동 실행하지 않고
  `manual_reconciliation_required` 후보로 보고한다.
- `completed`/`failed`: exact run/fingerprint terminal evidence만 읽고 side effect를 재수행하지 않는다.

[확정] startup reconciliation은 read-only scan과 redacted report 생성만 한다. 자동 phase 변경, decision resubmit,
approval/capability reconstruction과 backend retry는 금지한다. checksum, foreign key, phase/version, schema version 또는 canonical
payload가 손상되면 해당 request와 process preflight를 fail closed하고 자동 repair하지 않는다.

#### Isolation, use-time currentness와 failure mapping

[확정] prerequisite authority resolution은 request build 전 명시적으로 시작한 read-only `REPEATABLE READ` transaction에서
수행하고 immutable request binding material을 확정한 뒤 종료한다. journal claim은 별도 `READ COMMITTED` transaction이다.
두 transaction은 원자적이지 않다. decision resolve 직전과 DecisionSource submit 직전에 짧은 read-only transaction으로
referenced authority, decision, issuer와 approver의 use-time currentness를 다시 검증한다. 재검증 뒤 revoke와 process-local
submit/consume 사이에도 잔여 race가 있으며 distributed revocation 또는 exactly-once로 표현하지 않는다.

| Failure point | Statement sent | Commit requested | Commit acknowledged | Durable outcome | Retry DB op | Retry authority/backend | Required handling |
|---|---:|---:|---:|---|---|---|---|
| connection loss before statement send | no | no | no | mutation 0 proven | 아래 DB-only allowlist에서 최대 1회 | 금지 | same immutable input으로 새 transaction |
| statement sent 뒤 commit request 전 loss | yes/unknown | no | no | server가 rollback을 확인한 경우만 known rollback; 아니면 unknown | known rollback+allowlist만 최대 1회 | 금지 | 확인 불가면 re-read/classify, raw mutation 재실행 금지 |
| commit request 뒤 acknowledgement 전 loss | yes | yes | no | pre-ack outcome unknown | 금지 | 금지 | durable re-read는 분류용; 증명 불가면 manual reconciliation |
| successful commit acknowledgement 뒤 loss | yes | yes | yes | committed | 금지 | 금지 | acknowledged DB mutation을 사용하고 같은 mutation 재실행 금지 |
| read-only authority snapshot 중 loss | read only | 해당 없음 | 해당 없음 | mutation 0 | policy-bounded 최대 1회 | submission/consume/backend 금지 | snapshot 전체를 새 transaction으로 다시 읽음 |
| deadlock/serialization, server-confirmed rollback | yes | no/aborted | rollback 확인 | mutation 0 | allowlist transaction 전체 최대 1회 | 금지 | partial statement 재시도 금지, 전체 unit 재시도 |
| decision submission response ambiguity | process-local call 가능 | 해당 없음 | 해당 없음 | submission/claim 여부 unknown | 금지 | 금지 | 새 authorization 생성·resubmit 금지, manual reconciliation |
| approval issue/consume ambiguity | DB 밖 side effect 가능 | 해당 없음 | 해당 없음 | consume 여부 unknown | 금지 | 금지 | approval 복원·재발급 금지, manual reconciliation |
| backend entry/result ambiguity | backend side effect 가능 | 해당 없음 | 해당 없음 | entry/result unknown | 금지 | 금지 | backend 재호출 금지, manual reconciliation |

connection이 끊겼다는 사실만으로 이미 받은 successful commit acknowledgement를 잃은 것으로 재분류하지 않는다. 반대로
acknowledgement를 받지 못한 transaction을 성공 또는 rollback으로 추측하지 않는다. durable re-read는 상태 분류 evidence일 뿐
decision submission, approval issue/consume 또는 backend side effect의 재실행 권한이 아니다.

automatic DB retry allowlist는 다음 세 transaction뿐이며 모두 **server-confirmed rollback 또는 statement 미전송**, 같은
immutable input, 최대 1회 조건을 동시에 요구한다.

1. read-only prerequisite/currentness snapshot 전체
2. decision resolve/submission 전 journal claim transaction
3. decision resolve/submission 전 `claimed -> resolved` 또는 `resolved -> validated` journal transition transaction

`decision_submitted` 진입 및 이후 transition, authority event writer operation, reconciliation closure와 backend result 기록은
automatic retry allowlist 밖이다. 같은 SQL 함수라도 decision submission, approval consume 또는 backend entry가 이미 가능했던
호출 맥락이면 재시도하지 않는다. unique violation은 새 INSERT retry가 아니라 existing row의 replay/conflict 재판정이다.
raw DB/schema/corruption error는 sanitized invalid/unavailable로 mapping하고 SQL, query parameter, DSN, host, credential과 path를
노출하지 않는다.

commit ambiguity 뒤 row를 재-read해도 decision submission, approval issuance/consume 또는 backend entry를 자동 재실행하지
않는다. consume 또는 backend entry 가능성이 있거나 journal transition 결과를 증명할 수 없으면
`MANUAL_RECONCILIATION_REQUIRED`다. manual transition commit도 불명확하면 external success를 반환하지 않는다.
connection pool은 composition construction-owned이고 process/fork 사이에 공유하지 않는다. child/restarted process는 이전
connection과 process boundary ID를 폐기하고 새 pool/preflight를 요구한다. timestamp authority는 DB transaction clock이다.

### 9. accountable operations, retention과 audit

| Role | Owns | May authorize | Must not do | Required evidence | Activation blocker |
|---|---|---|---|---|---|
| Production Training Deployment Owner | approved DB version과 service deployment | rollout/stop | Training approval 생성 | compatibility/preflight | matrix 밖 DB |
| Training Authority Producer Owner | producer workflow, writer role과 exact `training_authority_producer` domain identifier | authority/event append | Host/caller write 허용 또는 다른 persisted producer identifier | provenance/currentness/GRANT tests | producer 또는 mapping 미승인 |
| Training Database Migration Owner | schema, role, migration lock | forward/rollback policy | adapter activation | migration report | partial/unknown schema |
| Training Database Backup/Restore Owner | encrypted backup, PITR, restore drill | restore 수행 제안 | approval 복원 | cadence·RPO/RTO·drill | 수치/drill 미승인 |
| Training Reconciliation Approver | manual case review/closure | 새 run 허용 또는 계속 차단 | approval 복원/자동 backend 실행 | append-only closure evidence | unresolved case |
| Production Training Process Owner | non-CLI bootstrap/shutdown/restart | process lifecycle | caller adapter injection | lifecycle/restart evidence | process contract 미승인 |
| Security/Secret Provisioning Owner | DSN file ACL, rotation/revoke | credential provision/rotation | repo/CLI secret 제공 | ACL/rotation evidence | insecure/missing secret |

role은 stable repository contract이며 개인명, credential 또는 private deployment path가 아니다. 실제 deployment assignment는
Activation evidence에서 기록한다.

[확정] v1 authority, authority event, registry, journal과 reconciliation closure row는 자동 삭제하지 않는다. retention,
archive/deletion 변경은 별도 ADR, migration과 Training Database Backup/Restore Owner 승인이 필요하다. backup cadence와 RPO/RTO
수치, encrypted backup, access control, PITR와 restore drill evidence가 운영 Gate에서 승인되기 전 production activation을
차단한다. restore 뒤 backup 기준시점 이후 event/current projection을 재동기화하고 모든 currentness/revocation을 재검증하기
전 intent intake를 열지 않는다.

[확정] manual reconciliation closure는 approver role, original run, observed phase/version, redacted evidence, disposition과 DB
timestamp를 append-only로 기록한다. closure는 기존 approval/capability를 복원하거나 backend를 자동 실행하지 않으며 새 run과
새 decision만 허용할 수 있다.

[확정] audit는 prerequisite resolution policy reference와 decision policy reference를 이름이 분리된 opaque reference로 보존하고,
그 밖에는 reference, fingerprint, phase, version, reason code, timestamp와 redacted correlation만 포함한다. DSN,
credential, absolute path, raw config/readiness/Dataset/decision payload, approval, capability, exception repr와 stack trace를 log,
error 또는 caller result에 넣지 않는다. durable audit export·SIEM 전송은 이 ADR이 승인하지 않는다.

### 10. secret/configuration contract

[확정] Security/Secret Provisioning Owner는 exact environment name `DOHALM_TRAINING_DATABASE_DSN_FILE`에 protected secret
file의 absolute path만 설정한다. raw DSN environment fallback과 caller/CLI/API DSN/path argument는 금지한다. file은 UTF-8
단일 non-empty PostgreSQL DSN line만 포함하며 production process의 least-privilege reader identity만 읽는다. missing,
relative, unreadable, malformed, symlink/reparse-point substitution, final-handle containment 실패, group/world-readable POSIX mode
또는 Windows explicit ACL 검증 불가 상태는 fail closed한다. path와 DSN은 error/log/audit/repr에서 redaction한다. application은
secret file을 생성·수정하지 않는다.

rotation은 새 credential로 새 connection pool을 construction/preflight한 뒤 process restart/switchover하는 Gate에 결속하며
기존 pool에서 DSN string만 바꾸지 않는다. local/CI credential은 isolated ephemeral fixture이고 production secret과 분리한다.

schema name, server version, reference namespace와 timeout은 runtime override가 없는 v1 constants다. test는 environment나 live
credential을 쓰지 않고 exact storage protocol을 구현한 in-memory fake와 ephemeral PostgreSQL contract suite를 분리한다.
ephemeral suite의 image digest와 driver version은 C1에서 dependency review와 함께 고정해야 하며, 그 승인 전 live adapter
구현은 시작하지 않는다.

### 11. composition lifecycle와 multiprocess ownership

[확정] future non-CLI executable/service boundary는 별도 Composition PR C3에서 exact symbol로 확정한다. 현재 존재하지 않는
`src.training.production_composition`이나 `python -m` entrypoint를 사실로 고정하지 않는다. Production Training Process
Owner가 process당 object graph 하나와 pool, adapters, clock/policy, DecisionSource/issuer와 Host를 construction-owned로
bootstrap한다. module import는 connection, migration, registration, request, approval와 backend side effect가 0이어야 한다.
future explicit startup은 다음 순서만 수행한다.

1. secret/config validation
2. database connect와 server/schema/version/least-privilege preflight
3. read-only corruption/reconciliation scan
4. construction-owned pool, adapter와 exact Host object graph bootstrap
5. 별도 Activation approval이 존재할 때만 intent intake 시작

[확정] 한 process에는 Host object graph 하나만 존재한다. pool/connection은 fork·process·restart 사이 공유하지 않는다.
여러 process는 같은 database CAS를 공유하지만 process-local
DecisionSource, issuer, approval와 capability를 공유·복구하지 않는다. graceful shutdown은 새 intent 수신을 먼저 닫고 bounded
duration을 기다린 뒤 pool을 폐기한다. duration과 timeout disposition은 C3 운영 Gate에서 승인하며 timeout/process loss 뒤
active journal은 startup에서 자동 재개하지 않는다.

### 12. non-activating preflight와 test 전략

[확정] C2/C3는 production activation 없이 다음을 검증하는 package-private preflight만 구현할 수 있다.

- approved server compatibility matrix/schema version, required table/column/constraint와 least-privilege read/CAS 권한
- reference namespace, canonical bytes/checksum, expiry/revoke/supersede와 provenance validation
- prerequisite/decision policy의 별도 producer·write phase·all-or-none binding, exact producer-role literal과 DB GRANT mapping
- 5-state `state_effective_at` 재계산, same-family/cycle-free supersession과 family envelope NOT NULL constraint
- journal claim/conflict/CAS/terminal/manual-reconciliation 및 concurrent single winner
- transaction failure, connection loss와 corrupt row의 sanitized fail-closed behavior
- Host와 fake execution boundary 통합에서 actual Dataset content/model/GPU/backend side effect 0
- source checkout와 built wheel의 private surface, import side effect와 redaction parity

production credential, production data, actual backend, Dataset content, Model, GPU, output과 Training은 test input이 아니다.

## Implementation PR 순서

1. **ADR-021 승인·병합**: 설계만 확정하며 구현·activation 없음.
2. **Schema/Dependency PR C1**: PostgreSQL driver와 migration tool 선택, pinned ephemeral image, v1 schema/migration/roles,
   compatibility matrix, migration lock, bootstrap/upgrade와 rollback-or-forward-only, 두 policy column/phase CHECK,
   exact producer literal/GRANT, state timestamp rebuild와 same-family supersession constraint, family envelope NOT NULL 및
   isolated migration/restore contract tests.
   adapter·production credential·activation 없음.
3. **Adapter PR C2**: production prerequisite/decision/journal adapters, restricted DB operations, non-activating preflight와
   isolated DB contract tests. prerequisite adapter는 exact `resolution_policy_reference`를 claim input으로, decision adapter는
   exact provenance policy를 decision-submitted input으로만 제공한다. caller policy input, fallback과 placeholder는 없다.
   executable·runtime activation 없음.
4. **Composition PR C3**: exact non-CLI process symbol, object graph/pool/bootstrap/shutdown/restart contract와 fake/bounded
   integration. production intent intake와 actual Training은 비활성.
5. **Production Activation Gate**: 별도 운영 증거와 사용자 명시 승인.

C1 전에는 driver/migration implementation을 시작하지 않는다. C2는 C1 독립 검증·병합 뒤, C3는 C2 독립 검증·병합 뒤에만
시작한다. 각 PR은 dependency/schema, adapter, composition과 activation 범위를 겹치지 않는다. authority producer workflow와
writer role은 C2 전 Training Authority Producer Owner가 승인하며 readiness/config mapping fixture도 C2 입력으로 고정한다.

## Production Activation Gate

[확정] ADR 또는 C1/C2/C3 병합은 production activation 승인이 아니다. 다음이 모두 충족되기 전 future actual run
entrypoint, intent intake와 backend invocation은 fail closed한다.

1. ADR-016~021과 C1/C2/C3의 독립 검증·명시 승인·병합
2. approved PostgreSQL compatibility matrix와 current supported minor
3. migration, least-privilege role, backup cadence/RPO/RTO, restore drill과 reconciliation evidence
4. credential provisioning/rotation과 process lifecycle owner assignment
5. bounded non-activating preflight 및 source/wheel parity 통과
6. 실제 Dataset pair/config/readiness/source/output/disk/GPU의 새 request 결속 검증
7. 실행 범위·비용·중단·복구에 대한 별도 사용자 명시 승인

exactly-once Training, cross-process capability, automatic restart/retry와 durable approval persistence는 주장하지 않는다.

## Consequences

- 장점: prerequisite, decision와 journal이 한 transaction-capable authority에 있어 lookup·CAS·recovery 경계가 명확하다.
- 장점: caller와 CLI가 storage, credential, resolver 또는 decision을 선택하지 못한다.
- 장점: process-local approval 의미를 보존하면서 crash ambiguity를 durable manual reconciliation으로 차단한다.
- 비용: PostgreSQL 운영, driver, migration, role, backup과 restore evidence가 C1/C2/C3 순서로 선행돼야 한다.
- 비용: ADR-015 local publication을 authority catalog에 ingest하는 별도 producer workflow가 필요하다.
- 한계: 이 결정만으로 production data 접근, backend 실행, Training 재시도 또는 exactly-once가 가능해지지 않는다.

## Revisit conditions

- deployment topology가 managed cloud secret provider 또는 cross-process/network decision service로 바뀐다.
- compatibility matrix 밖 PostgreSQL major, separate authority databases 또는 external transaction coordinator가 필요해진다.
- Dataset content location, artifact access credential 또는 production scheduler를 결정한다.
- approval consume와 Training side effect를 하나의 transactional system으로 결속한다.
- retention 삭제, durable audit export 또는 automatic reconciliation 요구가 승인된다.

## 승인 Gate

이 ADR의 architecture contract는 독립 검증, 사용자 명시 승인과 PR #126 squash merge로 `approved`다. `approved`는
`implemented`가 아니며 C1/C2/C3 구현, migration, credential 설치, process activation 또는 Training을 승인하지 않는다.
각 구현 PR과 Production Activation Gate는 위 순서대로 별도 독립 검증과 사용자 승인을 받아야 한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-13 | [확정] PR #126 사용자 승인·squash merge provenance에 맞춰 `approved`로 동기화하고 C1 image security policy를 ADR-022로 분리 |
| 2026-08-13 | [제안] 8개 authority family에 공통 envelope 7개 column의 exact C1 DDL을 56/56으로 명시 |
| 2026-08-13 | [제안] C1 잔여 Gate의 policy provenance ordering, exact producer identifier, 5-state effective-time·same-family supersession, family envelope NOT NULL 계약 확정 |
| 2026-08-13 | [제안] journal·phase-event exact schema, authority UUID identity/event time model과 commit outcome matrix 확정 |
| 2026-08-13 | [제안] independent validation의 persistent decision, authority projection, journal evidence, transaction, PR 순서와 accountable owner 결함 보완 |
| 2026-08-13 | [제안] production authority catalog, adapter source, durable journal과 composition lifecycle 계약 초안 등록 |
