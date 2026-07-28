# EOS·불완전 블록 진단

- 문서 상태: `review`
- 승인 상태: `approved`
- 승인일: 2026-07-27
- 승인 범위: Candidate A Full EOS 기준선과 Candidate B 평가 성공 조건
- 대체 여부: `not_superseded`
- 마지막 검토일: 2026-07-27
- 진단 ID: `eos-quick-policy-20260727-03`
- 결과 fingerprint: `sha256:c79f8c281952d55f86eb1bda85cf35927020fe5a5e2e19e1915e0d5262c86e6e`

## 범위와 불변성

[확정] Candidate A Final과 승인된 `pilot-v2` internal evaluation을 읽기 전용으로 진단했다. optimizer·scheduler를 만들지 않았고 gradient·backward를 사용하지 않았다. checkpoint, model state와 네 source artifact의 실행 전후 checksum은 각각 동일했다. 원문, 생성문, 전체 token ID 배열은 저장하지 않았다.

[확정] 최초 실행 `-01`은 synthetic generation에 FP16 autocast를 사용해 기존 Quick의 FP32 생성 계약과 직접 비교할 수 없다. `-02`는 FP32로 이를 바로잡았고, `-03`은 EOS logit·문서 길이 bucket·repeated n-gram을 보강했다. 모두 삭제하거나 덮어쓰지 않으며 이 문서는 가장 완전한 `-03`만 canonical evidence로 사용한다.

## EOS reconciliation

| 항목 | 결과 |
|---|---:|
| record | 4,799 |
| 연속 token stream | 3,668,048 |
| input EOS | 4,799 |
| shifted target EOS | 4,782 |
| `eos_preserved` | 4,782 |
| `eos_shifted_out_of_target` | 17 |
| unexplained | 0 |
| EOS position 0 / 255 | 17 / 18 |
| masked EOS | 0 |
| padding token | 176 |

[확정] 17개 차이는 EOS가 유실·절단·mask된 것이 아니다. 연속 stream을 256 token block으로 나눈 뒤 각 block에서 `labels[1:]`를 target으로 사용하므로, block position 0에 놓인 EOS 17개는 그 block 안에 이전 token이 없어 예측 target에서 제외된다. position 255의 EOS 18개는 target에 포함된다.

[확정] 마지막 record 한 개만 마지막 불완전 block에 걸치며 EOS는 position 79에 보존된다. 남은 176 position은 padding되고 label `-100`으로 mask된다. 따라서 incomplete-block 처리로 빠진 EOS는 0개다. record truncation과 EOS block-boundary crossing도 0개다.

[확정] 4,780개 경계는 같은 block 안에서 EOS 다음 BOS를 학습한다. position 255의 EOS 18개 다음 BOS는 다음 block position 0이므로 그 BOS는 shifted target에서 제외된다. 이 진단은 기존 packing 정책의 기술적 설명이며 정책 변경 승인이 아니다.

## Candidate A Final EOS 순위

| 지표 | 값 |
|---|---:|
| EOS target | 4,782 |
| Top-1 / Top-2~5 / Top-6~10 / 11+ | 12.2543% / 74.0485% / 3.1786% / 10.5186% |
| rank median / p90 / p95 / p99 / max | 3 / 12 / 183.8 / 868.38 / 9,588 |
| EOS probability mean / median / p90 | 0.096433 / 0.053220 / 0.265261 |
| EOS logit mean / median / p90 | -0.246694 / -0.194885 / 2.208398 |
| Top-1−EOS logit margin mean / median | 1.818872 / 1.541016 |

[확정] 대다수 EOS는 rank 2~5이지만, 11+인 10.52%의 긴 꼬리가 평균 rank를 44.28까지 높인다. 짧은 context(0~63)의 rank-1은 9.37%, 긴 context(128~255)는 13.74%다. position 255는 18건뿐이며 rank-1 0%, median 2.5로 표본이 작아 단독 원인으로 일반화하지 않는다.

문서 길이 0~255 / 256~511 / 512+ token의 EOS 수는 1,120 / 1,958 / 1,704이며 rank-1은 3.39% / 16.96% / 12.68%, rank 11+는 6.25% / 8.17% / 16.02%였다. 짧은 문서는 EOS가 주로 rank 2~5이나 rank-1 전환이 약하고, 긴 문서는 긴 꼬리가 가장 크다.

## 제한적 decoding 비교

10개 synthetic prompt, profile별 16 token, 고정 seed, FP32에서 비교했다. 모든 profile의 EOS 도달률은 0%, maximum-length 도달률은 100%였다.

| Profile | 인접 반복 | 반복 bi/tri/4-gram | Distinct-1/2/3 | Loop | EOS |
|---|---:|---|---|---:|---:|
| greedy | 45.3333% | 52.00% / 42.14% / 33.85% | .3813/.4800/.5786 | 80% | 0% |
| temperature 0.7 | 9.3333% | 8.67% / 2.86% / 1.54% | .7313/.9133/.9714 | 0% | 0% |
| temperature 1.0 | 0.6667% | 0.67% / 0% / 0% | .9375/.9933/1.0000 | 0% | 0% |
| top-k 20 | 8.6667% | 5.33% / 1.43% / 0.77% | .7313/.9467/.9857 | 0% | 0% |
| top-k 50 | 4.6667% | 2.00% / 0% / 0% | .8000/.9800/1.0000 | 0% | 0% |
| top-p 0.9 | 2.0000% | 1.33% / 0.71% / 0% | .9188/.9867/.9929 | 0% | 0% |
| top-p 0.95 | 1.3333% | 0% / 0% / 0% | .9625/1.0000/1.0000 | 0% | 0% |

[확정] sampling은 이 제한 표본의 반복·loop를 줄였지만 EOS 종료는 만들지 못했다. 생성 step에서 EOS rank가 대체로 수백~수천 위였으므로 greedy만의 문제가 아니다. 다만 16-token 제한은 늦은 EOS를 관측하지 못하게 하며, 이 결과만으로 EOS 학습·packing·decoding 정책을 변경하지 않는다.

## 승인 상태와 재검토

- [확정] EOS 성공 기준은 [Candidate B 평가 계약](./candidate-b-evaluation-contract.md)과 [ADR-007](../decisions/ADR-007-evaluation-baseline-and-candidate-comparison.md)에 따라 승인됐다.
- [제외] Candidate B 학습, 데이터·split·tokenizer·packing 변경, EOS 삽입·masking·decoding 변경은 승인되지 않았다.
- [검증 필요] evaluation identity 변경, EOS 개선과 일반 Top-k·반복 성능 충돌 또는 후속 Candidate에서 기준이 부적절할 때 재검토한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | Candidate A Final EOS 4,782/4,799 reconciliation, 순위와 제한적 decoding 진단 기록 |
| 2026-07-27 | 사용자 승인으로 EOS success baseline과 Candidate B 평가 조건을 `approved`로 변경 |
[확정] 이 문서의 Candidate B 성공 조건은 2026-07-27 승인 당시 계약의 historical 기준이다. 2026-07-28
승인된 [ADR-008](../decisions/ADR-008-eos-generation-and-decoding-evaluation-policy.md)과
[EOS Success Policy](./eos-success-policy.md)는 향후 모델 단계별 계약이며 과거 판정을 소급 변경하지 않는다.
