# ADR-034: Cross-Repository Rights Authority와 CurrentEvidence Snapshot

- 문서 상태: `approved`
- 마지막 검토일: 2026-09-01
- 결정 상태: `approved`
- 실행 영향: Rights authority·CurrentEvidence snapshot·Dataset governance binding 구현 진입을 승인한다. 실제 Rights record 발행,
  Dataset publication, production PostgreSQL provisioning과 Training 실행은 승인하지 않는다.
- 기준 DohaLM commit: `44de930482e5b007f20b1b2280faa92dc38ef99b`
- 기준 DohaLM tree: `b7bbae74d5df816180b5aab9bda061b4bdf28fe7`
- 선행 결정: [ADR-027](./ADR-027-dataset-governance-production-prerequisites.md),
  [ADR-028](./ADR-028-current-evidence-source-authority.md),
  [ADR-029](./ADR-029-rights-metadata-ownership-authority.md),
  [ADR-030](./ADR-030-cross-repository-rights-domain-ownership.md)
- 관련 결정: [ADR-015](./ADR-015-dataset-version-publication-contract.md),
  [ADR-025](./ADR-025-dataset-version-proposal-authority-contract.md),
  [ADR-026](./ADR-026-dataset-review-authority-contract.md),
  [ADR-031](./ADR-031-dataset-publication-pair-public-read-contract.md),
  [ADR-032](./ADR-032-production-training-intent-authority.md),
  [ADR-033](./ADR-033-local-production-training-accountability.md)
- 승인 근거: 2026-09-01 사용자 `DDORINY`의 명시적 Cross-Repository Rights / Licensing Ownership Decision

## Context

[현재] ADR-027~030은 production CurrentEvidence를 구성하는 RightsMetadata의 accountable owner, canonical source identity,
logical key, create·replace·revoke actor, durable history/current projection, authenticated reader와 cross-source snapshot을 결정하지
못해 fail closed했다. 당시 조사 결과와 `STILL BLOCKED` 판정은 유효한 역사 기록이다.

[현재] 2026-09-01 조직 결정은 별도 shared DohaStudio Rights/Licensing domain인 **DohaRights**를 canonical owner로 승인하고,
DohaLM을 read-only Dataset Governance consumer로 제한했다. 또한 source-issued token을 합성하는 Model C, exact immutable composite
snapshot binding과 publication·Training currentness recheck를 승인했다. 이 ADR은 그 결정의 final architecture record다.

[현재] DohaMusic의 consent persistence는 partial authority이며 음악·voice consent에 한정된다. DohaLM의 manifest와 Candidate A
eligibility material은 검토 증거이지 canonical Rights authority가 아니다. 어느 기존 파일이나 partial store도 DohaRights로 간주하지
않는다.

## Decision summary

| 결정 | 승인 값 |
|---|---|
| accountable owner | `DohaRights / shared DohaStudio Rights-Licensing domain` |
| canonical source identity | `DohaRights source-authority UUID + schema version` |
| logical key | `stable Rights Subject ID with Dataset source identity binding` |
| create·replace·revoke actor | `DohaRights dedicated Rights authority producer` |
| durable history/current projection owner | `DohaRights` |
| authenticated reader | `DohaLM Dataset Governance read-only consumer` |
| snapshot model | `Model C — source-issued tokens + composite snapshot` |
| snapshot issuer | `DohaLM Dataset Governance Snapshot Coordinator` |
| publication binding | exact immutable composite snapshot ID + canonical SHA-256 fingerprint |
| Training currentness recheck | `YES`, intent 생성과 activation 모두 |

승인된 machine-readable decision labels는 다음과 같다.

```text
RIGHTS_ACCOUNTABLE_OWNER = DohaRights / shared DohaStudio Rights-Licensing domain
RIGHTS_CANONICAL_SOURCE_IDENTITY = DohaRights source-authority UUID + schema version
RIGHTS_LOGICAL_KEY = stable Rights Subject ID with Dataset source identity binding
RIGHTS_CREATE_ACTOR = DohaRights dedicated Rights authority producer
RIGHTS_REPLACE_ACTOR = DohaRights dedicated Rights authority producer
RIGHTS_REVOKE_ACTOR = DohaRights dedicated Rights authority producer
RIGHTS_DURABLE_HISTORY_OWNER = DohaRights
RIGHTS_CURRENT_PROJECTION_OWNER = DohaRights
RIGHTS_AUTHENTICATED_READER = DohaLM Dataset Governance read-only consumer
SNAPSHOT_MODEL = Model C — Source-issued Tokens + Composite Snapshot
SNAPSHOT_ISSUER = DohaLM Dataset Governance Snapshot Coordinator
PUBLICATION_SNAPSHOT_BINDING = exact immutable composite snapshot ID + SHA-256 fingerprint
TRAINING_RIGHTS_CURRENTNESS_RECHECK = YES
```

## Ownership decision

검토한 선택지는 다음과 같다.

| 선택지 | 결과 | 근거 |
|---|---|---|
| A. DohaMusic owner | 기각 | voice consent는 partial authority이고 Dataset training·redistribution·commercial rights 전체 의미와 맞지 않는다. |
| B. DohaLM owner | 기각 | Dataset consumer가 legal/Rights lifecycle writer까지 소유하면 domain과 권한 분리가 무너진다. |
| C. shared Rights/Licensing domain | 채택 | Dataset·music 저장소와 독립된 lifecycle, 다중 consumer, revoke·audit와 semantic ownership을 함께 보존한다. |
| D. external system | 현재 기각 | 승인된 local architecture와 운영 가능한 authority owner가 없다. 향후 교체는 새 ADR을 요구한다. |

[확정] canonical owner의 이름은 **DohaRights**다. 이는 이 저장소에 임시 table을 만드는 별칭이 아니라 shared DohaStudio
Rights/Licensing domain과 그 accountable 운영 경계다. DohaLM은 Rights 발행자가 아니다.

## Canonical source identity와 logical subject

### Source identity

[확정] Rights source는 pairwise stable한 `source_authority_id` UUID와 `schema_version`의 조합으로 식별한다. origin domain은
`DohaRights`로 검증한다. filesystem path, URL, DSN, service hostname, repository commit 또는 payload fingerprint만으로 source를
식별하지 않는다.

[확정] source authority UUID 교체는 silent configuration change가 아니다. 새 source identity와 명시적 transition evidence를
요구하며 기존 history의 issuer identity를 바꾸지 않는다.

### Logical key와 granularity

[확정] lookup key는 stable `rights_subject_id`와 Dataset source identity binding이다. Dataset source identity는 원천 Dataset을
안정적으로 식별하며, DatasetVersion ID나 publication pair fingerprint를 logical key로 대체하지 않는다.

[확정] Rights subject는 source Dataset, 특정 DatasetVersion 또는 derived artifact를 명시적으로 나타낼 수 있다. subject type과
parent/source binding은 record에 포함한다. 상위 subject의 권리를 하위 artifact에 암묵적으로 상속하지 않고, 해당 usage를 포괄하는
current record가 없거나 둘 이상이면 fail closed한다.

[확정] DatasetVersion·manifest·pair identity는 review/publication binding이다. pair fingerprint는 immutable evidence binding이지
Rights lifecycle key가 아니다.

## Rights record contract

canonical immutable Rights record는 최소 다음 의미를 가진다.

- source authority UUID, schema version와 immutable record ID
- stable Rights Subject ID, subject type와 Dataset source identity binding
- usage scope: internal Training, commercial use/Training, redistribution, model publication
- 각 scope의 allow/deny/limited 상태와 제한 조건
- effective time, optional expiry와 source provenance/evidence references
- issuer authority identity, issued timestamp와 audit correlation
- superseded/revoked 대상 record ID와 lifecycle reason(해당하는 경우)

[확정] raw legal document, consent body, credential, DSN과 private path는 record·snapshot·로그에 복제하지 않는다. 검증 가능한
opaque evidence reference만 저장한다.

## Lifecycle, mutation과 projection

[확정] history는 append-only다. lifecycle은 다음 둘 중 하나다.

- `ISSUED -> SUPERSEDED`
- `ISSUED -> REVOKED`

replacement는 새 immutable `ISSUED` record와 기존 record의 supersession event를 한 authority operation으로 발행한다. 기존
canonical row를 덮어쓰지 않는다. revoke는 immutable revoke event를 남기고 과거 record를 삭제하지 않는다.

[확정] logical subject마다 current record는 정확히 0 또는 1개다. missing은 permission이 아니며, 두 current record, broken chain,
projection/record mismatch 또는 unknown lifecycle은 fail closed한다. timestamp, array order, filesystem mtime과 process-local last
write로 current를 추론하지 않는다.

[확정] create, replacement와 revoke는 모두 `DohaRights dedicated Rights authority producer`만 수행한다. DohaRights가 durable
history와 unique-current projection을 소유한다. arbitrary DohaLM caller, Dataset reviewer·approver, manifest generator와 snapshot
coordinator는 mutation 권한이 없다.

[확정] audit에는 actor authority ID, action time, subject, scope, new/previous record, reason과 source authority identity를 남긴다.
같은 single-user local operator가 producer responsibility를 수행할 수 있다. 다만 authority producer credential과 DohaLM application
consumer credential은 분리하며, 동일 human 운영이 authority identity나 grant의 분리를 없애지 않는다.

## Authenticated read boundary

[확정] DohaLM은 construction-bound authenticated application adapter와 protected service credential을 통해 DohaRights의 최소 typed
port를 사용한다. conceptual operations는 다음 두 개뿐이다.

- exact subject key의 current immutable Rights record와 source-issued current token 읽기
- exact source token이 여전히 current인지 검증하기

[확정] DohaLM Dataset Governance principal은 scoped read와 currentness verification만 허용한다. create, replace, revoke, arbitrary
query, history dump와 credential delegation은 금지한다. direct cross-repository table query는 canonical integration이 아니다.
local deployment가 DB transport를 선택하더라도 dedicated read-only role과 owner-owned adapter contract를 거쳐야 한다.

[확정] unavailable, timeout, authentication/authorization failure, malformed response와 currentness ambiguity는 fail closed한다.
cache는 성능 최적화일 뿐 authority가 아니며 stale fallback은 금지한다.

## Composite CurrentEvidence snapshot

### Selected model

[확정] `SNAPSHOT_MODEL = Model C — source-issued tokens + composite snapshot`이다. independent reads only는 read 사이 revoke race를
막지 못해 기각한다. coordinator-only token은 source currentness를 증명할 owner-issued token이 없어 기각한다. cross-repository
distributed transaction은 ownership을 결합하고 filesystem publication까지 원자화하지 못하므로 요구하지 않는다.

[확정] 각 source authority는 exact immutable evidence identity·fingerprint와 current/version token을 발행한다. DohaLM Dataset
Governance Snapshot Coordinator는 이 토큰들을 검증하고 canonical composite payload를 만들어 immutable snapshot을 발행한다.
snapshot coordinator는 Rights writer가 아니며 source record를 수정하지 않는다.

### Snapshot contents and identity

composite snapshot은 최소 다음을 포함한다.

- snapshot schema/version와 immutable snapshot UUID
- logical proposal/publication subject, Dataset subject identity와 lifecycle correlation
- Dataset evidence identity·fingerprint·source authority identity·source token
- Rights subject identity, Rights record identity·fingerprint·DohaRights source authority identity·source token
- TrainingEligibility evidence가 사용되면 그 identity·fingerprint·authority identity·source token
- captured-at timestamp와 coordinator issuer identity

[확정] snapshot ID와 fingerprint는 구분한다. fingerprint는 repository의 기존 canonical JSON 원칙에 맞춘 sorted-key, UTF-8,
whitespace-independent canonical payload의 SHA-256이다. secret, credential과 transport token은 canonical payload에 포함하지 않는다.

[확정] 같은 idempotency request와 exact source tokens의 replay는 같은 snapshot ID와 fingerprint를 반환한다. 별도 issuance는 새 UUID를
가질 수 있지만 canonical evidence state가 같으면 fingerprint가 같을 수 있다. fingerprint가 같다는 사실만으로 authorization이나
currentness를 주장하지 않는다. snapshot token은 immutable evidence identity이며 capability가 아니다.

### Currentness and stale behavior

[확정] snapshot은 영구 current authority가 아니다. Review, Approval과 Publication은 exact snapshot ID와 fingerprint에 결속된다.
각 lifecycle transition은 source tokens가 current인지 재검증하며, atomic publication mutation 직전에는 모든 source token과 exact
proposal·review·approval binding을 다시 검증한다.

[확정] review 뒤 Rights revoke, Dataset evidence 교체, eligibility 교체, missing token 또는 source unavailable이 발생하면 기존
snapshot은 stale이다. publication은 실패하고 fresh evidence, snapshot과 필요한 review/approval을 요구한다. 부분적으로 새 token을
섞거나 caller payload로 대체하지 않는다.

## Publication and Training binding

[확정] Dataset review result, approval decision과 publication record는 동일한 exact composite snapshot UUID와 canonical SHA-256
fingerprint를 저장한다. publication pair는 이 binding을 freeze한다. 이 binding을 manifest 내부의 임의 metadata나 filename으로
대체하지 않는다.

[확정] publication 직전 revalidation은 다음을 모두 만족해야 한다.

1. proposal, review와 approval이 같은 exact snapshot에 결속된다.
2. source authority identities와 source tokens가 변경되지 않았다.
3. Rights record와 Eligibility가 현재이며 requested internal Training scope를 허용한다.
4. Dataset publication pair input identity와 snapshot subject가 일치한다.

[확정] post-publication Rights revoke는 역사적 publication과 그 snapshot evidence를 삭제하거나 다시 쓰지 않는다. 그러나 future
Training eligibility는 즉시 `NO`이며 새 current evidence 없이는 새 intent나 activation을 허용하지 않는다.

[확정] Training intent 생성과 activation은 각각 Rights currentness를 다시 검증한다. Dataset publication은 영구 usage grant가
아니다. intent 이후 activation 전에 revoke되면 activation은 fail closed한다.

## Candidate A permission boundary

[확정] Candidate A의 현재 승인 범위는 `internal production Training`뿐이다.

- commercial use: `NO`
- redistribution: `NO`
- external model publication: `NO`
- commercial model deployment: `NO`
- Dataset publication 또는 Training 성공이 위 권한을 암묵적으로 추가하는가: `NO`

해당 eligibility manifest와 source files는 DohaRights 발행 입력 evidence가 될 수 있으나 canonical Rights record나 current projection은
아니다. 실제 Candidate A Rights record 발행과 Dataset publication은 후속 implementation/provisioning Gate의 별도 mutation이다.

[확정] DohaMusic의 기존 voice consent/Rights 기능은 유지하며 DohaRights가 이를 임의로 supersede하지 않는다. 향후 voice Dataset을
Training에 사용할 때 DohaMusic·DohaVocal의 domain-specific consent evidence를 DohaRights Dataset Training Rights decision의
provenance로 연결한다. 이 evidence 연결도 DohaMusic·DohaVocal을 canonical Dataset Training Rights owner로 만들지는 않는다.

## Cross-repository responsibility

| 책임 | owner |
|---|---|
| Rights semantic·record issuance·replace·revoke | DohaRights |
| Rights durable history·unique-current projection·authenticated read | DohaRights |
| Common payload schema/validator compatibility | Common contract owner; authority lifecycle 소유권은 없음 |
| Dataset evidence·TrainingEligibility production | DohaLM Dataset Governance |
| source token 검증과 composite snapshot issuance | DohaLM Dataset Governance Snapshot Coordinator |
| Dataset review·approval·publication binding | DohaLM Dataset Governance |
| Training intent/activation currentness enforcement | DohaLM Production Training application boundary |
| files/manifests | evidence material only; authority 아님 |

## Implementation authorization and exclusions

[확정] 이 ADR의 병합은 다음 후속 구현 Gate 진입을 승인한다.

- DohaRights shared authority foundation과 append-only lifecycle/current projection
- DohaLM authenticated read port·adapter와 least-privilege composition
- source-issued token과 composite snapshot authority
- Dataset review·approval·publication exact snapshot binding
- post-publication 및 Training intent/activation currentness recheck

[제외] 이 ADR 자체에서는 production code, migration, database, credential, Rights record, snapshot record, Dataset publication,
PostgreSQL provisioning, Host/backend invocation과 Training workload를 생성하지 않는다. implementation merge는 실제 publication 또는
Training 실행 승인이 아니다. ruleset과 required checks도 변경하지 않는다.

## Historical blocker resolution

| predecessor | 당시 판정 | ADR-034 이후 상태 |
|---|---|---|
| ADR-027 | CurrentEvidence source `BLOCKED` | owner/source/snapshot architecture blocker resolved; runtime 구현은 후속 Gate |
| ADR-028 | Rights producer/authority·projection/snapshot `STILL BLOCKED` | final ownership과 Model C로 resolved |
| ADR-029 | owner·logical key·revoke/read authority `STILL BLOCKED` | DohaRights owner와 actor/read contract로 resolved |
| ADR-030 | `D. ORGANIZATIONAL OWNERSHIP STILL BLOCKED` | explicit organizational approval로 resolved |

[확정] 선행 ADR의 원래 상태와 당시 판정은 수정하지 않는다. 이 ADR은 그 기록을 소급 삭제하지 않고 이후 결정을 연결한다.

## Approval and acceptance

- [확정] production-critical 결정 필드에 미결정 표지가 없다.
- [확정] Rights authority, eligibility material, Dataset publication, snapshot과 commercial permission을 구분했다.
- [확정] append-only history, unique-current, authenticated read와 fail-closed source failure를 승인했다.
- [확정] Model C와 exact review·approval·publication binding, publication/Training currentness 재검증을 승인했다.
- [확정] 사용자 `DDORINY`가 2026-09-01 owner·identity·key·actors·snapshot·binding을 명시적으로 승인했다.
- [확정] 문서 상태와 결정 상태는 `approved`다. 구현 상태는 `not_implemented`다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-09-01 | [확정] DohaRights accountable owner, source identity, logical key, lifecycle actors, Model C composite snapshot, publication binding과 Training currentness recheck 승인 |
