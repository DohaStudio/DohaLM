# AIHUB-71748 canonical pilot-v2 100-step Pilot 결과

- 문서 상태: `review`
- 실행일: 2026-07-27
- 실행 브랜치: `feat/pilot-pretraining`
- 실행 commit: `c3b778df31b9888ca6539b1d2b3c09faca6ec0e9`
- 승인 기준 commit: `556f395092b5065874552a116db801d1b5999bdc`
- 승인·결과 manifest: [pilot-pretraining-100-v2.manifest.yaml](./pilot-pretraining-100-v2.manifest.yaml)
- 공개 설정: [pilot-pretraining-100-v2.example.yaml](../../configs/pilot-pretraining-100-v2.example.yaml)

## 1. 판정

- [확정] canonical `pilot-v2`와 승인된 운영 tokenizer만 사용해 정확히 100 optimizer step을 실행했다.
- [확정] 상태는 `completed_pilot_100_steps`, runtime validation과 checkpoint/resume는 `passed`다.
- [확정] 해당 100-step 실행 승인은 `consumed`다.
- [확정] Full Pretraining, 자동 연장, 100 step 초과 학습은 `not_approved`다.
- [확정] Gate 상태는 변경하지 않았다.

승인 기준 commit과 실제 실행 commit의 차이는 사용자가 직전에 요청한 pilot-v2 readiness·runtime 검증 변경의 commit·push 결과다. 실행 전 branch, HEAD, code/config identity를 manifest와 다시 비교했고 불일치는 없었다. 현재 작업에서 추가한 미커밋 실행 안전장치와 결과 기록 때문에 environment manifest의 `git_dirty`는 `true`다.

## 2. 승인된 identity

| 항목 | 값 |
|---|---|
| Dataset version | `pilot-v2` |
| Canonical contract | `aihub-71748-training-selection-v1` |
| Contract fingerprint | `sha256:bea1f19b1571e062096bd1d9dbd7b2c4144f2e9bf8f578448b190e3a60eb4293` |
| Pilot dataset fingerprint | `sha256:89c721902844d6242d2bbb4a5be4be80286bd7debd19c52b5382078f3110c77b` |
| Training lineage fingerprint | `sha256:a0677dc18dbc98371d349aef0f83ea610ab4a984657412bd1518b883a66bd3c6` |
| PII fingerprint | `sha256:91c6ad9827645249641d96e2da1d415124a4069ca45929150e9d49fb830ee3ed` |
| Split fingerprint | `sha256:dd71433c11a69345fed217620ba84b4ebc8b969b25400db07af9bc5ef0f4696f` |
| Tokenization fingerprint | `sha256:a0fbc78d4e7e55e7e79bd72362946964514d111993bd8889d312f8d6efceef6c` |
| Packing fingerprint | `sha256:e7ad635dafa3f18a77a243ec17b2bcb9d5f29c72e081ad161bd63b2218e0680b` |
| Tokenizer | `operating-16k-v2/unigram-16k` |
| Tokenizer fingerprint | `sha256:9ce19a118a893fd69bad3124f94cea78f804d450a2ff6a9c4149b3064312f0ff` |
| Model fingerprint | `sha256:a7a4d109c6d9f385bc65f33a0c5b9a0e9af218764b2e0648ea0c81b317fed106` |
| Config fingerprint | `sha256:9d78f5dbc668eafaa44d558364405e266db9e4c7626ac0b749c2c5c2b81d967f` |
| Training config fingerprint | `sha256:31136e924cd63a29c428400dd955dc956564de770e7295d692ec2c67c60b72c0` |

Source 107,226건에서 Training 내부 train 92,948건과 internal evaluation 4,799건을 사용했다. AI Hub 원래 Validation, benchmark, RLHF, SFT, preference, label-only, metadata field는 사용하지 않았다. 실제 텍스트·prompt·continuation·전체 token ID 배열은 산출물에 저장하지 않았다.

## 3. Resolved training config

| 항목 | 값 |
|---|---:|
| Model / parameters | DohaLM-Tiny / 16,889,856 |
| Optimizer | AdamW |
| Learning rate / weight decay | `3e-4` / `0.1` |
| Scheduler / warmup | cosine / 10 step |
| Micro batch / accumulation / effective batch | 2 / 4 / 8 |
| Context length | 256 |
| Maximum optimizer step | 100 |
| Checkpoint / evaluation / logging interval | 25 / 10 / 1 |
| Precision | FP16 AMP |
| Seed | 17 |

Resolved config에는 prompt 원문이 없고 SHA-256과 `prompt_text_stored: false`만 기록된다. 생성 전후 결과도 digest와 길이만 기록하며 `decoded_text_stored: false`다.

## 4. Run과 처리량

- Run ID: `PILOT-100-V2-20260727-0001`
- 논리 위치: `configured_external_root/analysis/pilot-pretraining/AIHUB-71748/runs/PILOT-100-V2-20260727-0001`
- Global/optimizer/micro step: 100 / 100 / 400
- 소비 record/token: 800 / 204,800
- Sampler sample offset: 800
- Equivalent epoch: 약 0.002872
- 평균 처리량: 10,323.06 token/s
- 평균 optimizer step 시간: 0.199633초
- 전체 wall time: 928.491초, 약 15분 28.5초

전체 wall time에는 시작·10-step 주기·종료 시점의 full internal evaluation 11회와 checkpoint I/O가 포함된다.

## 5. Train loss와 learning rate

| Step 구간 | 평균 loss | 최저 | 최고 | 시작 LR | 종료 LR |
|---|---:|---:|---:|---:|---:|
| 1~10 | 213.0133 | 119.5940 | 250.5206 | 0.0000300 | 0.0003000 |
| 11~25 | 53.2034 | 39.8432 | 88.9848 | 0.0002999 | 0.0002819 |
| 26~50 | 34.3666 | 30.4142 | 38.8923 | 0.0002795 | 0.0001884 |
| 51~75 | 30.0123 | 27.1984 | 32.4531 | 0.0001838 | 0.0000782 |
| 76~100 | 28.2591 | 26.7322 | 29.5555 | 0.0000747 | 0.0000300 |

Step 1 loss는 249.1661, step 10은 119.5940, step 100은 27.2650이다. Loss는 비정상 발산 없이 감소했으며 이 결과는 100-step 운영 안정성 evidence이지 전체 학습 수렴 판정이 아니다.

## 6. Internal evaluation

매 평가마다 7,165 batch, 14,329 packed sequence, 3,653,719 target token 전체를 평가했다.

| Step | Loss | Perplexity | 시간(초) |
|---:|---:|---:|---:|
| 0 | 251.0258 | 1.045047e109 | 76.956 |
| 10 | 90.4956 | 2.003260e39 | 76.551 |
| 20 | 44.3872 | 1.892875e19 | 76.362 |
| 30 | 36.7441 | 9.072895e15 | 76.622 |
| 40 | 33.2306 | 2.703008e14 | 76.499 |
| 50 | 31.2358 | 3.677192e13 | 88.709 |
| 60 | 29.9766 | 1.043896e13 | 98.819 |
| 70 | 29.1380 | 4.513223e12 | 81.834 |
| 80 | 28.6354 | 2.730284e12 | 85.175 |
| 90 | 28.3368 | 2.025491e12 | 80.219 |
| 100 | 28.1548 | 1.688374e12 | 82.292 |

모든 loss와 perplexity는 finite였다. Perplexity의 절대값은 짧은 Pilot 초기 상태 특성이며 모델 품질 승인 근거로 사용하지 않는다.

## 7. 안정성과 자원

| 항목 | 결과 |
|---|---:|
| NaN/Inf metric | 0 |
| OOM | 0 |
| AMP skip | 0 |
| Peak GPU allocated | 524,780,032 bytes |
| Peak GPU reserved | 593,494,016 bytes |
| Peak CPU working set | 1,025,712,128 bytes |
| 완료 시 남은 disk | 992,156,565,504 bytes |

자동 중단 조건은 발생하지 않았다. 정확히 global step 100에 도달한 뒤 추가 학습 없이 종료했다.

## 8. Checkpoint와 atomic publish

| Checkpoint | Bundle bytes | 저장 시간(초) | 검증 |
|---|---:|---:|---|
| checkpoint-25 | 202,789,734 | 0.757826 | passed |
| checkpoint-50 | 202,789,737 | 0.676339 | passed |
| checkpoint-75 | 202,789,738 | 0.752244 | passed |
| checkpoint-100 | 202,789,742 | 0.725923 | passed |

각 checkpoint는 정확히 `model.pt`, `optimizer.pt`, `scheduler.pt`, `scaler.pt`, `training-state.json`, `config.json`, `manifest.json`, `checksums.json` 8개 파일을 포함한다. 개별 파일 checksum, inventory digest, bundle byte와 집계 manifest가 모두 일치했다. staging·temporary artifact와 예상 밖 파일은 없었다.

## 9. Load-only resume와 mismatch 차단

별도 Python 프로세스에서 checkpoint-100을 실제 load-only로 복원했다. Model, optimizer, scheduler, AMP scaler와 TrainingState를 읽었고 추가 optimizer step은 실행하지 않았다.

- 복원 state: global/optimizer 100, micro 400, records 800, tokens 204,800
- Stateful sampler: batches 400, records 800, sample offset 800
- Dataset version/fingerprint/split/source lineage mismatch: `CHECKPOINT_DATASET_MISMATCH`
- Tokenizer fingerprint mismatch: `CHECKPOINT_TOKENIZER_MISMATCH`
- Training config/seed/model config mismatch: `CHECKPOINT_CONFIG_MISMATCH`

8종 mismatch는 모두 fail-closed로 차단됐다.

## 10. Log·출력 무결성

- JSONL: 정확히 100행, global step 1~100 연속, 모든 수치 finite
- JSONL 크기: 61,630 bytes
- 실행 디렉터리 실제 총크기: 811,315,448 bytes
- Run summary SHA-256: `sha256:bbd6bf4b631adc263708395a98da21e7daee9962b0a4361eea3c87c5df55dee5`
- Failure report: 없음
- Staging·temporary file: 없음
- Prompt·decoded text 저장: 없음

## 11. 기존 artifact 보호

실행 전 기준선과 실행 후 SHA-256을 비교했다. Historical corpus, 운영 tokenizer model, pilot-v1 dataset manifest, 기존 v1/v2 Smoke summary, pilot-v2 prepared checksum inventory, Gate 7 checkpoint checksum inventory가 모두 동일했다. 원본 ZIP과 prepared dataset은 수정·이동·삭제하지 않았고 기존 Smoke checkpoint를 시작점으로 사용하지 않았다.

`src/tokenizer/__init__.py`와 `src/tokenizer/pilot.py`에는 diff가 없다. API, Frontend, 배포, SFT, RLHF, Preference Training, Gate 상태 변경은 수행하지 않았다.

## 12. 결론과 다음 승인 경계

100-step Pilot의 주목적인 runtime 안정성, full internal evaluation, FP16 AMP, checkpoint/atomic publish, load-only resume, fingerprint fail-closed, 로그·산출물 무결성은 모두 통과했다.

이 완료는 Full Pretraining 승인이 아니다. 다음 작업 전에 별도 사용자 승인이 필요한 항목은 Full Pretraining 범위·최대 step/token budget, 장시간 GPU 실행, checkpoint 승격·보존, 평가·중단·재시작 정책, 추가 disk 예산과 결과 공개·재배포 경계다.
