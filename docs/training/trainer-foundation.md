# DohaLM Phase 5 Trainer Foundation

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-24 |
| 선행 문서 | [모델 통합](../architecture/model-integration.md), [사전학습 계획](./pretraining-plan.md), [실험 관리](./experiment-management.md), [ADR-006](../decisions/ADR-006-development-quality-gates.md) |
| 후속 문서·작업 | [Tiny 실규모 검증](./tiny-training-validation.md), [Sampler와 재개](./sampler-state-and-resume.md), [Trainer 테스트](../quality/trainer-testing.md), Gate 6·7 사용자 검토 |
| 구현 전 필수 여부 | 실제 학습 기반 확장 전 예 |

- [확정] Phase 5는 `DohaLMTiny`를 실제로 최적화할 수 있는 최소 Trainer Foundation을 구현한다.
- [확정] 입력은 고정 seed의 synthetic token ID뿐이며 실제 AI Hub 데이터, 승인 corpus와 tokenizer artifact를 사용하지 않는다.
- [제외] 장시간 사전학습, SFT, 분산·멀티 GPU, API·Frontend는 구현하지 않았다.

## 2. 구현 구성

| 구성 | 구현 내용 |
|---|---|
| 설정 | immutable `TrainingConfig`, 유효 batch·AMP·경로 검증과 fingerprint |
| Dataset | 결정론적 random 또는 반복 pattern `SyntheticTokenDataset` |
| Collator | dynamic padding, `<pad>=0`, label padding `-100`, boolean attention mask |
| DataLoader | 고정 generator seed, shuffle, worker seed, Windows 기본 worker 0 |
| Optimizer | AdamW, bias·LayerNorm no-decay, tied/frozen parameter 제외 |
| Scheduler | 기본 linear warmup+decay, 명시 선택 가능한 cosine 후보 |
| Trainer | AMP, accumulation, clipping, metric, checkpoint boundary |
| State | step·token·record·시간·lineage fingerprint |

`batch_size`는 유효 sequence batch이며 `micro_batch_size × gradient_accumulation_steps`와 같아야 한다. 운영 batch, learning rate, weight decay, warmup, clipping과 저장 주기는 여전히 `[검증 필요]`다.

## 3. Synthetic Dataset과 Batch

Dataset은 vocabulary, sequence length, record 수, seed, BOS/EOS와 선택 반복 pattern으로 결정론적 tensor를 만든다. 각 record는 `input_ids`, 복사된 `labels`, 전부 유효한 `attention_mask`를 반환한다. Dataset fingerprint는 원문이나 절대경로 없이 생성 인자에서 SHA-256으로 계산한다.

Collator는 batch 내 최대 길이에 맞춰 입력을 `0`, label을 `-100`으로 채우고 mask를 생성한다. 빈 batch, 잘못된 rank·dtype·shape와 context 초과를 자동 수정하지 않는다.

## 4. Optimizer와 Scheduler

- [확정] AdamW의 bias와 직접 구현 LayerNorm weight·bias는 weight decay에서 제외한다.
- [확정] token embedding과 LM Head의 동일 Parameter는 한 번만 optimizer group에 포함한다.
- [확정] frozen parameter와 빈 trainable model은 각각 제외·차단한다.
- [확정] smoke scheduler는 step 0, warmup 경계, max step과 resume LR를 검증한 linear warmup + linear decay다.
- [검증 필요] 운영 사전학습의 승인 계획은 warmup+cosine이며 이번 synthetic linear scheduler가 이를 변경하지 않는다.
- [확정] 실제 Tiny 합성 검증용 cosine 구현은 linear warmup, cosine decay와 `min_lr_ratio`를 지원하지만 운영값으로 승인하지 않는다.

## 5. Trainer 실행 순서

```text
batch 이동 → autocast → forward/loss → loss÷accumulation
→ scaled backward → accumulation boundary
→ scaler unscale → finite 검사 → gradient clipping
→ optimizer step → scaler update → scheduler step → zero_grad
→ state·metric 갱신 → checkpoint
```

- [확정] `max_steps`와 `target_steps`는 optimizer step 기준이다.
- [확정] accumulation 중간에는 optimizer·scheduler·checkpoint를 실행하지 않는다.
- [확정] Trainer가 필요한 수의 DataLoader cycle을 반복해 완전한 accumulation boundary에서만 종료한다. 미완성 gradient는 저장하거나 암묵적으로 step하지 않는다.
- [확정] non-finite loss·gradient는 `NON_FINITE_LOSS`, `NON_FINITE_GRADIENT`로 차단하고 실패 optimizer step의 state 증가를 되돌린다.
- [확정] gradient clipping은 AMP unscale 후 실행하며 clipping 전·후 norm을 기록한다.

## 6. AMP와 정밀도

CUDA AMP는 `torch.amp.autocast`와 `GradScaler`를 사용한다. CPU AMP 요청은 `AMP_NOT_AVAILABLE`로 차단하며 BF16은 이번 Foundation에서 지원하지 않는다.

- [가정] FP16 synthetic smoke의 initial scale `1024`는 RTX 3060 Ti 단기 검증 후보다. 운영 loss-scale 정책으로 승인하지 않는다.
- [확정] scaler state는 checkpoint에 저장·복원한다.
- [확정] CUDA FP16 10-step과 checkpoint-5→10 resume에서 finite loss·gradient와 optimizer update를 확인했다.

## 7. State와 Logging

State는 global/micro/optimizer step, epoch, tokens·records, best·last metric, sampler state, 시작·갱신 시각과 model/training/dataset/tokenizer fingerprint를 가진다. JSONL metric은 step, loss, LR, clipping 전·후 gradient norm, 누적 token·record, step time, tokens/sec와 peak allocated/reserved byte를 기록한다.

- [확정] token sequence와 실제 로컬 절대경로는 로그에 기록하지 않는다.
- [확정] output은 `.gitignore`가 보호하는 `tests/output`, `checkpoints`, `logs`, `artifacts`, `experiments` 상대경로만 허용한다.

## 8. 실행 결과와 한계

| 검증 | 조건 | 결과 |
|---|---|---|
| CPU | small config, batch 2, sequence 8, step 5→10 resume | loss `21.1677 → 0.002842`, checkpoint 검증 통과 |
| CUDA AMP | small config, batch 2, sequence 16, step 5→10 resume | loss `21.4333 → 0.326715`, finite gradient |
| Overfit 준비 | 반복 batch, dropout 0, CPU 50 step | loss `21.1677 → 0.00002262` |
| 실제 Tiny CUDA | 16,889,856 params, S=256, micro 1×accum 8, step 5→10 | loss `254.3525 → 83.2656`, bitwise resume, peak allocated 634,336,768 B |
| 실제 Tiny 제한 overfit | 반복 pattern, S=64, CUDA FP16 100 step | loss `249.9167 → 1.7976e-7` |

- [확정] loss 감소는 synthetic trainer wiring 검증이며 실제 한국어 학습 성공이나 품질 근거가 아니다.
- [확정] Gate 3~7은 사용자 승인 전까지 `planned`를 유지한다.

## 9. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-24 | [확정] 명시적 sampler state, cosine 후보와 실제 Tiny 합성 CUDA·VRAM·resume 검증 결과를 연결함 |
| 2026-07-24 | [확정] synthetic Dataset→Trainer→metric→checkpoint·resume 최소 기반과 CPU·CUDA 결과를 기록함 |
