# DohaLM v0.2 Terminal Checkpoint 및 Evaluation-Only Recovery 계약

- 문서 상태: `review`
- 최종 검토일: 2026-08-02
- Training Run: `DOHALM-V0.2-QLORA-20260801-0001`
- Recovery ID: `DOHALM-V0.2-EVALUATION-RECOVERY-20260802-0001`
- Training execution source: `a4d3ab5e5adf1e4d41789c297bdb28f6ece9810f`
- Recovery 실행 상태: `pending`

## 범위

이 계약은 2 epoch와 optimizer step 1,298을 완료한 뒤 checkpoint inventory 검증에서
`CHECKPOINT_SCHEDULE_INVALID`로 격리된 v0.2 Run의 평가만 복구한다. Training backend,
`Trainer.train()`, backward, optimizer, scheduler, checkpoint 저장 및 adapter 저장은 호출하지 않는다.

기존 `.failed` 디렉터리는 감사 증거이며 수정·삭제·rename하지 않는다. Recovery 결과는 별도
`/home/doha/dohalm-evaluation/DohaLM-v0.2` 경로에 atomic no-replace 방식으로 게시한다.

## Checkpoint schedule

Scheduled checkpoint는 `step % save_steps == 0`이고 terminal step보다 작다. 전체 optimizer step이
save 주기에 맞지 않으면 정확히 하나의 terminal checkpoint를 허용한다.

```yaml
save_steps: 250
total_optimizer_steps: 1298
allowed_steps: [250, 500, 750, 1000, 1250, 1298]
maximum_terminal_checkpoint_count: 1
```

누락, 중복, 중간 비배수 step, terminal 초과 step, 복수 terminal checkpoint는 모두 Fail Closed다.

## Terminal과 Final Adapter 동등성

`checkpoint-1298`과 `final-adapter`는 다음 identity가 모두 일치해야 한다.

- `adapter_model.safetensors` SHA-256
- canonical `adapter_config.json` fingerprint
- LoRA safetensors payload fingerprint
- base model identity
- global optimizer step 1,298
- immutable training config SHA-256

두 artifact는 삭제하거나 합치지 않는다. 동등성이 확인되면 generation은 `checkpoint-1298`에서 한 번만
실행하고 `final-adapter` 결과는 fingerprint 동등성 관계로 연결한다.

## Recovery gate

다음 조건을 모두 만족해야 한다.

- Run ID와 `.failed` 경로가 고정 identity와 일치
- 마지막 metric과 trainer state가 epoch 2, optimizer step 1,298을 증명
- train loss와 모든 기록 loss가 finite
- 실행 중인 v0.2 full training process가 없음
- checkpoint inventory와 checksum이 유효
- terminal checkpoint와 final adapter가 동등
- repository training config와 보존 config가 byte-identical
- Dataset, Tokenization, Sidecar fingerprint 재검증 통과
- Recovery output ID가 미사용 상태

OOM, NaN/Inf, 미완료 epoch, 미완료 optimizer step, 손상 checkpoint, fingerprint drift 및 다른 failure
signature에는 이 경로를 사용할 수 없다.

## Evaluation 계약

고유 adapter 상태마다 validation 1,287건을 SequentialSampler와 assistant-only label mask로 평가한다.
token-weighted loss, batch mean loss, perplexity 및 valid label token 수를 기록한다. Generation은 기존
category·length balanced deterministic 20건 subset과 다음 설정을 그대로 사용한다.

```yaml
do_sample: false
max_new_tokens: 256
repetition_penalty: 1.05
no_repeat_ngram_size: 0
eos_token_id: 151645
pad_token_id: 151643
```

원문 prompt, reference, decoded text 및 token sequence는 artifact에 저장하지 않는다.

## 후보 선정

Hard blocker를 통과한 후보만 선정할 수 있다. 그 안에서 Character F1, ROUGE-L, EOS 종료,
반복 억제, 미완결 억제, validation loss 순으로 비교한다. Hard blocker 통과 후보가 없으면 결과는
다음과 같다.

```yaml
selected_candidate: null
deployment_ready: false
verdict: NEEDS_MODEL_IMPROVEMENT
```

## Recovery artifact

- `recovery-manifest.yaml`
- `checkpoint-inventory.json`
- `validation-loss-results.json`
- `generation-evaluation.json`
- `candidate-selection.json`
- `environment.json`
- `training-recovery-result.yaml`
- `checksums.sha256`

Writer는 exclusive staging, file fsync, directory fsync, atomic no-replace publish, reload checksum 검증을
수행한다. 실패하면 canonical artifact를 남기지 않고 실패 증거를 격리한다.

## 안전 불변식

```yaml
training_reexecution: false
retry: false
resume: false
training_calls: 0
backward_calls: 0
optimizer_steps_added: 0
scheduler_steps: 0
checkpoint_writes: 0
adapter_writes: 0
checkpoint_deletion: false
dataset_changes: 0
tokenization_changes: 0
```
