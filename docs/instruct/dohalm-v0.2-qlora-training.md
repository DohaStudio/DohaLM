# DohaLM v0.2 Weighted QLoRA 실행 계약

- 문서 상태: `review`
- 마지막 검토일: 2026-08-04

## 상태

`training_completed_postprocessing_recovered_no_eligible_candidate`

이 문서는 v0.2 tokenized dataset과 Sidecar sampling weight를 사용하는 단일 RTX 3060 Ti/WSL2 QLoRA 실행 계약을 정의한다. 구현과 synthetic 검증은 완료 대상으로 삼지만, 실제 smoke와 2-epoch 학습 완료 여부는 runtime artifact로만 판정한다.

## 불변 입력

- Dataset: `DOHALM-V0.2-DATASET-SIDECAR-20260801-0001`
- Tokenization: `DOHALM-V0.2-TOKENIZATION-20260801-0001`
- Sampling simulation: `DOHALM-V0.2-SAMPLING-SIMULATION-20260801-0001`
- epoch 0 draw fingerprint: `sha256:b8157713c04bf2cdb7fd178031de1b8cb3f19287246577d14663940fb12998d3`
- 설정: [dohalm-v0.2-qlora.yaml](../../configs/training/dohalm-v0.2-qlora.yaml)

원본 JSONL, Sidecar, tokenized dataset, sampling policy는 수정하거나 덮어쓰지 않는다. `maximum_single_record_draws=14` 경고는 유지하며 weight clamp나 정책을 자동 변경하지 않는다.

## Weighted sampling

학습은 `WeightedRandomSampler(replacement=true)`를 사용하고 epoch별 seed는 `42 + epoch_index`이다. epoch당 draw는 10,374건이다. Validation은 `SequentialSampler`이며 sampling weight를 적용하지 않는다. sampler와 shuffle을 함께 쓰지 않는다.

## 고정 실행 순서

1. Allocation smoke: forward 4건, backward/optimizer 0회
2. Backward diagnostic: 128/256/512/768/max 길이, optimizer 0회
3. Stage 1: microbatch 2, accumulation 2, optimizer 1회
4. Stage 2: microbatch 32, accumulation 16, optimizer 2회
5. Stability: microbatch 256, accumulation 16, optimizer 16회
6. Runtime estimate가 48시간 이하인지 검증
7. 위 결과와 Git·artifact fingerprint가 모두 일치할 때만 2 epoch full training

각 ID는 코드에 고정되어 있다. 경로 충돌 시 overwrite, retry, resume, 자동 ID 증가 없이 fail closed한다. GPU 실행에는 직전 AC 전원과 냉각·환기 확인이 필요하다.

## Full training

- epochs: 2
- draw/epoch: 10,374
- gradient accumulation: 16
- optimizer step/epoch: 649
- total optimizer steps: 1,298
- save step: 250
- 최종 보관 checkpoint: 최대 2개

Checkpoint 250/500/750/1000/1250와 final adapter는 삭제 전에 generation-aware 평가를 끝낸다. 평가가 durable하게 기록된 뒤에만 이전 checkpoint를 정리한다.

## Generation-aware 평가

Validation에서 category별 2건, 총 20건을 stable hash로 선택한다. 질문·reference·생성 원문과 token array는 artifact에 저장하지 않는다.

- decoding: greedy, `max_new_tokens=256`, `repetition_penalty=1.05`, `no_repeat_ngram_size=0`
- metrics: token-weighted validation loss, Character F1, ROUGE-L, EOS, max-length, repetition, incomplete, empty, special-token exposure
- hard blocker: v0.1보다 낮은 Character F1 또는 ROUGE-L, repetition 50% 초과, special-token 노출, empty output
- 목표: EOS 80% 이상, repetition/incomplete 15% 미만, Character F1 0.48 초과, ROUGE-L 0.32 초과

목표는 학습 완료 조건과 분리한다. 학습이 완료돼도 hard blocker를 통과한 보관 후보가 없으면 `deployment_ready=false`, `selected_candidate=null`이다.

## 산출물과 실패 정책

Full artifact에는 `checkpoints/`, `final-adapter/`, `training-config.yaml`, `training-result.yaml`, `sampler-metadata.json`, `generation-evaluation.json`, `environment.json`, `checksums.sha256`가 필요하다. 모든 runtime 산출물은 Git 밖 `/home/doha/dohalm-training` 아래에 둔다.

Smoke 실패 시 후속 단계를 실행하지 않는다. Stability 실패 또는 48시간 초과 추정이면 full training을 실행하지 않는다. Full training 실패 시 자동 retry/resume을 하지 않고 마지막 정상 checkpoint와 격리된 실패 artifact를 보존한다.

종료 step이 save 주기의 배수가 아니면 정확히 하나의 terminal checkpoint를 허용한다. v0.2 Run의
terminal step은 1,298이며 허용 checkpoint는 `250/500/750/1000/1250/1298`이다. 완료된 학습의
후처리만 복구하는 절차는 [Terminal Checkpoint 및 Evaluation-Only Recovery 계약](./dohalm-v0.2-evaluation-recovery.md)을 따른다.

## Readiness

```yaml
implementation: implemented
synthetic_tests: required
runtime_smokes: completed
full_training: completed_2_epochs_1298_steps
postprocessing: failed_checkpoint_schedule_validation
evaluation_recovery: completed_no_eligible_candidate
runtime_integration: blocked_no_eligible_candidate
automatic_retry: false
automatic_resume: false
source_modified: false
```

[확정] Recovery 결과는 [Evaluation-Only Recovery](./dohalm-v0.2-evaluation-recovery.md)와
[Adapter 후보 선정 결과](./general-instruct-adapter-candidate-selection.md)를 따른다. 학습 완료와 recovery 완료는
Runtime eligibility가 아니며 `selected_candidate=null`, `deployment_ready=false`를 유지한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | evaluation-only recovery 완료와 eligible candidate 0건 상태 동기화 |
