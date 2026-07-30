# DohaLM v0.1 QLoRA 학습 실행 계약

- 문서 상태: `review`
- 마지막 검토일: 2026-07-30
- Backend 상태: `implemented_awaiting_gpu_smoke`
- Training 상태: `explicit_run_approval_required`

## 목적과 계보

[확정] 이 backend는 `Qwen/Qwen2.5-1.5B-Instruct` revision
`989aa7980e4cf806f80c7fef2b1adb7bc71aa306`과
`DOHALM-TOKENIZATION-20260730-0001`을 사용해 외부 Base derivative Adapter를 학습한다.
ADR-010의 Candidate B immutable parent는 변경하지 않는다.

## 실행 경계

[확정] CLI는 `smoke`와 `full`을 분리하며 각 mode의 정확한 Run ID를
`--approved-run-id`로 받아야 한다. 기본 QLoRA config의 `training_allowed: false`와
`execution_allowed: false`는 범용 실행 권한을 부여하지 않는 fail-closed 기본값으로 유지한다.

[확정] `full`은 동일 Git HEAD에서 생성된 Allocation/Training Smoke artifact의 checksum,
optimizer step 1, finite eval loss와 checkpoint reload를 검증한 뒤에만 시작한다.
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

## 상태

```yaml
backend: implemented
allocation_smoke: not_started
training_smoke: not_started
full_training: not_started
adapter: not_created
base_model_merge: false
```

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-30 | QLoRA smoke·full training·adapter reload·inference 계약과 backend 추가 |
