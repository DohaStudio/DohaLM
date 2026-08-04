# DohaLM v0.1 QLoRA 학습 실행 계약

- 문서 상태: `review`
- 마지막 검토일: 2026-08-04
- Backend 상태: `implemented_verified`
- Training 상태: `completed_external_artifact_not_runtime_integrated`

## 목적과 계보

[확정] 이 backend는 `Qwen/Qwen2.5-1.5B-Instruct` revision
`989aa7980e4cf806f80c7fef2b1adb7bc71aa306`과
`DOHALM-TOKENIZATION-20260730-0001`을 사용해 외부 Base derivative Adapter를 학습한다.
ADR-010의 Candidate B immutable parent는 변경하지 않는다.

## 실행 경계

[확정] CLI는 `allocation`, `backward`, `training-smoke-1`,
`training-smoke-2`, `full`을 분리하며 각 mode의 정확한 Run ID를
`--approved-run-id`로 받아야 한다. 기본 QLoRA config의 `training_allowed: false`와
`execution_allowed: false`는 범용 실행 권한을 부여하지 않는 fail-closed 기본값으로 유지한다.

[확정] `full`은 동일 Git HEAD에서 생성된 Allocation, Backward Diagnostic,
Training Smoke artifact의 checksum, optimizer step 1, finite eval loss와 checkpoint
reload를 검증한 뒤에만 시작한다.
CLI의 `--expected-head`는 필수이며 merge된 `develop`의 immutable HEAD를 명시한다.

## 모델과 메모리

- 4-bit NF4, double quantization, BF16 compute
- 단일 `cuda:0`; CPU/disk/multi-device offload 금지
- LoRA `r=16`, `alpha=32`, `dropout=0.05`
- target: `q/k/v/o_proj`, `gate/up/down_proj`
- Base 일반 weight는 frozen
- gradient checkpointing on, `use_cache=false`

## 데이터와 Collator

[확정] 이미 tokenized된 `input_ids`, `attention_mask`, `labels`만 사용한다. Dynamic right
padding에서 input은 공식 PAD ID, attention은 0, labels는 `-100`으로 채운다. Text formatting,
재토크나이징, packing, split 결합은 수행하지 않는다.

## 산출물

[확정] Smoke, checkpoint, final Adapter, metrics와 환경 기록은 모두 외부
`<training_root>` 아래에 저장하고 Git에 포함하지 않는다. Run ID 충돌 시 overwrite 또는 자동 번호
증가 없이 중단한다. 쓰기 중 실패하면 staging을 `.failed`로 격리한다.

## 중단 조건

- Dataset checksum/fingerprint 또는 Git HEAD/worktree 변경
- CUDA OOM, GPU loss, NaN/Inf loss·gradient
- target module 누락, Base weight trainable, CPU offload
- checkpoint 저장·reload 실패, 디스크 부족
- optimizer step·epoch budget 불일치

## Smoke 역할 분리

[확정] Allocation Smoke는 train 중앙 길이와 train/validation 통합 최장 길이의
두 배치에 대해 BF16 forward graph와 VRAM 할당만 확인한다. backward 호출,
optimizer 생성, optimizer step은 모두 0이어야 한다.

[확정] Backward Diagnostic은 `128`, `256`, `512`, `768`, `1015` 각 목표 길이에
가장 가까운 실제 tokenized record 하나로 forward와 backward만 수행한다. 길이별
hard timeout은 600초이고 optimizer 생성·step은 금지한다. 앞 길이의 정상 artifact가
없으면 다음 길이를 실행할 수 없다.

[확정] Training Smoke만 optimizer를 생성하고 step을 수행한다. Stage 1은
2 micro-batch, accumulation 2, validation 1 batch이며, Stage 2는 16 micro-batch,
accumulation 16, validation 2 batch이다. 두 단계 모두 LoRA update, Base freeze,
checkpoint 저장 및 reload를 검증한다.

[확정] Gradient checkpointing owner는 `attach_lora()` 한 곳이다.
`prepare_model_for_kbit_training()`과 `TrainingArguments`는 checkpointing을 다시
활성화하지 않는다. 모델 로딩 900초, allocation forward별 120초, training smoke
1800초, reload 600초의 stage deadline을 적용하고 PID·시작·완료·경과 시간을
stderr JSON event로 기록한다.

[확정] Full Training은 Allocation, 다섯 Backward Diagnostic, Training Smoke
Stage 1·2 artifact의 checksum과 계약을 모두 검증하고, Stage 2 실측 기반 예상 시간이
72시간 이내일 때만 진입할 수 있다. 실패·timeout 시 자동 retry, runtime 연장 또는
하이퍼파라미터 완화는 하지 않는다.

## WSL2 실행 계약

[확정] Windows Run `DOHALM-V0.1-QLORA-20260730-0001`은 Step 71 이후
BitsAndBytes 4-bit backward가 31분 이상 진행되지 않아 terminal failure로 격리됐다.
checkpoint와 final adapter는 생성되지 않았으며 이 identity는 재사용하지 않는다.

[확정] WSL2에서는 `--profile wsl`을 사용하고 별도 Allocation, Backward,
Training Smoke 및 Stability ID를 소비한다. Full Run ID는
`DOHALM-V0.1-QLORA-20260731-0002`이다. Windows artifact를 WSL 승인 근거로
재사용하지 않는다.

[확정] Stability artifact Hotfix 병합 후 prerequisite는 Allocation
`DOHALM-V0.1-QLORA-ALLOCATION-SMOKE-WSL-20260731-0003`, Backward
`DOHALM-V0.1-QLORA-BACKWARD-DIAG-WSL-20260731-0003`, Training Smoke Stage 1·2의
각 `...-0003` ID로 현재 HEAD에서 새로 생성한다. 기존 prerequisite `0001`과 `0002`는
폐기 상태로 보존하고 재사용하지 않는다. Stability와 Full Run ID는 각각 기존 미사용
`DOHALM-V0.1-QLORA-STABILITY-WSL-20260731-0002`와
`DOHALM-V0.1-QLORA-20260731-0002`를 유지한다.

[확정] WSL Backward Diagnostic과 Training Smoke micro-batch timeout은 300초다.
Full Training 전 고정 seed로 실제 train record 128개, accumulation 16,
optimizer step 8회의 Stability Smoke를 수행한다. P50·P90·P95·P99·최대 batch 시간과
VRAM을 기록하며 stalled batch, non-finite loss 또는 Base weight 변경이 하나라도 있으면
Full Training을 차단한다.

[확정] 성공한 Stability canonical artifact는 `stability-result.yaml`,
`batch-metrics.jsonl`, `environment.json`, `stage-state.json`, `checksums.sha256`의
정확한 다섯 파일만 포함한다. batch metrics는 원문·token ID·record ID 없이 micro-batch별
canonical JSON을 append하고 매 record flush, 8 record 및 최종 시점 fsync를 적용한다.
stage state는 매 진행 단계에서 임시 파일 완전 기록과 fsync 후 atomic replace한다.
결과 게시 전체에는 300초 별도 watchdog을 적용하며 timeout이면 canonical final을 남기지
않고 staging 또는 failed 정책으로 격리한다. checksum, reload, identity, count, 완료 상태와
temp·lock residue가 모두 검증된 경우에만 성공으로 보고한다.

[확정] Full Training은 각 micro-batch의 global step, micro-batch index, sequence
length와 GPU memory를 heartbeat로 기록한다. 300초 동안 micro-batch가 완료되지 않으면
supervisor가 해당 worker PID만 종료하고 자동 retry하지 않는다.

[확정] 모델·Dataset·Tokenization·LoRA·optimizer·epoch 설정은 유지한다. 기존 config의
`save_steps: 250`, `eval_steps: 100`, `save_total_limit: 2`도 변경하지 않으므로 config
fingerprint를 새로 만들지 않는다. WSL Linux filesystem의 venv, cache, Dataset 복사본,
training output은 Git에 포함하지 않는다.

## 상태

```yaml
backend: implemented
allocation_smoke: completed
backward_diagnostic: completed
training_smoke: completed
full_training: completed
windows_run_0001: failed_terminal
wsl_run_0002: completed
adapter: created_external_not_runtime_integrated
adapter_loader: not_implemented
deployment_ready: false
base_model_merge: false
```

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-04 | 후속 독립 평가 문서에 기록된 완료 Adapter와 Runtime 미연결 상태 동기화 |
| 2026-07-30 | QLoRA smoke·full training·adapter reload·inference 계약과 backend 추가 |
| 2026-07-31 | WSL2 전용 Run identity·128-batch stability·300초 micro-batch heartbeat 계약 추가 |
| 2026-07-31 | Stability durable artifact·300초 publish watchdog 계약과 prerequisite 0003 ID 확정 |
