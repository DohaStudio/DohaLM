# Candidate B 25M Full Pretraining 설계

- 문서 상태: `review`
- 마지막 검토일: 2026-07-28
- 학습 승인: `not_approved`
- 실행 허용: `false`
- 관련 문서: [ADR-007](../decisions/ADR-007-evaluation-baseline-and-candidate-comparison.md), [Candidate A 결과](./full-pretraining-candidate-a-result.md), [Candidate A Final Full](../evaluation/candidate-a-final-full-result.md), [Candidate B 평가 계약](../evaluation/candidate-b-evaluation-contract.md), [Readiness](./candidate-b-readiness.md)
- 공개용 config: [Candidate B example](../../configs/candidate-b.example.yaml)
- 설계 manifest: [Candidate B readiness manifest](./candidate-b-readiness.manifest.yaml)

## 1. 목적과 범위

- [확정] Candidate A Final Full을 공식 internal baseline으로 사용한다.
- [확정] Candidate B는 기존 [사전학습 계획](./pretraining-plan.md)의 `B 25M` 후보를 구체화한다.
- [확정] 이번 마일스톤은 설계·readiness package만 작성하며 optimizer, backward, GPU 학습과 checkpoint 생성은 수행하지 않는다.
- [확정] Candidate B training, Resume와 재실행은 별도 사용자 승인 전까지 `not_approved`다.
- [제외] Dataset·split·tokenizer·model·context·packing·masking·EOS 삽입·loss weighting·decoding을 변경하지 않는다.
- [제외] Candidate A checkpoint 승격, Candidate C, SFT, RLHF, Preference Training, API, Frontend와 배포를 포함하지 않는다.

## 2. 공식 baseline

| 항목 | Candidate A Final Full |
|---|---:|
| Run / checkpoint | `FULL-PRETRAIN-CANDIDATE-A-20260727-0001` / step `4,883` |
| Scheduled token / equivalent epoch | `10,000,384` / `0.14024222267534303` |
| Checkpoint checksum | `sha256:80f2aee72605ffcfeea13e158cbf7a132682591cf4295cd01c16f514686338f8` |
| Evaluation ID | `candidate-a-final-full-20260727-01` |
| Evaluation result | `sha256:1ec526e2dc6b1792f2d071fc788cd384ad3a22a0c2750df7437158153ca2d78d` |
| Loss / PPL | `6.369027` / `583.4899` |
| Top-1 / Top-5 / Top-10 | `16.8417%` / `29.2154%` / `35.5767%` |
| EOS Top-1 / Top-5 / Top-10 | `12.2334%` / `86.3028%` / `89.4814%` |
| EOS mean loss / median rank / p90 rank | `3.165948` / `3` / `12` |
| Greedy EOS / maximum-length | `0%` / `100%` |

Baseline identity는 dataset `sha256:0265e2d4...f8790`, split `sha256:dd71433c...f4696f`, tokenizer `sha256:9ce19a11...12f0ff`로 고정한다. 전체 값은 설계 manifest에 기록한다.

## 3. 학습 목표와 단일 비교 변수

- [검증 필요] Candidate B의 승인 제안 목표는 동일 초기화·설정에서 token budget을 10M에서 25M으로 늘렸을 때 일반 next-token 지표를 유지하면서 EOS 종료 능력이 개선되는지 검증하는 것이다.
- [확정] 비교 변수는 token budget 하나다. Candidate B도 DohaLM-Tiny를 seed 17로 새로 초기화하며 Candidate A model·optimizer·scheduler·AMP·RNG·sampler state를 사용하지 않는다.
- [확정] 추가 EOS token 삽입, EOS up-weighting과 packing 변경 없이 기존 Training corpus 노출 증가만 검증한다.
- [확정] 개선이 실패해도 설정을 자동 변경하거나 Candidate C로 전환하지 않는다.

## 4. Token·step budget

| 항목 | 값 |
|---|---:|
| 요청 token | `25,000,000` |
| Context / effective batch | `256` / `8` |
| Step당 scheduled token | `2,048` |
| Optimizer step | `ceil(25,000,000 / 2,048) = 12,208` |
| Scheduled token | `25,001,984` |
| Packed sequence | `97,664` |
| Train token 대비 equivalent epoch | `0.35061991694052586` |
| 마지막 batch 최대 overshoot | `2,047` token capacity |

어느 상한이든 먼저 도달하면 종료한다. 자동 연장과 예산 override는 허용하지 않는다.

## 5. Training config

Candidate A와 동일하게 AdamW, learning rate `3e-4`, weight decay `0.1`, cosine scheduler, warmup 10, min LR ratio `0.1`, micro batch 2, gradient accumulation 4, FP16 AMP, gradient clipping `1.0`, context 256과 seed 17을 사용한다. 공개용 example checksum은 manifest에 고정하며 실제 실행 전 run ID와 외부 output을 확정한 resolved config를 별도로 fingerprint해야 한다.

## 6. EOS 개선과 품질 성공 조건

[확정] 공식 판정은 승인된 [Candidate B 평가 계약](../evaluation/candidate-b-evaluation-contract.md)을 그대로 적용한다.

- EOS Top-1/5/10은 `12.2334% / 86.3028% / 89.4814%`보다 낮아지지 않는다.
- EOS mean loss `3.165948`, median rank `3`, p90 rank `12`보다 악화되지 않는다.
- Greedy EOS rate는 `0%`보다 높고 maximum-length rate는 `100%`보다 낮아야 한다.
- Full loss/PPL, Top-1/5/10, Korean·English·number·symbol·byte fallback, position gap을 모두 보고한다.
- 반복률 `45.3333%`, loop `80%`, special-token exposure `0%`와 일반 Top-k의 심각한 회귀가 있으면 EOS만 개선돼도 통과하지 않는다.
- 임의 종합 점수는 사용하지 않는다.

[검증 필요] “심각한 회귀”의 추가 수치 임계값은 승인된 평가 계약에 정의돼 있지 않다. Candidate B 실행 승인 전 별도 임계값을 승인하거나 지표별 사용자 판정을 유지해야 한다.

## 7. Quick·Full 평가 계약

- [확정] Quick은 `start`, step `4,883`, `final`에서 개발 회귀 확인용으로 사용한다.
- [확정] step 4,883 Quick은 Candidate A와 동일 scheduled token 지점의 재현성 확인이다.
- [확정] Full은 final step 12,208에서 한 번 실행하고 이것만 공식 Candidate 판정에 사용한다.
- [확정] Quick의 낙관 편향을 명시하며 Quick만으로 성공·Gate·release 판정을 하지 않는다.
- [확정] 동일 internal evaluation 4,799 record·14,329 packed sequence·3,653,719 target token을 사용한다. AI Hub 원래 Validation과 외부 benchmark는 사용하지 않는다.
- [확정] 평가 산출물에는 원문과 전체 token ID를 저장하지 않는다.

## 8. 초기화·Checkpoint·Resume

### 초기화

Candidate B는 seed 17 fresh initialization이다. Candidate A checkpoint는 baseline evidence로만 읽으며 parent 또는 warm-start artifact로 사용하지 않는다. 이로써 10M 대 25M 비교에서 token budget 이외의 state 계보 차이를 제거한다.

### Checkpoint

| 구분 | Step | Scheduled token | 목적 |
|---|---:|---:|---|
| A-equivalent | `4,883` | `10,000,384` | Candidate A 동일 token 지점 점검 |
| Late | `9,766` | `20,000,768` | 후반 추세와 안전한 복구점 |
| Final | `12,208` | `25,001,984` | 공식 Candidate B artifact |

세 bundle만 최대 3개 보존한다. Atomic publish, 파일별 SHA-256, checksum inventory와 저장 직후 load 검증이 필수다. 실행 중 자동 삭제와 종료 후 무승인 삭제는 금지한다.

### Resume

Resume는 같은 Candidate B Run ID의 checksum-valid checkpoint에서만 가능하며 별도 사용자 승인이 필요하다. Dataset·lineage·PII·split·tokenization·packing·tokenizer·model·initialization·resolved config·budget과 optimizer·scheduler·AMP·RNG·sampler 상태가 모두 일치해야 한다. 자동 resume/retry, Candidate A 또는 다른 run checkpoint 사용과 config 변경 resume는 차단한다.

## 9. GPU·시간·Disk 예산

| 항목 | 설계값 | 근거 |
|---|---:|---|
| 예상 wall-clock | `3,276초` | Candidate A 1,310.184초를 scheduled token 비율로 보수적 선형 외삽 |
| Planned / hard stop | `3,600초` / `5,400초` | 외삽 오차·checkpoint·평가 여유 |
| 예상 output | 약 `0.65GiB` | 약 202.79MB checkpoint 3개와 log·manifest 여유 |
| Output hard limit | `2GiB` | Candidate A와 동일 안전 상한 |
| 시작 / 실행 중 free disk | `10GiB` / `5GiB` 이상 | atomic staging과 실패 artifact 보존 |
| Reserved VRAM / CPU hard limit | `7GiB` / `4GiB` | RTX 3060 Ti 8GB 기준 기존 승인 상한 |
| 예상 checkpoint | `3개` | 10M·20M·25M |

- [가정] 시간과 output은 Candidate A 실측 기반 추정이며 Candidate B runtime 측정값이 아니다.
- [확정] 실행 직전 output write/atomic/checksum probe, free disk, 전원·냉각·환기·절전·GPU 점유를 다시 확인한다.

## 10. 실행 Manifest와 승인 소비

- [확정] 실행 backend와 CPU fail-closed 검증은 구현됐지만 manifest의 `execution_allowed`는 `false`다. Immutable commit·물리 preflight·실행 승인이 별도로 필요하다.
- [확정] 실행 승인은 Candidate B 25M·immutable Git commit·resolved config·manifest fingerprint·output Run ID를 묶는 single-use 승인으로만 소비한다.
- [확정] 승인 소비는 첫 optimizer step 성공 경계에서 외부 run 디렉터리에 atomic record로 남긴다.
- [확정] 소비 후 자동 복원하지 않는다. step 1 이후 실패, retry, Resume와 새 Run ID는 각각 별도 승인이 필요하다.
- [확정] 승인 전에 inspect/readiness만 허용하며 `--execute`, optimizer와 backward는 금지한다.

## 11. 중단 조건

NaN/Inf, OOM, fingerprint·identity 불일치, 미승인 execution, disk·wall-clock·VRAM·CPU 상한 위반, checksum·atomic publish·log·evaluation 실패는 즉시 중단한다. AMP skip 3회 연속 또는 100-step rolling 정상값 대비 loss/gradient norm 4배가 10 step 연속이면 중단한다. 자동 설정 변경과 자동 retry는 금지한다.

## 12. 승인 경계

이 문서는 Candidate B 실행 승인이 아니다. 실행 전에는 최소한 training config·budget·checkpoint·resume·resource policy, immutable commit, resolved config fingerprint, output probe·physical preflight와 single-use execution approval이 별도로 확정돼야 한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | Candidate A Full baseline 기반 Candidate B 25M 목표·EOS·평가·초기화·checkpoint·resume·자원·승인 소비 설계 작성 |
| 2026-07-28 | Candidate B backend·CPU validation·output probe 구현 후 실행 차단 경계 갱신 |
