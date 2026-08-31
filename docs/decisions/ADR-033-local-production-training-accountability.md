# ADR-033: Local Production Training Accountability

- 문서 상태: `approved`
- 마지막 검토일: 2026-09-01
- 결정 상태: `approved`
- 승인 근거: 사용자의 `Production Dataset Eligibility + Non-Local Full-Pretraining Config Contract + Self-Approval ADR Remediation` 명시 요청
- 관련 문서: [ADR-032](./ADR-032-production-training-intent-authority.md), [Dataset eligibility material](../data/aihub-71748-candidate-a-internal-production-eligibility.manifest.yaml)

## Context

[확정] v1 production target은 single-user local/on-prem runtime이다. 여기서 `production`은 durable authority와 실제 backend를 사용하는 실행 topology를 뜻하며 commercial use나 public release를 뜻하지 않는다.

[확정] submitter, issuer, approver는 서로 다른 책임이다. 동일한 accountable local operator가 세 책임을 수행할 수 있는지와 동일 authority identity를 재사용할 수 있는지는 별개의 문제다.

## Decision

[확정] internal non-commercial production Training에는 `SAME_HUMAN_SEPARATE_AUTHORITY_IDENTITIES`를 적용한다. 동일한 accountable local operator가 세 역할을 수행할 수 있지만 submitter, issuer, approver authority UUID는 모두 달라야 한다.

[확정] domain validation은 issuer와 approver 충돌을 binding 생성 시 거부하고, execution validation은 submitter까지 포함한 세 UUID의 pairwise distinct를 요구한다. caller label, OS account 또는 같은 human이라는 사실은 authority identity가 아니다.

[확정] 이 정책은 internal non-commercial Training execution에만 적용한다. Dataset redistribution, commercial service, external publication과 model release를 승인하지 않는다.

## Dataset and config boundary

[확정] AIHUB-71748 Candidate A의 exact verified bytes는 별도 eligibility material에 결속한다. 학생·비상업 범위의 local internal full-pretraining만 허용하며 historical pilot/full execution approval은 재사용하지 않는다. actual Common Dataset publication은 fresh current-evidence review를 요구한다.

[확정] full-pretraining config는 `local_experiment`와 `production_internal`을 명시적으로 구분한다. production scope는 별도 Dataset eligibility material을 요구하고 publication, redistribution과 model release는 계속 false다.

## Consequences

- [확정] second human이나 외부 IAM 없이 v1 single-user runtime을 운영할 수 있다.
- [확정] 역할별 immutable provenance와 revoke/supersede lifecycle은 유지된다.
- [확정] production scope는 example flag 하나로 활성화할 수 없다.
- [제외] commercial/public action, multi-user IAM, actual authority provisioning과 Training execution.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-09-01 | [확정] internal non-commercial Training의 same-human/separate-authority 정책과 production config scope를 승인 |
