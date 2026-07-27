# Full Pretraining Evaluation 정책

- 문서 상태: `approved`
- 마지막 검토일: 2026-07-27
- 관련 문서: [ADR-005](../decisions/ADR-005-evaluation-and-experiment-policy.md), [실행 계획](./full-pretraining-execution-plan.md)

## 고정 identity

| 항목 | 값 |
|---|---:|
| Source | AIHUB-71748 Training 내부 evaluation |
| Record | 4,799 |
| Packed sequence | 14,329 |
| Target token | 3,653,719 |
| Fingerprint | `sha256:0265e2d4b2ab94cd4f3df3afba14e671a58cc76b8e11434ebd64db36506f8790` |
| AI Hub 원래 Validation | 사용하지 않음 |

## 실행 정책

- [확정] 실행 시작 전과 4,883 step 종료 후에만 full internal evaluation을 각각 1회 수행한다.
- [확정] 중간 evaluation, 별도 subset, generation, 실제 문자열 저장은 하지 않는다.
- [확정] loss, perplexity, sequence/target token 수, 시간, finite 여부와 fingerprint만 저장한다.
- [확정] evaluation 실패는 run 실패로 처리한다.
- [확정] best는 final checkpoint를 가리키는 논리 reference이며 별도 bundle을 복사하지 않는다.
- [확정] evaluation 1.5배 급증 2회 연속 중단 규칙은 일반 정책으로 유지하지만, 평가가 시작·종료 두 번뿐인 Candidate A에서는 연속 2회 비교가 불가능하다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | [확정] Candidate A 시작·종료 full evaluation 정책 승인 |
