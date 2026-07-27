# Pilot Pretraining 5-step 자원 Smoke 결과

## 상태

- [확정] `AIHUB-71748` Training의 `data_info[].contents`만 사용한 `pilot-v1`을 준비했다.
- [확정] 5 optimizer step 자원 Smoke는 통과했다.
- [확정] 5-step 자원 실행 자체는 통과했지만 source dataset은 superseded v1이며 pilot-v2 학습 evidence로 사용할 수 없다.
- [제외] 100-step Pilot 실행, Full Pretraining, Gate 변경, checkpoint 승격은 승인되지 않았다.

## Dataset 및 PII

| 항목 | 결과 |
|---|---:|
| 검사 record | 107,274 |
| 검사 문자 / byte | 199,290,927 / 459,496,763 |
| PII 후보 탐지·제외 record | 9,480 |
| 포함 train / internal evaluation record | 92,994 / 4,800 |
| 사람 검토 필요 잔여 record | 0 |
| exact duplicate 교차 split | 0 |
| source ID 교차 split | 0 |
| Dataset fingerprint | `sha256:1f585de3bc1c4a60de51577b37aaad7bf070240f8dfcc474b4de8eb458108191` |
| Split fingerprint | `sha256:3541c92da478486511a116bcc37340d855e45ef8d4c2bc641f366b9925b9075d` |
| PII 결과 fingerprint | `sha256:1670228dbd5fb010cdfe7697fd75c793ac49df4637eae41b7c44741b9e91578d` |

- [확정] 탐지 문자열은 문서·console·Git에 저장하지 않았다.
- [확정] 자동 탐지 record는 원본을 수정하지 않고 파생 corpus에서 전부 제외했다.
- [확정] AI Hub 원래 Validation과 evaluation·benchmark는 사용하지 않았다.

## Tokenization 및 Packing

| 항목 | Train | Internal evaluation |
|---|---:|---:|
| token | 71,524,523 | 3,668,546 |
| packed sequence | 279,393 | 14,331 |
| padding token | 85 | 190 |
| utilization | 99.6093% | 99.6042% |

- [확정] 운영 tokenizer `operating-16k-v2/unigram-16k`, vocabulary 16,000, special ID 0~7을 사용했다.
- [확정] UNK·범위 초과 ID·empty sequence·split 혼합은 모두 0건이다.
- [확정] context 256, continuous packing, final remainder padding 정책이다.

## 5-step 결과

| Step | Loss | Learning rate | Tokens/s | Step seconds |
|---:|---:|---:|---:|---:|
| 1 | 250.538052 | 0.000060 | 6,636.42 | 0.3086 |
| 2 | 250.845215 | 0.000120 | 10,520.61 | 0.1947 |
| 3 | 249.269058 | 0.000180 | 9,967.61 | 0.2055 |
| 4 | 237.461525 | 0.000240 | 9,572.97 | 0.2139 |
| 5 | 226.371078 | 0.000030 | 10,870.76 | 0.1884 |

| 자원·검증 | 결과 |
|---|---:|
| AMP skip / non-finite / OOM | 0 / 0 / 0 |
| 평균 tokens/s | 9,513.67 |
| 평균 optimizer step | 0.2222 s |
| Peak VRAM allocated / reserved | 524,190,208 / 593,494,016 bytes |
| Peak CPU working set | 1,018,101,760 bytes |
| 전체 실행 시간 | 5.9722 s |
| checkpoint-5 크기 / 저장 시간 | 202,788,185 bytes / 0.7082 s |
| JSONL log 크기 | 1,926 bytes |
| 실행 전 / 후 evaluation loss | 254.020098 / 194.970741 |

- [확정] evaluation은 시작 전과 종료 후 각각 고정 8 batch·16 sequence만 사용했다.
- [확정] checkpoint checksum·dataset/tokenizer/config fingerprint를 검사했다.
- [확정] 변경된 seed를 사용한 resume는 `CHECKPOINT_CONFIG_MISMATCH`로 차단됐다.
- [확정] Smoke checkpoint는 100-step Pilot에 승격·재사용하지 않는다.

## 승인 경계

- [확정] 48건은 byte quota 예외 후 archive 반복을 계속한 Pilot selector 버그의 `pilot_only` records로 전수 분류됐다.
- [확정] canonical pilot-v2는 기존 corpus 107,226건과 source SHA를 재현했다.
- [확정] `pilot-v1`과 checkpoint-5는 자원 Smoke evidence로만 보존하며 100-step 입력·checkpoint로 승격하지 않는다.
- [확정] 100-step 후보 config와 checkpoint 25/50/75/100, 최대 4개 보존 정책의 수치 승인은 유지하지만 dataset readiness는 차단한다.
- [제외] 최종 사용자 승인 전 `--execute`로 100-step Pilot을 시작하지 않는다.
