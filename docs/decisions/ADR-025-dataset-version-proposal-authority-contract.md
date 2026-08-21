# ADR-025: DatasetVersion Proposal Authority 계약

- 문서 상태: `draft`
- 결정일: 미결정
- 작성일: 2026-08-21
- 실행 영향: proposal lifecycle port·검증 service와 별도 승인된 PostgreSQL adapter 구현; 자동 activation·publication·Training 영향 없음

## 배경

- [확정] `ProductDatasetComposition`은 완전한 Common DatasetVersion `draft` mapping을 side effect 없이 만든다.
- [확정] 기존 `propose_dataset_version()`은 Common schema 검증과 immutable proposal 구성을 담당하는 순수 함수다.
- [확정] 동일한 `DatasetVersionIdentity`에 서로 다른 canonical proposal이 입력되어도 순수 함수만으로는 기존 proposal 조회, replay 또는 충돌을 판정할 수 없다.
- [확정] proposal 시점의 RightsMetadata와 TrainingEligibility가 current인지 확인하지 않으면 이전의 유효한 evidence로 revoked 또는 expired 상태를 우회할 수 있다.
- [확정] 이 결정은 DatasetVersion review·approval·publication보다 앞선 proposal authority 경계만 다룬다.

## 제안 결정

### 책임과 identity

- [제안] DohaLM Dataset Governance가 DatasetVersion proposal lifecycle의 authoritative owner다.
- [제안] authority lookup key는 기존 `DatasetVersionIdentity(object_id, dataset_id, dataset_version)`다. 별도 평행 identity를 만들지 않는다.
- [제안] caller는 완전한 DatasetVersion mapping, 명시적인 timezone-aware `proposed_at`, proposal authority와 current evidence authority를 모두 제공해야 한다.
- [제안] authority 또는 current evidence authority를 생략하는 fallback 경로는 없다.

### canonical proposal과 replay

- [제안] `propose_dataset_version()`이 검증·정규화한 immutable payload 전체의 canonical checksum이 proposal fingerprint다.
- [제안] `created_at`, producer, workspace, lineage, split·group, evidence와 Manifest identity를 포함한 canonical payload 차이는 proposal 차이다.
- [제안] adjudication 시각인 `proposed_at`과 authority metadata는 proposal payload가 아니므로 fingerprint에 포함하지 않는다.
- [제안] authority는 lookup과 put-if-absent를 하나의 atomic `compare_and_create` 연산으로 제공한다.
- [제안] identity가 없으면 `CREATED`, identity와 canonical fingerprint가 모두 같으면 기존 immutable object를 `REPLAYED`로 반환한다.
- [제안] identity가 같고 canonical fingerprint가 다르면 conflict로 실패하며 기존 proposal을 덮어쓰지 않는다.
- [제안] read-then-write, optional existing proposal, process-global cache 또는 caller의 lookup 생략 경로는 허용하지 않는다.

### current evidence

- [제안] current evidence authority는 canonical RightsMetadata와 TrainingEligibility authority를 조정하는 port다. 이 port가 evidence policy나 원본 객체 ownership을 가져오지 않는다.
- [제안] evidence는 명시적인 `proposed_at`을 기준으로 proposal identity와 fingerprint에 결속해 검증한다.
- [제안] `MISSING`, `EXPIRED`, `REVOKED`, `INVALID` 또는 identity mismatch는 proposal authority 호출 전에 fail closed한다.
- [제안] replay도 새 adjudication이므로 current evidence를 다시 검증한다. 과거 proposal의 존재가 currentness를 대체하지 않는다.

### 원자성과 구현 경계

- [제안] 구체 authority adapter는 동시 caller에 대해 단일 winner, 동일 proposal replay와 다른 proposal conflict를 원자적으로 보장해야 한다.
- [현재] 별도 승인된 후속 구현은 `dohalm_dataset_governance_v1` schema와 전용 least-privilege role에서 PostgreSQL atomic compare-and-create를 제공한다. 한 transaction이 canonical composite identity의 advisory lock 하나를 소유한 뒤 DB primary key로 create·replay·conflict를 판정하며 retry나 overwrite를 사용하지 않는다.
- [현재] adapter는 명시적 dependency injection으로만 사용할 수 있고 production composition 등록과 자동 activation은 여전히 후속 Gate다.
- [제안] authority 오류는 credential, raw payload 또는 개인 경로를 포함하지 않는 stable code로 fail closed한다.

## 상태 전이

| 기존 authoritative proposal | incoming canonical proposal | 결과 | mutation |
|---|---|---|---|
| 없음 | valid/current | `CREATED` | proposal 1개 생성 |
| 있음 | identity·fingerprint 동일 | `REPLAYED` | 없음; 기존 object 반환 |
| 있음 | identity 동일·fingerprint 다름 | conflict | 없음 |
| 무관 | evidence non-current 또는 mismatch | error | authority 호출 없음 |

`CREATED`와 `REPLAYED` 모두 `draft/approved=false/frozen=false/training_allowed=false`를 보존한다. 이 결과는 review, approval, publication 또는 Training 권한이 아니다.

## 제외 범위

- [제외] filesystem persistence adapter와 PostgreSQL adapter의 자동 runtime 등록
- [제외] composition root 또는 production runtime 등록
- [제외] DatasetVersion review·approval, DatasetManifest publication과 freeze
- [제외] Training request·approval·execution, Evaluation과 Model promotion
- [제외] RightsMetadata 또는 TrainingEligibility canonical authority의 재구현

## 대안 검토

- [기각] 순수 proposal 함수에 optional `existing`을 전달: caller가 조회를 생략할 수 있고 lookup과 create 사이 경쟁을 막지 못한다.
- [기각] process-local dictionary를 production authority로 사용: process restart와 multi-worker에서 authoritative identity를 보장하지 못한다.
- [기각] payload가 다르면 마지막 입력으로 overwrite: immutable lineage와 review 근거를 손상한다.
- [기각] replay에서는 evidence 재검증 생략: revoked·expired evidence로 lifecycle 진행이 가능해진다.

## 결과

- [제안] pure construction과 lifecycle authority 책임이 분리된다.
- [제안] 후속 adapter는 단일 atomic port를 구현해야 하며 caller나 composition에서 conflict 의미를 재구성하지 않는다.
- [확정] 이 ADR과 구현은 Dataset proposal만 다루며 Ready 전환, publication 또는 Training을 승인하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-21 | [현재] 별도 승인된 PostgreSQL durable adapter가 계약을 구현했으며 자동 activation은 제외됨을 정합화 |
| 2026-08-21 | [제안] DatasetVersionIdentity 기반 atomic create·replay·conflict와 proposal-time current evidence 재검증 계약 등록 |
