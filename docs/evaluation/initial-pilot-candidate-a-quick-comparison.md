# Initial·Pilot·Candidate A 동일 Quick Evaluation 비교

- 문서 상태: `review`
- 마지막 검토일: 2026-07-27
- 태그: `evaluation`, `quick`, `comparison`, `candidate-a`
- 관련 문서: [평가 계획](./evaluation-plan.md), [평가 지표](./evaluation-metrics.md), [체크포인트 비교 정책](./checkpoint-comparison-policy.md), [리더보드](./model-evaluation-leaderboard.md)

## 목적과 비교 조건

학습량이 0, 204,800, 5,001,216, 10,000,384 token으로 증가할 때 DohaLM-Tiny의 내부 Quick Evaluation 변화를 확인했다. Gate 7 checkpoint는 memorization-only이므로 비교군에서 제외했다. 네 실행은 각각 128 packed sequence, 32,640 target token, 16 batch를 평가했다.

| Identity | 값 |
|---|---|
| Comparison ID | `initial-pilot-candidate-a-quick-20260727-01` |
| Dataset | `sha256:0265e2d4b2ab94cd4f3df3afba14e671a58cc76b8e11434ebd64db36506f8790` |
| Quick subset | `sha256:0bc66ac5061fa0a5c0415cd78ef4fa663265e6ed8bfb054652874addb375b254` |
| Tokenizer | `sha256:9ce19a118a893fd69bad3124f94cea78f804d450a2ff6a9c4149b3064312f0ff` |
| Config | `sha256:a5b12cceaa07c2ce59d303f74f7569d4a6bc37e3a515e4f9a6f7a60d67b36c5c` |
| Prompt set | `sha256:694dfe54a78706c8e77ec52df575b14f4d9e4714bbba184859a1590686de8ebc` |
| Comparison result | `sha256:dce27e0970ab0407359d5d6055125964a22654edb31d5ae996dc8bcada6dd288` |

모든 identity와 profile, precision이 일치해 상태는 `comparable`이다. AI Hub 원래 Validation과 외부 benchmark는 사용하지 않았다.

## Artifact identity

| Artifact | Step | Checksum manifest | Bundle bytes | Result fingerprint |
|---|---:|---|---:|---|
| Initial seed 17 | 0 | checkpoint 없음, seed/config 결정론 검증 | 0 | `sha256:6e621bfe6231285c4c17a7a6c0e0b724230ceeb3dbb6dbbb9115d0596c064e10` |
| Pilot 100 | 100 | `sha256:8ad3dc5f...f241d4` | 202,789,742 | `sha256:fcc9237251f8fa46ab113d5b5366d46a1d5594324140f573fc187ec615675a25` |
| Candidate A Mid | 2,442 | `sha256:99519a1d...744d7e` | 202,790,078 | `sha256:423ec4892fb5abb4230b5c89c7b2051faba2015ad129ed8723f71c4885b81837` |
| Candidate A Final | 4,883 | `sha256:80f2aee7...6338f8` | 202,790,081 | `sha256:21649cca219f8254937deb6af7d9402171a68e4589630194aa4d18c2ca1ad2ab` |

세 checkpoint는 공통 model fingerprint와 tokenizer fingerprint 및 등록된 source lineage를 만족했다. Initial은 등록된 model config fingerprint와 seed 17로 재생성했다.

## Loss와 Top-k

| Artifact | Loss | Perplexity | Top-1 | Top-5 | Top-10 |
|---|---:|---:|---:|---:|---:|
| Initial | 250.683483 | 7.4208e+108 | 1.0968% | 1.1121% | 1.1397% |
| Pilot | 27.605845 | 9.7514e+11 | 6.8260% | 15.0827% | 17.2335% |
| Mid | 6.559930 | 706.2223 | 15.9559% | 28.1373% | 34.1728% |
| Final | 6.282144 | 534.9342 | 18.2353% | 30.8915% | 37.0221% |

Initial→Pilot, Pilot→Mid, Mid→Final의 loss 변화는 각각 -223.077638, -21.045915, -0.277786이다. Top-1 변화는 +5.7292%p, +9.1299%p, +2.2794%p다. Final까지 예측 지표는 계속 개선됐지만 Mid 이후 개선폭은 작아졌다.

## Position-aware 결과

| Artifact | Packed loss | Rebased loss | Packed Top-1 | Rebased Top-1 | Position gap |
|---|---:|---:|---:|---:|---:|
| Initial | 250.683483 | 249.291938 | 1.0968% | 1.0078% | -0.0890%p |
| Pilot | 27.605845 | 27.541730 | 6.8260% | 7.1535% | +0.3275%p |
| Mid | 6.559930 | 6.458744 | 15.9559% | 16.6033% | +0.6475%p |
| Final | 6.282144 | 6.179990 | 18.2353% | 19.2962% | +1.0609%p |

| Artifact | 0–31 | 32–63 | 64–127 | 128–191 | 192–255 |
|---|---:|---:|---:|---:|---:|
| Initial | 1.2097% | 1.1963% | 1.1108% | 1.0986% | 0.9766% |
| Pilot | 7.0313% | 6.7627% | 6.8481% | 7.0435% | 6.5186% |
| Mid | 15.1966% | 14.8682% | 16.4673% | 16.1499% | 16.1621% |
| Final | 17.5907% | 17.7734% | 18.5791% | 18.2617% | 18.4082% |

모든 bucket이 학습 단계와 함께 개선됐다. 다만 rebased 우위가 커져 position dependency 변화는 Full Evaluation에서 재확인할 가치가 있다.

## Generation과 continuation

| Artifact | EOS | Max length | Adj. repetition | Repeated 2/3-gram | Distinct-1/2/3 | Degenerate loop |
|---|---:|---:|---:|---:|---:|---:|
| Initial | 0% | 100% | 100.0000% | 93.3333% / 92.8571% | 0.0625 / 0.0667 / 0.0714 | 100% |
| Pilot | 0% | 100% | 88.0000% | 79.3333% / 77.8571% | 0.1750 / 0.2067 / 0.2214 | 100% |
| Mid | 0% | 100% | 69.3333% | 64.6667% / 57.1429% | 0.2813 / 0.3533 / 0.4286 | 90% |
| Final | 0% | 100% | 45.3333% | 52.0000% / 42.1429% | 0.3813 / 0.4800 / 0.5786 | 80% |

EOS 0%와 maximum length 100%는 Initial부터 계속됐다. 따라서 Final에서 새로 시작된 퇴화로 볼 수 없다. 오히려 adjacent repetition과 loop 비율은 단계마다 감소하고 distinct-n은 증가했다. 남은 핵심 문제는 greedy 16-token 조건에서 EOS를 학습하지 못한 현상이며, decoding 특성과 모델 문제를 분리하려면 EOS target 빈도 분석과 별도 승인된 진단 평가가 필요하다.

Continuation first-token은 Initial 0%, Pilot 25.0%, Mid 12.5%, Final 18.75%였고 exact continuation은 모두 0/16이다. teacher-forced loss는 249.2362, 34.3318, 9.0047, 8.3374로 감소했다. 16개 probe의 autoregressive 지표는 변동성이 커 순위 근거로 단독 사용하지 않는다.

## Stability와 불변성

모든 실행에서 NaN/Inf logits 0건, NaN/Inf loss 없음, vocabulary 16,000 및 special-token 계약 유효, 반복 forward 결정론 일치를 확인했다. FP16/FP32 loss 절대 gap은 Initial 0.000488, Pilot 0.000483, Mid 0.000056, Final 0.000123으로 허용 범위 안이었다. 평가 전후 model state/checkpoint, tokenizer, evaluation dataset, dataset manifest와 split manifest checksum이 모두 동일했다. optimizer, scheduler, backward, gradient, checkpoint write는 실행하지 않았다.

Candidate A Final 신규 result fingerprint와 모든 핵심 metric은 기존 canonical Quick 결과와 정확히 일치했다.

## 한계와 후속 권장 작업

Quick subset은 전체 internal evaluation을 대표한다고 확정할 수 없고 generation은 synthetic prompt 10개, greedy 16 token으로 제한된다. Candidate A Mid→Final 차이가 상대적으로 작고 position gap 설명이 필요하며 Candidate B 기준선을 더 정확히 정할 필요가 있으므로 Candidate A Final Full Evaluation을 권장한다. 이번 작업에서는 실행하지 않았다.

Candidate B 전에는 별도 승인 아래 다음을 권장한다.

1. Candidate A Final Full Evaluation으로 loss·position bucket 신뢰구간을 보강한다.
2. 원문을 노출하지 않는 EOS target 빈도 집계와 EOS calibration 진단을 설계한다.
3. greedy 고정과 별도로 decoding 정책 비교 계약을 먼저 승인한다.
4. continuation probe 수와 대표성을 재검토한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | 네 학습 단계의 동일 Quick Evaluation 비교 및 재현성·불변성 결과 기록 |
