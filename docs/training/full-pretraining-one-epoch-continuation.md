# Full Pretraining 누적 1 epoch continuation

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
