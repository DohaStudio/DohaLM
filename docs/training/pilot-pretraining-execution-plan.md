# AIHUB-71748 Pilot Pretraining 실행 준비 계획

- 문서 상태: `review`
- 마지막 검토일: 2026-07-27
- 선행 문서: [Pilot 준비 검증](./pilot-pretraining-readiness.md), [학생용 Pilot](./pilot-pretraining.md), [Gate 7 검증](./aihub-71748-gate7-tiny-overfit.md)
- 실행 manifest: [Pilot 실행 manifest](./pilot-pretraining-execution.manifest.yaml)
- 공개 설정: [Pilot example config](../../configs/pilot-pretraining.example.yaml)
- 구현 전 필수 여부: 실제 Pilot 실행 전 예

## 1. 목적과 범위

- [확정] 이 계획은 최대 100 optimizer step의 학생·비상업 로컬 Pilot을 안전하게 준비한다.
- [확정] 이번 단계는 설정·계보·저장·checkpoint·logging·중단 정책과 fail-closed CLI만 구성한다.
- [제외] Pilot 실행, corpus 생성·tokenization·packing, GPU 학습과 checkpoint·로그·sample 생성은 수행하지 않는다.
- [제외] 전체 Pretraining, SFT, RLHF, Preference Training, API, Frontend와 배포는 승인 범위 밖이다.

## 2. 현재 Blocker

| Code | 현재 상태 | 해소 조건 |
|---|---|---|
| `CORPUS_NOT_APPROVED` | 차단 | AIHUB-71748 Training의 Pilot Pretraining 목적별 승인 |
| `PII_NOT_CLEARED` | 차단 | 승인된 PII 검토 결과 `clear` 또는 조건부 승인 |
| `CORPUS_MANIFEST_MISSING` | 차단 | 승인 후 생성한 Pilot corpus manifest checksum |
| `SPLIT_NOT_VERIFIED` | 차단 | Training 내부 train/validation split version·seed·누수 검증 |
| `DATASET_FINGERPRINT_MISSING` | 차단 | 최종 tokenized/packed train·validation identity fingerprint |
| `STORAGE_NOT_VERIFIED` | 부분 확인 | 승인된 run 경로의 쓰기·atomic rename과 시작 직전 여유 공간 검사 |
| `CHECKPOINT_RETENTION_NOT_APPROVED` | 차단 | 25-step 주기·4개 전량 보존 정책 승인 |
| `TRAINING_CONFIG_NOT_APPROVED` | 차단 | example config의 resolved 값 사용자 승인 |
| `SCHEDULER_NOT_APPROVED` | 차단 | cosine·warmup 10·min LR ratio 0.1 승인 |
| `BATCH_POLICY_NOT_APPROVED` | 차단 | micro batch 2·accumulation 4 승인 |
| `ESTIMATE_NOT_VERIFIED` | 차단 | 5-step smoke 또는 별도 사용자 승인으로 시간·VRAM 범위 확인 |

- [확정] Gate 3~7, 운영 tokenizer, Tiny Overfit, CUDA FP16과 checkpoint/resume 기반 구현은 충족했다.
- [확정] `approved_tokenizer_development`는 Pilot corpus 승인이 아니며 readiness validator는 `approved_pilot_pretraining`만 인정한다.

## 3. Candidate 실행 설정

| 항목 | 후보값 | 상태 |
|---|---:|---|
| Model / context / vocab | DohaLM-Tiny / 256 / 16,000 | [확정] 기존 계약 |
| Optimizer | AdamW | [검증 필요] Pilot 승인 |
| Learning rate / weight decay | `3e-4` / `0.1` | [가정] Candidate B |
| Scheduler | cosine, min LR ratio `0.1` | [검증 필요] Pilot 승인 |
| Warmup | 10 optimizer step | [검증 필요] Pilot 승인 |
| Micro batch / accumulation / effective batch | 2 / 4 / 8 sequence | [가정] RTX 3060 Ti 후보 |
| Precision | FP16 AMP | [확정] 구현·Gate 7 검증 |
| Max step | 100 | [확정] Pilot 코드 상한 |
| Checkpoint / validation / log | 25 / 10 / 1 step | [검증 필요] Pilot 승인 |
| Seed | 17 | [검증 필요] Pilot 승인 |

- [확정] 설정 fingerprint는 `sha256:87a08a988158d2346ea3621214fd608da435cffa6c6cc91a2c6aad78e3c3ad2e`다.
- [확정] CLI override를 제거해 승인된 파일과 실제 resolved config가 달라지는 경로를 차단했다.

## 4. 실행 Manifest와 계보

| 항목 | 값 |
|---|---|
| Candidate source dataset fingerprint | `sha256:c0caeb05eb323c4237f43afbd1c10c295bbcd619512524974d4f5f61d325afbb` |
| Pilot dataset fingerprint | `null` — split·packing 승인 후 생성 |
| Tokenizer fingerprint | `sha256:9ce19a118a893fd69bad3124f94cea78f804d450a2ff6a9c4149b3064312f0ff` |
| Model fingerprint | `sha256:a7a4d109c6d9f385bc65f33a0c5b9a0e9af218764b2e0648ea0c81b317fed106` |
| Planning baseline Git commit / branch | `556f395092b5065874552a116db801d1b5999bdc` / `feat/pilot-pretraining` |
| Python / Torch / CUDA | 3.12.5 / 2.7.1+cu118 / 11.8 |
| GPU / VRAM / driver | NVIDIA GeForce RTX 3060 Ti / 8,589,410,304 bytes / 610.62 |

- [확정] 실제 실행 직전에는 현재 Git commit·branch·clean 상태와 환경을 새 resolved manifest에 다시 기록한다.
- [확정] config, model, dataset 또는 tokenizer fingerprint가 다르면 CLI와 resume는 fail-closed한다.

## 5. Pilot Ready Checklist

| 항목 | 상태 | 증거·조치 |
|---|---|---|
| Gate 3~7 | 완료 | 개발 로드맵 `passed` |
| 학생·비상업 라이선스 | 완료 | `approved_student_noncommercial` |
| Pilot 목적 dataset 승인 | 완료 | 제한 100-step 후보 목적 `approved_pilot_pretraining` |
| 운영 tokenizer | 완료 | operating-16k-v2 Unigram fingerprint 고정 |
| Tiny Overfit / FP16 / checkpoint / resume | 완료 | Gate 7 승인 보고서 |
| PII | 완료 | canonical 107,226 record 집계 검사, 후보 9,479건 파생 제외, 잔여 수동 검토 0 |
| Split·evaluation 제외 | 완료 | Training 내부 train 92,948 / evaluation 4,799, AI Hub Validation 미사용, 교차 ID 0 |
| Pilot dataset·manifest fingerprint | 완료 | `pilot-v2` dataset·split·PII·tokenization·packing fingerprint |
| Source selection 계보 | 완료 | quota control-flow 원인 48건 전수 분류, canonical pilot-v2 107,226건·source SHA 재현 |
| Config·scheduler·batch | 완료 | 100-step 후보 정책 확정, pilot-v2 전용 5-step Runtime Smoke 통과 |
| Disk capacity | 완료 | Smoke 종료 후 D: 가용 992,973,340,672 bytes 관측 |
| Output write·atomic rename | 완료 | small probe write·rename·read/checksum·delete 통과 |
| Log/output 위치·Git ignore | 설계 완료 | 외부 logical root 사용, Git 추적 금지 |
| Checkpoint retention | 완료 | 25/50/75/100 최대 4개, 자동 삭제 없음 |
| 실행 Git 상태 | 실행 직전 재검사 | 계획 시작 시 clean, 작업 후에는 의도된 diff 존재 |
| Pilot 실행 승인 | 미승인 | readiness 완료, 100-step manifest `not_approved` |

## 6. 디렉터리 구조

실제 경로는 `configs/local-datasets.yaml`의 external root에서 해석하며 공개 파일에는 절대경로를 기록하지 않는다.

```text
configured_external_root/
└── analysis/
    └── pilot-pretraining/
        └── AIHUB-71748/
            ├── plans/
            ├── prepared/
            │   ├── train.jsonl
            │   ├── validation.jsonl
            │   ├── corpus-manifest.json
            │   └── split-manifest.json
            └── runs/
                └── <run-id>/
                    ├── checkpoints/
                    ├── logs/
                    ├── metrics/
                    ├── samples/
                    └── reports/
```

- [확정] 이번 작업에서는 위 디렉터리와 파일을 생성하지 않았다.
- [확정] 원본 dataset, 운영 tokenizer와 Gate 7 run은 별도 read-only 계보로 참조한다.

## 7. Checkpoint 정책

- [검증 필요] step 25·50·75·100에 저장하고 최대 4개를 Pilot 종료 판정까지 전량 보존한다.
- [확정] 같은 step을 덮어쓰지 않고 atomic staging→rename을 사용한다.
- [확정] resume 전에 모든 파일 checksum, model/config/dataset/tokenizer fingerprint, optimizer·scheduler·scaler·RNG·sampler·global step을 검사한다.
- [확정] config, dataset, tokenizer 또는 accumulation 정책이 달라지면 새 run ID를 사용하고 기존 checkpoint resume를 차단한다.
- [확정] 저장 실패·용량 부족·checksum 불일치는 마지막 정상 checkpoint를 보존하고 즉시 중단한다.

## 8. Logging 정책

| 형식 | 정책 |
|---|---|
| JSONL | step별 authoritative training metric |
| Console | 상태·주기 요약과 오류 code만 출력 |
| CSV | 실행 후 JSONL에서 만드는 선택적 파생물; 원본 아님 |
| TensorBoard | 새 의존성을 추가하지 않아 이번 Pilot 후보에서는 비활성 |

- [확정] loss, LR, gradient norm, tokens/sec, step time, allocated/reserved VRAM, validation loss/perplexity와 checkpoint event를 기록한다.
- [확정] 원문, prompt·target text, 개인정보와 절대 로컬 경로는 metric/log에 기록하지 않는다.
- [가정] 100-step JSONL·요약·CSV는 10MiB 이하로 예상하지만 실제 크기는 종료 보고에서 측정한다.

## 9. 즉시 종료 조건

- NaN/Inf loss·gradient 또는 AMP 반복 skip
- CUDA OOM, 잘못된 device/dtype 또는 예상 범위를 벗어난 VRAM
- dataset/tokenizer/model/config fingerprint 불일치
- split·evaluation 제외·목적 승인 또는 PII 상태 불일치
- 입력 manifest/checksum 변경이나 손상
- 시작 전 5GiB 미만의 가용 공간, checkpoint 저장·atomic publish 실패
- resume state, RNG, sampler cursor 또는 global step 불일치
- 사용자의 중단 요청, 승인 범위 초과 또는 100 optimizer step 도달

## 10. 실행 규모 추정

| 항목 | 계획값 |
|---|---|
| 최대 optimizer step | 100 |
| Validation 횟수 | 초기 1회 + 10-step마다 10회 후보 |
| Checkpoint 수 | 최대 4개 |
| Checkpoint 예상 총량 | Gate 7의 약 202.79MB/개 기준 약 811MB + filesystem 여유 |
| 최소 시작 여유 공간 | 5GiB |
| 예상 로그 | [가정] 10MiB 이하 |
| 예상 VRAM | [가정] Gate 7 peak reserved 약 0.51GB보다 증가 가능; 8GB 이내 여부는 승인된 5-step smoke로 검증 |
| 예상 실행 시간 | [가정] 2~10분; validation·checkpoint I/O를 포함한 실제 smoke로 보정 |

- [확정] 5-step Smoke에서 평균 9,513.67 tokens/s, peak VRAM reserved 593,494,016 bytes를 실측했으며 이는 100-step 추정 보정용 자원 evidence다.

## 11. 성공·실패 기준

- [확정] 성공 후보는 100 step 정상 종료, finite loss·gradient, 계획된 validation·checkpoint, fingerprint·resume 검사, 자원·계보 기록 완료다.
- [확정] validation loss 개선이나 생성 품질을 임의의 필수 성공 조건으로 추가하지 않고 결과를 그대로 보고한다.
- [확정] 위 즉시 종료 조건, 필수 artifact 누락, 승인 위반 또는 실행 재현 정보 누락은 `failed`, `stopped` 또는 `invalid`로 기록한다.
- [확정] Pilot 성공은 전체 Pretraining 승인이나 모델 품질 보장이 아니다.

## 12. CLI와 실행 승인 경계

현재 허용되는 명령은 inspection-only 계획 검사다.

```powershell
python -m scripts.training.validate_pilot_readiness `
  --config configs/pilot-pretraining.example.yaml `
  --json

python -m scripts.training.run_pilot_pretraining `
  --config configs/pilot-pretraining.example.yaml `
  --manifest docs/training/pilot-pretraining-execution.manifest.yaml `
  --json
```

- [확정] 두 번째 명령은 기본적으로 plan만 출력하며 `training_started: false`다.
- [확정] `--execute`는 manifest approval, readiness, dataset/config/model/tokenizer identity, storage와 환경 필드가 모두 충족되지 않으면 `PILOT_EXECUTION_BLOCKED`로 종료한다.
- [제외] 100-step manifest는 계속 `not_approved`이므로 최종 사용자 승인 전 `--execute`를 사용하지 않는다.

## 13. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | [확정] pilot-v2 전용 5-step Runtime Smoke와 checkpoint load-only·mismatch 검증을 통과하고 readiness를 최종 100-step 실행 승인 대기로 갱신함 |
| 2026-07-27 | [확정] canonical selector로 pilot-v2를 생성하고 source·PII·split·tokenization·packing fingerprint를 재검증함; 기존 v1 Smoke는 승격하지 않고 runtime 재검증 승인을 대기함 |
| 2026-07-27 | [확정] `pilot-v1` dataset, PII 자동 제외, 95/5 split, 운영 tokenizer packing과 5-step 자원 Smoke를 검증해 기존 11개 readiness blocker를 해소함; 최종 100-step 실행 승인만 유지 |
| 2026-07-27 | [확정] Gate 7 이후 Pilot 실행 전 config·manifest·checklist·디렉터리·checkpoint·logging·중단·추정·CLI fail-closed 계획을 작성하고 실제 실행은 차단함 |
