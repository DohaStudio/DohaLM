# DohaLM Instruct Safety

- 문서 상태: `review`
- 마지막 검토일: 2026-07-28
- Safety framework: `design_completed`
- Safety dataset·평가·학습: `not_approved`

## Threat model

| Risk | 설계 경계 |
|---|---|
| PII | 입력·output·metadata의 민감정보 검토, 원문 비저장, 목적 제한 |
| Prompt injection | user/tool content가 system·permission을 덮어쓰지 못함 |
| Tool abuse | 미등록·고위험·destructive tool과 무승인 실행 차단 |
| Role confusion | system/developer/user/tool 경계와 우선순위 고정 |
| System prompt leakage | 비공개 instruction의 복원·출력 요구 차단 |
| Refusal | 허용 요청 과잉 거절과 위험 요청 미거절을 함께 평가 |
| Hallucination | 입력·source 밖 사실과 tool 실행 결과 허위 주장 억제 |
| Unsafe code/SQL | secret·취약 코드·파괴 query·실행 권한 분리 |
| Domain harm | Recruit 편향·Game IP 등 domain별 추가 review |

## Dataset safety

License·PII·저작권·유해성·benchmark contamination과 source lineage 승인이 없는 record는 SFT에 사용할 수
없다. Safety label은 학습 입력이 아니라 검토·층화 metadata이며 실제 민감값을 복제하지 않는다.

## Prompt와 output safety

- System prompt source와 version을 승인하고 user input과 분리한다.
- Delimiter injection, role spoofing과 hidden instruction 추출 probe를 평가한다.
- 거절은 간결하고 안전한 대안을 제시하되 정책 원문이나 secret을 노출하지 않는다.
- Tool·code·SQL output은 실행되지 않았음을 명시하고 permission 검증을 요구한다.
- Chain style은 숨은 chain-of-thought 공개를 요구하지 않으며 결과에 필요한 짧은 근거만 후보로 둔다.

## 승인 경계

Safety framework 설계는 safety dataset, refusal policy 수치, 사람 평가, red-team 실행 또는 model safety 승인이
아니다. 실제 SFT 전에 risk owner, rubric, severe failure, incident 보존과 중단 조건을 별도 승인한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | PII·injection·tool abuse·role·refusal·hallucination safety framework 설계 |
