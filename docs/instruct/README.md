# DohaLM Instruct 설계 문서

- 문서 상태: `review`
- 마지막 검토일: 2026-07-29
- 프로젝트 상태: `design_completed`
- 실행 상태: `execution_not_approved`
- 관련 결정: [ADR-010](../decisions/ADR-010-dohalm-instruct-strategy.md)

## 범위

이 디렉터리는 Candidate B Base를 immutable parent로 사용하는 `DohaLM Instruct Tiny v1`의 목적, lineage,
데이터 schema, prompt template, 평가, tool calling, safety와 readiness를 정의한다. 실제 instruction dataset,
SFT backend, checkpoint와 모델은 생성하지 않는다.

## 문서 목록

- [Instruct 전략](./instruct-strategy.md)
- [Instruction Dataset 전략](./instruction-dataset-strategy.md)
- [Instruction Schema](./instruction-schema.md)
- [AI Hub Instruction Dataset 후보 Read-only 검토](./aihub-dataset-candidate-review.md)
- [AIHUB-71748 SFT 이용조건 검토](./aihub-71748-sft-terms-review.md)
- [AIHUB-71748 SFT 원문 비출력 검증 계획](./aihub-71748-sft-validation-plan.md)
- [AIHUB-71748 SFT Schema Inspection](./aihub-71748-schema-inspection.md)
- [Safe Dataset Inspector](./safe-dataset-inspector.md)
- [AIHUB-71748 SFT Join Integrity 결과](./aihub-71748-join-integrity-result.md)
- [AIHUB-71748 SFT 제한 PII Scan 결과](./aihub-71748-pii-scan-result.md)
- [AIHUB-71748 SFT PII False Positive 및 Threshold 정책](./aihub-71748-pii-policy.md)
- [AIHUB-71748 SFT Content Exact Duplicate Scan 결과](./aihub-71748-exact-duplicate-result.md)
- [AIHUB-71748 SFT Exact Duplicate 처리 정책](./aihub-71748-exact-duplicate-policy.md)
- [AIHUB-71748 SFT Near Duplicate Scanner 최적화](./aihub-71748-near-duplicate-optimization.md)
- [AIHUB-71748 SFT Near Duplicate Scan 결과](./aihub-71748-near-duplicate-result.md)
- [Prompt Template](./instruction-prompt-template.md)
- [Instruction Evaluation](./instruction-evaluation.md)
- [Tool Calling 전략](./tool-calling-strategy.md)
- [Instruction Safety](./instruction-safety.md)
- [Readiness](./instruction-readiness.md)

## Fail Closed

```text
design_status: design_completed
execution_allowed: false
training: not_approved
backend: not_started
dataset: not_selected
publication: not_approved
```

별도 사용자 승인 전에는 dataset 다운로드·생성·변환, SFT, optimizer, backward, evaluation 실행,
checkpoint 생성과 publication을 수행하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-29 | 새 독립 승인 Run 0002의 Near Duplicate 1회 aggregate-only 결과와 미승인 처리 경계 등록 |
| 2026-07-29 | Near Duplicate 첫 timeout 보존과 bounded 후보 비교·12,000 Synthetic retry readiness 등록 |
| 2026-07-29 | AIHUB-71748 Exact Duplicate 유형·처리 후보·Fail Closed 정책과 미승인 처리 경계 등록 |
| 2026-07-29 | AIHUB-71748 Content Exact Duplicate 1회 scan과 split overlap·component consistency 결과 등록 |
| 2026-07-29 | AIHUB-71748 PII 민감 주제·식별자 분리, false positive·threshold proposal과 정책 계층 등록 |
| 2026-07-29 | AIHUB-71748 제한 PII 후보 scan과 첫 Fail Closed·두 번째 독립 실행 결과 등록 |
| 2026-07-29 | AIHUB-71748 SFTdata/SFTlabel `data_id` 제한 Join Integrity 계약 통과 결과 등록 |
| 2026-07-28 | AIHUB-71748 Schema Inspection incident와 synthetic-only Safe Dataset Inspector 구현·회귀 문서 등록 |
| 2026-07-28 | AIHUB-71748 SFT 이용조건과 원문 비출력 join·PII·중복·누수·품질 검증 계획 등록 |
| 2026-07-28 | AI Hub dataset 5종의 read-only inventory, schema 적합성, PII·license blocker 검토 문서 등록 |
| 2026-07-28 | DohaLM Instruct 설계·Readiness 문서 진입점 작성 |
