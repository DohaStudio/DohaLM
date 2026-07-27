# Candidate B Final Full Evaluation 결과

- 문서 상태: `review`
- 마지막 검토일: 2026-07-28
- 태그: `evaluation`, `candidate-b`, `full`, `gpu`, `eos`
- 관련 문서: [평가 계약](./candidate-b-evaluation-contract.md), [계약 수정](./candidate-b-full-evaluation-contract-fix.md), [Candidate A/B 비교](./candidate-a-b-full-comparison.md), [리더보드](./model-evaluation-leaderboard.md)

## Identity와 실행 경계

| 항목 | 값 |
|---|---|
| Run | `FULL-PRETRAIN-CANDIDATE-B-20260728-0002` |
| Training commit | `4c2eced3bf70551fbf7bc8ebde6666062584d92b` |
| Evaluation code commit | `79a88b00ae02325119fd7b04f9d1a90f4abaa27d` |
| Evaluation ID | `candidate-b-final-full-20260728-03` |
| EOS diagnostic ID | `eos-candidate-b-final-20260728-01` |
| Artifact identity | `sha256:24a02a1e27a8f8ae45bd2ab5b15339c18b40bf386098f8feac7c53fb59db9558` |
| Checkpoint checksum | `sha256:f3edc978db9d88e9de8e2e423a28291e9f35e2e163f0413c0e27e95facc55395` |
| Quick result | `sha256:96f7d91451fd81b1aa75e2937b2a16d4509728f0ee1b71f16adfaf01998732d4` |
| Full result | `sha256:7b796f3abed0d6bd7a2426f9dff619f0609f59a4e1d04bf232545548d25d9df0` |
| EOS diagnostic result | `sha256:f218e22db64f20ea7ac69ec5d00fffd352beb88c010bcfbf5d54d13cf5768040` |

전체 14,329 packed sequence, 3,653,719 target token을 CUDA FP16과 deterministic seed 17로 평가했다.
원문·decoded text·전체 token ID는 저장하지 않았다. optimizer, scheduler, backward와 gradient는 생성하거나
호출하지 않았고 checkpoint, model, tokenizer, dataset checksum은 실행 전후 동일했다.

## Full 지표

| 지표 | 값 |
|---|---:|
| Loss / PPL | 5.591160 / 268.0464 |
| Top-1 / Top-5 / Top-10 | 21.8782% / 36.8569% / 43.9577% |
| Sequence mean / median | 21.8782% / 19.2157% |
| Sequence p10 / p25 / p75 / p90 | 12.1569% / 15.2941% / 25.4902% / 36.0784% |
| Packed / rebased Top-1 | 21.8782% / 22.1533% |
| Position gap | +0.2751%p |

Perplexity는 finite이고 NaN/Inf와 평가 실패는 0건이다.

## Token category

| Category | Tokens | Top-1 | Top-5 | Top-10 | Mean loss |
|---|---:|---:|---:|---:|---:|
| Korean | 2,603,354 | 9.4773% | 21.9453% | 28.5095% | 6.707260 |
| English | 59,240 | 48.1499% | 51.7691% | 53.1465% | 4.977655 |
| Number | 245,485 | 30.9522% | 67.4330% | 88.6066% | 2.499328 |
| Symbol | 428,063 | 59.9325% | 78.6485% | 84.4901% | 2.176666 |
| Special | 4,780 | 100.0000% | 100.0000% | 100.0000% | 0.000078 |
| EOS | 4,782 | 28.0845% | 88.4358% | 90.8407% | 2.572150 |
| Byte fallback | 96,967 | 72.4123% | 85.0537% | 88.7993% | 1.636476 |
| Unclassified | 211,048 | 54.6065% | 71.5373% | 74.8574% | 4.529762 |

## EOS rank와 generation

EOS target 4,782개는 masking·label mismatch 없이 loss에 포함됐다. EOS rank median/p90은 `2`/`7`,
mean은 56.41이며 rank 1/2–5/6–10/11+ 비율은 28.2936%/60.4350%/2.1121%/9.1593%다.
EOS probability mean/median은 0.206174/0.108677이고 Top-1−EOS logit margin mean/median은
1.5031/0.9063이다.

현재 repository prompt의 greedy 10개에서 EOS rate 0%, maximum-length rate 100%, loop 80%, 인접 반복
23.3333%, distinct-1/2/3 0.4188/0.5667/0.6643, special-token exposure 0%다. EOS rank는 개선됐지만
승인 계약의 greedy EOS `>0%`와 maximum-length `<100%`를 충족하지 못했다.

## Position, stability와 resource

| Position | Tokens | Top-1 | Top-5 | Mean loss |
|---|---:|---:|---:|---:|
| 0–31 | 444,199 | 20.4883% | 35.2335% | 5.717281 |
| 32–63 | 458,528 | 21.9241% | 36.9018% | 5.598790 |
| 64–127 | 917,008 | 22.1094% | 37.0513% | 5.572949 |
| 128–191 | 916,992 | 22.2137% | 37.2347% | 5.558281 |
| 192–255 | 916,992 | 21.9618% | 37.0485% | 5.577342 |

32-sequence FP16/FP32 loss gap은 0.0000105, Top-1 gap은 0.0368%p이며 tolerance 안이다. 반복 forward는
결정론적으로 일치했다. Full wall-clock 123.432초, 처리량 29,601 target token/s, peak GPU
allocated/reserved 1,683,661,824/3,032,481,792 bytes, CPU working set 896,049,152 bytes다.

## Quick 대비와 판정

Full−Quick는 loss +0.094946, Top-1/5/10 -1.5440/-1.5071/-1.3610%p다. 제안 임계값 중 Top-1과
position gap 항목을 벗어나 `candidate_threshold_outcome: fail`, 대표성 상태는
`insufficient_evidence`다. Quick은 공식 판정에 사용하지 않는다.

Candidate B Full 자체는 `completed`이고 teacher-forced 비교는 유효하다. 다만 승인된 EOS generation
성공 조건을 충족하지 못했으므로 최종 상태는 `evaluated_contract_not_passed`이며 Candidate A 공식 baseline을
자동 대체하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | Candidate B Final Full·EOS ranking·불변성 및 계약 판정 기록 |
