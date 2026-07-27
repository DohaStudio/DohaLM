# 평가 데이터 정책

- 문서 상태: `review`
- 마지막 검토일: 2026-07-27
- 태그: `evaluation`, `dataset`, `privacy`, `leakage`
- 관련 결정: [ADR-004](../decisions/ADR-004-data-governance.md), [ADR-005](../decisions/ADR-005-evaluation-and-experiment-policy.md)

## 고정 데이터 정체성

AIHUB-71748 Training에서 승인된 방식으로 분리한 internal evaluation만 사용한다. AI Hub 원래 Validation, benchmark, SFT, RLHF, preference 데이터는 사용하지 않는다.

| 항목 | 값 |
|---|---:|
| record | 4,799 |
| packed sequence | 14,329 |
| target token | 3,653,719 |
| split fingerprint | `sha256:dd71433c11a69345fed217620ba84b4ebc8b969b25400db07af9bc5ef0f4696f` |
| 기존 evaluation fingerprint | `sha256:0265e2d4b2ab94cd4f3df3afba14e671a58cc76b8e11434ebd64db36506f8790` |

데이터 identity, tokenizer, context length, packing과 masking이 다르면 직접 비교를 차단한다. 원문, decoded text와 전체 token ID 배열은 결과에 저장하지 않는다.

## Quick와 Full

Quick profile은 고정 seed 17과 `sha256(dataset fingerprint, seed, index)` 순위로 128개 sequence를 고른다. 선택 인덱스 자체는 복사하지 않고 index fingerprint와 개수만 외부 manifest에 기록한다. Full profile은 14,329개 sequence 전체를 순서대로 평가한다. Quick 결과는 Full 결과로 간주하지 않는다.

[확정] Quick은 개발 회귀·방향성 용도, Full은 milestone·공식 판정 용도로 구분한다. 대표성 임계값과 Candidate A 판정은 2026-07-27 승인된 [Quick·Full 대표성 정책](./quick-full-representativeness-policy.md)을 따른다. Quick v2는 `planned_awaiting_separate_approval`이며 생성하지 않는다.

## 누수와 개인정보

PII 검토를 통과한 internal evaluation만 허용한다. 결과에는 hash 기반 sample ID, 길이와 집계값만 쓴다. 데이터 fingerprint가 바뀌면 기존 leaderboard와 `incomparable_dataset`으로 분리한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | internal evaluation identity와 Quick selection 계약 확정 |
| 2026-07-27 | Quick 개발용·Full 공식 판정 용도와 대표성 정책 제안 연결 |
| 2026-07-27 | Quick 대표성 정책 승인과 Quick v2 별도 승인 경계 반영 |
