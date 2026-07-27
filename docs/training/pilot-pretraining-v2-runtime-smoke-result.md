# AIHUB-71748 pilot-v2 Runtime Smoke 결과

- 문서 상태: `review`
- 검증일: 2026-07-27
- 승인 manifest: [pilot-v2 Runtime Smoke manifest](./pilot-pretraining-v2-runtime-smoke.manifest.yaml)
- dataset manifest: [pilot-v2 manifest](../data/aihub-71748-pilot-v2.manifest.yaml)
- 실행 범위: pilot-v2 전용 최대 5 optimizer step Runtime Smoke
- 최종 readiness: `ready_awaiting_final_execution_approval`

## 1. 범위와 승인 경계

- [확정] `feat/pilot-pretraining`, Git commit `556f395092b5065874552a116db801d1b5999bdc`에서 새 run `SMOKE-PILOT-V2-0001`을 정확히 5 optimizer step 실행했다.
- [확정] 100-step Pilot, Full Pretraining, SFT, RLHF, Preference Training과 Gate 상태 변경은 실행하거나 승인하지 않았다.
- [확정] checkpoint-5는 Runtime Smoke 전용이며 100-step 시작 checkpoint로 승격할 수 없다.
- [확정] 실제 원문, prompt, continuation, decoded text와 token ID 배열은 출력하거나 저장하지 않았다. 생성 검증에는 길이와 SHA-256만 저장했다.

## 2. 입력 identity와 무결성

| 항목 | 검증값 |
|---|---|
| Dataset version | `pilot-v2` |
| Canonical selection contract | `aihub-71748-training-selection-v1` |
| Contract fingerprint | `sha256:bea1f19b1571e062096bd1d9dbd7b2c4144f2e9bf8f578448b190e3a60eb4293` |
| Source records | 107,226 |
| Pilot dataset fingerprint | `sha256:89c721902844d6242d2bbb4a5be4be80286bd7debd19c52b5382078f3110c77b` |
| Training lineage fingerprint | `sha256:a0677dc18dbc98371d349aef0f83ea610ab4a984657412bd1518b883a66bd3c6` |
| PII fingerprint | `sha256:91c6ad9827645249641d96e2da1d415124a4069ca45929150e9d49fb830ee3ed` |
| Split fingerprint | `sha256:dd71433c11a69345fed217620ba84b4ebc8b969b25400db07af9bc5ef0f4696f` |
| Tokenization manifest SHA-256 | `sha256:a0fbc78d4e7e55e7e79bd72362946964514d111993bd8889d312f8d6efceef6c` |
| Packing manifest SHA-256 | `sha256:e7ad635dafa3f18a77a243ec17b2bcb9d5f29c72e081ad161bd63b2218e0680b` |
| Tokenizer fingerprint | `sha256:9ce19a118a893fd69bad3124f94cea78f804d450a2ff6a9c4149b3064312f0ff` |
| Smoke config fingerprint | `sha256:cdb5c9d536c82a90872a1690cf109d118b2c31eff9c83d6d3c178914734712cc` |
| Model fingerprint | `sha256:a7a4d109c6d9f385bc65f33a0c5b9a0e9af218764b2e0648ea0c81b317fed106` |

- [확정] Train 92,948 records와 내부 evaluation 4,799 records만 연결했고 AI Hub Validation은 사용하지 않았다.
- [확정] UNK, vocabulary 범위 초과, empty sequence와 train/evaluation 혼합은 모두 0이다.

## 3. 실행 설정

| 항목 | 값 |
|---|---:|
| Model / context / vocab | DohaLM-Tiny / 256 / 16,000 |
| Optimizer | AdamW |
| LR / weight decay | `3e-4` / `0.1` |
| Scheduler / warmup | cosine / 5 step |
| Micro batch / accumulation / effective batch | 2 / 4 / 8 |
| FP16 AMP | enabled |
| Seed | 17 |
| Validation | 시작 전·종료 후 각 최대 8 batch |
| Checkpoint | step 5에서 1개 |

## 4. Step별 Runtime 결과

| Step | Loss | LR | Tokens/s | Step time (s) | Gradient norm | AMP skip |
|---:|---:|---:|---:|---:|---:|---|
| 1 | 249.166054 | 0.00006 | 6,315.57 | 0.3243 | 1.000000 | false |
| 2 | 250.520584 | 0.00012 | 8,680.02 | 0.2359 | 1.000000 | false |
| 3 | 247.912014 | 0.00018 | 9,195.66 | 0.2227 | 1.000000 | false |
| 4 | 242.469608 | 0.00024 | 8,781.36 | 0.2332 | 1.000000 | false |
| 5 | 224.065567 | 0.00003 | 8,793.18 | 0.2329 | 1.000000 | false |

- [확정] 평균 처리량은 8,353.16 tokens/s, 평균 optimizer step 시간은 0.2498초다.
- [확정] NaN/Inf 0건, AMP skip 0건, OOM 0건이며 정확히 global/optimizer step 5에서 종료했다.

## 5. Evaluation과 자원

| 항목 | 시작 전 | 종료 후 |
|---|---:|---:|
| Evaluation loss | 254.020098 | 195.741898 |
| Batches / sequences / target tokens | 8 / 16 / 4,080 | 8 / 16 / 4,080 |

| 자원 항목 | 측정값 |
|---|---:|
| Peak allocated VRAM | 524,190,208 bytes |
| Peak reserved VRAM | 593,494,016 bytes |
| Peak CPU working set | 1,015,390,208 bytes (`windows_psapi`) |
| 전체 실행 시간 | 6.3931초 |
| 실행 후 D: 여유 공간 | 992,973,340,672 bytes |

Loss 감소는 참고 지표이며 Runtime Smoke의 필수 성공 조건으로 사용하지 않았다.

## 6. Output과 checkpoint 검증

- 논리 위치: `configured_external_root/analysis/pilot-pretraining/AIHUB-71748/runs/SMOKE-PILOT-V2-0001`
- 전체 크기: 202,799,718 bytes
- JSONL log: 1,926 bytes
- 결과 summary SHA-256: `sha256:d04a1388dc3b94049fd7faead48d23305efa47fada8f9fbaff6402d59583cc3c`
- checkpoint-5 크기: 202,788,185 bytes
- checkpoint 저장 시간: 0.7772초
- checkpoint checksum manifest SHA-256: `sha256:3fc27c1f560819ae4b00136c1e5a459ebbe14282dc51bc87791489ce2c698dbc`
- [확정] checkpoint 필수 파일 8개와 파일별 SHA-256을 재검증했고 mismatch는 0건이다.
- [확정] staging directory가 남지 않아 atomic publish 완료 상태를 확인했다.
- [확정] 출력 경로 write·atomic rename·read checksum·probe delete와 실행 전 5GiB 이상 여유 공간을 확인했다.

## 7. Load-only Resume와 fail-closed

- [확정] 추가 학습 호출 없이 checkpoint-5를 load-only로 복원했다.
- [확정] global step 5, optimizer step 5, micro step 20, records 40, tokens 10,240이 복원됐다.
- [확정] sampler state의 batches 20, records 40, sample offset 40, epoch 0, seed 17과 permutation fingerprint를 확인했다.
- [확정] dataset version, dataset fingerprint, split fingerprint 변경은 composite training dataset fingerprint 불일치로 `CHECKPOINT_DATASET_MISMATCH` 차단된다.
- [확정] tokenizer fingerprint 변경은 `CHECKPOINT_TOKENIZER_MISMATCH`, config·seed·model fingerprint 변경은 `CHECKPOINT_CONFIG_MISMATCH`로 차단됨을 실제 load-only 호출로 확인했다.

Dataset version과 split identity는 corpus/split manifest checksum을 포함한 composite training dataset fingerprint에 결합되어 있다. checkpoint에 독립 필드로 중복 저장하지 않지만 구성 요소가 바뀌면 composite fingerprint가 달라져 resume가 차단된다.

## 8. 기존 artifact 보호와 최종 상태

- [확정] historical corpus, 운영 tokenizer, pilot-v1 manifest, 기존 `SMOKE-0001` summary/checkpoint, Gate 7 checkpoint를 수정하지 않았다.
- [확정] 새 run 외의 데이터 artifact를 생성·수정·이동·삭제하지 않았다.
- [확정] `RUNTIME_REVALIDATION_REQUIRED`는 해제됐고 readiness validator blocker는 0건이다.
- [확정] 최종 상태는 `ready_awaiting_final_execution_approval`이다. validator의 기계 상태 `ready_for_user_approval`은 실행 승인 자체를 뜻하지 않는다.
- [확정] 100-step Pilot과 Full Pretraining은 계속 `not_approved`다.
