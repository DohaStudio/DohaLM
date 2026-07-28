# DohaLM Domain Model Strategy

- 문서 상태: `review`
- 마지막 검토일: 2026-07-28
- 현재 실행 권한 영향: 없음
- 관련 문서: [Model Family Roadmap](./model-family-roadmap.md), [Model Lineage](./model-lineage.md), [Data Governance ADR](../decisions/ADR-004-data-governance.md)

## 1. 공통 원칙

- [제안] Domain 모델은 승인된 Base 또는 명시적인 derivative를 parent로 사용한다.
- [제안] 데이터 적격성, 라이선스·PII·누수, domain evaluation, Base regression과 release 조건을 family별로 검증한다.
- [확정] 아래 내용은 장기 설계이며 현재 데이터 사용, SFT, preference training이나 publication 승인이 아니다.

## 2. Domain별 데이터와 위험

| Domain | 목적 | 데이터 범주 | 학습 후보 | 핵심 위험 | Domain 평가 | Base regression | 상태 |
|---|---|---|---|---|---|---|---|
| Code | 생성·설명·debug·test | source, comments, docs, tests, fixes | CPT + SFT | license, secret, vulnerable code, benchmark contamination | syntax·compile·unit test·functional·security | 일반 언어·한국어·EOS | `long_term_planned` |
| SQL | query 생성·수정·교육 | NL-SQL, schema-query, explanation, fixes | CPT/SFT | PII DB dump, schema leakage, dialect 혼합, 위험 query | parse·execution·result·dialect | 일반 언어·format·safety | `long_term_planned` |
| Recruit | JD·지원 문서·면접 보조 | JD, 문서 구조, career writing | domain SFT | PII, bias, fabricated career, confidential company docs | relevance·factuality·privacy·bias | 일반 언어·hallucination | `long_term_planned` |
| Game | NPC·quest·lore·상태 상호작용 | dialogue, quest, lore, rules, state traces | CPT/SFT | IP, consistency, harmful content, player PII | lore·state·quest·repetition·safety | language·EOS·stability | `long_term_planned` |
| Chat | 대화·질의응답·맥락 유지 | multi-turn, instruction, refusal | SFT, 별도 preference | PII, harmful content, bias, long-context failure | coherence·retention·relevance·safety | Base Full + generation | `long_term_planned` |
| Agent | tool calling·workflow·recovery | tool schema, JSON, action traces | tool-calling SFT | privilege abuse, injection, secret exposure, unsafe action | selection·arguments·permission·recovery | Base·Chat·format regression | `long_term_planned` |

추가 데이터 경계는 다음과 같다.

- Code: 언어별 source·주석·문서·테스트·오류 수정·설명 pair의 라이선스와 secret을 검사하고 benchmark contamination을 분리한다.
- SQL: 자연어-SQL, schema-query, 설명, 오류-수정 pair와 SQLD 개념을 dialect별로 관리하며 실제 개인정보 DB dump는 사용하지 않는다.
- Recruit: 이력서 구조·경력 기술·면접 질문·지원서 예시·직무 분석을 후보로 삼고 실제 사용자 데이터, 민감정보, 고용 편향과 기업 문서 저작권을 별도 승인한다.
- Game: 분기 대화·quest·lore·character·world·rule·state interaction을 다루고 IP, 유해 콘텐츠와 player PII를 검사한다.
- Chat: 일반 질의응답·multi-turn·요약·안전한 거절·style control을 다루고 역할 혼동·긴 문맥·일관성과
  응답 종료를 평가한다. Service decoding은 모델 EOS 평가와 분리한다.
- Agent: tool schema·selection·JSON·observation-action trace·failure recovery·permission handling을 다루고
  injection·허위 tool result·secret·자동 실행 권한을 차단한다. 종료는 EOS뿐 아니라 tool call·workflow·권한
  경계의 structured termination으로 평가한다.

## 3. Release 조건

각 Domain은 최소한 다음이 필요하다.

1. 승인된 parent와 완전한 lineage
2. 목적별 dataset·license·PII 승인
3. benchmark contamination과 evaluation leakage 검사
4. Domain 평가와 동일 parent 대비 Base regression
5. 실패·한계·안전 정보를 포함한 model card
6. checkpoint, model, dataset 각각의 publication 승인

## 4. 평가 분리

- Base 평가는 Full internal loss, perplexity, Top-k, token category, position, EOS, generation stability, precision, privacy와 lineage를 사용한다.
- Domain 평가는 task 성공률과 안전성을 추가하되 Base 평가를 대체하지 않는다.
- 임의 종합 점수로 핵심 지표의 실패를 숨기지 않는다.

## 5. Family별 평가 계약 후보

| Family | Domain 지표 | 공통 회귀·안전 지표 |
|---|---|---|
| Instruct | instruction following, format compliance, task completion, multi-step 수행 | refusal, hallucination, Base Full |
| Chat | multi-turn coherence, context retention, relevance, consistency | safety, Base Full, generation stability |
| Code | syntax, compilation, unit test, functional correctness, explanation | security, license contamination, Base Full |
| SQL | parse, execution, result, dialect, explanation | dangerous query detection, schema leakage, Base Full |
| Recruit | JD relevance, factual consistency, structure | fabricated experience, privacy, bias, Base Full |
| Game | lore, dialogue, state, quest, repetition | safety, IP review, Base Full |
| Agent | tool selection, arguments, workflow, recovery | permission, injection resistance, secret exposure, Base Full |

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | Code·SQL·Recruit·Game·Chat·Agent 데이터·위험·평가·release 전략 초안 작성 |
