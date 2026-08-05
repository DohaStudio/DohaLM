# DohaLM Base Training Readiness

- 문서 상태: `review`
- 마지막 검토일: 2026-08-05
- 기준 브랜치: `develop`
- 종합 판정: `blocked`
- 실행 권한: `false`
- 범위: Candidate C 실행 전 Foundation Base 본훈련 준비 상태 조사

## 1. 목적과 범위

이 문서는 Candidate A/B의 완료 근거, 현재 학습·평가·EOS 구현과 승인 정책을 하나의 Candidate C 진입 판단으로
통합합니다. 실제 학습, Tokenization, Dataset 변경, GPU 실행 또는 publication을 승인하지 않습니다.

상태는 다음 다섯 값만 사용합니다.

| 상태 | 의미 |
|---|---|
| `completed` | 기존 artifact와 검증 근거가 있으며 해당 범위가 끝남 |
| `planned` | 작업과 완료 조건은 정의됐지만 착수 전 |
| `blocked` | 선행 결정·승인·근거가 없어 다음 단계로 진행 불가 |
| `reviewing` | 기존 근거를 Candidate C 계약으로 채택할지 검토 중 |
| `not_started` | Candidate C 전용 작업이나 실행이 시작되지 않음 |

## 2. Base Training 전체 흐름

```text
Raw Dataset
  → Source·License·PII·Schema Validation
  → Dataset Selection·Split Freeze
  → Tokenizer Artifact Freeze
  → Tokenized Training/Evaluation Dataset Freeze
  → Model·Training Config Freeze
  → Immutable Run Identity·Environment Snapshot·Approval
  → CPU Preflight·GPU Smoke
  → Base Training
  → Quick 진단·Full Evaluation·EOS 진단
  → Candidate Evidence Package
  → Candidate Selection
  → Immutable Foundation Base
```

Quick는 개발 진단이며 Candidate 선택 근거를 대신하지 않습니다. Candidate 공식 판정에는 동일 identity의 Full
Evaluation과 별도 선택 결정이 필요합니다. 학습 완료, 평가 완료, Candidate 선택, Foundation Base 승격과 publication은
서로 다른 상태입니다.

## 3. 현재 Readiness 상태

| 영역 | 상태 | 현재 근거 | Candidate C에 남은 일 |
|---|---|---|---|
| DohaLM-Tiny 모델·Trainer | `completed` | 직접 구현, Gate 4~7, 실제 corpus overfit, A/B 학습 완료 | 현재 구현을 변경할 경우 별도 재검증 |
| Candidate A | `completed` | 10,000,384 scheduled token, Full Evaluation 완료 | historical baseline으로 보존 |
| Candidate B | `completed` | Run 0002 25,001,984 scheduled token, Full·EOS 평가 완료 | current Base baseline과 비교 기준으로 보존 |
| Dataset 기반 | `completed` | AIHUB-71748 canonical source, PII·split·packing fingerprint와 A/B 사용 근거 | Candidate C가 같은 identity를 채택할지 동결 |
| Candidate C Dataset Freeze | `reviewing` | 재사용 가능한 immutable pilot-v2 계보 존재 | dataset·split·packing checksum을 Candidate C 계약에 고정 |
| 운영 Tokenizer 기반 | `completed` | 16k v2 Unigram, special ID 0~7, Gate 3 통과 | artifact 변경 없음 확인 |
| Candidate C Tokenizer Freeze | `reviewing` | 승인 bundle과 fingerprint 존재 | Candidate C manifest에 exact model·vocab·fingerprint 고정 |
| Evaluation Framework | `completed` | Quick·Full·category·position·EOS·generation·stability·privacy·lineage 구현 | Candidate C용 판정 기준 승인 |
| EOS 현상 진단 | `completed` | A/B teacher-forced와 pure/assisted generation 비교 완료 | root cause 확정 필요 |
| EOS Root Cause | `blocked` | 원인 후보는 있으나 인과 검증 없음 | 학습 변경 전에 원인과 검증 가능한 가설을 승인 |
| Candidate C 목적·ADR 정합성 | `blocked` | 새 공식 우선순위는 Candidate C이나 ADR-009는 `candidate_c: not_required` | ADR-009를 개정·대체하는 승인 결정 필요 |
| Candidate C Training Config | `blocked` | A/B의 검증된 설정은 있으나 Candidate C 채택·budget 미확정 | resolved config와 fingerprint 동결 |
| Candidate C Evaluation Gate | `blocked` | 기존 정책과 B baseline은 있으나 Candidate C 전용 합격선 미승인 | 임의 threshold 없이 판정 계약 승인 |
| Run identity·환경 snapshot | `not_started` | A/B fail-closed 절차 재사용 가능 | immutable commit, 새 Run ID, 환경·저장소 snapshot 생성 |
| CPU preflight·GPU smoke | `not_started` | 과거 A/B evidence는 존재 | exact Candidate C config로 별도 수행·승인 |
| Candidate C 실행 승인 | `not_started` | 기존 single-use 승인은 모두 소비됨 | 새 Run 전용 single-use 승인 필요 |
| Candidate C 학습·평가·선택 | `not_started` | 실행되지 않음 | Gate C-1~C-5 통과 후 별도 순차 실행 |
| Publication | `blocked` | checkpoint·tokenizer·log·sample 공개는 `not_approved` | 학습 승인과 분리된 publication 승인 필요 |

현재 Base 기반 구현과 Candidate A/B 실험은 완료됐지만 Candidate C 실행 준비는 `blocked`입니다.

## 4. 현재 Blocker

1. **ADR 정합성** — 새 공식 우선순위는 Candidate C를 요구하지만 승인된 ADR-009는 Candidate B를 current Base로
   채택하면서 Candidate C를 `not_required`로 기록합니다. Candidate C 실행 전에 개정·대체 ADR이 필요합니다.
2. **EOS Root Cause** — 현상과 상관관계는 확인됐지만 원인이 확정되지 않았습니다. 원인 없이 설정만 변경하는 재학습은
   Candidate C 목적과 성공 판정을 설명할 수 없습니다.
3. **Evaluation Gate** — Full·EOS 평가 방법은 승인됐지만 Candidate C 전용 통과 기준은 없습니다. 새 수치를 임의로
   만들 수 없으므로 사용자 승인 또는 ADR로 동결해야 합니다.
4. **Training Config** — Candidate B 설정은 검증된 historical reference일 뿐 Candidate C 설정이 아닙니다. token budget,
   checkpoint schedule, initialization과 EOS 관련 변경 여부를 포함한 resolved config가 없습니다.
5. **Dataset·Tokenizer Freeze** — 기존 immutable artifact는 사용 가능하지만 Candidate C manifest에 exact identity를 다시
   결속하지 않았습니다. 재생성이나 새 Tokenization은 승인되지 않았습니다.
6. **Run·Approval·Physical Preflight** — 새 immutable Git identity, Run ID, 충돌 없는 output, disk·전원·냉각·GPU 점유,
   environment manifest와 single-use 승인이 없습니다.
7. **Publish** — 학습 실행 승인은 공개 승인이 아닙니다. model checkpoint, tokenizer, raw log, sample과 Dataset의 외부
   게시·재배포는 현재 승인되지 않았습니다.

여기서 environment/runtime snapshot은 Python·PyTorch·CUDA·driver·GPU·commit·resolved config를 기록하는 **학습 환경
snapshot**입니다. Phase 2 Qwen Runtime 작업을 뜻하지 않습니다.

## 5. Candidate C 시작 최소 완료 조건

Candidate C 학습은 다음 조건을 모두 충족하기 전 시작할 수 없습니다.

- EOS 현상의 root cause 또는 검증 가능한 단일 가설과 변경 범위를 승인한다.
- ADR-009의 `candidate_c: not_required`와 새 공식 우선순위 충돌을 후속 ADR로 해소한다.
- Dataset source·license·PII·split·tokenization·packing identity와 checksum을 freeze한다.
- 운영 v2 Unigram tokenizer의 model·vocab checksum, fingerprint와 special ID 0~7을 freeze한다.
- architecture, initialization, token budget, optimizer, scheduler, LR, batch, accumulation, context, checkpoint,
  seed, evaluation, resume, output과 중단 정책을 단일 resolved config로 freeze한다.
- Candidate B Full 결과를 비교 기준으로 하는 Candidate C Evaluation Gate를 승인한다.
- immutable commit, 새 Run ID, 신규 output 경로, 환경 snapshot과 artifact 저장 용량을 확정한다.
- exact Candidate C config의 CPU preflight와 단일 RTX 3060 Ti 8GB GPU smoke를 통과한다.
- 해당 Run에만 유효하고 재사용·자동 연장·자동 retry가 불가능한 single-use 실행 승인을 발급한다.

## 6. Candidate C Gate

| Gate | 목적 | 통과 조건 | 현재 상태 |
|---|---|---|---|
| C-1 Training Readiness | 범위·ADR·EOS·평가·승인 경계 통합 | 이 문서의 blocker가 모두 해소되고 근거 fingerprint가 고정됨 | `blocked` |
| C-2 Dataset Freeze | 학습·평가 데이터 계보 고정 | source/license/PII/split/tokenization/packing manifest와 checksum 승인 | `reviewing` |
| C-3 Tokenizer Freeze | 모델 입력 identity 고정 | v2 Unigram model·vocab·fingerprint·special ID 일치 승인 | `reviewing` |
| C-4 Training Config Freeze | 실행 의미 고정 | resolved config, budget, checkpoint, stop·resume 정책과 fingerprint 승인 | `blocked` |
| C-5 GPU Smoke | exact config 자원·수치 안정성 확인 | 단일 RTX 3060 Ti 8GB에서 finite forward/backward/optimizer, VRAM·처리량 기록 | `not_started` |
| C-6 Training | 단일 승인 Base 재학습 | C-1~C-5, immutable Run identity와 single-use 승인 후 정상 종료 | `not_started` |
| C-7 Evaluation | Candidate C 공식 평가 | 동일 identity Full Evaluation, EOS·generation·stability·privacy·lineage 완료 | `not_started` |
| C-8 Candidate Selection | Foundation Base 결정 | 승인 계약으로 B/C를 비교하고 별도 사용자 선택·승격 결정 기록 | `not_started` |

기존 Gate 0~7의 통과 상태는 구현 기반 evidence로 유지되지만 Candidate C 전용 C-1~C-8을 자동 통과시키지 않습니다.

## 7. Training Config 점검

`확정`은 현재 코드·A/B 승인 계약에서 확인되는 값, `미확정`은 Candidate C 채택 결정이 없는 값, `위험`은 실행 전에
명시적으로 관리해야 하는 조건입니다.

| 항목 | 현재 근거 | Candidate C 판정 | 위험 |
|---|---|---|---|
| Optimizer | AdamW, bias·LayerNorm decay 제외 | `미확정` | 변경 시 B와 비교 가능성·resume fingerprint 변경 |
| Scheduler | cosine, min LR ratio 0.1 | `미확정` | budget 변경 시 decay 의미 변경 |
| Learning Rate | A/B `3e-4` | `미확정` | EOS 개선과 전체 loss 회귀를 분리 판정해야 함 |
| Weight Decay | A/B `0.1` | `미확정` | optimizer group 계약과 함께 고정 필요 |
| Batch | micro 2, accumulation 4, effective 8 | `미확정` | 8GB VRAM과 gradient 의미 변경 |
| Accumulation | 4, step당 2,048 token | `미확정` | resume 호환성과 scheduler step 의미 변경 |
| Sequence | DohaLM-Tiny context 256 | `확정` | 구조 변경은 별도 ADR·재검증 대상 |
| Precision | CUDA FP16 autocast·GradScaler | `확정` | AMP skip·NaN/Inf·dtype·VRAM 실측 필요 |
| Gradient Clip | max norm 1.0 | `미확정` | EOS 변경과 무관한 안정성 회귀 가능 |
| Token Budget / Steps | A 10M/4,883, B 25M/12,208 | `미확정` | 임의 연장 금지, step은 budget/2,048과 일치해야 함 |
| Checkpoint | atomic, checksum, no overwrite | `확정` | Candidate C step schedule·retention 수는 미확정 |
| Seed / Initialization | A/B fresh seed 17, cross-candidate resume 금지 | `미확정` | parent/재초기화 선택은 비교 해석을 바꿈 |
| Evaluation | 공식 판정은 Full, Quick는 진단 | `확정` | Candidate C 합격 기준은 미확정 |
| Resume | same-run·checksum-valid·별도 승인, 자동 resume/retry 금지 | `확정` | Candidate C가 resume 허용 여부를 config에 명시해야 함 |
| Output | Git 밖 external path, no-replace, 사전 용량 probe | `확정` | 새 Run ID·경로·용량은 미확정 |
| Logging / Stop | loss·LR·gradient·AMP·resource 기록, non-finite/OOM 중단 | `확정` | Candidate C spike·wall-clock 수치는 미확정 |

따라서 A/B 설정 전체를 Candidate C의 `확정` 설정으로 복사해서는 안 됩니다. 기존 값은 검증된 비교 출발점이며,
Candidate C resolved config 승인으로만 실행 설정이 됩니다.

## 8. EOS Root Cause 분석

### 확정

- Candidate A와 B는 pure greedy 16/32/64/128-token 진단에서 EOS 종료율 0%, maximum-length 종료율 100%였습니다.
- Candidate B는 Candidate A보다 teacher-forced EOS loss·rank·Top-k가 개선됐지만 greedy EOS 선택으로 이어지지 않았습니다.
- EOS target은 Dataset에 존재하고 loss에 포함되며, 확인된 label mismatch나 packing boundary 손상은 없습니다.
- 128-token에서 Candidate B의 adjacent repetition은 A보다 낮았지만 32-token 이상 loop 발생률은 둘 다 100%였습니다.
- Candidate B는 no-repeat bigram 같은 decoding assistance에서만 일부 EOS 종료가 관찰돼
  `decoding_assisted_termination_only`로 설명할 수 있습니다.
- 승인된 ADR-008에 따라 Base의 greedy EOS는 필수 진단이지만 단독 자동 탈락 기준은 아닙니다. 심각한 반복·무한 loop·일반
  성능 붕괴는 별도 blocker입니다.

### 추정

- 반복 token 경쟁이 EOS logit을 밀어내거나, teacher-forced 조건과 autoregressive 생성 조건의 차이가 누적될 가능성이 있습니다.
- token budget, 문서 packing, boundary 빈도, 학습 objective 또는 logit calibration이 현상에 기여할 가능성이 있습니다.
- decoding assistance에서 EOS가 나타나는 점은 EOS 표현 자체의 완전한 부재보다는 선택 경쟁 문제일 가능성을 높입니다.

### 미확인

- 위 후보 중 어느 하나가 주된 root cause인지 인과적으로 확인되지 않았습니다.
- Dataset 재구성, EOS 가중치, packing 변경, curriculum, learning-rate 또는 decoding 변경 중 무엇이 필요한지 결정되지 않았습니다.
- Candidate C가 B보다 높은 greedy EOS 종료율을 달성할지, 그 변화가 Full loss·Top-k·반복률에 어떤 영향을 줄지 미확인입니다.

이 문서는 원인 후보만 정리하며 EOS 수정안을 선택하거나 구현하지 않습니다.

## 9. Candidate C Evaluation 기준

새로운 수치 threshold를 만들지 않고 현재 승인 문서와 코드의 조건만 적용합니다.

- Candidate B Final Full을 current Base 비교 기준으로 사용하고 Candidate A는 historical reference로 유지합니다.
- Candidate 공식 판단은 Full profile로 수행합니다. Quick는 동일 artifact의 회귀·대표성 진단이며 선택 결정을 할 수 없습니다.
- B/C 비교는 동일 evaluation Dataset·split·Tokenizer·model architecture·context·packing·masking identity에서 수행합니다.
- 전체 loss·perplexity와 next-token Top-1/5/10을 보고합니다.
- language/token category, position, teacher-forced EOS loss·rank·Top-k와 packing boundary 진단을 보고합니다.
- pure greedy EOS·maximum-length·generation length·repetition·degenerate loop와 decoding-assisted 결과를 분리합니다.
- FP16 반복·FP32 비교 등 stability, resource 사용량, privacy, source lineage, checkpoint checksum과 평가 전후 불변성을 확인합니다.
- 임의 종합 점수를 만들지 않고 지표별 필수 조건과 참고 지표를 구분합니다.
- ADR-008에 따라 Base greedy EOS 0%만으로 자동 탈락시키지 않으며, 심각한 반복·무한 loop·일반 성능 붕괴를 별도로 판정합니다.
- Candidate C의 수치 합격선·허용 회귀 폭은 현재 미승인입니다. C-4 이전에 사용자 승인 또는 ADR로 동결해야 합니다.

ADR-007의 Quick 대표성 오차 기준은 Quick가 Full을 얼마나 대표하는지 판단하는 기준이지 Candidate C 성능 합격선이
아닙니다. historical Candidate B 계약의 수치도 새 승인 없이 Candidate C에 소급하지 않습니다.

## 10. Readiness 결론과 다음 Task

현재 Foundation Base 구현, Candidate A/B, 운영 Tokenizer와 Evaluation Framework는 재사용 가능한 완료 기반입니다. 그러나
Candidate C는 ADR 충돌, EOS root cause, Dataset·Tokenizer·Training Config freeze, Evaluation Gate, 새 Run identity·GPU smoke와
single-use 승인 미완료로 `blocked`입니다.

다음 Task는 **Candidate C 학습이 아니라 Candidate C 설계·ADR 정합성 및 Config/Evaluation 계약 동결**입니다. C-1~C-4가
통과하기 전 C-5 GPU Smoke나 C-6 Training으로 넘어가지 않습니다.

## 11. 기준 문서와 구현

- 전략·상태: [README](../../README.md), [Foundation Strategy](../project/foundation-model-strategy.md),
  [Current Status](../project/current-project-status.md), [Roadmap](../project/model-family-roadmap.md)
- Candidate 근거: [Candidate A 결과](./full-pretraining-candidate-a-result.md), [Candidate B 설계](./candidate-b-design.md),
  [Candidate B 결과](./candidate-b-execution-result.md), [A/B Full 비교](../evaluation/candidate-a-b-full-comparison.md)
- 평가·EOS: [Evaluation Framework](../evaluation/README.md), [EOS Success Policy](../evaluation/eos-success-policy.md),
  [EOS 진단 결과](../evaluation/eos-generation-decoding-diagnostic-result.md), [ADR-008](../decisions/ADR-008-eos-generation-and-decoding-evaluation-policy.md)
- 결정·Gate: [ADR-005](../decisions/ADR-005-evaluation-and-experiment-policy.md),
  [ADR-006](../decisions/ADR-006-development-quality-gates.md), [ADR-009](../decisions/ADR-009-candidate-b-official-reassessment.md)
- 학습·artifact: [Checkpoint와 Resume](./checkpoint-and-resume.md), [Candidate B config](../../configs/candidate-b.example.yaml),
  [Publication 경계](./full-pretraining-publication-boundary.md)

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | Candidate C 진입을 위한 Base Training 흐름·상태·blocker·C-1~C-8 Gate·config·EOS·평가 기준을 통합하고 실행 금지 경계를 기록 |
