# AIHUB-71748 Gate 7 Tiny Overfit 검증

- 문서 상태: `review`
- 마지막 검토일: 2026-07-27
- 실행 브랜치: `feat/gate7-tiny-overfit`
- 승인 근거: [제한 승인 manifest](../data/aihub-71748-gate7-tiny-overfit-approval.manifest.yaml)
- 실행 설정: [공개 example config](../../configs/gate7-tiny-overfit.example.yaml)

## 1. 범위와 판정

- [확정] AIHUB-71748의 Training 일반 원천데이터와 승인된 `operating-16k-v2/unigram-16k`만 사용했다.
- [확정] Validation, evaluation, benchmark, RLHF, SFT와 metadata는 사용하지 않았다.
- [확정] 64개 실제 JSON record, context 256, 최대 500 optimizer step으로 제한했다.
- [확정] 전체 Pretraining, Pilot Pretraining, Gate 7 상태 변경은 승인 범위에 포함하지 않았다.
- [검증 필요] loss 감소·checkpoint/resume·실행 안정성은 확인했지만 500 step에서 exact continuation을 재현하지 못했으므로 Gate 7은 `planned`를 유지한다.

## 2. Artifact 계보

외부 Git 제외 논리 위치:

`configured_external_root/analysis/gate7-tiny-overfit/AIHUB-71748/gate7-overfit-20260727-03`

| 항목 | 값 |
|---|---|
| source corpus fingerprint | `sha256:2812606509281c9246c56c5bad2efbcf53897a105b75e1843d61b2101891f28c` |
| source corpus SHA-256 | `sha256:0c7119106261e9a8487b5e2e1ba76ba220761a2fdaeb14738e968b91fdbeeb00` |
| tokenizer fingerprint | `sha256:9ce19a118a893fd69bad3124f94cea78f804d450a2ff6a9c4149b3064312f0ff` |
| model / vocab SHA-256 | `sha256:11e536f275b9377794a52c8f3f5fadfe358f631c4b7af51bf9e371d2124fff0a` / `sha256:9030a0cdc2fba938ac2a3fc8d0f7ae259d22b30ab22a2c57edb3d7cbcdfab11b` |
| dataset SHA-256 | `sha256:c6cd4a5bb072886256bbf5dee573d4f22584f90982f202f69212cb10c0358f3e` |
| dataset fingerprint | `sha256:c0caeb05eb323c4237f43afbd1c10c295bbcd619512524974d4f5f61d325afbb` |
| tokenization fingerprint | `sha256:d3da635d018e2821c2688697d95af9cb3b0082b524d7905c942cf07aae0f50d7` |
| packing fingerprint | `sha256:deb634292a0d71f56954bef419303daa285d4154593a994aafdd109e0fea4900` |

- [확정] 기존 corpus builder의 25개 Training source ZIP, quota, NFC 정규화와 exact duplicate 제거를 record 단위로 재현했다.
- [확정] 재현된 source record 수 `107,226`은 승인 corpus manifest와 일치했다.
- [확정] 첫 준비 시 `corpus.txt`의 물리적 줄을 문서 경계로 오인한 `gate7-overfit-20260727-01`은 무효로 격리했고 학습에 사용하지 않았다. 원문 내부 개행으로 물리적 줄 `2,411,164`와 record 수가 달랐다.
- [확정] 시간 제한으로 중단된 `gate7-overfit-20260727-02` staging도 증거에 사용하지 않았다.

## 3. Dataset·tokenization·packing

| 항목 | 결과 |
|---|---:|
| 문서 / 문자 / 원문 bytes | 64 / 58,745 / 136,776 |
| sampling seed | 7,174,807 |
| 최대 문서 문자 / bytes | 4,096 / 16,384 |
| 전체 token | 30,535 |
| 문서 token 길이 min / p50 / p90 / p95 / p99 / max | 102 / 381 / 864 / 1,030 / 1,634 / 1,634 |
| UNK / 범위 초과 / empty / round-trip 실패 | 0 / 0 / 0 / 0 |
| truncation | 없음 |
| BOS / EOS | 각 문서에 ID 2 / 3 삽입 |
| packed sequence | 120 × 256 |
| padding / dropped token | 185 / 0 |
| utilization | 99.3978% |

- [확정] packing은 기존 `continuous + pad` 구현을 사용했다. BOS/EOS가 문서 경계를 표시하고 마지막 block의 PAD는 attention mask 0과 label `-100`으로 제외된다.
- [확정] 동일 seed 준비 재실행 `gate7-overfit-20260727-repro`에서 dataset SHA-256과 dataset·tokenization·packing fingerprint가 모두 동일했다.
- [확정] manifest와 로그에는 원문을 기록하지 않았다. 원문 포함 파생 파일은 외부 제한 경로에만 있다.

## 4. 실제 실행 설정

| 항목 | 값 |
|---|---|
| 모델 | DohaLM-Tiny, 16,889,856 parameters |
| vocabulary / context | 16,000 / 256 |
| micro batch / accumulation / effective batch | 1 / 4 / 4 |
| optimizer | AdamW, LR `1e-3`, weight decay `0` |
| scheduler | warmup 10, cosine, min LR ratio `0.1` |
| gradient clipping | max norm `1.0` |
| seed | 17 |
| runtime | Python 3.12.5, PyTorch 2.7.1+cu118, CUDA 11.8 |
| device | NVIDIA GeForce RTX 3060 Ti, FP16 AMP |

실행은 10 step smoke 후 checkpoint를 통해 `10 → 50 → 100 → 200 → 500`으로 재개했다. GPU optimizer step 누적 시간은 약 72.27초이며 source checksum·준비 재현 검증 시간은 별도다.

## 5. 학습 결과

| step | loss | learning rate | clip 전 gradient norm |
|---:|---:|---:|---:|
| 1 | 252.593750 | 0.000100 | 35.7896 |
| 10 | 52.294390 | 0.001000 | 31.2540 |
| 50 | 23.958219 | 0.000985 | 3.8573 |
| 100 | 16.261802 | 0.000927 | 4.3635 |
| 200 | 9.222350 | 0.000705 | 2.4528 |
| 500 | 5.355370 | 0.000100 | 2.3743 |

- [확정] 전체 최초 loss는 `252.593750`, 최저 loss는 `3.694955`, 최종 loss는 `5.355370`이며 최초 대비 최종 감소율은 97.8797%다.
- [확정] 최종 perplexity는 약 `211.7422`다.
- [확정] NaN/Inf, OOM, tokenizer·vocabulary mismatch는 0건이다.
- [확정] 평균 처리량은 8,585.35 tokens/sec, 평균 optimizer step은 0.12046초다.
- [확정] peak allocated / reserved VRAM은 425,297,408 / 503,316,480 bytes다.
- [검증 필요] `psutil`이 설치되지 않아 CPU RSS는 측정하지 못했다.

## 6. Checkpoint·resume

- [확정] checkpoint-10, 50, 100, 200, 500을 외부 경로에 저장했고 각 저장 직후 manifest·파일 checksum을 검사했다.
- [확정] 각 checkpoint는 model, optimizer, scheduler, AMP scaler, training state, config, manifest와 checksum을 포함한다.
- [확정] checkpoint-500 크기는 202,788,699 bytes, 저장 시간은 약 0.770초다.
- [확정] dataset·tokenizer·model·resume config fingerprint와 global step을 매 resume에서 검증했다.
- [확정] 직전 loss 대비 resume 첫 batch loss 상대 차이는 10→50 `3.47%`, 50→100 `3.03%`, 100→200 `26.80%`, 200→500 `1.46%`였다. 단일 batch가 달라 직접 동일 loss 비교는 아니며 상태 복원과 step 연속성은 모두 통과했다.

## 7. 생성 검증

실제 prefix와 정답 문자열은 문서·로그에 출력하지 않았다.

| 시점 | continuation loss | token accuracy | exact | 인접 반복 | special 노출 |
|---|---:|---:|---|---:|---:|
| 학습 전 | 238.9297 | 0% | 실패 | 15 | 0 |
| step 50 | 23.2297 | 18.75% | 실패 | 0 | 0 |
| step 100 | 15.0673 | 18.75% | 실패 | 14 | 0 |
| step 200 | 7.3416 | 18.75% | 실패 | 14 | 0 |
| step 500 | 3.2443 | 0% | 실패 | 15 | 0 |

- [확정] teacher-forced continuation loss는 크게 감소했지만 greedy exact continuation은 개선되지 않았고 최종 출력은 반복 경향을 보였다.
- [검증 필요] 이는 실제 64-document dataset에 대한 엄격한 overfit 성공 증거가 부족함을 뜻한다.

## 8. Gate 7 판정과 보완안

- [확정] 실제 corpus 연결, tokenizer 계약, tokenization, packing, CUDA FP16, checkpoint/resume와 loss 감소 파이프라인은 정상 작동했다.
- [검증 필요] Gate 7 통과 후보 기준 중 생성 개선과 명확한 memorization을 충족하지 못했으므로 사용자 승인 전 `passed`로 변경하지 않는다.
- [검증 필요] 다음 보완은 문서 수 확대가 아니라 동일 64문서에서 learning rate, effective batch, sampling 반복도와 생성 probe 대표성을 먼저 진단하는 것이다.
- [검증 필요] 500 step 추가 실행, 128·256문서 확대, 전체 Pretraining 또는 Pilot은 새 사용자 승인이 필요하다.

## 9. 범위 준수

- [확정] 원본 ZIP, source corpus, 운영 tokenizer bundle은 수정하지 않았다.
- [확정] Validation·evaluation·benchmark·SFT·RLHF·Preference 데이터는 사용하지 않았다.
- [확정] API, Frontend, 배포, Git add·commit·push를 수행하지 않았다.
- [확정] Gate 7 상태는 `planned`, Pretraining은 `not_approved`를 유지한다.
