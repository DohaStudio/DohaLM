# ADR-021: Production Training Adapters와 Durable Journal Authority

- 문서 상태: `draft`
- 마지막 검토일: 2026-08-13
- 결정 상태: `proposed`
- 실행 영향: 없음
- 관련 문서: [ADR-015](./ADR-015-dataset-version-publication-contract.md),
  [ADR-016](./ADR-016-generic-training-execution-approval-boundary.md),
  [ADR-017](./ADR-017-production-training-execution-issuer-trust-anchor.md),
  [ADR-018](./ADR-018-composition-root-owned-training-execution-decision-source.md),
  [ADR-019](./ADR-019-production-full-pretraining-host-and-trusted-decision-input.md),
  [ADR-020](./ADR-020-production-training-orchestration-ownership-seams.md),
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
proposed 계약을 정의한다. 이 문서 PR은 Python, dependency, migration, credential, production data와 runtime activation을
변경하지 않는다.

## 검토한 선택지

### Authority와 persistence 제품

| 선택지 | 장점 | 문제 | 판정 |
|---|---|---|---|
| ADR-015 local publication 디렉터리와 JSON journal | dependency가 작음 | cross-process CAS, transaction, fsync·power-loss, schema migration과 backup 계약이 없음 | 기각 |
| process별 SQLite database | 단일 파일·local test가 쉬움 | process/service ownership, network filesystem 금지, writer contention과 운영 backup 경계가 배포 topology에 결속됨 | 기각 |
| prerequisite별 별도 저장소 + journal database | 각 도메인 독립 운영 가능 | 한 request snapshot의 currentness와 decision/journal claim 사이 원자 경계가 없고 분산 복구가 필요 | 기각 |
| supported PostgreSQL authority catalog + 외부 immutable artifact reference | row-level CAS, constraint, transaction, recovery와 운영 도구가 명확함 | 운영 database와 driver·migration·backup 책임이 추가됨 | 채택 제안 |
| object storage를 모든 authority와 journal로 사용 | immutable payload 보관에 적합 | conditional update와 journal transaction 의미가 provider마다 달라짐 | metadata/journal에는 기각; Dataset content 위치는 후속 범위 |

### Credential 공급

| 선택지 | 장점 | 문제 | 판정 |
|---|---|---|---|
| DSN 원문 environment variable | 배포가 단순함 | process listing·diagnostic·error 환경 dump에 secret 노출 위험 | 기각 |
| caller 또는 CLI가 DSN/path 전달 | test가 쉬움 | caller가 production composition과 authority를 선택함 | 기각 |
| deployment-owned protected DSN file의 절대 경로만 environment로 전달 | secret rotation과 application config 분리 | mount·ACL 운영 책임 필요 | 채택 제안 |
| 특정 cloud secret SDK | rotation 기능이 풍부함 | deployment provider가 선택되지 않았고 새 dependency가 필요 | 현재 기각; topology 변경 시 재검토 |

## Proposed Decision

### 1. authority topology와 소유권

[제안] production metadata authority와 durable journal은 단일 PostgreSQL database, 고정 schema
`dohalm_training_v1`에 둔다. product version policy는 **PostgreSQL 16 이상이며 upstream이 지원하고 DohaLM compatibility
matrix가 명시적으로 승인한 major의 최신 supported minor**다. 최초 Schema/Dependency PR C1의 validation baseline과 초기
allowlist는 `16.x`/`{16}`이지만 16-only 기능을 주장하지 않는다. 다른 supported major는 driver·migration·concurrency·backup/
restore contract suite를 통과해 matrix가 갱신된 뒤 사용할 수 있다. unsupported/EOL major, matrix 밖 major와 승인 minor보다
낮은 보안 minor는 fail closed한다. major upgrade는 별도 migration·restore·recovery 독립 검증 Gate다. schema version은 exact
integer `1`이다. Dataset 원문·model·checkpoint·output은 database에 저장하지 않는다.

[제안] Production Training Deployment Owner와 Security/Secret Provisioning Owner가 database deployment와 secret mount를
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

[제안] Host foundation의 기존 `[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}` 검증을 유지하면서 production reference를 아래 exact
ASCII 형식으로 제한한다. `<id>`는 lowercase UUID textual form이고 namespace와 id의 조합은 immutable하다.

```text
config:<id>
readiness:<id>
dataset-version:<id>
dataset-manifest:<id>
dataset-pair:<id>
decision:<id>
```

`authorization_id`, `issuer_id`, `approver_reference`와 `policy_reference`는 whitespace 없는 위 Host reference grammar의
opaque scalar다. `evidence_reference`는 exact `decision:<authority_id>`다. scalar를 소지하거나 재구성해도 authority는 없다.

[제안] 모든 authority row는 다음 공통 envelope를 갖는다. DB timestamp를 canonical ISO 8601로 직렬화할 때 UTC offset
`+00:00`을 포함한다. `payload_sha256`은 `sha256:` + lowercase hex 64이며 payload의 repository-defined canonical bytes에
기존 `checksum_value()`와 동일한 SHA-256 표현을 적용한 값이다.

| field | exact type / constraint | 의미 |
|---|---|---|
| `authority_id` | UUID primary key | reference의 `<id>` |
| `schema_version` | smallint, exact `1` | record envelope version |
| `payload_bytes` | bytea, non-empty | immutable source bytes |
| `payload_sha256` | text, fingerprint pattern | exact source-byte identity |
| `created_at` | timestamptz, non-null | DB가 기록한 생성 시각 |
| `valid_from` | timestamptz, non-null, `created_at <= valid_from` | 효력 시작 |
| `valid_until` | timestamptz nullable, `valid_from < valid_until` | null이면 별도 expiry 없음 |
| `source_commit` | text, lowercase Git SHA-1 40 | producer source provenance |

`payload_sha256`은 existing `sha256_bytes(payload_bytes)`와 exact 동일하다. JSON resource는 먼저 existing
`canonical_json_bytes()`로 만들며 UTF-8, key 이름순, compact separator, trailing LF 하나와 non-finite rejection을 그대로
사용한다. YAML source는 byte-for-byte identity를 보존한다.

insert 뒤 identity, validity, `payload_bytes`, fingerprint와 provenance는 UPDATE·DELETE할 수 없다. raw secret, DSN, absolute
path, capability, approval과 PII payload를 저장하지 않는다. revoke/supersede는 immutable row를 수정하지 않고 아래 공통
append-only `training_authority_event`에만 기록한다.

| field | exact type / constraint |
|---|---|
| `event_id` | UUID primary key |
| `subject_family` | closed authority-family enum |
| `subject_key` | varchar(256), family-specific stable primary key/reference |
| `subject_version` | bigint, `>= 1` |
| `event_kind` | exact `created`, `revoked`, `superseded` |
| `superseded_by` | varchar(256) nullable; `superseded`일 때만 non-null, self-reference 금지 |
| `effective_at` | timestamptz, non-null |
| `recorded_at` | timestamptz, DB transaction time |
| `producer_role` | closed accountable-role identifier |
| `evidence_reference` | opaque Host-reference grammar |

`UNIQUE(subject_family, subject_key, subject_version)`이 duplicate/same-version conflict를 차단하며 version은 subject별 직전
version + 1이다. event insert는 family별 immutable row primary key에 대한 exact referential predicate를 요구한다.
`(subject_family, subject_key)` PK를 가진 `training_authority_current`는 `current_event_id`,
`current_version`, `state`, `effective_at`, `superseded_by` projection을 갖는다. event insert와 exact expected-version projection
CAS는 하나의 transaction이다. event stream으로 projection을 결정적으로 재계산할 수 있어야 한다. version gap, event/projection
불일치, impossible successor, checksum/FK/schema 손상은 해당 subject와 process preflight를 fail closed하고 자동 repair하지
않는다.

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
| issuer registry | opaque `issuer_id` PK | identity, adapter kind, active interval | issuer+ID | projection version | Training Authority Producer | Production Training Decision Resolver |
| approver registry | opaque reference PK | identity, active interval | approver+ID | projection version | Training Authority Producer | Production Training Decision Resolver |
| currentness event | event UUID | subject/version/effect/evidence | family+subject | expected version | Training Authority Producer | both resolvers |

Producer DB role만 immutable row와 event를 INSERT하고 projection CAS를 실행한다. Resolver DB role은 authority/projection
read-only, Journal DB role은 restricted journal claim/transition function만 실행한다. Host/caller/CLI/runtime role은 authority
row/event/projection을 직접 생성·변경·삭제할 수 없고 unrestricted table UPDATE 권한을 갖지 않는다.

### 3. Config authority

[제안] `training_config_authority`는 공통 envelope 외에 `config_kind = 'full_pretraining'`과
`config_schema_version = 1`을 갖는다. `payload_bytes`는 UTF-8, BOM 없음, duplicate YAML key 없음인 exact YAML source다.
fingerprint는 existing `file_checksum(config_path)`와 같아지도록 exact bytes에 `sha256_bytes()`를 적용한다. schema는 existing
`FullPretrainingConfig.from_yaml()`이 exact type·required field·value를 검증하고 `to_dict()`가 만드는 snapshot으로 고정한다.
unknown field, YAML alias/custom tag, environment substitution과 type coercion은 허용하지 않는다.

[제안] adapter는 DB bytes를 process마다 새로 만든 private directory의 `config.yaml`에 exclusive create하고 flush/fsync한 뒤
absolute `Path`를 만든다. directory는 caller가 지정할 수 없고 OS temporary-directory API로 생성하며 symlink/reparse point,
pre-existing file, `..`, backslash와 final-handle containment 불일치를 차단한다. materialized file은 read-only로 바꾸고 resolve와
backend revalidation 사이 checksum·parsed snapshot을 다시 확인한 뒤 request 종료 시 삭제한다. reference, expected fingerprint,
`source_commit` 중 하나라도 현재 clean checkout과 다르면 fail closed한다. DB source bytes가 authority이며 temporary path는
authority나 audit identity가 아니다.

### 4. Readiness evidence authority

[제안] `training_readiness_authority`는 existing Full Pretraining approval manifest의 exact UTF-8 YAML bytes를 공통 envelope에
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

[제안] `dataset_version_authority`와 `dataset_manifest_authority`는 ADR-015와 pinned Common package가 검증한 각 canonical JSON
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

[제안] 별도 승인 workflow가 `training_execution_decision_authority`에 decision을 append한다. Host, adapter, issuer와 caller는
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

[제안] resolved seven-field value는 기존 same-process DecisionSource에 exact 한 번 submit되고 process-local claim 뒤 issuer
adapter로 전달된다. restart 뒤 DB decision을 다시 읽는 것은 새 orchestration attempt와 새 canonical request decision을
필요로 하며 이전 process의 claim, approval 또는 capability를 복원하지 않는다.

### 7. Durable journal schema와 concurrency

[제안] `training_execution_journal`은 current lifecycle projection이다. primary key는 `run_id`다. request/prerequisite
binding column은 INSERT 뒤 immutable하고 decision metadata는 null에서 `decision_submitted` transition 때 한 번만 기록한 뒤
immutable하다. columns는 아래 exact set을 갖는다.

| field | type / constraint |
|---|---|
| `run_id` | varchar(256) primary key, Host reference pattern |
| `request_fingerprint` | char(71), fingerprint pattern |
| `intent_fingerprint` | char(71), fingerprint pattern |
| `host_schema_version` | smallint, v1 exact `1` |
| `host_lifecycle_version` | smallint, v1 exact `1` |
| `orchestration_correlation_id` | varchar(256), opaque reference, unique |
| `dataset_version_id` | varchar(256), non-empty Common object ID |
| `dataset_manifest_id` | varchar(256), non-empty Common object ID |
| `dataset_pair_fingerprint` | char(71), fingerprint pattern |
| `config_fingerprint` | char(71), fingerprint pattern |
| `readiness_fingerprint` | char(71), fingerprint pattern |
| `source_commit` | char(40), lowercase Git SHA-1 |
| `authorization_id` | varchar(256) nullable before decision submission; opaque reference grammar |
| `issuer_id` | varchar(256) nullable before decision submission; registry reference |
| `approver_reference` | varchar(256) nullable before decision submission; registry reference |
| `evidence_reference` | varchar(265) nullable before decision submission; exact decision reference |
| `policy_reference` | varchar(256), opaque reference, non-null |
| `phase` | text check: `claimed`, `resolved`, `validated`, `decision_submitted`, `approval_consumed`, `backend_entered`, `completed`, `failed`, `manual_reconciliation_required` |
| `version` | bigint, starts `1`, strictly increments |
| `authorization_fingerprint` | char(71) nullable, fingerprint pattern |
| `decision_evidence_fingerprint` | char(71) nullable, fingerprint pattern |
| `backend_entered` | boolean, phase invariant과 일치 |
| `reconciliation_required` | boolean, manual phase와 exact 동치 |
| `reason_code` | varchar(128) nullable, uppercase reason pattern |
| `process_boundary_id` | varchar(256), opaque process-start identity; host/user/credential가 아님 |
| `created_at` | timestamptz, DB transaction time |
| `updated_at` | timestamptz, DB transaction time |

[제안] append-only `training_execution_phase_event`는 `(run_id, journal_version)` primary key, unique event UUID,
from/to phase, process boundary ID, sanitized reason과 `occurred_at` DB transaction timestamp를 갖는다. journal projection CAS와
phase event INSERT는 한 transaction이다. 이 table이 ADR-019의 각 phase timestamp와 restart boundary를 보존한다.

approval/capability/token, DecisionSource·adapter object, raw config/readiness/Dataset/decision payload, raw exception/stack trace,
absolute path, DSN과 credential은 두 journal table에 저장하지 않는다.

[제안] claim은 `run_id` primary key를 actual `ON CONFLICT` arbiter로 사용한다. `INSERT ... ON CONFLICT DO NOTHING
RETURNING`이 row를 반환하면 acquired다. 반환하지 않으면 같은 `READ COMMITTED` transaction에서 primary key로 existing row를
읽고 immutable binding을 비교한다. 같은 run/fingerprint의 terminal result만 read-only terminal replay이며, 다른 fingerprint,
active/manual row 또는 binding mismatch는 deterministic conflict다.

transition은 restricted DB function 안에서
`UPDATE ... WHERE run_id = ? AND request_fingerprint = ? AND phase = ? AND version = ? RETURNING ...` CAS와 phase event insert를
한 transaction으로 수행한다. 이 predicate의 `phase`와 `version`은 caller가 읽은 exact expected phase와 expected version이다.
affected row 0은 re-read하여 terminal conflict, stale phase/version 또는 unavailable로 mapping한다.
unrestricted direct UPDATE 권한, lossy upsert, last-write-wins, advisory/filesystem/in-memory lock을 권한 근거로 쓰지 않는다.

[제안] legal phase graph는 ADR-019·020의
`claimed -> resolved -> validated -> decision_submitted -> approval_consumed -> backend_entered -> terminal`뿐이다.
terminal overwrite, phase skip, backward transition과 deletion은 DB constraint와 restricted transition function으로 차단한다.
immutable binding update, phase event gap, impossible flag 조합도 거부한다. `approval_consumed`는
`backend_entered=false`, `backend_entered`·`completed`는 true이고 `reconciliation_required=true` iff manual phase다. consumed 또는
entered 결과가 불명확하면 automatic retry 없이 `MANUAL_RECONCILIATION_REQUIRED`를 새 version으로 기록한다. 이 phase는
terminal이며 Training Reconciliation Approver가 closure evidence를 검토해 새 run과 새 decision을 허용하기 전 재실행할 수 없다.

### 8. transaction, restart와 corruption

[제안] authority snapshot read와 journal CAS는 같은 database를 쓰지만 approval consume와 Training side effect를 하나의 DB
transaction으로 묶었다고 주장하지 않는다. process loss 위치에 따라 다음처럼 처리한다.

- `decision_submitted` 이하: 기존 process-local authority는 복구하지 않고 record를 active conflict로 유지한다.
- `approval_consumed` 또는 `backend_entered`: startup reconciliation이 자동 실행하지 않고
  `manual_reconciliation_required` 후보로 보고한다.
- `completed`/`failed`: exact run/fingerprint terminal evidence만 읽고 side effect를 재수행하지 않는다.

[제안] startup reconciliation은 read-only scan과 redacted report 생성만 한다. 자동 phase 변경, decision resubmit,
approval/capability reconstruction과 backend retry는 금지한다. checksum, foreign key, phase/version, schema version 또는 canonical
payload가 손상되면 해당 request와 process preflight를 fail closed하고 자동 repair하지 않는다.

#### Isolation, use-time currentness와 failure mapping

[제안] prerequisite authority resolution은 request build 전 명시적으로 시작한 read-only `REPEATABLE READ` transaction에서
수행하고 immutable request binding material을 확정한 뒤 종료한다. journal claim은 별도 `READ COMMITTED` transaction이다.
두 transaction은 원자적이지 않다. decision resolve 직전과 DecisionSource submit 직전에 짧은 read-only transaction으로
referenced authority, decision, issuer와 approver의 use-time currentness를 다시 검증한다. 재검증 뒤 revoke와 process-local
submit/consume 사이에도 잔여 race가 있으며 distributed revocation 또는 exactly-once로 표현하지 않는다.

| failure | sanitized mapping | automatic retry | 제한 |
|---|---|---|---|
| known rollback 전 read-only transient failure | unavailable | policy-bounded same-process retry 가능 | submit/consume/backend 0이 증명될 때만 |
| unique violation | replay/conflict 재판정 | 없음 | 새 authority/attempt 생성 금지 |
| deadlock/serialization failure | DB conflict/unavailable | known rollback DB-only unit만 최대 1회 | authority/backend operation 포함 시 금지 |
| commit 전 connection loss | unavailable | read-only/DB-only만 조건부 | side effect 0이 증명돼야 함 |
| commit acknowledgement 전 connection loss | outcome unknown | 없음 | 재-read는 분류용; operation 재실행 금지 |
| submit/consume/backend entry 중·후 failure | outcome unknown | 없음 | 가능한 경우 manual reconciliation |
| raw DB/schema/corruption error | invalid/unavailable | 없음 | query/DSN/host/path 비노출 |

commit ambiguity 뒤 row를 재-read해도 decision submission, approval issuance/consume 또는 backend entry를 자동 재실행하지
않는다. consume 또는 backend entry 가능성이 있거나 journal transition 결과를 증명할 수 없으면
`MANUAL_RECONCILIATION_REQUIRED`다. manual transition commit도 불명확하면 external success를 반환하지 않는다.
connection pool은 composition construction-owned이고 process/fork 사이에 공유하지 않는다. child/restarted process는 이전
connection과 process boundary ID를 폐기하고 새 pool/preflight를 요구한다. timestamp authority는 DB transaction clock이다.

### 9. accountable operations, retention과 audit

| Role | Owns | May authorize | Must not do | Required evidence | Activation blocker |
|---|---|---|---|---|---|
| Production Training Deployment Owner | approved DB version과 service deployment | rollout/stop | Training approval 생성 | compatibility/preflight | matrix 밖 DB |
| Training Authority Producer Owner | producer workflow와 writer role | authority/event append | Host/caller write 허용 | provenance/currentness tests | producer 미승인 |
| Training Database Migration Owner | schema, role, migration lock | forward/rollback policy | adapter activation | migration report | partial/unknown schema |
| Training Database Backup/Restore Owner | encrypted backup, PITR, restore drill | restore 수행 제안 | approval 복원 | cadence·RPO/RTO·drill | 수치/drill 미승인 |
| Training Reconciliation Approver | manual case review/closure | 새 run 허용 또는 계속 차단 | approval 복원/자동 backend 실행 | append-only closure evidence | unresolved case |
| Production Training Process Owner | non-CLI bootstrap/shutdown/restart | process lifecycle | caller adapter injection | lifecycle/restart evidence | process contract 미승인 |
| Security/Secret Provisioning Owner | DSN file ACL, rotation/revoke | credential provision/rotation | repo/CLI secret 제공 | ACL/rotation evidence | insecure/missing secret |

role은 stable repository contract이며 개인명, credential 또는 private deployment path가 아니다. 실제 deployment assignment는
Activation evidence에서 기록한다.

[제안] v1 authority, authority event, registry, journal과 reconciliation closure row는 자동 삭제하지 않는다. retention,
archive/deletion 변경은 별도 ADR, migration과 Training Database Backup/Restore Owner 승인이 필요하다. backup cadence와 RPO/RTO
수치, encrypted backup, access control, PITR와 restore drill evidence가 운영 Gate에서 승인되기 전 production activation을
차단한다. restore 뒤 backup 기준시점 이후 event/current projection을 재동기화하고 모든 currentness/revocation을 재검증하기
전 intent intake를 열지 않는다.

[제안] manual reconciliation closure는 approver role, original run, observed phase/version, redacted evidence, disposition과 DB
timestamp를 append-only로 기록한다. closure는 기존 approval/capability를 복원하거나 backend를 자동 실행하지 않으며 새 run과
새 decision만 허용할 수 있다.

[제안] audit는 reference, fingerprint, phase, version, reason code, timestamp와 redacted correlation만 포함한다. DSN,
credential, absolute path, raw config/readiness/Dataset/decision payload, approval, capability, exception repr와 stack trace를 log,
error 또는 caller result에 넣지 않는다. durable audit export·SIEM 전송은 이 ADR이 승인하지 않는다.

### 10. secret/configuration contract

[제안] Security/Secret Provisioning Owner는 exact environment name `DOHALM_TRAINING_DATABASE_DSN_FILE`에 protected secret
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

[제안] future non-CLI executable/service boundary는 별도 Composition PR C3에서 exact symbol로 확정한다. 현재 존재하지 않는
`src.training.production_composition`이나 `python -m` entrypoint를 사실로 고정하지 않는다. Production Training Process
Owner가 process당 object graph 하나와 pool, adapters, clock/policy, DecisionSource/issuer와 Host를 construction-owned로
bootstrap한다. module import는 connection, migration, registration, request, approval와 backend side effect가 0이어야 한다.
future explicit startup은 다음 순서만 수행한다.

1. secret/config validation
2. database connect와 server/schema/version/least-privilege preflight
3. read-only corruption/reconciliation scan
4. construction-owned pool, adapter와 exact Host object graph bootstrap
5. 별도 Activation approval이 존재할 때만 intent intake 시작

[제안] 한 process에는 Host object graph 하나만 존재한다. pool/connection은 fork·process·restart 사이 공유하지 않는다.
여러 process는 같은 database CAS를 공유하지만 process-local
DecisionSource, issuer, approval와 capability를 공유·복구하지 않는다. graceful shutdown은 새 intent 수신을 먼저 닫고 bounded
duration을 기다린 뒤 pool을 폐기한다. duration과 timeout disposition은 C3 운영 Gate에서 승인하며 timeout/process loss 뒤
active journal은 startup에서 자동 재개하지 않는다.

### 12. non-activating preflight와 test 전략

[제안] C2/C3는 production activation 없이 다음을 검증하는 package-private preflight만 구현할 수 있다.

- approved server compatibility matrix/schema version, required table/column/constraint와 least-privilege read/CAS 권한
- reference namespace, canonical bytes/checksum, expiry/revoke/supersede와 provenance validation
- journal claim/conflict/CAS/terminal/manual-reconciliation 및 concurrent single winner
- transaction failure, connection loss와 corrupt row의 sanitized fail-closed behavior
- Host와 fake execution boundary 통합에서 actual Dataset content/model/GPU/backend side effect 0
- source checkout와 built wheel의 private surface, import side effect와 redaction parity

production credential, production data, actual backend, Dataset content, Model, GPU, output과 Training은 test input이 아니다.

## Implementation PR 순서

1. **ADR-021 승인·병합**: 설계만 확정하며 구현·activation 없음.
2. **Schema/Dependency PR C1**: PostgreSQL driver와 migration tool 선택, pinned ephemeral image, v1 schema/migration/roles,
   compatibility matrix, migration lock, bootstrap/upgrade와 rollback-or-forward-only, isolated migration/restore contract tests.
   adapter·production credential·activation 없음.
3. **Adapter PR C2**: production prerequisite/decision/journal adapters, restricted DB operations, non-activating preflight와
   isolated DB contract tests. executable·runtime activation 없음.
4. **Composition PR C3**: exact non-CLI process symbol, object graph/pool/bootstrap/shutdown/restart contract와 fake/bounded
   integration. production intent intake와 actual Training은 비활성.
5. **Production Activation Gate**: 별도 운영 증거와 사용자 명시 승인.

C1 전에는 driver/migration implementation을 시작하지 않는다. C2는 C1 독립 검증·병합 뒤, C3는 C2 독립 검증·병합 뒤에만
시작한다. 각 PR은 dependency/schema, adapter, composition과 activation 범위를 겹치지 않는다. authority producer workflow와
writer role은 C2 전 Training Authority Producer Owner가 승인하며 readiness/config mapping fixture도 C2 입력으로 고정한다.

## Production Activation Gate

[제안] ADR 또는 C1/C2/C3 병합은 production activation 승인이 아니다. 다음이 모두 충족되기 전 future actual run
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

이 ADR은 `draft`와 `proposed`다. 독립 검증과 사용자 명시 승인·병합 전에는 implementation requirement가 아니다. 이 문서
병합만으로 C1/C2/C3 구현, migration, credential 설치, process activation 또는 Training을 승인하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-13 | [제안] independent validation의 persistent decision, authority projection, journal evidence, transaction, PR 순서와 accountable owner 결함 보완 |
| 2026-08-13 | [제안] production authority catalog, adapter source, durable journal과 composition lifecycle 계약 초안 등록 |
