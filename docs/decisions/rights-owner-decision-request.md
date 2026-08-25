# Cross-Repository Rights Owner Decision Request

- 문서 상태: `review`
- 마지막 검토일: 2026-08-25
- 결정 상태: `decision_required`
- 현재 판정: `D. ORGANIZATIONAL APPROVAL STILL BLOCKED`
- 실행 영향: 없음
- 기준 DohaLM develop: `ceaf1ba3f754647a33a1a0750ef61428b6f7132f`
- 기준 DohaLM tree: `93e091f9aa89b745c7353d2de13adfa4408c6180`
- 선행 결정: [ADR-028](./ADR-028-current-evidence-source-authority.md),
  [ADR-029](./ADR-029-rights-metadata-ownership-authority.md),
  [ADR-030](./ADR-030-cross-repository-rights-domain-ownership.md)

## 목적

RightsMetadata의 source-wide accountable owner와 운영 책임을 조직 소유자가 명시적으로 선택하도록 요청한다. 이 문서는
승인을 추론하거나 대신하지 않는다. 승인된 owner, scope와 provenance가 기록될 때까지 production Rights authority와 이를
요구하는 CurrentEvidence·Publication binding·Runtime Activation은 fail closed 상태를 유지한다.

## Approval evidence 재검증

2026-08-25에 접근 가능한 DohaStudio 공개 저장소의 최신 `develop`, 병합 PR, accepted/approved ADR, authority 문서와 GitHub
issue를 조사했다.

| evidence | 상태 | 확인된 범위 | Rights owner 승인으로 사용할 수 없는 이유 |
|---|---|---|---|
| `DohaStudio/.github` ADR-001, RightsMetadata specification, PR #5 | `draft`·`제안`, PR merged | Common payload·validator와 제안된 DohaMusic runtime-data 방향 | PR #5가 draft/proposal이며 production ownership 승인이 아님을 명시 |
| `DohaStudio/DohaMusic` ADR-038, PR #109 | `승인`·merged | product/reviewer identity, delegated assertion issuer, service identity | authentication은 Rights approval과 분리되며 Rights owner·writer·authority를 결정하지 않음 |
| `DohaStudio/DohaAudio` ADR-012·015, PR #15 | `Accepted`·merged | semantic ReviewerAuthority, DohaMusic assertion 검증과 private mapping | semantic approval과 Rights approval을 명시적으로 분리함 |
| `DohaStudio/DohaAudio` PR #7 | merged | candidate-bound Dataset rights evidence의 fail-closed enrollment | 실제 candidate 셋 모두 Rights Gate 실패; cross-product owner 결정 아님 |
| `DohaStudio/DohaMusic` voice consent policy, PR #92 | `계획`, merged consumer | voice consent snapshot과 Common RightsMetadata consumer 경계 | canonical RightsMetadata를 완성하지 못하고 governance·persistence가 후속임을 명시 |
| `DohaStudio/DohaVocal` ADR-003와 consent 문서 | `제안` | vocal consent/deletion 방향 | 제안 상태이며 source-wide Rights 운영 owner가 아님 |
| `DohaStudio/DohaLM` PR #160·#162, ADR-029·030 | merged, ADR은 `draft`·`proposed` | owner 후보 분석과 Option D blocker | 두 PR 모두 조직 승인을 얻지 못했다고 명시 |
| GitHub issue approval record | 검색 결과 0 | 해당 없음 | owner/team·scope·provenance를 갖춘 승인 record가 없음 |

관련 병합 PR의 review record도 owner/team의 별도 approval provenance를 제공하지 않았다. 따라서 merged 상태, code location,
README 문구, proposed architecture와 제한된 authentication authority를 전체 RightsMetadata ownership 승인으로 확대하지 않는다.

## 현재 확인된 부분 책임

| 책임 | 확인된 owner | 범위 |
|---|---|---|
| Product identity·Workspace authorization | DohaMusic | 제품 사용자와 Workspace 경계 |
| Reviewer identity·assertion issuer | DohaMusic | V1 local reviewer authentication |
| Semantic ReviewerAuthority·mapping revoke | DohaAudio | audio semantic review scope |
| Common schema·validator | `DohaStudio/.github` | payload 의미와 validation; runtime data authority 아님 |
| Dataset governance consumer | DohaLM | RightsMetadata read/validation; source Rights writer 아님 |

위 부분 책임은 accountable Rights business owner, source identity issuer, create·replace·revoke writer, durable authority, current
projection 또는 authenticated Rights read contract owner를 승인하지 않는다.

## 요청하는 결정

조직 소유자는 다음 중 정확히 하나를 선택하고 선택한 owner/team과 승인 provenance를 기록해야 한다.

| option | 요청 내용 | 필수 후속 기록 |
|---|---|---|
| `A. DOHAMUSIC OWNERSHIP APPROVED` | DohaMusic의 책임을 모든 source 유형의 Rights/Licensing+Consent authority로 확장 | DohaMusic accountable team, repository placement, 다른 consumer/effect owner의 동의 |
| `B. NEW RIGHTS DOMAIN APPROVED` | 별도 cross-repository Rights domain과 owning team을 승인 | domain/repository 이름, accountable team, 생성·운영 권한과 consumer migration 책임 |
| `C. ANOTHER EXISTING DOMAIN APPROVED` | DohaMusic 이외의 기존 domain을 owner로 승인 | exact repository/domain, accountable team, source-wide scope 적합성 |
| `D. ORGANIZATIONAL APPROVAL STILL BLOCKED` | A~C를 아직 승인하지 않음 | blocker owner와 승인 회의를 주관할 actor |

## 선택과 함께 반드시 확정할 사항

1. accountable business owner와 organizational/legal approval actor
2. owning repository/domain과 운영·on-call 책임
3. 모든 source 유형을 포괄하는 source identity namespace와 issuer
4. immutable Rights chain의 logical key, alias·merge·split·collision policy
5. create writer와 intake/evidence review authority
6. replacement writer와 correction·scope·expiry change authority
7. revoke writer, withdrawal/license/legal trigger owner와 emergency actor
8. immutable history와 event를 보존하는 durable authority owner
9. unique-current projection owner와 transaction boundary
10. authenticated read contract와 availability·failure owner
11. Workspace/tenant authorization owner와 private evidence access 경계
12. DohaMusic·DohaAudio·DohaVocal·DohaLM의 consumer/effect 책임
13. Common schema 변경 승인 경로와 version migration owner

## 승인 기록 양식

```text
decision: A | B | C
approved_at: <timezone-aware timestamp>
approving_actor: <named accountable person or organizational role>
approving_team: <team/domain>
approval_provenance: <approved ADR, issue decision, or equivalent durable record>
business_scope: Rights/Licensing + purpose-scoped Consent Management
owning_repository_or_domain: <exact value>
source_identity_issuer: <exact value>
rights_logical_key_owner: <exact value>
create_writer_owner: <exact value>
replacement_writer_owner: <exact value>
revocation_writer_owner: <exact value>
durable_authority_owner: <exact value>
current_projection_owner: <exact value>
read_contract_owner: <exact value>
workspace_authorization_owner: <exact value>
consumer_effect_owners: <DohaMusic, DohaAudio, DohaVocal, DohaLM responsibilities>
common_contract_change_path: <exact approval/migration path>
```

필드 일부만 채운 답변, PR merge만 있는 답변, `proposed`·`draft` 문서, 구현 위치 또는 가장 자연스러운 후보라는 설명은 승인으로
간주하지 않는다.

## READY 기준

`READY FOR RIGHTS AUTHORITY CONTRACT`는 다음 조건이 모두 참일 때만 선언한다.

- A, B 또는 C 중 하나가 명시적으로 선택됐다.
- approving actor/team과 durable approval provenance가 있다.
- business scope와 repository/domain placement가 source 전체 범위를 덮는다.
- source identity, logical key와 create·replacement·revoke writer owner가 모두 채워졌다.
- durable authority, current projection, read contract와 Workspace authorization owner가 모두 채워졌다.
- 네 consumer/effect repository와 Common contract 변경 경로가 승인됐다.
- 승인 간 충돌과 미해결 부분 승인이 0이다.

현재 충족 수는 0이며 최종 상태는 `D. ORGANIZATIONAL APPROVAL STILL BLOCKED`다.

## 차단 범위

승인 전에는 Rights Authority port/adapter, DB·migration, service API, source registry, runtime composition, CurrentEvidence snapshot,
Publication binding과 production Runtime Activation을 시작하지 않는다. 이 문서는 production source, test, migration, runtime,
Common package 또는 다른 repository를 변경하거나 그러한 변경을 승인하지 않는다.

## 승인 후 절차

완전한 승인 record가 생기면 새 cross-repository ADR에서 선택된 owner와 13개 책임을 승인하고 ADR-028~030의 blocker를
재평가한다. 그 ADR이 approved되기 전에는 구현 PR을 열지 않는다.

## 문서 검증

- 변경 Markdown 5개 상대 링크 누락: 0
- 변경 Markdown code fence 불균형: 0
- production source·test·migration 변경: 0
- 다른 repository 변경: 0
- `git diff --check`: 통과

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-25 | accepted/approved ADR·병합 PR·authority 문서·issue를 재검증하고 부분 authentication authority와 전체 Rights ownership을 분리; Option D 유지와 조직 Decision Request 등록 |
