# 평가 지표 계약

- 문서 상태: `review`
- 마지막 검토일: 2026-07-27
- 태그: `evaluation`, `metrics`, `position`, `stability`
- 관련 결정: [ADR-005](../decisions/ADR-005-evaluation-and-experiment-policy.md)

## 손실과 Perplexity

shifted target의 cross entropy 합을 유효 target token 수로 나눈 token-weighted mean loss를 사용한다. `log_perplexity`는 loss와 같고, `exp(loss)`가 float 범위를 넘으면 `perplexity: null`, `perplexity_overflow: true`, `finite_perplexity: false`로 기록한다. 반올림 전 수치로 result fingerprint를 만든다.

## Next-token

Top-1/5/10, sequence별 Top-1 분포(min, p10, p25, median, mean, p75, p90, max), special/EOS/Korean/English/number/symbol/byte-fallback token 정확도를 기록한다. 분류가 불명확한 piece는 `unclassified`로 남기며 언어 범주로 추정하지 않는다.

EOS 진단은 target 위치의 rank·probability·Top-1 margin을 position/context bucket별로 추가 기록한다. Packing reconciliation에서는 input EOS와 shifted target EOS를 구분하며 block position 0에서 shift되어 target 밖으로 나간 EOS를 유실 또는 masking으로 오분류하지 않는다. 상세 기준은 [EOS·불완전 블록 진단](./eos-incomplete-block-diagnostic.md)을 따른다.

## Position-aware

Packed 평가는 실제 0~255 learned absolute position 조건을 유지한다. bucket은 0~31, 32~63, 64~127, 128~191, 192~255이다. Document-rebased 평가는 packed sequence 안의 완결된 EOS 경계 segment만 position 0에서 다시 forward한다. 두 지표는 별도로 보고하며 `rebased top-1 - packed top-1`을 position gap으로 기록한다.

## Continuation과 안정성

고정 sample hash와 prefix 16/32/64/128에서 first-1/4/8/16, prefix match, exact continuation, teacher-forced loss, AR match, EOS, repetition, special token 비율을 기록한다. 원 prefix와 target은 기록하지 않는다.

FP16/FP32 loss 차이는 절대 0.05 또는 상대 1% 중 큰 값 이내를 기본 허용치로 사용한다. bitwise 일치는 요구하지 않는다. 같은 seed의 반복 forward, finite logits/loss, vocabulary shape, special token ID, parameter/checkpoint 전후 fingerprint도 확인한다.

[확정] Candidate 공식 비교는 Full Evaluation을 사용하고, EOS 및 Candidate B 지표는 2026-07-27 승인된 [ADR-007](../decisions/ADR-007-evaluation-baseline-and-candidate-comparison.md)과 [Candidate B 평가 계약](./candidate-b-evaluation-contract.md)을 따른다. 종합 가중 점수는 사용하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | loss, accuracy, position, continuation, 안정성 지표 계약 작성 |
| 2026-07-27 | EOS rank·probability·margin과 input/shifted-target reconciliation 계약 보완 |
| 2026-07-27 | Candidate A Full baseline과 Candidate B 지표별 평가 계약 승인 반영 |
