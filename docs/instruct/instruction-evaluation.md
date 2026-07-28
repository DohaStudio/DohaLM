# DohaLM Instruct Evaluation 계약

- 문서 상태: `review`
- 마지막 검토일: 2026-07-28
- Framework 상태: `design_completed`
- Numeric thresholds: `proposed`
- Evaluation 실행: `not_approved`

## 평가 계층

[확정] Instruct 평가는 parent Base 회귀와 instruction capability를 분리한다. 임의 종합 점수를 만들지 않고
category·format·safety·termination별 결과와 실패 분포를 보고한다.

| Category | 목적 | 필수 evidence 후보 |
|---|---|---|
| Instruction Following | 지시 핵심 조건 수행 | 조건별 pass/fail·누락 |
| Format | 요구 구조 준수 | exact/structural validity |
| JSON | schema-valid JSON | parse·schema·추가 text |
| Markdown | heading/list/table/fence 구조 | parser·구조 검증 |
| Hallucination | 입력 밖 주장 억제 | attribution·unsupported claim |
| Refusal | 허용/거절 경계 | over/under-refusal |
| Safety | PII·유해·권한 경계 | policy category별 결과 |
| Multi-step | 제한된 단계 지시 완결 | 단계·순서·최종 결과 |
| EOS | 응답 종료 | teacher-forced와 generation 분리 |
| Length | 조기 중단·과도한 장문 억제 | category별 길이·max rate |
| Consistency | 동일 조건의 구조·결론 안정성 | seed/profile별 변동 |

## Structured output 성공 기준

- JSON: 단일 JSON value, parse 성공, schema 일치, 필수 key·type·enum 일치, 추가 prose 없음
- Markdown: 요청된 heading/list/table/code fence가 균형 있고 지정 구조를 만족
- Code block: fence·language tag·syntax가 유효하고 승인된 경우 compile/unit test 통과
- Table: header·separator·column 수가 일치하고 요구 field가 존재
- List: 순서·개수·중첩 계약을 만족
- Tool call: tool 이름·argument schema·permission state가 유효하며 임의 실행 결과를 주장하지 않음

수치 threshold는 실제 benchmark·dataset·사람 평가 rubric과 표본 크기 승인 전 `proposed`다.

## EOS와 decoding

[ADR-008](../decisions/ADR-008-eos-generation-and-decoding-evaluation-policy.md)에 따라 teacher-forced EOS,
pure generation과 decoding-assisted behavior를 분리한다. Instruct는 응답 완결성이 필수지만 exact threshold는
미승인이다. Service decoding은 모델 평가와 별도이며 forced termination을 모델 EOS 성공으로 계산하지 않는다.

## Evaluation dataset

- Training·validation·test·benchmark identity와 fingerprint를 분리한다.
- Training contamination 검사와 hidden test 접근 경계를 기록한다.
- 실제 prompt·answer·generated text의 Git 저장은 금지한다.
- Base Full baseline과 Instruct regression은 동일 tokenizer·parent-compatible identity에서 비교한다.
- Chat·Agent 평가는 Instruct 결과에 자동 포함하지 않는다.

## 합격·실패 경계

필수 category, severe safety failure, invalid lineage, dataset leakage, malformed artifact 또는 Base 심각 회귀가
있으면 fail closed한다. Numeric threshold가 승인되지 않은 상태에서는 모델 승인 판정을 내리지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | Instruct capability·structured output·EOS·Base 회귀 평가 framework 설계 |
