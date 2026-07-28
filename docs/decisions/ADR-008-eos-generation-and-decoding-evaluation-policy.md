# ADR-008: EOS Generation and Decoding Evaluation Policy

- 상태: `approved`
- 작성일: 2026-07-28
- 결정일: 2026-07-28
- 승인일: 2026-07-28
- 대체 여부: `not_superseded`
- 관련 문서: [EOS Success Policy](../evaluation/eos-success-policy.md), [생성 평가](../evaluation/generation-evaluation.md), [EOS Generation·Decoding 정책](../evaluation/eos-generation-decoding-policy.md), [Candidate B 평가 계약](../evaluation/candidate-b-evaluation-contract.md)

## 배경

Candidate B는 Candidate A보다 teacher-forced EOS Top-k·loss·rank가 개선됐지만 기존 16-token greedy
generation에서 EOS 0%, maximum-length 100%였다. 현재 결과만으로 모델의 긴 horizon 종료 능력과
sampling·반복 억제의 효과, Base Model과 서비스 종료 정책을 구분할 수 없다.

## 결정

1. Teacher-forced EOS와 autoregressive generation EOS를 별도 지표로 유지한다.
2. 보정 없는 greedy를 pure model baseline으로 유지한다.
3. sampling과 repetition control은 decoding-assisted diagnostic으로만 보고한다.
4. 16/32/64/128 생성 길이와 versioned synthetic prompt category를 같은 identity에서 평가한다.
5. Base·Instruct·Chat Model의 EOS 성공 계약을 분리한다. Instruct·Chat 수치 임계값은 별도 승인 전 `proposed`다.
6. forced EOS·logit bias·heuristic stop 결과는 모델 성능 점수에 포함하지 않는다.
7. 서비스 decoding policy는 별도 ADR·사용자 승인 전에는 채택하지 않는다.
8. Candidate A Full을 공식 baseline으로 유지하고 Candidate B 재평가는 별도 승인으로만 수행한다.
9. Base pure greedy EOS는 `diagnostic_required`이지만 `not_sufficient_as_single_failure_condition`이다.
10. 심각한 반복·무한 loop·전반 성능 붕괴는 generation EOS 단독 판정과 별개로 blocker다.
11. historical 결과와 당시 승인 계약은 소급 재판정하지 않는다.

## 대안

- 기존 16-token greedy만 유지: 장점은 단순성이나 긴 horizon과 보조 decoding의 근거가 없다.
- sampling 결과를 공식 점수에 합산: 서비스 체감과 가까울 수 있지만 모델 능력과 정책 효과를 섞는다.
- forced EOS를 적용: 종료는 보장하지만 모델 EOS 능력을 측정하지 못하므로 이번 범위에서 제외한다.

## 영향

진단 비용과 결과 차원은 늘지만 Candidate A/B를 동일 prompt·seed·profile로 직접 비교할 수 있다.
Candidate B의 historical 상태는 `evaluated_contract_not_passed`로 그대로 유지한다. 별도 재평가 승인 전에는
Candidate A 공식 baseline도 변경하지 않는다. 결과 artifact에는
decoded text와 raw token sequence를 저장하지 않는다.

## 단계별 계약 상태

- Base EOS 계약: `approved`
- Instruct EOS 정책 framework: `approved`; numeric thresholds: `proposed`; training: `not_approved`
- Chat EOS 정책 framework: `approved`; numeric thresholds: `proposed`; training: `not_approved`
- Service decoding policy: `proposed`; implementation: `not_started`
- Candidate B reassessment: `awaiting_separate_approval`

## 후속 결정

[확정] 별도 승인된 [ADR-009](./ADR-009-candidate-b-official-reassessment.md)가 이 재평가 조건을 소비했다.
Candidate B historical 상태는 불변이며 current reassessment는 `approved_as_base_baseline`이다.

## 승인 전 검증

- Candidate A/B artifact와 Full evaluation identity 불변
- 15개 prompt category와 11개 profile, 4개 길이 계약
- deterministic sampling, repetition/no-repeat 동작과 privacy schema
- checkpoint/model checksum 전후 불변
- 전체 Evaluation·Candidate A/B·checkpoint·tokenizer·dataset 회귀

## 재검토 조건

진단 결과가 길이·category별로 재현되고 Base/Chat 모델 목적이 확정되거나, 승인된 EOS 계약과 실제
사용 목적이 충돌할 때 재검토한다.
