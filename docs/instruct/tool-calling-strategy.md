# Tool Calling 전략

- 문서 상태: `review`
- 마지막 검토일: 2026-07-28
- 설계 상태: `design_completed`
- Tool 실행·학습: `not_approved`

## 범위

[확정] Instruct 단계의 tool calling은 tool schema 이해, 선택과 argument 구조화 능력의 설계 후보다. 외부
도구 실행, credential 사용, 자동 재시도와 Agent workflow 권한은 포함하지 않는다.

## 계약

| 영역 | 계약 |
|---|---|
| Tool schema | name·description·typed arguments·required·constraints·version |
| Selection | 필요할 때만 허용된 tool 선택; 불필요하거나 미등록 tool 차단 |
| Arguments | JSON schema·type·enum·range 검증; 추정 credential 금지 |
| Permission | read/write/destructive/network 범위와 사용자 승인 상태를 명시 |
| Failure | validation·permission·runtime 실패를 구분하고 성공을 허위 주장하지 않음 |
| Recovery | 수정 가능한 argument 제안은 허용 후보; 자동 실행·무한 retry 금지 |
| Workflow | 단일 call 중심; multi-step 실행은 Agent 단계로 분리 |

## Structured termination

Tool call은 EOS만으로 완료를 판단하지 않는다. `selected → arguments_validated → permission_checked →
execution_not_performed` 상태를 구조화한다. 실제 observation이나 결과가 없으면 생성하지 않는다.

## Prompt injection과 권한

- Tool output·retrieved content·user text는 system permission을 변경할 수 없다.
- Secret, filesystem broad path, destructive action과 외부 message는 명시 승인 없이는 차단한다.
- Tool schema와 permission fingerprint가 다르면 비교·실행을 fail closed한다.
- Recruit 등 고위험 domain에서 tool call이 자동 의사결정을 수행하지 않도록 별도 정책을 요구한다.

## Readiness blocker

Tool registry, schema validator, permission model, sandbox, failure taxonomy, evaluation set과 사용자 승인 방식이
모두 미구현이다. 따라서 tool-calling dataset·SFT·execution은 `not_approved`다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | Tool schema·selection·argument·permission·failure recovery 경계 설계 |
