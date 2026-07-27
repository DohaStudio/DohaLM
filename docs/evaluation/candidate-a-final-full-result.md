# Candidate A Final Full Evaluation 결과

- 문서 상태: `review`
- 마지막 검토일: 2026-07-27
- 태그: `evaluation`, `candidate-a`, `full`, `gpu`, `eos`
- 관련 문서: [Quick 결과](./candidate-a-final-quick-result.md), [Quick 비교](./initial-pilot-candidate-a-quick-comparison.md), [리더보드](./model-evaluation-leaderboard.md)

## 목적과 identity

Candidate A Final step 4,883을 전체 internal evaluation에 평가해 Candidate B 전 기준선을 확정했다. 학습, optimizer, scheduler, backward와 gradient는 사용하지 않았다.

| 항목 | 값 |
|---|---|
| Evaluation ID | `candidate-a-final-full-20260727-01` |
| Artifact identity | `sha256:e82fe840828bc5ec8e30d860d8c4e83c1f1dac953f6089ed694533b8d3ba8708` |
| Checkpoint checksum | `sha256:80f2aee72605ffcfeea13e158cbf7a132682591cf4295cd01c16f514686338f8` |
| Dataset | `sha256:0265e2d4b2ab94cd4f3df3afba14e671a58cc76b8e11434ebd64db36506f8790` |
| Split | `sha256:dd71433c11a69345fed217620ba84b4ebc8b969b25400db07af9bc5ef0f4696f` |
| PII | `sha256:91c6ad9827645249641d96e2da1d415124a4069ca45929150e9d49fb830ee3ed` |
| Tokenizer | `sha256:9ce19a118a893fd69bad3124f94cea78f804d450a2ff6a9c4149b3064312f0ff` |
| Full profile | `sha256:321e17685e03695ae650edf2c8688375fbd4c23eccb6e48dec17a4d2a3f26a90` |
| Result | `sha256:1ec526e2dc6b1792f2d071fc788cd384ad3a22a0c2750df7437158153ca2d78d` |

Full profile은 CUDA FP16, seed 17, deterministic algorithms, batch 8, 900초 상한이다. AI Hub 원래 Validation과 외부 benchmark는 사용하지 않았다. 4,799 record에서 생성된 전체 14,329 packed sequence와 3,653,719 target token을 1,792 batch로 평가했다.

## Loss, Top-k와 sequence 분포

| 지표 | 값 |
|---|---:|
| Token-weighted loss / perplexity | 6.369027 / 583.4899 |
| Top-1 / Top-5 / Top-10 | 16.8417% / 29.2154% / 35.5767% |
| Sequence mean / median | 16.8416% / 14.9020% |
| Minimum / maximum | 2.7451% / 54.9020% |
| p10 / p25 / p75 / p90 | 9.0196% / 11.3725% / 20.0000% / 28.2353% |
| p95 / p99 | 32.9412% / 42.3529% |

Perplexity는 finite이며 overflow와 NaN/Inf는 없었다.

## Token category

| Category | Tokens | Top-1 | Top-5 | Top-10 | Mean loss |
|---|---:|---:|---:|---:|---:|
| Korean | 2,603,354 | 4.1705% | 12.7224% | 18.3405% | 7.582973 |
| English | 59,240 | 44.2860% | 49.0564% | 49.3349% | 5.640322 |
| Number | 245,485 | 28.9916% | 64.6610% | 85.6419% | 2.790494 |
| Symbol | 428,063 | 52.0377% | 72.9738% | 79.2911% | 2.730741 |
| Special | 4,780 | 100.0000% | 100.0000% | 100.0000% | 0.006367 |
| EOS | 4,782 | 12.2334% | 86.3028% | 89.4814% | 3.165948 |
| Byte fallback | 96,967 | 65.4295% | 77.0231% | 80.6697% | 2.609403 |
| Unclassified | 211,048 | 55.8195% | 72.2480% | 74.0329% | 5.085059 |

Korean target이 평가 token의 대부분을 차지하며 category별 난이도가 크게 다르다. Category 집계는 tokenizer piece 형태만 사용하고 원문을 저장하지 않는다.

## Position-aware 결과

| 구분 | Loss | Top-1 | Top-5 |
|---|---:|---:|---:|
| Packed | 6.369027 | 16.8417% | 29.2154% |
| Document-rebased | 6.370322 | 16.6767% | 28.9988% |

Position gap은 -0.1650%p다.

| Position | Tokens | Top-1 | Top-5 | Mean loss |
|---|---:|---:|---:|---:|
| 0–31 | 444,199 | 16.0255% | 28.2590% | 6.447919 |
| 32–63 | 458,528 | 16.9527% | 29.2519% | 6.374048 |
| 64–127 | 917,008 | 17.0429% | 29.3973% | 6.356391 |
| 128–191 | 916,992 | 17.0708% | 29.5045% | 6.345990 |
| 192–255 | 916,992 | 16.7511% | 29.1896% | 6.363974 |

## EOS 진단

- EOS ID는 special-token 계약의 `3`과 일치한다.
- EOS target은 4,782개, 전체 target의 0.1309%다.
- Top-1/5/10은 12.2334%/86.3028%/89.4814%, mean loss는 3.165948이다.
- Input EOS 4,782개가 모두 label target으로 보존됐고 masking 0건, label mismatch 0건이다.
- EOS는 loss에 포함됐으며 packing boundary 보존 검증을 통과했다.
- EOS context length는 평균 125.15, median 123, p95 240, p99 252 token이다.
- 위치별 EOS 수는 0–31: 513, 32–63: 627, 64–127: 1,236, 128–191: 1,173, 192–255: 1,233이다.

따라서 generation EOS 0%의 직접 원인을 EOS 삭제, masking 또는 packing 손상으로 볼 근거는 없다. EOS가 Top-5에는 자주 포함되지만 Top-1은 12.23%이므로 greedy decoding에서 선택되지 않는 현상과 모델의 EOS 순위 학습을 우선 검토해야 한다. 4,799 record와 EOS 4,782개의 17개 차이는 마지막 incomplete document/block 정책을 후속 read-only 진단할 근거다.

## Generation과 stability

동일 synthetic prompt 10개 결과는 기존 Quick와 fingerprint 수준의 결정론적 지표가 일치했다. EOS 0%, maximum length 100%, 평균 길이 16, adjacent repetition 45.3333%, repeated bigram/trigram 52.0%/42.1429%, distinct-1/2/3 0.3813/0.4800/0.5786, degenerate loop 80%다. 실제 생성 문자열은 저장하지 않았다.

32-sequence 안정성 probe에서 FP16/FP32 loss는 7.620217/7.620123, 절대 gap 0.000094이며 Top-1 gap은 0.0123%p다. 반복 forward는 결정론적으로 일치했고 NaN/Inf와 평가 실패는 0건이다.

## Resource

| 지표 | 값 |
|---|---:|
| Full evaluation wall-clock | 135.8096초 |
| Teacher-forced forward | 66.2999초 |
| 전체 처리량 | 26,903 target token/s |
| Teacher-forced 처리량 | 55,109 target token/s |
| Peak GPU allocated / reserved | 1,683,661,824 / 3,032,481,792 bytes |
| CPU working set | 879,890,432 bytes |

## Quick 대비 Full

| 지표 | Full - Quick |
|---|---:|
| Loss | +0.086884 (+1.3830%) |
| Perplexity ratio | 1.090770 |
| Top-1 / Top-5 / Top-10 | -1.3936%p / -1.6761%p / -1.4453%p |
| Packed / rebased Top-1 | -1.3936%p / -2.6195%p |
| Position gap | -1.2259%p |
| Evaluation time ratio | 173.02× |
| Peak reserved VRAM ratio | 3.249× |

승인된 기준에서 모든 `approximately_representative` 임계값을 충족한다. Candidate A Final Quick은 `approximately_representative`이며 `biased_optimistic` 특성을 가진다. Quick은 개발용 신호로만 쓰고 공식 기준선은 이 Full 결과를 사용한다.

## Candidate B 기준선과 후속 작업

Candidate A Final Full 결과는 identity, 전체 범위, 안정성 및 불변성 검증을 통과했으므로 Candidate B의 공식 내부 baseline으로 사용 가능하다. Candidate B 개발 중 Quick을 사용할 경우 Full 대비 편향을 명시하고, Candidate B 완료 후 동일 Full Evaluation을 필수 비교로 둔다.

EOS·Quick 대표성과 Candidate B Evaluation Contract는 2026-07-27 승인됐다. Candidate B training은 `not_approved`이므로 설정·학습은 별도 승인 전 시작하지 않는다. 이번 작업에서는 packing·모델·decoding을 변경하지 않았다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | Candidate A Final 전체 internal evaluation, EOS 진단, Quick 비교 및 기준선 판단 기록 |
| 2026-07-27 | Candidate A Full 공식 baseline과 Candidate A Quick 대표성 승인 반영 |
