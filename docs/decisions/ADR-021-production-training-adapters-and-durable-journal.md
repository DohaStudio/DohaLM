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

[확정] 따라서 PR C의 Python 구현은 Definition of Ready의 입력·출력, 설정, persistence와 recovery 조건을 충족하지
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
| PostgreSQL 16 authority catalog + 외부 immutable artifact reference | row-level CAS, constraint, transaction, recovery와 운영 도구가 명확함 | 운영 database와 driver·migration·backup 책임이 추가됨 | 채택 제안 |
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

[제안] production metadata authority와 durable journal은 PostgreSQL `16.x`의 단일 database, 고정 schema
`dohalm_training_v1`에 둔다. adapter는 server major version이 16이 아니거나 schema version이 exact integer `1`이 아니면
fail closed한다. Dataset 원문·model·checkpoint·output은 database에 저장하지 않는다.

[제안] deployment supervisor가 database와 secret mount를 소유한다. DohaLM의 non-CLI production composition module
`src.training.production_composition`만 연결을 만들고 아래 adapter를 정확히 한 번 구성한다.

- `_PostgresTrainingPrerequisiteResolver`
- `_PostgresTrainingDecisionResolver`
- existing same-process `TrainingExecutionDecisionSource`와 `ProductionTrainingExecutionIssuerAdapter`
- `_PostgresTrainingExecutionJournal`
- `ProductionFullPretrainingHost`

위 symbol은 후속 PR C의 package-private 목표이며 이 ADR PR에서 생성하지 않는다. caller, CLI, request, plugin, dynamic import,
service locator와 environment-selected class는 adapter나 connection을 선택할 수 없다.

### 2. reference 문법과 공통 record envelope

[제안] Host foundation의 기존 `[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}` 검증을 유지하면서 production reference를 아래 exact
ASCII 형식으로 제한한다. `<id>`는 lowercase UUID textual form이고 namespace와 id의 조합은 immutable하다.

```text
config:<id>
readiness:<id>
dataset-version:<id>
dataset-manifest:<id>
decision:<id>
```

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
| `valid_until` | timestamptz nullable | null이면 별도 expiry 없음 |
| `revoked_at` | timestamptz nullable | non-null이면 즉시 unusable |
| `superseded_by` | UUID nullable, self-reference 금지 | successor 표시; non-null이면 unusable |
| `source_commit` | text, lowercase Git SHA-1 40 | producer source provenance |

`payload_sha256`은 existing `sha256_bytes(payload_bytes)`와 exact 동일하다. JSON resource는 먼저 existing
`canonical_json_bytes()`로 만들며 UTF-8, key 이름순, compact separator, trailing LF 하나와 non-finite rejection을 그대로
사용한다. YAML source는 byte-for-byte identity를 보존한다.

insert 뒤 `payload_bytes`, fingerprint, provenance와 identity는 UPDATE·DELETE할 수 없다. revoke/supersede는 별도 append-only
authority event가 transaction 안에서 현재 projection을 갱신한다. adapter는 unknown field, duplicate key, type coercion,
checksum mismatch, future schema, expired/revoked/superseded record를 거부한다. database read는 한 PostgreSQL transaction의
repeatable snapshot에서 수행하며 caller timestamp나 caller payload를 신뢰하지 않는다.

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
`dataset_pair_authority`는 다음 exact key를 갖는 immutable join record다.

```text
(dataset_version_authority_id, dataset_manifest_authority_id,
 pair_fingerprint, publication_scenario, created_at)
```

두 Host reference는 같은 join row를 가리켜야 하며 expected pair fingerprint와 일치해야 한다. adapter는 한 snapshot에서 두
payload를 읽고 Common runtime verification, ADR-015 pair validation과 current authority event를 확인한다. 이어 authority에
저장된 upstream provenance·split·artifact reference만으로 existing `evaluate_dataset_training_entry()`를 호출해 exact
`DatasetTrainingPermission`을 만든다. permission을 DB에 직렬화·복원하지 않으며 caller가 payload, local path 또는 permission을
공급할 수 없다. raw Dataset content와 artifact accessibility 검사는 PR C가 아니라 별도 Activation preflight 범위다.

### 6. Business decision authority

[제안] 별도 승인 workflow가 `training_execution_decision_authority`에 decision을 append한다. Host, adapter, issuer와 caller는
business decision을 생성하거나 기본값으로 대체하지 않는다. record는 공통 envelope와 아래 exact seven-field projection을
갖는다.

| field | constraint / authority |
|---|---|
| `decision` | exact `APPROVED`, `DENIED` 또는 `UNAVAILABLE`; approval workflow |
| `authorization_id` | non-empty opaque reference, unique; approval workflow |
| `issuer_id` | `training_issuer_registry.issuer_id`; registry |
| `approver_reference` | non-empty opaque reference; approval workflow |
| `evidence_reference` | exact `decision:<id>`; decision row identity |
| `request_fingerprint` | canonical request builder fingerprint; workflow exact echo |
| `issued_at` | canonical aware timestamp; DB transaction time |

decision row의 `valid_until`은 non-null이고 `issued_at < valid_until`이어야 한다. `training_issuer_registry`와
`training_approver_registry`는 각각 opaque identity, `active_from`, `active_until`, `revoked_at`, `schema_version`을 갖는
append-only registry다. issuer registry는 `adapter_kind`도 가지며 v1 exact 값은
`same_process_training_execution_issuer`다. resolver는 DB clock, 두 registry active interval, decision expiry,
revoke/supersede event, intent evidence reference와 request fingerprint를 한 snapshot에서 검증한다. `DENIED`와
`UNAVAILABLE`을 예외 fallback이나 `APPROVED`로 변환하지 않는다.

[제안] resolved seven-field value는 기존 same-process DecisionSource에 exact 한 번 submit되고 process-local claim 뒤 issuer
adapter로 전달된다. restart 뒤 DB decision을 다시 읽는 것은 새 orchestration attempt와 새 canonical request decision을
필요로 하며 이전 process의 claim, approval 또는 capability를 복원하지 않는다.

### 7. Durable journal schema와 concurrency

[제안] `training_execution_journal`의 primary key는 `run_id`이고 `request_fingerprint`와의 조합은 immutable하다. columns는
아래 exact set을 갖는다.

| field | type / constraint |
|---|---|
| `run_id` | varchar(256) primary key, Host reference pattern |
| `request_fingerprint` | char(71), fingerprint pattern |
| `phase` | text check: `claimed`, `resolved`, `validated`, `decision_submitted`, `approval_consumed`, `backend_entered`, `completed`, `failed`, `manual_reconciliation_required` |
| `version` | bigint, starts `1`, strictly increments |
| `authorization_fingerprint` | char(71) nullable, fingerprint pattern |
| `decision_evidence_fingerprint` | char(71) nullable, fingerprint pattern |
| `backend_entered` | boolean, phase invariant과 일치 |
| `reconciliation_required` | boolean, manual phase와 exact 동치 |
| `reason_code` | varchar(128) nullable, uppercase reason pattern |
| `created_at` | timestamptz, DB transaction time |
| `updated_at` | timestamptz, DB transaction time |

[제안] claim은 `INSERT ... ON CONFLICT DO NOTHING` 뒤 existing row를 읽는다. 같은 run/fingerprint의 terminal result만
deterministic replay할 수 있고, 다른 fingerprint, active row 또는 다른 attempt는 conflict다. transition은 한 statement의
`UPDATE ... WHERE run_id = ? AND request_fingerprint = ? AND phase = ? AND version = ? RETURNING ...` CAS이며 affected row가
정확히 1이 아니면 stale conflict다. transaction isolation은 `READ COMMITTED`; row uniqueness와 CAS predicate가 per-run
single winner를 보장한다. advisory lock, filesystem lock, in-memory lock과 automatic transaction retry를 권한 근거로 쓰지
않는다.

[제안] legal phase graph는 ADR-019·020의
`claimed -> resolved -> validated -> decision_submitted -> approval_consumed -> backend_entered -> terminal`뿐이다.
terminal overwrite, phase skip, backward transition과 deletion은 DB constraint/adapter validation으로 차단한다. consumed 또는
entered 결과가 불명확하면 automatic retry 없이 `MANUAL_RECONCILIATION_REQUIRED`를 새 version으로 기록한다. 이 phase는
terminal이며 operator가 evidence를 검토해 새 run과 새 decision을 만들기 전 재실행할 수 없다.

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

### 9. retention, backup와 audit

[제안] v1 authority, authority event, issuer registry와 journal row는 자동 삭제하지 않는다. 운영 retention 변경은 별도 ADR과
migration이 필요하다. database owner는 encrypted backup, access control, point-in-time recovery와 restore drill을 책임진다.
restore가 검증되지 않았거나 backup 기준시점 뒤 active row가 존재할 가능성이 있으면 production activation을 차단한다.

[제안] audit는 reference, fingerprint, phase, version, reason code, timestamp와 redacted correlation만 포함한다. DSN,
credential, absolute path, raw config/readiness/Dataset/decision payload, approval, capability, exception repr와 stack trace를 log,
error 또는 caller result에 넣지 않는다. durable audit export·SIEM 전송은 이 ADR이 승인하지 않는다.

### 10. secret/configuration contract

[제안] deployment supervisor는 exact environment name `DOHALM_TRAINING_DATABASE_DSN_FILE`에 protected secret file의 absolute
path를 설정한다. file은 UTF-8 단일 non-empty line PostgreSQL DSN만 포함한다. composition root는 startup에서 한 번 읽고
즉시 application buffer를 폐기하며 environment나 DSN을 log하지 않는다. missing, relative, symlink/reparse point, group/world
readable POSIX mode 또는 Windows ACL 검증 불가 상태는 fail closed한다. application은 secret file을 생성·회전·수정하지 않는다.

schema name, server version, reference namespace와 timeout은 runtime override가 없는 v1 constants다. test는 environment나 live
credential을 쓰지 않고 exact storage protocol을 구현한 in-memory fake와 ephemeral PostgreSQL contract suite를 분리한다.
ephemeral suite의 image digest와 driver version은 PR C에서 dependency review와 함께 고정해야 하며, 그 승인 전 live adapter
구현은 시작하지 않는다.

### 11. composition lifecycle와 multiprocess ownership

[제안] deployment supervisor가 non-CLI `python -m src.training.production_composition` process를 명시적으로 시작한다.
module import는 connection, registration, request, approval와 backend side effect가 0이어야 한다. explicit `main()`은 다음
순서만 수행한다.

1. secret/config validation
2. database connect와 server/schema/version/least-privilege preflight
3. read-only corruption/reconciliation scan
4. adapter와 exact Host object graph bootstrap
5. 별도 Activation approval이 존재할 때만 intent intake 시작

[제안] 한 process에는 Host object graph 하나만 존재한다. 여러 process는 같은 database CAS를 공유하지만 process-local
DecisionSource, issuer, approval와 capability를 공유·복구하지 않는다. graceful shutdown은 새 intent 수신을 먼저 닫고 bounded
active operation을 기다린 뒤 connection을 닫는다. timeout/process loss 뒤 active journal은 startup에서 자동 재개하지 않는다.

### 12. non-activating preflight와 test 전략

[제안] PR C는 production activation 없이 다음을 검증하는 package-private preflight만 구현할 수 있다.

- server major/schema version, required table/column/constraint와 least-privilege read/CAS 권한
- reference namespace, canonical bytes/checksum, expiry/revoke/supersede와 provenance validation
- journal claim/conflict/CAS/terminal/manual-reconciliation 및 concurrent single winner
- transaction failure, connection loss와 corrupt row의 sanitized fail-closed behavior
- Host와 fake execution boundary 통합에서 actual Dataset content/model/GPU/backend side effect 0
- source checkout와 built wheel의 private surface, import side effect와 redaction parity

production credential, production data, actual backend, Dataset content, Model, GPU, output과 Training은 test input이 아니다.

## PR C implementation Gate

[제안] 이 ADR이 독립 검증되고 명시 승인·병합된 뒤에도 PR C는 다음이 모두 별도 증거로 준비된 경우에만 시작한다.

1. PostgreSQL driver와 pinned ephemeral test image의 dependency/security/license 검토
2. v1 SQL migration과 rollback/forward-only policy의 독립 검토
3. authority producer workflow와 least-privilege database role의 owner 승인
4. exact existing readiness schema와 canonical config bytes mapping test fixture
5. production composition module은 activation false인 상태에서 preflight만 수행한다는 test

PR C 범위는 위 private adapters, storage mapping, migrations와 non-activating preflight뿐이다. CLI/API/worker/scheduler intake,
actual Training, runtime deployment와 production credential 설치는 포함하지 않는다.

## Production Activation Gate

[제안] ADR 또는 PR C 병합은 production activation 승인이 아니다. 다음이 모두 충족되기 전 composition `main()`은 intent
intake와 backend invocation을 fail closed한다.

1. ADR-016~021과 PR C의 독립 검증·명시 승인·병합
2. migration/backup/restore/reconciliation evidence와 least-privilege review
3. bounded non-activating preflight 및 source/wheel parity 통과
4. 실제 Dataset pair/config/readiness/source/output/disk/GPU의 새 request 결속 검증
5. 실행 범위·비용·중단·복구에 대한 별도 사용자 명시 승인

exactly-once Training, cross-process capability, automatic restart/retry와 durable approval persistence는 주장하지 않는다.

## Consequences

- 장점: prerequisite, decision와 journal이 한 transaction-capable authority에 있어 lookup·CAS·recovery 경계가 명확하다.
- 장점: caller와 CLI가 storage, credential, resolver 또는 decision을 선택하지 못한다.
- 장점: process-local approval 의미를 보존하면서 crash ambiguity를 durable manual reconciliation으로 차단한다.
- 비용: PostgreSQL 운영, driver, migration, role, backup과 restore evidence가 선행돼야 한다.
- 비용: ADR-015 local publication을 authority catalog에 ingest하는 별도 producer workflow가 필요하다.
- 한계: 이 결정만으로 production data 접근, backend 실행, Training 재시도 또는 exactly-once가 가능해지지 않는다.

## Revisit conditions

- deployment topology가 managed cloud secret provider 또는 cross-process/network decision service로 바뀐다.
- PostgreSQL 16 외 제품·major version, separate authority databases 또는 external transaction coordinator가 필요해진다.
- Dataset content location, artifact access credential 또는 production scheduler를 결정한다.
- approval consume와 Training side effect를 하나의 transactional system으로 결속한다.
- retention 삭제, durable audit export 또는 automatic reconciliation 요구가 승인된다.

## 승인 Gate

이 ADR은 `draft`와 `proposed`다. 독립 검증과 사용자 명시 승인·병합 전에는 implementation requirement가 아니다. 이 문서
병합만으로 PR C 구현, migration, credential 설치, process activation 또는 Training을 승인하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-13 | [제안] production authority catalog, adapter source, durable journal과 composition lifecycle 계약 초안 등록 |
