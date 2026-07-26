# AIHUB-71748 Gate 7 Tiny Overfit 검증

- 문서 상태: `approved`
- 마지막 검토일: 2026-07-27
- 실행 브랜치: `feat/gate7-tiny-overfit`
- 승인 근거: [제한 승인 manifest](../data/aihub-71748-gate7-tiny-overfit-approval.manifest.yaml)
- 실행 설정: [공개 example config](../../configs/gate7-tiny-overfit.example.yaml)

## 1. 범위와 판정

- [확정] AIHUB-71748의 Training 일반 원천데이터와 승인된 `operating-16k-v2/unigram-16k`만 사용했다.
- [확정] Validation, evaluation, benchmark, RLHF, SFT와 metadata는 사용하지 않았다.
- [확정] 최초 실행은 64개 실제 JSON record, context 256, 최대 500 optimizer step으로 제한했다. 후속 승인에서는 동일 64문서와 packing을 유지하고 LR 3개를 200 step 비교한 뒤 단일 후보만 최대 1,000 step까지 허용했다.
- [확정] 전체 Pretraining, Pilot Pretraining, Gate 7 상태 변경은 승인 범위에 포함하지 않았다.
- [확정] 후속 검증에서 학습 조건과 동일한 packed sequence 기준의 명확한 memorization과 exact continuation을 확인했다.
- [확정] 2026-07-27 사용자 최종 승인에 따라 Gate 7은 `passed`다.

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

## 8. 최초 Gate 7 판정과 보완안

- [확정] 실제 corpus 연결, tokenizer 계약, tokenization, packing, CUDA FP16, checkpoint/resume와 loss 감소 파이프라인은 정상 작동했다.
- [검증 필요] Gate 7 통과 후보 기준 중 생성 개선과 명확한 memorization을 충족하지 못했으므로 사용자 승인 전 `passed`로 변경하지 않는다.
- [검증 필요] 다음 보완은 문서 수 확대가 아니라 동일 64문서에서 learning rate, effective batch, sampling 반복도와 생성 probe 대표성을 먼저 진단하는 것이다.
- [검증 필요] 500 step 추가 실행, 128·256문서 확대, 전체 Pretraining 또는 Pilot은 새 사용자 승인이 필요하다.

## 9. 범위 준수

- [확정] 원본 ZIP, source corpus, 운영 tokenizer bundle은 수정하지 않았다.
- [확정] Validation·evaluation·benchmark·SFT·RLHF·Preference 데이터는 사용하지 않았다.
- [확정] API, Frontend, 배포, Git add·commit·push를 수행하지 않았다.
- [확정] 이 항목은 최초 500-step 실행 당시 기록이다. 후속 보완 검증과 사용자 최종 승인으로 Gate 7은 `passed`가 됐으며 Pretraining은 `not_approved`를 유지한다.

## 10. 보완 검증 범위와 기존 run 무결성

후속 외부 Git 제외 논리 위치:

`configured_external_root/analysis/gate7-tiny-overfit/AIHUB-71748/gate7-followup-20260727-01`

- [확정] 최초 유효 run `gate7-overfit-20260727-03`을 read-only로 다시 검사했다. dataset, tokenization, packing, tokenizer fingerprint와 checkpoint-500의 파일 checksum, global/optimizer/scheduler step `500`, AMP scaler 상태가 모두 일치했다.
- [확정] 후속 run은 최초 run의 준비 artifact를 checksum 검증 후 별도 run ID로 복제했다. dataset `sha256:c0ca...afbb`, tokenization `sha256:d3da...50d7`, packing `sha256:deb6...4900`, tokenizer `sha256:9ce1...f0ff`를 유지했다.
- [확정] 문서 `64`, packed sequence `120`, target token `30,415`를 유지했다. dataset 확대, Validation, evaluation, benchmark는 사용하지 않았다.
- [확정] 원문, prompt, target, 생성 문자열은 저장소 문서나 평가 JSON에 기록하지 않았다.

## 11. 생성 평가 코드 분석과 수정

- [확정] 기존 causal alignment는 off-by-one이 없었다. `logits[t]`가 `input_ids[t+1]`을 예측하며, 첫 continuation은 `logits[prefix_length-1]`과 `input_ids[prefix_length]`을 비교한다.
- [확정] generation은 `model.eval()`, inference mode, 전체 prompt attention mask, greedy decoding, EOS ID 3 종료, 최대 16 new token 조건을 사용한다. KV cache와 special-token suppression은 사용하지 않는다.
- [발견] 최초 평가는 raw document 하나를 position 0에서 시작했지만 학습은 120개의 연속 packed sequence와 learned absolute position을 사용했다. 따라서 최초 단일 probe는 실제 학습 목적 전체를 대표하지 않았다.
- [수정] 학습과 동일한 `train.jsonl`의 sequence 경계, absolute position, attention mask, label `-100` 제외 조건으로 전체 120 sequence teacher-forced 평가를 추가했다.
- [수정] raw document를 position 0으로 재배치한 평가는 일반화 성격의 보조 지표 `document_rebased_teacher_forced`로 분리했다.
- [수정] AR probe도 첫 번째 유효 packed training sequence로 고정하고 prefix 16/32/64/128을 동일 token ID 기준으로 평가했다.
- [확정] 합성 정답 sequence의 causal shift, BOS-to-EOS teacher forcing, padding 제외, first-token, prefix match와 deterministic divergence 단위 테스트를 추가했다. 동일 checkpoint-500의 평가를 두 번 실행한 결과는 byte-equivalent evaluation JSON이었다.

## 12. LR 3개 200-step 비교

세 후보는 seed 17, 동일 model initialization, 동일 120-sequence packing, micro batch 1, accumulation 4, FP16 AMP, warmup 10과 1,000-step cosine scheduler를 공유했다. 세 실행의 최초 batch loss는 모두 `252.593750`이었다.

| LR | 최저 / 최종 train loss | 감소율 | packed TF top-1 / top-5 | packed TF loss | AR first-token (16/32/64/128) | prefix match | NaN/Inf/OOM |
|---:|---:|---:|---:|---:|---|---|---:|
| 3e-4 | 15.555992 / 17.498101 | 93.07% | 9.2027% / 19.5627% | 16.950180 | 0/0/0/0 | 0/0/0/0 | 0 |
| 5e-4 | 11.333527 / 13.159567 | 94.79% | 10.3403% / 21.5946% | 12.627393 | 0/0/0/1 | 0/0/0/1 | 0 |
| 1e-3 | 7.638476 / 8.852613 | 96.50% | 12.9114% / 25.1290% | 8.194499 | 0/1/0/1 | 0/1/0/1 | 0 |

- [확정] `1e-3`이 train loss, 전체 packed teacher-forced 지표와 AR first-token/prefix 지표에서 가장 우수했고 generation 반복도 최초 단일-probe 결과보다 악화되지 않아 유일한 연장 후보로 선정했다.
- [확정] 나머지 두 후보는 checkpoint-200에서 종료했고 연장하지 않았다.

## 13. 선택 후보 연장 결과

| step | 최저 / 최종 train loss | packed TF top-1 / top-5 | packed TF loss / perplexity | AR first-token | AR prefix match | exact continuation |
|---:|---:|---:|---:|---|---|---|
| 200 | 7.638476 / 8.852613 | 12.9114% / 25.1290% | 8.194499 / 3,621.10 | 0/1/0/1 | 0/1/0/1 | 0/4 |
| 300 | 5.168037 / 5.943514 | 22.3081% / 39.8586% | 5.679759 / 293.88 | 0/0/0/1 | 0/0/0/1 | 0/4 |
| 500 | 2.047490 / 2.757749 | 58.3857% / 77.0870% | 2.224770 / 9.251 | 0/1/0/1 | 0/5/0/6 | 0/4 |
| 750 | 0.096490 / 0.147213 | 97.6393% / 99.6285% | 0.114812 / 1.1217 | 1/1/1/1 | 15/16/16/6 | 2/4 |
| 1,000 | 0.003040 / 0.006732 | 99.9047% / 99.9934% | 0.006235 / 1.0063 | 1/1/1/1 | 16/16/16/16 | 4/4 |

- [확정] step 1,000의 packed TF sequence별 top-1은 min `98.4314%`, median `100%`, mean `99.9052%`, max `100%`다.
- [확정] prefix 16/32/64/128 모두 16-token greedy exact continuation을 재현했다. 인접 반복은 각각 `1/0/0/0`, unique-token ratio는 `0.8125/0.9375/0.9375/0.625`, special token 노출은 모두 0이었다.
- [확정] 16-token target 구간에 EOS가 없으므로 EOS 생성도 모두 false였다. 이는 EOS 종료 실패 증거가 아니다.
- [주의] 문서별 position을 0으로 재배치한 보조 평가는 step 1,000에서도 top-1 `9.2613%`, loss `21.8727`이었다. 결과는 동일 packed 학습 조건의 Tiny Overfit 성공을 입증하며 문서 독립 시작 위치에 대한 일반화를 입증하지 않는다.

## 14. Sampling, 자원과 resume

| step | consumed sequence / token | equivalent epoch / 완전 반복 | sampler epoch / cursor |
|---:|---:|---:|---:|
| 200 | 800 / 204,800 | 6.6667 / 6 | 6 / 80 |
| 300 | 1,200 / 307,200 | 10.0000 / 10 | 9 / 120 |
| 500 | 2,000 / 512,000 | 16.6667 / 16 | 16 / 80 |
| 750 | 3,000 / 768,000 | 25.0000 / 25 | 24 / 120 |
| 1,000 | 4,000 / 1,024,000 | 33.3333 / 33 | 33 / 40 |

- [확정] sampler의 records/batches yielded는 각 시점의 consumed sequence와 일치했다. resume 후 중복·누락 또는 step 불연속 증거는 없다.
- [확정] resume 직전 마지막 batch 대비 첫 batch loss 상대 차이는 200→300 `2.45%`, 300→500 `4.42%`, 500→750 `25.96%`, 750→1,000 `19.10%`였다. 서로 다른 batch 비교이며 optimizer/scheduler/scaler/sampler 상태와 global step은 정상 복원됐다.
- [확정] 최종 segment 평균 처리량은 `9,168.68 tokens/sec`, optimizer step은 `0.11236초`다.
- [확정] peak allocated/reserved VRAM은 `426,477,056 / 507,510,784 bytes`, Windows PSAPI peak working set은 `1,071,263,744 bytes`다.
- [확정] checkpoint-1,000은 202,788,710 bytes이며 model, optimizer, scheduler, scaler, training state, config, manifest, checksums를 포함한다. 검사 시 global step과 모든 checksum이 일치했다.

## 15. 보완 검증 판정

- [확정] 실제 승인 corpus에서 loss가 지속적으로 감소했고 NaN/Inf/OOM 없이 RTX 3060 Ti에서 안정적으로 실행됐다.
- [확정] packed teacher-forced top-1이 99.9%까지 증가했고 네 AR prefix 모두 exact continuation에 성공했다.
- [확정] dataset/tokenizer/packing/config identity와 checkpoint/resume가 일치하고 동일 seed 초기화도 재현됐다.
- [확정] 2026-07-27 사용자 최종 승인으로 Tiny Overfit Validation은 `approved`, Actual Corpus Training Pipeline Validation과 Checkpoint/Resume Validation은 `completed`, Gate 7은 `passed`다.
- [확정] 이 승인은 동일 packed 학습 조건의 memorization 검증에 한정된다. Pretraining, Pilot Pretraining, 데이터 확대와 기타 모델 학습은 계속 승인되지 않았다.

## 16. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | [확정] 동일 64문서 보완 검증의 packed top-1 99.9047%, loss 0.006235, prefix 4종 exact continuation과 checkpoint/resume 증거에 대한 사용자 최종 승인으로 문서 상태를 `approved`, Gate 7을 `passed`로 변경함 |
