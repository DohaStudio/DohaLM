# Production CurrentEvidence와 DohaRights 통합

- 상태: `implemented`
- 기준 결정: [ADR-034](../decisions/ADR-034-cross-repository-rights-authority-and-current-evidence-snapshot.md)
- canonical Rights owner: `DohaStudio/DohaRights`

## 책임 경계

DohaRights는 stable source-authority UUID, Rights Subject, append-only issue·supersede·revoke history,
unique-current projection과 owner-issued token을 소유한다. DohaLM은 producer credential을 받지 않으며
`doharights_reader`로 `get_current_rights`와 `verify_rights_token` 함수만 호출한다. source 장애,
authentication/authorization 실패, missing·multiple current, malformed response와 stale token은 모두
fail closed이다. eligibility manifest나 filesystem은 Rights authority fallback이 아니다.

## Model C snapshot

`DatasetGovernanceSnapshotCoordinator`는 caller가 전달한 raw token을 받지 않는다. Dataset evidence
authority와 DohaRights authority를 직접 호출해 각 owner-issued token을 얻고 immutable snapshot으로
고정한다. snapshot은 UUID, proposal·Dataset·Rights identity, 두 source token, capture time과 coordinator
identity를 포함하며 sorted-key UTF-8 canonical JSON의 SHA-256 fingerprint를 사용한다.

`0008_current_evidence_snapshot.sql`은 snapshot, review·approval·publication lifecycle binding과 readiness
binding을 append-only authority로 보존한다. coordinator와 resolver role은 분리되며 resolver는 write할 수
없다. snapshot은 capability가 아니며 source token 둘이 계속 current일 때만 사용할 수 있다.

## Dataset lifecycle와 Training

review, approval, publication은 같은 snapshot ID/fingerprint를 결속한다. 다음 단계는 직전 binding equality와
두 source token currentness를 다시 확인한다. publication 직전 검증이 실패하면 publication mutation은 시작하지
않는다. historical publication은 revoke 뒤에도 삭제하지 않지만 future Training eligibility는 즉시 거부한다.

ADR-032의 11-field `TrainingExecutionRequest v1` fingerprint는 변경하지 않는다. production readiness authority가
exact snapshot을 결속하고, intent submission과 `activate()`의 journal/Host 진입 직전 각각 currentness를
검증한다. intent 승인 후 Rights가 revoke되면 journal reservation, Host와 backend 호출 전에 실패한다.

## 비밀과 runtime 상태

production credential, DSN, raw legal document와 transport secret은 snapshot·로그·Git에 저장하지 않는다.
이 구현 merge는 authority schema와 application boundary만 활성화한다. production DohaRights PostgreSQL,
Candidate A Rights record, Dataset publication, Training intent와 workload는 생성하지 않는다.
