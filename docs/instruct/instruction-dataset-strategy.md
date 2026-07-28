# Instruction Dataset 전략

- 문서 상태: `review`
- 마지막 검토일: 2026-07-29
- Dataset 상태: AIHUB-71748 SFT `CONDITIONALLY_SELECTED`
- 목적별 사용 승인: `not_approved`
- 관련 승인: [AIHUB-71748 Selection Decision](./aihub-71748-selection-decision.md)

## 원칙

[확정] AIHUB-71748 SFT Component의 조건부 선정 이후에도 dataset을 다운로드·생성·표본화·변환하지 않는다.
source, 취득 근거, license, 목적별 SFT 허용, 수정·파생·재배포 범위, PII와 저작권은 별도 승인을 받아야 한다.
Validation·benchmark·evaluation prompt와 정답은 학습에서 제외한다.

## Category

| Category | 목적 | 핵심 위험 |
|---|---|---|
| QA | 질문에 직접 답변 | 정답성·benchmark 누수 |
| Instruction | 명시적 작업 수행 | 지시 모호성·role 혼동 |
| Summarization | 입력 핵심 압축 | 누락·원문 저작권 |
| Translation | 언어 간 의미 보존 | 언어쌍 품질·PII |
| Extraction | 요구 field 추출 | schema 오류·민감정보 노출 |
| Rewrite | 형식·톤 변환 | 의미 왜곡·저작권 |
| Classification | 고정 label 선택 | label 정의·편향 |
| JSON | schema-constrained 출력 | parse 실패·추가 text |
| Tool | tool 선택·argument 구조화 | 권한·injection·실행 오인 |
| SQL | schema 기반 query 작성 | 실행 안전·dialect·누수 |
| Code | 코드 생성·설명·수정 | license·secret·취약 코드 |
| Recruit | 채용 문서 보조 | 민감정보·차별·고위험 결정 |
| Game | lore·quest·NPC 지시 | IP·일관성·player PII |

## 승인 pipeline

1. Dataset registry와 owner·source·version·취득 증빙 등록
2. 공식 license와 학생·비상업 연구/SFT 허용 범위 검토
3. PII·저작권·유해성·편향 risk plan 승인
4. schema mapping·품질 rule·중복 제거 방식 설계
5. train/validation/test·benchmark exclusion과 leakage fingerprint 고정
6. category·language·difficulty 분포 계획 승인
7. 원본 read-only, 파생 산출물 Git 외부 저장과 manifest 정책 승인
8. 목적별 single-use 또는 명시적 범위의 사용자 승인

## Filtering과 contamination

- Exact/near duplicate는 split 경계를 넘지 않도록 group 단위 처리한다.
- 원문, prompt, answer hash를 이용한 내부 중복·평가 누수 검사는 원문 비공개 방식으로 설계한다.
- Benchmark 이름만으로 제외하지 않고 문제·정답·해설·paraphrase 후보를 정책에 따라 검사한다.
- Empty, placeholder, 광고, 개인 연락처, secret, 실행 위험 code/tool argument는 fail closed한다.
- 자동 quality score는 승인 판정을 대체하지 않으며 threshold는 dataset 실측 전 확정하지 않는다.

## 저장과 공개

원본과 대용량 파생 dataset은 Git 외부 제한 경로에 저장하고 manifest·fingerprint만 공개 가능성을 검토한다.
원문·instruction·output·PII sample과 파생 dataset redistribution은 별도 승인 전 `not_approved`다.

## 미결정 사항

- [검증 필요] AIHUB-71748 SFT 공식 이용조건과 처리 범위 증빙
- [검증 필요] category별 표본 수·비율·quality threshold
- [검증 필요] split seed·group key·dedup algorithm
- [검증 필요] loss mask와 multi-turn serialization 대상

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-29 | AIHUB-71748 SFT 조건부 선정과 목적별 사용·처리 미승인 경계 반영 |
| 2026-07-28 | Instruction category·license·PII·중복·누수·filtering 승인 전략 작성 |
