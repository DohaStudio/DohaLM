# ADR-007: Evaluation Baseline and Candidate Comparison Policy

- 문서 상태: `approved`
- 결정일: 2026-07-27
- 승인 상태: `approved`
- 대체 여부: baseline selection만 [ADR-009](./ADR-009-candidate-b-official-reassessment.md)로 후속 결정; 나머지 정책 유지
- 관련 문서: [Candidate A Final Full 결과](../evaluation/candidate-a-final-full-result.md), [EOS 진단](../evaluation/eos-incomplete-block-diagnostic.md), [Quick 대표성 정책](../evaluation/quick-full-representativeness-policy.md), [Candidate B 평가 계약](../evaluation/candidate-b-evaluation-contract.md)

## 결정 배경

Candidate A Final의 동일 Quick와 전체 Full Evaluation에서 Quick이 성능을 낙관적으로 추정했다. EOS 4,799 input과 4,782 shifted target의 차이는 packing position 0의 label shift로 완전히 설명됐으며, Candidate B 전 공식 비교 기준과 EOS 성공 조건을 고정할 근거가 마련됐다.

## 결정

- [확정] Candidate A Final Full을 공식 internal baseline으로 채택한다.
- [확정] Quick은 개발 회귀·방향성 확인용이며 공식 baseline, Candidate 최종 우열, Gate·release 판단에는 사용하지 않는다.
- [확정] 공식 Candidate·milestone 판단과 주요 model·dataset 변경 비교에는 Full Evaluation을 필수로 한다.
- [확정] 대표성 등급은 `representative`, `approximately_representative`, `directionally_consistent`, `biased_optimistic`, `biased_pessimistic`, `insufficient_evidence`를 사용한다.
- [확정] Candidate A Final Quick은 `approximately_representative`이며 `biased_optimistic` 특성을 병기한다.
- [확정] Candidate B는 동일 Quick·Full·synthetic generation·EOS·position·token-category·stability·불변성·privacy·lineage 검증을 완료해야 한다.
- [확정] 지표별 판정을 유지하며 임의 종합 가중 점수를 만들지 않는다.
- [확정] EOS 기준선과 합격 조건은 [EOS 진단](../evaluation/eos-incomplete-block-diagnostic.md)과 [Candidate B 평가 계약](../evaluation/candidate-b-evaluation-contract.md)을 따른다.
- [확정] Quick v2는 `planned_awaiting_separate_approval`이며 lineage·층화·비용 검토 없이 생성하지 않는다.
- [확정] Candidate B training은 `not_approved`다.

## 대표성 임계값

| 등급 | Loss | Top-1 | Top-5 | Top-10 | Position gap | 추가 조건 |
|---|---:|---:|---:|---:|---:|---|
| `representative` | ≤ 0.05 | ≤ 0.5%p | ≤ 0.75%p | ≤ 1.0%p | ≤ 0.5%p | 핵심 지표 방향 일치 |
| `approximately_representative` | ≤ 0.10 | ≤ 1.5%p | ≤ 2.0%p | ≤ 2.0%p | ≤ 1.5%p | 방향 일치, 순위 반전 없음 |

범위를 넘지만 방향과 순위가 유지되면 `directionally_consistent`로 기록한다. Quick이 지속해서 좋은 방향이면 `biased_optimistic`, 나쁜 방향이면 `biased_pessimistic`을 병기한다. 대응 Full evidence가 없으면 `insufficient_evidence`다.

## 대안과 이유

- [제외] Quick만으로 공식 baseline 확정: Candidate A에서 정량 편향이 관측됐다.
- [제외] 하나의 종합 점수: EOS·언어·position·자원 회귀를 숨길 수 있다.
- [제외] 즉시 Quick v2 생성: 승인 artifact에 archive lineage가 없어 층화 근거가 부족하다.

## 재검토 조건

- Quick/Full 쌍에서 현재 임계값이 반복적으로 잘못된 판정을 만든다.
- Dataset, split, tokenizer, packing, context 또는 evaluation identity가 변경된다.
- Candidate B 이후 EOS 개선 기준이 일반 Top-k·반복·자원 성능과 충돌한다.
- 외부 공개·benchmark·release가 다른 평가 계약을 요구한다.

## 후속 결정

[확정] Candidate A를 공식 baseline으로 선택한 2026-07-27 결정은 historical 적용으로 보존한다. ADR-009가
Candidate B를 현재 Base baseline으로 승격했으며 Quick/Full 역할, 동일 identity와 지표별 판정 정책은 계속 유효하다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | ADR-009 current baseline 변경과 ADR-007 historical 적용 범위 명시 |
| 2026-07-27 | Candidate A Full baseline, Quick 대표성, EOS success와 Candidate B 평가 계약 승인 |
