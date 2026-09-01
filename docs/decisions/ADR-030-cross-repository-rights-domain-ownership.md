# ADR-030: Cross-repository Rights domain ownership 결정 Gate

- 문서 상태: `draft`
- 마지막 검토일: 2026-09-01
- 결정 상태: `proposed`
- 실행 영향: 없음
- 기준 DohaLM commit: `5127d594869b289ec60ed414dcdfcd22b32bb031`
- 기준 DohaLM tree: `bc023d67b95e56c8e0699ee81925a4b1cd653011`
- Common 권위 기준: `DohaStudio/.github@dd75fc88c16e9ae9a04acfafb72756a905f6365b`
- 선행 ADR: [ADR-028](./ADR-028-current-evidence-source-authority.md),
  [ADR-029](./ADR-029-rights-metadata-ownership-authority.md)
- 후속 결정: [ADR-034](./ADR-034-cross-repository-rights-authority-and-current-evidence-snapshot.md)
- 관련 문서: [데이터 라이선스 정책](../data/data-license-policy.md),
  [제품 지속 학습 경계](../project/ai-music-director-continuous-learning.md),
  [Rights Owner Decision Request](./rights-owner-decision-request.md)

## Context

[현재] ADR-029는 source-level Rights authority가 적합한 방향임을 확인했지만 accountable business owner, canonical producer,
logical source identity, create·replacement·revoke writer, durable authority, current projection과 authenticated read owner를 찾지
못해 `STILL BLOCKED`로 판정했다. 이번 Gate는 코드나 저장소 배치를 설계하기 전에 기존 owner를 확정할 수 있는지, 새
cross-repository Rights domain이 필요한지, DohaLM이 owner여야 하는지, 또는 조직 결정이 계속 필요한지를 판정한다.

[현재] 조사 범위는 접근 가능한 여섯 저장소의 고정 commit과 Common contract다. production source, test, migration, runtime,
CLI/API/worker, 다른 repository와 Common package는 변경하지 않는다.

## 조사 기준과 coverage

| repository | 조사 commit | 조사 범위 | coverage 한계 |
|---|---|---|---|
| `DohaStudio/DohaLM` | `5127d594869b289ec60ed414dcdfcd22b32bb031` | Rights consumer, Dataset governance, CurrentEvidence | 이 ADR branch의 선행 문서는 별도 Draft PR 상태 |
| `DohaStudio/DohaMusic` | `63633d462043ad3ba78fee92473d19e90c361431` | Workspace, Asset, voice consent, provider boundary | `main` 문서·코드 기준; 조직 승인 문서 아님 |
| `DohaStudio/DohaAudio` | `5133c49c91c4928878d254de47bd0c0c39d21358` | audio Dataset·Artifact·Provider ownership | source-wide Rights service 없음 |
| `DohaStudio/DohaVocal` | `932466adb435b2a987baacdbefd2361470a2a7fa` | vocal lineage, consent·deletion boundary | 문서가 `[제안]` 또는 `[계획]` 상태 |
| `DohaStudio/DohaMusicBook` | `4235b9d8e262d3a6155b125aaa3688d29099837a` | Rights 교육·설계 문서 | Runtime·authority 저장소가 아님 |
| `DohaStudio/.github` | `dd75fc88c16e9ae9a04acfafb72756a905f6365b` | Common RightsMetadata schema·ADR·용어 | ADR·specification이 `draft`·`제안`; Runtime data owner 아님 |

[현재] 공개 조직 repository 목록에는 위 여섯 개만 보이며 별도 Rights, Licensing, Consent 또는 source registry repository는
없다. private/local unavailable repository, 조직 정책과 실제 legal accountability는 repository evidence만으로 부재를 증명할
수 없다. GitHub code search coverage와 ACL warning도 조사 한계로 남긴다.

## Rights scope

[제안] Rights domain의 business scope는 `Rights/Licensing + purpose-scoped Consent Management`다. source의 생성·업로드·외부
도입 근거, 분석·학습·파생 생성·재배포·보관 허용, jurisdiction, expiry·revocation과 evidence reference를 source 수준에서
관리해야 한다.

[현재] Consent는 권리 판정의 입력 또는 evidence이며 전체 Rights와 같지 않다. 음성 녹음·처리·학습·공개 consent는 서로
다르고, audio sample/license, 외부 Dataset 약관, 생성물 이용 조건과 저작권 검토는 consent만으로 표현되지 않는다. 반대로
RightsMetadata의 Boolean만으로 consent 원문·주체 인증·철회 command를 대신할 수 없다.

## Source-level과 Dataset-level 경계

| 기준 | Source-level Rights | Dataset-level governance |
|---|---|---|
| 대상 | 재사용 가능한 원본·업로드·생성·reference source | 특정 DatasetVersion의 후보·member 집합 |
| 생성 시점 | source 등록·검토·권리 변경 | candidate review·Dataset proposal·publication |
| current 판정 | replacement·expiry·revoke를 전 제품에 반영 | upstream current 판정을 exact historical binding과 함께 소비 |
| 재사용 | Music·Audio·Vocal·LM이 같은 source chain을 참조 | Dataset마다 별도 local copy를 만들면 drift 발생 |
| owner 방향 | cross-product business domain | DohaLM Dataset governance |

[제안] canonical Rights owner는 source-level이어야 한다. DohaLM Dataset proposal이 RightsMetadata를 생성하거나 복제해 새 source
of truth로 만드는 모델은 기각한다. DatasetVersion approval도 item-level Rights와 Consent를 덮어쓰지 않는다.

## Repository 분석

### DohaMusic

[현재] Common draft와 DohaMusic 문서는 사용자·Workspace·Asset·Provider orchestration, voice consent·접근·삭제 결정과 최종
선택을 DohaMusic 방향으로 둔다. 이는 existing owner의 가장 강한 후보 증거다.

[현재] 그러나 voice consent policy는 인증 없는 local MVP의 `consent_confirmed`, policy version과 확인 시각만 구현됐다고
명시한다. `consent_records`, authenticated subject, withdrawal API, revoked state, pending-job stop, derivative/cache/model deletion과
감사 흐름은 공개 운영 전 요구사항이다. physical voice profile deletion은 canonical Rights revoke event가 아니다. Workspace
Asset ID도 provider Dataset·external source까지 포괄하는 승인된 stable source identity가 아니다.

[판정] `PROPOSED OWNER — REQUIRES CROSS-REPOSITORY AND ORGANIZATIONAL APPROVAL`. 기존 확정 owner로 승격하지 않는다.

### DohaAudio

[현재] DohaAudio는 audio Dataset, training, evaluation, Model Manifest와 Provider Runtime의 기술 책임을 가진다. Dataset
`licenses` 영역은 출처·약관·저작권·상업 이용 evidence를 보관하는 provider-local lifecycle이다. 사용자·Workspace·Asset과
전체 source Rights는 명시적 비목표다.

[판정] audio-specific evidence producer 또는 영향 소비자 후보이며 cross-product Rights business owner가 아니다.

### DohaVocal

[현재] DohaVocal은 vocal Dataset 기술 계보와 승인된 입력의 처리를 맡고, 사용 권한 최종 판단·삭제 결정은 DohaMusic에 둔다.
ADR-003과 Consent 문서는 모두 제안 상태이며, 실제 Rights producer·writer·projection·read service는 없다.

[판정] vocal lineage/effect executor 후보이며 Rights owner 또는 revoke authority가 아니다.

### DohaMusicBook

[현재] DohaMusicBook은 Copyright·Ownership·License, Dataset·Model·Voice 권리와 release checklist를 가르치는 학습·설계
문서다. `UNKNOWN/BLOCKED` fail-closed 원칙과 evidence 양식을 제공하지만 Runtime, DB, writer, IAM 또는 authority contract는
소유하지 않는다.

[판정] policy education/reference이며 production owner가 아니다.

### DohaLM

[현재] DohaLM은 Common RightsMetadata를 validate하고 LearningCandidate·TrainingEligibility·Dataset governance에 exact ID로
결속하는 consumer다. Dataset licensing review와 publication은 LM Dataset 범위이며 cross-product source 등록, user consent,
external asset ingest 또는 legal review를 소유하지 않는다.

[판정] `C. DOHALM OWNERSHIP REQUIRED`를 기각한다. DohaLM 소유는 Dataset-local duplicate source of truth와 revoke drift를 만든다.

### New cross-repository Rights domain

[제안] source registry, licensing/consent workflow, immutable Rights history, current projection, authenticated read와 revoke propagation을
한 business domain에 모으는 `B. NEW CROSS-REPOSITORY RIGHTS DOMAIN REQUIRED`는 기술적으로 가장 응집도 높은 후보다.

[현재] 그러나 domain의 accountable organizational/legal actor, repository 생성 권한, 운영 예산, source registration owner와
각 product의 동의가 없다. 이 ADR이 새 조직 책임이나 repository를 일방적으로 생성할 수 없다.

[판정] `LEADING ARCHITECTURE ALTERNATIVE — NOT APPROVED`.

## Business owner와 repository owner

| 항목 | 판정 | 근거 |
|---|---|---|
| accountable business domain | `BLOCKED` | Rights/Licensing+Consent scope는 식별했으나 조직 actor 미승인 |
| existing repository owner | `NOT CONFIRMED` | DohaMusic은 가장 강한 후보지만 문서 상태·범위·구현이 부분적 |
| new domain owner | `NOT APPROVED` | architecture fit은 높으나 organizational/legal owner 없음 |
| DohaLM owner | `REJECTED` | Dataset consumer가 source-wide legal authority를 소유하면 경계 위반 |
| repository placement | `BLOCKED` | business owner 승인 전 기존/신규 repository를 확정하지 않음 |

## Source identity와 logical Rights key

[현재] Common `rights_metadata_id`는 immutable record ID이지 replacement chain의 logical key가 아니다. Common `object_id`,
DohaMusic `asset_id`/`asset_version_id`, Provider artifact ID, LearningCandidate ID와 DatasetVersionIdentity도 서로 다른 lifecycle과
namespace를 가진다.

[제안] future owner는 최소 다음 성질의 stable source identity를 발행해야 한다.

- product와 Dataset membership에서 독립적이다.
- source가 여러 Workspace·Project·Dataset에서 재사용되어도 동일하다.
- content checksum 변경, AssetVersion과 provider-local Artifact를 identity와 구분한다.
- private evidence·path·PII를 공개 key에 포함하지 않는다.
- merge/split/import alias와 duplicate resolution 정책을 가진다.

[현재] 구체 key 형태, namespace issuer, alias authority와 collision policy는 owner가 없으므로 `BLOCKED`다. 임시
`(repository, asset_id)`, filename, checksum, candidate ID 또는 `rights_metadata_id`를 canonical logical key로 채택하지 않는다.

## Event와 writer 경계

| event | 의미 | trigger 후보 | canonical writer | 현재 판정 |
|---|---|---|---|---|
| create | stable source에 첫 Rights record 발행 | source intake+evidence review 완료 | owner-local restricted producer | `BLOCKED` |
| replacement | correction, scope·expiry·evidence 변경으로 새 immutable record 발행 | 승인된 review/change request | owner-local replacement writer | `BLOCKED` |
| revocation | 기존 허용의 effective-time 철회와 영향 재평가 시작 | subject withdrawal, license termination, legal/policy action | authenticated revoke command+owner producer | `BLOCKED` |

[제안] product/Provider는 request 또는 evidence를 제출하고 영향을 처리할 수 있지만 canonical event를 직접 쓰지 않는다.
Reviewer는 판단 actor일 수 있으나 persistence writer와 동일하다고 가정하지 않는다. writer는 authenticated organizational actor,
reason/evidence, effective time, predecessor와 idempotency/correlation을 검증한 뒤 append-only event와 projection을 원자적으로
갱신해야 한다.

### Revocation trigger와 propagation

[제안] trigger 유형은 subject withdrawal, consent expiry, contract/license termination, evidence invalidation, legal hold/policy decision,
owner correction을 구분해야 한다. trigger vocabulary, 누가 각 trigger를 승인하는지와 emergency revoke 권한은 조직 승인이
필요하므로 미확정이다.

[제안] revocation은 Rights history를 삭제하지 않는다. current projection을 fail-closed 상태로 전이하고 affected source lineage,
Dataset eligibility, pending job, Runtime use, retention/deletion executor에 영향 재평가를 전달해야 한다. 각 repository는 local
effect를 수행하고 완료·실패 evidence를 돌려주되 Rights truth를 독립 변경하지 않는다.

## Durable authority와 current projection

[제안] future authority는 다음 불변 조건을 만족해야 한다.

1. immutable Rights resource와 append-only create/replacement/revoke event를 보존한다.
2. stable logical source key마다 current record가 최대 하나다.
3. replacement chain은 single root/tip, no branch/merge/cycle/self-reference를 강제한다.
4. event와 current projection 갱신은 동일 commit boundary를 가진다.
5. historical as-of read와 current read를 구분한다.
6. authority/projection revision, selected Rights ID와 effective time을 반환한다.
7. unknown, missing, revoked, expired, conflict, corrupt와 unavailable을 fail closed한다.

[현재] storage technology, DB schema, service와 owning repository는 `BLOCKED`다. Common repository는 schema·validator authority이지
Runtime durable authority나 current projection owner가 아니다. DohaLM PostgreSQL Dataset governance를 cross-product Rights DB로
확장하지 않는다.

## Read contract와 boundary

| boundary | 장점 | 위험 | 판정 |
|---|---|---|---|
| owner DB direct read | transaction snapshot 가능 | cross-repo DB coupling·credential 확대 | 미선택 |
| authenticated service API | owner-local storage 은닉, policy·authorization 중앙화 | service availability·snapshot protocol 필요 | 선호 후보, 미승인 |
| signed registry/manifest | immutable 배포와 offline 검증 | current pointer·revoke freshness·CAS 필요 | 보조 evidence 후보 |
| Dataset-local copy/cache | 단순한 local read | stale revoke·이중 source of truth | canonical authority로 기각 |
| 미정 | 근거 없는 topology 확정 방지 | runtime activation 차단 | `D. READ CONTRACT BLOCKED` |

[제안] new domain이 승인된다면 authenticated service API가 기본 후보이고 immutable signed snapshot은 보조 evidence 후보다.
그러나 owner와 topology 승인 전 API·DB·registry 중 하나를 확정하지 않는다.

## Authentication과 authorization

[제안] read/write 모두 anonymous 또는 caller-asserted identity를 금지한다. future contract는 workload identity, authenticated human
or service actor, owner-managed trust anchor, credential rotation·revocation과 audit correlation을 요구한다. mTLS, OIDC 또는 다른
구체 mechanism은 운영 owner가 선택한다.

[제안] authorization은 최소 action, workspace/tenant, source scope, purpose와 evidence sensitivity를 검사한다. DohaLM은
least-privilege current/snapshot read만 받고 create·replace·revoke 권한을 갖지 않는다. private consent evidence 원문은 opaque
reference로 남기며 일반 Rights consumer가 읽지 않는다.

[현재] identity provider, role roster, workspace mapping, emergency actor와 secret owner가 없어 authentication·authorization owner는
`BLOCKED`다.

## Consent integration

[제안] Consent system은 subject identity, scope, purpose, expiry, withdrawal과 private evidence를 소유하고 Rights domain은 해당
authority reference와 current outcome을 목적별 Rights 판정에 결속한다. 한 service로 합칠지 별도 bounded context로 둘지는
organizational owner가 결정한다.

[현재] DohaMusic voice consent row를 모든 Rights source의 consent authority로 승격하지 않는다. DohaVocal/Audio/LM은 consent
evidence 원문을 복제하지 않고 required reference와 decision만 소비해야 한다.

## Cross-product reuse와 event notification

[제안] source identity와 Rights current projection은 product-neutral이어야 하며 product-local AssetVersion·Artifact·candidate와
mapping을 통해 연결한다. mapping의 issuer와 lifecycle도 source identity owner가 승인해야 한다.

[제안] revoke/replacement notification은 빠른 영향 처리를 위해 필요하지만 correctness authority는 notification이 아니라 owner의
current read다. event delivery가 누락되어도 invocation·publication 전 fresh current read가 fail closed해야 한다. outbox, queue,
webhook, polling과 retry/DLQ 방식은 authority contract 이후 결정한다. 따라서 notification은 future invalidation latency와 운영
효율을 위한 후속 기능이며 CurrentEvidence correctness 또는 첫 Runtime activation의 독립 선행 조건으로 두지 않는다.

## Snapshot metadata

[제안] 후속 CurrentEvidence Snapshot Gate는 최소 logical source key, selected `rights_metadata_id`, positive authority revision,
positive projection revision, state/effective time, purpose, workspace authorization context와 read timestamp를 요구해야 한다.
snapshot token은 여러 authority를 한 관찰점에 결속해야 할 때의 추가 후보이며 이번 Gate의 필수 field로 확정하지 않는다. 실제
field, atomicity, TTL과 Publication fingerprint 결속은 후속 Gate가 결정한다.

[현재] positive snapshot metadata와 revoke freshness를 제공할 owner가 없으므로 ADR-028의 cross-source snapshot과 ADR-015
Publication binding은 계속 `BLOCKED`다.

## Common boundary와 schema change

[현재] Common package는 RightsMetadata payload 의미, immutable ID, status·purpose flags와 validation을 소유한다. product producer,
source registry, DB, current selector, IAM, audit, notification과 legal workflow는 소유하지 않는다. draft ADR의 DohaMusic 방향은
cross-repository consent를 얻은 operational ownership 승인이 아니다.

[현재] Common v1에는 stable logical source key, predecessor/supersedes, authority/projection revision과 current snapshot metadata가
없다. 다만 이 정보가 canonical payload field인지 owner-specific authority envelope인지 결정할 owner가 없다.

[판정] Common schema change는 `BLOCKED`, `NOT YET DETERMINABLE`이다. owner·source identity·read contract가 승인된 뒤 Common
interoperability가 요구하면 `.github` 별도 ADR·PR과 version migration으로 결정한다. DohaLM convenience field를 먼저 추가하지
않는다.

## Ownership matrix

| 항목 | DohaMusic | DohaAudio | DohaVocal | New Rights Domain | DohaLM |
|---|---|---|---|---|---|
| source ownership | Workspace Asset partial | provider-local audio | provider-local vocal | cross-product 후보 | Dataset candidate/member만 |
| consent | voice consent partial | 소비자/영향 처리 | voice effect·lineage | consent reference 통합 후보 | 소비자 |
| licensing | product metadata partial | audio Dataset evidence | vocal Dataset evidence | 중앙 workflow 후보 | LM Dataset review만 |
| revocation | voice withdrawal 미구현 | local effect 후보 | local effect 후보 | canonical owner 후보 | fail-closed consumer |
| cross-product | Workspace 중심 | audio 한정 | vocal 한정 | 가장 적합 | LM 한정 |
| stable identity | Asset identity는 부분 범위 | provider identity | provider identity | 발행 필요 | source identity 없음 |
| security | 인증 없는 local MVP 한계 | owner IAM 없음 | owner IAM 없음 | 새 IAM 필요 | read-only least privilege 필요 |
| audit | voice audit 미구현 | provider evidence | 제안 문서만 | 중앙 audit 후보 | consumption audit만 |
| operational fit | strongest existing 후보 | 부적합 | 부적합 | leading architecture 후보 | 부적합 |

## Writer matrix

| 항목 | Source ingest | Rights service | Consent service | DohaLM | Human/legal |
|---|---|---|---|---|---|
| create | evidence/request 제출 | canonical writer 후보 | consent ref 제공 | 쓰기 금지 | review·approval actor 후보 |
| replace | change request 제출 | canonical replacement writer 후보 | changed consent ref 제공 | 쓰기 금지 | correction/scope 승인 후보 |
| revoke | trigger 전달 | canonical revoke writer 후보 | withdrawal authority 후보 | 쓰기 금지 | license/legal/policy trigger 후보 |
| auditability | ingest provenance | event+projection audit 필요 | private evidence audit | read/decision audit | actor·reason evidence 필요 |
| authority fit | source identity 미정 | 가장 적합하나 owner 미승인 | consent에 한정 | 부적합 | command 승인과 persistence 분리 |

[판정] 세 event의 canonical writer와 human/legal organizational actor는 모두 `BLOCKED`다.

## Read matrix

| 항목 | DB role | Service API | Registry |
|---|---|---|---|
| cross-repo isolation | 낮음; DB 결합 | 높음; owner 경계 유지 | 중간; 배포 contract 필요 |
| workspace auth | role/RLS 설계 필요 | owner가 중앙 강제 가능 | signed payload만으로 부족 |
| revision metadata | transaction에서 제공 가능 | response envelope로 제공 가능 | manifest/pointer로 제공 가능 |
| availability | DB failure domain 공유 | service SLA·retry 필요 | stale/revoke freshness 위험 |
| deployment | credential·schema coupling | 별도 service 운영 필요 | publisher·distribution 필요 |
| least privilege | dedicated read role 필요 | purpose-scoped endpoint 가능 | artifact access 범위가 거칠 수 있음 |

[판정] read interface는 `D. BLOCKED`. 새 Rights domain 승인 시 `B. authenticated service API`가 우선 후보이며 `C. shared
registry`는 signed snapshot/evidence 보조 후보, `A. direct DB role`은 owner-local transaction 요구가 확인될 때만 재검토한다.

## Final responsibility decisions

| 결정 항목 | 판정 |
|---|---|
| Business Domain | `BLOCKED`; 의미 범위는 Rights/Licensing+Consent Management |
| Repository owner | `BLOCKED`; DohaMusic proposed owner 또는 new domain 모두 cross-repository approval 필요 |
| Source identity owner | `BLOCKED` |
| Rights logical key | `BLOCKED` |
| Create writer | `BLOCKED` |
| Replacement writer | `BLOCKED` |
| Revocation writer | `BLOCKED` |
| Durable authority | `BLOCKED` |
| Current projection owner | `BLOCKED`; history와 같은 authority boundary 권장 |
| Read contract owner | `BLOCKED`; future owner domain이어야 함 |
| Read boundary model | `D. BLOCKED`; 승인 후 `B` 우선 후보 |
| Common schema change | `BLOCKED`; authority envelope 대 Common field 책임 미결정 |
| Cross-repository approval | `REQUIRED` |
| Overall | `STILL BLOCKED` |

## Options and final decision

| option | 판정 | 이유 |
|---|---|---|
| `A. EXISTING DOMAIN OWNER CONFIRMED` | 기각 | DohaMusic 방향은 강하지만 전체 source 범위와 조직 승인이 없음 |
| `B. NEW CROSS-REPOSITORY RIGHTS DOMAIN REQUIRED` | 유력 후보, 미승인 | 기술적 응집도는 높지만 accountable actor·repository consent 없음 |
| `C. DOHALM OWNERSHIP REQUIRED` | 기각 | Dataset consumer 범위를 넘고 cross-product revoke drift 발생 |
| `D. ORGANIZATIONAL OWNERSHIP STILL BLOCKED` | **선택** | code로 organizational/legal owner와 source identity를 확정할 수 없음 |

## Cross-repository approval Gate

[판정] cross-repository approval은 `REQUIRED`, 현재 `NOT OBTAINED`다. 최소 다음 명시 승인이 필요하다.

1. accountable Rights/Licensing business owner와 organizational/legal actor
2. DohaMusic 확장 또는 새 Rights domain 중 repository placement
3. source identity namespace와 mapping issuer
4. create·replacement·revoke policy owner와 emergency actor
5. durable authority/current projection/read contract 운영 owner
6. DohaMusic·DohaAudio·DohaVocal·DohaLM consumer/effect 책임
7. Common contract 변경 여부를 결정할 cross-repository schema approval 경로

승인이 owner·identity·writers·authority·read owner를 모두 채우면 다음 Gate는 `READY FOR RIGHTS AUTHORITY CONTRACT`로 전환할 수
있다. 단순히 여러 repository가 문서를 읽었다는 사실이나 한 Draft PR merge는 approval을 대신하지 않는다.

### Approval evidence 재검증

[현재] `ceaf1ba3f754647a33a1a0750ef61428b6f7132f` 기준 후속 Gate는 최신 공개 `develop`, accepted/approved ADR,
병합 architecture PR, authority 문서와 GitHub issue approval record를 재검증했다. DohaMusic ADR-038·PR #109와 DohaAudio
ADR-012·015·PR #15는 reviewer identity, assertion issuer와 semantic ReviewerAuthority만 승인한다. 각 문서는 authentication과
semantic approval을 Rights approval에서 분리하므로 source-wide Rights owner 승인으로 확대할 수 없다.

[현재] Common ADR·RightsMetadata specification, DohaVocal consent 결정과 DohaMusic voice consent policy는 여전히
`draft`·`제안`·`계획`이다. DohaLM PR #160·#162도 조직 승인이 없다는 blocker를 명시하며, owner/team·scope·provenance를
갖춘 별도 issue approval record는 찾지 못했다. 따라서 Option D와 `STILL BLOCKED`를 유지하고 구체적인 승인 요청은
[Rights Owner Decision Request](./rights-owner-decision-request.md)에 기록한다.

## Overall readiness

[최종] `STILL BLOCKED`.

business domain owner, logical source identity, revoke authority, projection owner와 read contract owner가 모두 미정이다. 따라서
Rights Authority port, adapter, migration, service API, runtime composition, CurrentEvidence snapshot, Publication binding과 production
activation을 시작하지 않는다.

## ADR strategy

[제안] 이번 결과는 ADR-029를 외부 구현 결정으로 확대하지 않고 별도 ADR-030에 보존한다. 새 Rights domain은 제안 후보로만
기록하며 repository 생성이나 다른 저장소 ADR·PR을 만들지 않는다. 조직 승인이 내려오면 다음 cross-repository ADR이 owner,
source identity, writer와 authority/read responsibility를 승인하고 ADR-030을 후속 결정으로 대체하거나 해소한다.

## Excluded scope

- [제외] production source, test, migration, runtime, CLI/API/worker 변경
- [제외] Rights service, DB, registry, source identity와 event schema 구현
- [제외] Common schema/package 변경
- [제외] 다른 repository 변경, branch, commit과 PR
- [제외] 조직·법무 owner, reviewer roster, IAM provider와 credential mechanism 임의 지정
- [제외] snapshot protocol, Publication payload와 runtime activation

## Acceptance and approval Gate

- [제안] 여섯 repository를 고정 commit 기준으로 조사했다.
- [제안] Rights와 Consent, source-level과 Dataset-level 책임을 분리했다.
- [제안] existing partial responsibility를 confirmed owner로 과장하지 않았다.
- [제안] 새 Rights domain의 architecture fit과 조직 승인을 분리했다.
- [제안] source identity, writers, durable authority, projection, read/auth와 Common change를 각각 판정했다.
- [제안] 전체 결과를 `D. ORGANIZATIONAL OWNERSHIP STILL BLOCKED`로 fail closed했다.
- [제안] production source·test·migration·runtime과 다른 repository 변경은 0이어야 한다.

이 ADR은 `draft`·`proposed`다. 사용자 승인과 merge 전 authoritative organization decision이 아니며, merge되더라도 새
repository, Rights authority implementation, Common 변경, runtime activation 또는 Training을 승인하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-09-01 | [후속] 명시적 조직 승인과 ADR-034가 shared DohaRights domain을 선택해 당시 Option D blocker를 해소; 원래 조사·판정은 역사 기록으로 보존 |
| 2026-08-25 | [현재] accepted ADR·병합 PR·authority 문서·issue approval을 재검증하고 authentication 부분 승인과 전체 Rights ownership을 분리; Decision Request와 Option D 유지 |
| 2026-08-25 | [제안] cross-repository Rights owner 후보를 비교하고 조직 owner·source identity·writer·authority/read 미확정으로 Option D와 `STILL BLOCKED` 판정 |
