# C1.2/C2 PostgreSQL Contract Alignment

- 문서 상태: `draft`
- 마지막 검토일: 2026-08-15
- 관련 결정: [ADR-021](../decisions/ADR-021-production-training-adapters-and-durable-journal.md)
- 범위: C1.2 port/DTO와 restricted database contract; C2 adapter·C3 composition·Production Activation 제외

## Architecture Freeze

[확정] future C2 adapter는 직접 table SQL, generic payload 추정, context variable 또는
resolver→journal hidden state 없이 아래 typed request/result만 사용한다. Host가 request ordering을
소유하고 PostgreSQL이 typed relationship, currentness, journal version과 reservation ownership을
반환한다.

| 작업 | 요청 | 응답 | authoritative boundary |
|---|---|---|---|
| prerequisite resolve | immutable Host intent와 Host가 계산한 intent fingerprint | DatasetVersion/Manifest/pair, config/readiness typed binding과 resolver policy | resolver role의 단일 REPEATABLE READ READ ONLY snapshot |
| decision resolve | composition-root-owned decision authority UUID, intent, canonical request fingerprint와 prerequisite snapshot binding | decision/issuer/approver currentness, evidence와 decision policy | resolver role의 단일 REPEATABLE READ READ ONLY snapshot |
| journal claim | complete immutable claim binding과 process boundary | complete durable record, reservation group와 version | journal role의 단일 READ COMMITTED transaction |
| journal transition | identity, process boundary, expected phase/version, target와 evidence/reason | complete version-advanced durable record | journal role의 expected phase/version CAS transaction |
| journal read | run ID | complete durable record 또는 not-found | journal role의 short-lived READ COMMITTED read transaction |

## End-to-End Field Matrix

| Field | 최초 생성 주체 | 기존 domain type | port 입력/출력 | DB typed source/function | C2 전달 경로 | persistence |
|---|---|---|---|---|---|---|
| run ID | Host intent | `ProductionTrainingHostIntent` | claim identity | journal PK / C2 journal functions | intent→request builder→claim DTO | yes |
| request fingerprint | existing request builder | `TrainingExecutionRequest` | claim identity | journal | builder→claim DTO | yes |
| intent fingerprint | Host canonical helper | `TrainingPrerequisiteResolutionRequest` | prerequisite request, claim DTO | journal | Host→resolver echo→claim | yes |
| orchestration correlation ID | Host, exact canonical run ID | `TrainingOrchestrationClaimRequest` | claim input/read output | journal UNIQUE/reservation | Host→claim DTO | yes |
| Dataset version ID | DatasetVersion authority payload verified by resolver | resolved prerequisites/claim DTO | prerequisite output/claim input | typed prerequisite snapshot | resolver→Host→claim | yes |
| Dataset manifest ID | DatasetManifest authority payload verified by resolver | resolved prerequisites/claim DTO | prerequisite output/claim input | typed prerequisite snapshot | resolver→Host→claim | yes |
| dataset-pair authority ID | PostgreSQL pair relationship | prerequisite snapshot result | prerequisite output | typed prerequisite snapshot | DB→resolver result | authority yes; journal no |
| pair fingerprint | dataset-pair authority | resolved prerequisites/claim DTO | prerequisite output/claim input | typed prerequisite snapshot | DB→resolver→claim | yes |
| config fingerprint | config payload SHA-256 | resolved prerequisites/claim DTO | prerequisite output/claim input | typed prerequisite snapshot | DB→resolver→claim | yes |
| readiness fingerprint | readiness payload SHA-256/report | resolved prerequisites/claim DTO | prerequisite output/claim input | typed prerequisite snapshot | DB→resolver→claim | yes |
| readiness evaluated/currentness | readiness producer + snapshot의 DB transaction clock/current projection | prerequisite snapshot result | prerequisite output | typed prerequisite snapshot | DB→resolver | authority yes |
| source commit | readiness authority producer | resolved prerequisites/claim DTO | prerequisite output/claim input | readiness typed row의 source commit | DB→resolver→claim | yes |
| prerequisite policy reference | construction-bound prerequisite resolver config | prerequisite provenance/claim DTO | prerequisite output/claim input | exact echo in journal | resolver→Host→claim | yes |
| decision ID | trusted composition configuration | decision resolution request/provenance | decision request/output | typed decision snapshot | composition root→Host→resolver | authority yes |
| authorization state | decision authority producer | issuer decision enum | decision output | typed decision snapshot | DB→resolver | journal bundle |
| issuer authority ID | issuer registry authority | decision snapshot result | decision output | typed decision snapshot | DB→resolver | authority yes |
| approver authority ID | approver registry authority | decision snapshot result | decision output | typed decision snapshot | DB→resolver | authority yes |
| evidence/reference bundle | decision authority producer | decision resolution/transition | decision output/transition input | typed decision snapshot/C2 transition | resolver→Host→journal | yes |
| process boundary ID | future composition root | claim/transition DTO | bootstrap-bound claim/transition input | journal/event | composition root→Host→journal | yes |
| journal phase | restricted journal function | orchestration enum | record/transition | journal projection | DB→adapter→Host | yes |
| journal version | PostgreSQL | journal record | record/expected version | journal CAS | DB record→next transition | yes |
| expected phase/version | last DB record, selected by Host | transition DTO | transition input | C2 transition CAS | record→Host→transition | no separate copy |
| reservation group ID | PostgreSQL claim function | journal record | claim/read output | reservation architecture | DB→adapter→Host | yes |

## Canonical Producer와 검증

- Adapter는 fingerprint, authority ID, correlation, process boundary 또는 policy reference를 만들지 않는다.
- Namespaced authority reference의 UUID는 resolver request에서 문법만 검증하고 DB relationship이 최종 권위다.
- Config/readiness payload와 typed columns는 한 snapshot에서 함께 반환되고 adapter가 exact mapping을 검증한다.
- Decision, issuer와 approver는 한 snapshot의 typed FK/currentness 결과로만 승인된다.
- Generic payload bytes는 typed binding과 checksum 검증을 통과한 뒤에만 domain parser 입력이 된다.

## Transaction과 오류

| 작업 | Role | Isolation | Connection | Commit owner | retry |
|---|---|---|---|---|---|
| prerequisite snapshot | resolver | REPEATABLE READ, READ ONLY | 호출별 short-lived | adapter | side effect 전 명시 정책만 |
| decision snapshot | resolver | REPEATABLE READ, READ ONLY | 호출별 short-lived | adapter | 자동 retry 없음 |
| claim | journal | READ COMMITTED | 호출별 short-lived | adapter | ambiguous outcome retry 금지 |
| transition | journal | READ COMMITTED | 호출별 short-lived | adapter | ambiguous outcome retry 금지 |
| read | journal | READ COMMITTED, READ ONLY 허용 | 호출별 short-lived | adapter | 자동 retry 없음 |
| setup/verification | bootstrap owner | 명시 transaction | 역할별 분리 | fixture | 없음 |

SQLSTATE와 named result column만 mapping한다. `40001` conflict/stale CAS, `XX001`
integrity failure, `42501` permission denial, `23514` invalid input/transition,
`25006` transaction contract 위반, `21000` typed relationship cardinality conflict로 분류한다.
Snapshot 0행은 missing, current projection 또는 validity가 부적합한 typed row는 stale로 분류한다. commit 결과가 불명확하면 자동 재호출하지
않고 manual reconciliation 대상으로 분류한다.

## Configuration 및 비활성 경계

[확정] process boundary, decision authority UUID와 resolver policy는 future C3 composition root가 trusted configuration에서
한 번 주입한다. C1.2는 DSN을 읽거나 connection을 만들지 않고 DTO와 DB function contract만
정의한다. C2 adapter, executable, actual credential, Production Activation과 Training은 이 문서의
범위가 아니다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-15 | [제안] C1.2/C2 field producer, typed snapshot, journal DTO와 transaction boundary 동결 |
