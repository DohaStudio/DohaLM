# Full Pretraining 누적 1 epoch continuation

## AMP overflow recovery contract

### Prospective numerical diagnostic seam

[확정] 이후 실행에서 AMP overflow가 발생하면 기존 복구 및 세 번째 연속 중단 정책을
변경하지 않고, 다음 policy 판정 전에 동일한 cached batch, step-start RNG, model 및
optimizer state를 사용하는 진단 전용 scale probe를 수행한다. 후보 scale은 현재 scale부터
2로 나누어 별도 계약인 `configs/amp-numerical-diagnostics.json`의 floor까지 생성한다.
이 floor는 Training config나 config fingerprint의 일부가 아니다.

[확정] Probe는 optimizer step을 수행하지 않는다. 각 후보 실행 뒤 gradient를
제거하고 RNG를 복구하며 model, optimizer, scheduler, production scaler, sampler와
step/token/record accounting이 변하지 않았음을 fingerprint와 checksum으로 검증한다.
복구 또는 evidence 기록 실패는 `DIAGNOSTIC_EVIDENCE_FAILURE`로 fail closed 한다.

[확정] `full-amp-numerical-diagnostics.jsonl`에는 run/step/attempt/scale, batch와 RNG
identity, model/optimizer fingerprint, gradient finite 상태·크기·norm 및 canonical
offender metadata만 저장한다. Dataset text, token ID, label과 prompt는 저장하지 않는다.

[확정] r4는 cumulative step 17,196 이후, AMP scale 262,144에서 발생한
scaled-gradient overflow를 `clip_grad_norm_(error_if_nonfinite=True)`가
`GradScaler.step()`과 `GradScaler.update()`보다 먼저 fatal 처리해 종료됐다.
직전 12,313개 완료 step과 실패 attempt의 loss는 finite였고, 실패 attempt의
optimizer update는 0회였다. 이 이력은 변경하거나 재사용하지 않는다.

[확정] CUDA FP16 continuation은 loss, model parameters와 optimizer tensor state가
finite이고 `GradScaler`가 `found_inf`에 따라 optimizer update를 skip하고 scale을
backoff한 경우만 recoverable AMP overflow로 분류한다. 이때 같은 cached batch와
같은 step-start RNG state를 재사용하며 sampler offset, token/record count, scheduler와
global optimizer step은 성공한 update에서만 한 번 증가한다. 각 attempt는 text-free
`full-amp-overflow-events.jsonl`에 scale before/after와 pending count를 기록한다.

[확정] 세 번째 연속 overflow, non-finite loss, model/optimizer state corruption,
AMP backoff로 입증되지 않은 non-finite gradient는 fail closed 한다. NaN/Inf clamp,
loss·learning-rate·clip threshold 변경, Dataset 변경, 자동 retry/resume는 허용하지
않는다. r4 checkpoint는 존재하지 않으므로 후속 logical run은 반드시 immutable
r3 `checkpoint-4883`에서 시작한다.

이 계약은 `run-aihub-71748-local-v1-r3/checkpoint-4883`을 유일한 source로 사용해 같은 immutable Dataset에서 누적 정확히 1 epoch까지 진행하는 local-only `r4` 실행만 허용한다. generic resume, automatic retry/resume, checkpoint 덮어쓰기와 다른 source 승격은 허용하지 않는다.

## 경계

- train packed sequence: `278,535`
- micro batch / gradient accumulation: `2 / 4`
- r3 sampler offset: `39,064`
- 시작 global step: `4,883`
- 누적 target step: `34,817`
- continuation step: `29,934`
- 누적 실제 input token: `71,304,960`
- continuation 실제 input token: `61,304,576`

마지막 optimizer step은 남은 7개 sequence만 소비한다. sampler는 epoch 0 permutation seed 17과 checkpoint의 permutation fingerprint·offset을 복원하며 처음부터 다시 시작하지 않는다.

## 상태와 scheduler

모델, AdamW, scaler, Python/CPU/CUDA RNG, sampler와 global step을 checksum-valid source checkpoint에서 복원한다. source cosine scheduler는 terminal step `4,883`이어야 하며, 승인된 누적 horizon `34,817`로만 확장한다. warmup과 global step을 0으로 되돌리지 않는다. 확장 직후 learning rate는 새 cumulative cosine horizon의 global step `4,883` 값이며 이 horizon 변경은 run package와 checkpoint metadata에 기록한다.

## 권한과 산출물

execution mode는 `r3_one_epoch_continuation` 하나뿐이다. production Host의 기존 Dataset permission, immutable decision, single-use approval 및 durable journal lifecycle을 그대로 거쳐야 한다. 출력은 별도 `run-aihub-71748-local-v1-r4` root에 원자 게시한다.

중간 checkpoint `19,850`과 final checkpoint `34,817`만 허용한다. r3 checkpoint와 Dataset은 수정하지 않으며, OOM·NaN/Inf·반복 AMP skip·checksum/atomic-write 실패·ambiguous journal outcome·disk/thermal/hard-stop 위반 시 자동 retry나 resume 없이 중단한다.
