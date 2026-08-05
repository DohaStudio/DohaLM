# DohaLM Base Training Readiness

- 문서 상태: `review`
- 마지막 검토일: 2026-08-05
- 기준 브랜치: `develop`
- 선행 문서: [Current Project Status](../project/current-project-status.md)
- 후속 문서: [Candidate C Design](./candidate-c-design.md)
- Readiness review: `completed`
- Candidate C readiness: `blocked`
- 실행 권한: `false`
- Candidate C training started: `false`
- 범위: Candidate C 실행 전 Foundation Base 본훈련 준비 상태 조사
- Candidate C 계약 설계: `completed`
- Candidate B EOS 진단 계약: `design_completed`
- Candidate B EOS 진단 실행 허용: `false`
- Candidate B checkpoint mutation 허용: `false`
- Candidate C 주가설: `not_selected`

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

## 2. 완료된 근거 조사와 향후 실행 흐름

두 흐름은 상태와 목적이 다르므로 하나의 pipeline으로 합치지 않습니다.

### 2.1 현재 근거 조사 — `completed`

```text
Candidate A/B Evidence
  → Candidate B EOS Diagnostic Review
  → Dataset·Tokenizer·Config Review
  → Candidate C Readiness Decision
```

이 흐름은 기존 artifact를 읽고 Candidate C 진입 가능성을 판정하는 review입니다. Candidate A/B 학습과 Evaluation을
재실행하거나 Candidate C artifact를 생성하지 않습니다. Review의 결론은 `candidate_c_readiness: blocked`입니다.

### 2.2 향후 Candidate C 실행 — `blocked` / `not_started`

```text
Dataset Freeze
  → Tokenizer Freeze
  → Training Config Freeze
  → GPU Smoke
  → Training
  → Evaluation
  → Candidate Selection
```

Run identity·환경 snapshot·single-use Approval은 C-4 이후 C-5/C-6 진입 조건입니다. Quick는 개발 진단이며 Candidate
선택 근거를 대신하지 않습니다. Candidate 공식 판정에는 동일 identity의 Full Evaluation과 별도 선택 결정이 필요합니다.
학습 완료, 평가 완료, Candidate 선택, Foundation Base 승격과 publication은 서로 다른 상태입니다.

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
| Candidate B EOS 진단 계약 | `completed` | [read-only 진단 계약](../evaluation/candidate-b-eos-diagnostic-contract.md)의 identity·D1~D8·artifact·Gate·Approval 설계 완료 | 구현·freeze·승인 후 실행; 현재 GPU·Full `not_started` |
| EOS 단일 Root Cause | `blocked` | [H1~H7 가설 계약](./candidate-c-eos-hypotheses.md)은 작성됐지만 어느 가설도 확정되지 않음 | Candidate B read-only 진단과 주가설 승인 |
| Candidate C 목적·ADR 정합성 | `reviewing` | [ADR-011](../decisions/ADR-011-candidate-c-experimental-successor.md) draft 작성 | 사용자 승인 전 ADR-009 효력 유지 |
| Candidate C Training Config | `blocked` | A/B의 검증된 설정은 있으나 Candidate C 채택·budget 미확정 | resolved config와 fingerprint 동결 |
| Candidate C Evaluation Gate | `reviewing` | [지표 분류·Selection 계약](./candidate-c-evaluation-contract.md) 작성 | 회귀 폭·EOS 승격 판정 승인 |
| Run identity·환경 snapshot | `not_started` | A/B fail-closed 절차 재사용 가능 | immutable commit, 새 Run ID, 환경·저장소 snapshot 생성 |
| CPU preflight·GPU smoke | `not_started` | 과거 A/B evidence는 존재 | exact Candidate C config로 별도 수행·승인 |
| Candidate C 실행 승인 | `not_started` | 기존 single-use 승인은 모두 소비됨 | 새 Run 전용 single-use 승인 필요 |
| Candidate C 학습·평가·선택 | `not_started` | 실행되지 않음 | Gate C-1~C-5 통과 후 별도 순차 실행 |
| Publication | `blocked` | checkpoint·tokenizer·log·sample 공개는 `not_approved` | 학습 승인과 분리된 publication 승인 필요 |

현재 Base 기반 구현, Candidate A/B evidence 조사와 readiness review는 완료됐지만 Candidate C execution readiness는
`blocked`입니다. 계약 설계 완료는 실행 준비 완료가 아닙니다.

## 4. 현재 Blocker

ID 기반 상세 registry는 [Candidate C 설계](./candidate-c-design.md#8-blocker-registry)를 기준으로 합니다.

1. `C-BLOCK-001` ADR conflict — ADR-011은 draft이며 사용자 승인 전 ADR-009의 `not_required`가 유효합니다.
2. `C-BLOCK-002` EOS root cause — H1~H7은 가설이며 Candidate B read-only 진단의
   [EOS-DIAG-BLOCK-001~010](../evaluation/candidate-b-eos-diagnostic-contract.md#13-blocker-registry) 해소, 실행 완료와
   [주가설 승인](../evaluation/candidate-c-hypothesis-selection-policy.md)이 필요합니다.
3. `C-BLOCK-003` Dataset freeze — 선택지 A를 권장했지만 Candidate C immutable manifest·source commit이 없습니다.
4. `C-BLOCK-004` Tokenizer freeze — v2 Unigram 유지가 권장되지만 Candidate C compatibility freeze가 없습니다.
5. `C-BLOCK-005` Training config — budget·initialization·intervention·checkpoint schedule 등 미결정값이 남았습니다.
6. `C-BLOCK-006` Evaluation Gate — 지표 역할은 분류했지만 회귀 폭·EOS 승격 판정이 미승인입니다.
7. `C-BLOCK-007` Run identity — immutable commit·Run ID·output·환경 snapshot이 없습니다.
8. `C-BLOCK-008` Approval — Run 전용 single-use 실행 승인이 없습니다.

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
| C-1 Training Readiness | 범위·ADR·EOS·평가·승인 경계 통합 | ADR-011 검토, Candidate B read-only 진단 완료·주가설 승인과 blocker resolution plan 확정; Candidate C 실행 권한은 false 가능 | `review` |
| C-2 Dataset Freeze | 학습·평가 데이터 계보 고정 | source/license/PII/split/tokenization/packing manifest와 checksum 승인 | `reviewing` |
| C-3 Tokenizer Freeze | 모델 입력 identity 고정 | v2 Unigram model·vocab·fingerprint·special ID 일치 승인 | `reviewing` |
| C-4 Training Config Freeze | 실행 의미 고정 | resolved config, budget, checkpoint, stop·resume 정책과 fingerprint 승인 | `blocked` |
| C-5 GPU Smoke | exact config 자원·수치 안정성 확인 | 단일 RTX 3060 Ti 8GB에서 finite forward/backward/optimizer, VRAM·처리량 기록 | `not_started` |
| C-6 Training | 단일 승인 Base 재학습 | C-1~C-5, immutable Run identity와 single-use 승인 후 정상 종료 | `not_started` |
| C-7 Evaluation | Candidate C 공식 평가 | 동일 identity Full Evaluation, EOS·generation·stability·privacy·lineage 완료 | `not_started` |
| C-8 Candidate Selection | Foundation Base 결정 | 승인 계약으로 B/C를 비교하고 별도 사용자 선택·승격 결정 기록 | `not_started` |

### 6.1 기존 Gate 1~7과 Candidate C Gate 관계

기존 Gate 1~7은 저장소 Foundation capability와 historical Tiny 검증입니다. Candidate C C-1~C-8은 특정 Candidate C
identity·config·실행·평가·선택에 적용되는 후속 Gate이며 기존 통과 상태를 상속하지 않습니다.

| 기존 Gate evidence | Candidate C에서 재사용하는 근거 | Candidate C 재확인 Gate |
|---|---|---|
| Gate 1 환경 | 단일 RTX 3060 Ti·개발 환경 기준 | C-4 환경 계약, C-5 exact GPU Smoke |
| Gate 2 데이터 pipeline | validation·lineage·PII·split 기능 | C-2 exact Dataset Freeze |
| Gate 3 운영 Tokenizer | v2 Unigram·16k·special ID 검증 | C-3 exact artifact Freeze |
| Gate 4~5 모델 component·통합 | DohaLM-Tiny architecture·forward/loss | C-4 model config 고정, 변경 시 재검토 |
| Gate 6 Trainer·checkpoint/resume | AMP·accumulation·atomic checkpoint 기반 | C-4 Run 정책, C-5 exact config Smoke |
| Gate 7 실제 corpus overfit | training path의 제한 검증 evidence | C-1 참고 근거만 제공; C-6 학습 승인 아님 |

C-1~C-4는 계약·identity freeze, C-5는 GPU Smoke, C-6은 Training, C-7은 Evaluation, C-8은 Candidate
Selection입니다. 기존 Gate 1~7이나 C-1~C-5 통과는 C-6 실행 승인을 자동 부여하지 않습니다.

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

EOS **현상 확인과 기존 진단 검토는 `completed`**입니다. 아래 확정 사실은 현상을 기술할 뿐 하나의 원인을 확정하지
않습니다. **단일 root cause는 `not_confirmed`**이며 H1~H7은 반증 가능한 후보입니다.

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

Candidate C는 기존 [Evaluation Framework](../evaluation/README.md)의 runner·Quick/Full profile·동일 evaluation Dataset·
metric 산출·artifact 불변성·privacy·lineage 검사를 그대로 재사용합니다. [Candidate C Evaluation 계약](./candidate-c-evaluation-contract.md)은
Framework를 복제하거나 변경하지 않고, Candidate B Final Full을 비교 기준으로 지표 역할과 Selection 판정만 추가합니다.

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

현재 Foundation Base 구현, Candidate A/B evidence review, 운영 Tokenizer와 Evaluation Framework는 재사용 가능한 완료
기반이며 `base_training_readiness_review: completed`입니다. 그러나
Candidate C는 ADR 충돌, EOS root cause, Dataset·Tokenizer·Training Config freeze, Evaluation Gate, 새 Run identity·GPU smoke와
single-use 승인 미완료로 `blocked`입니다.

```text
base_training_readiness_review: completed
candidate_c_contract_design: completed
candidate_b_eos_diagnostic_contract: design_completed
candidate_b_eos_diagnostic_execution_allowed: false
candidate_b_checkpoint_mutation_allowed: false
candidate_c_primary_hypothesis: not_selected
candidate_c_readiness: blocked
candidate_c_execution_allowed: false
candidate_c_training_started: false
gate_c1: review
gate_c4: blocked
gpu_diagnostic: not_started
full_diagnostic: not_started
```

다음 Task는 [진단 계약](../evaluation/candidate-b-eos-diagnostic-contract.md)의 **EOS-DIAG-R1 artifact schema·strict
validator와 R2 identity·generation matrix freezer 구현**입니다. R1~R7 합성 검증과 EOS-DIAG-1~3 evidence가 먼저이며,
그 뒤 별도 사용자 승인으로 R8 GPU smoke와 R9 Full 진단을 수행할 수 있습니다. 진단 결과 검토 전에는 주가설·Dataset
선택지·Training intervention을 확정하지 않습니다. C-1~C-4가 통과하기 전 C-5 GPU Smoke나 C-6 Training으로 넘어가지
않습니다.

## 11. 기준 문서와 구현

- 전략·상태: [README](../../README.md), [Foundation Strategy](../project/foundation-model-strategy.md),
  [Current Status](../project/current-project-status.md), [Roadmap](../project/model-family-roadmap.md)
- Candidate 근거: [Candidate A 결과](./full-pretraining-candidate-a-result.md), [Candidate B 설계](./candidate-b-design.md),
  [Candidate B 결과](./candidate-b-execution-result.md), [A/B Full 비교](../evaluation/candidate-a-b-full-comparison.md)
- 평가·EOS: [Evaluation Framework](../evaluation/README.md), [EOS Success Policy](../evaluation/eos-success-policy.md),
  [EOS 진단 결과](../evaluation/eos-generation-decoding-diagnostic-result.md),
  [Candidate B read-only 진단 계약](../evaluation/candidate-b-eos-diagnostic-contract.md),
  [주가설 선택 정책](../evaluation/candidate-c-hypothesis-selection-policy.md),
  [ADR-008](../decisions/ADR-008-eos-generation-and-decoding-evaluation-policy.md)
- 결정·Gate: [ADR-005](../decisions/ADR-005-evaluation-and-experiment-policy.md),
  [ADR-006](../decisions/ADR-006-development-quality-gates.md), [ADR-009](../decisions/ADR-009-candidate-b-official-reassessment.md)
- 학습·artifact: [Checkpoint와 Resume](./checkpoint-and-resume.md), [Candidate B config](../../configs/candidate-b.example.yaml),
  [Publication 경계](./full-pretraining-publication-boundary.md)
- Candidate C 계약: [설계·Gate](./candidate-c-design.md), [EOS 가설](./candidate-c-eos-hypotheses.md),
  [Evaluation·Selection](./candidate-c-evaluation-contract.md),
  [ADR-011 제안](../decisions/ADR-011-candidate-c-experimental-successor.md)

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | Candidate B EOS 진단 계약 설계 완료와 실행 false, 진단 blocker·주가설 선택 정책을 C-BLOCK-002/C-1에 연결 |
| 2026-08-05 | 완료된 A/B 근거 조사와 향후 Candidate C 실행 분리, Gate 1~7/C-1~C-8 관계, EOS 진단 완료/root cause 미확정, Evaluation Framework 재사용 명시 |
| 2026-08-05 | Candidate C 계약 설계 완료, ADR-011 draft·H1~H7·Dataset/Tokenizer/Config freeze·Evaluation 계약과 ID blocker 연결; Gate는 미통과 유지 |
| 2026-08-05 | Candidate C 진입을 위한 Base Training 흐름·상태·blocker·C-1~C-8 Gate·config·EOS·평가 기준을 통합하고 실행 금지 경계를 기록 |
