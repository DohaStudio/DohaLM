# DohaLM v0.2 Weighted Tokenization 및 Dataloader Readiness

- 문서 상태: `review`
- 검토일: 2026-08-01
- 학습 상태: `not_started`
- 실행 권한: `false`

## 범위

이 문서는 `DOHALM-V0.2-DATASET-SIDECAR-20260801-0001`의 검증된 Sidecar를 v0.1과 동일한 토큰열에 정렬하고, 단일 GPU weighted train sampler와 비가중 순차 validation loader를 구성하는 계약을 정의한다. QLoRA 모델 로드, backward, optimizer step, checkpoint 생성은 범위 밖이다.

## Tokenization 재사용 결정

Option A인 `verified_byte_reuse`를 사용한다. 다음 조건을 모두 fail-closed로 확인한 뒤 v0.1 Hugging Face Dataset 디렉터리를 byte-identical하게 복사한다.

- Source `train.jsonl`, `validation.jsonl` SHA-256 일치
- Tokenizer fingerprint와 고정 revision 일치
- 공식 chat template, assistant-only loss, `max_seq_length=1536`, `packing=false` 일치
- 원본 tokenized checksum, token fingerprint, 행 수 일치
- 모든 행의 token 범위, prompt mask, assistant label, 마지막 EOS 및 무절단 계약 통과

재사용은 원문이나 token sequence를 수정하지 않는다. v0.2 package에는 행 정렬 metadata와 float64 sampling weight만 추가한다.

## Row Alignment

Train row `i`는 v0.2 `train.jsonl` line `i`, Sidecar의 `split=train, line_index=i`, tokenized row `i`, weight index `i`와 동일해야 한다. Validation도 같은 순서를 유지하지만 모든 weight는 `1.0`이며 sampling에 사용하지 않는다. 정렬 증거는 record, sidecar, tokenized, weight order fingerprint로 보존한다.

## Dataloader 계약

| 구분 | Train | Validation |
|---|---|---|
| Sampler | weighted replacement | sequential |
| Draws | 10,374 / epoch | 1,287 |
| Shuffle | false | false |
| Drop last | false | false |
| Batch | 1 | 1 |
| Padding | dynamic | dynamic |

Train seed는 `42 + epoch_index`이다. `EpochWeightedSampler.set_epoch()`은 Transformers 4.57.6의 epoch dataloader 경계에서 전달된다. `SidecarWeightedTrainerMixin`을 `transformers.Trainer`보다 먼저 상속해 sampler 경계만 교체한다. `WeightedRandomSampler`와 `DistributedSampler`를 함께 사용하지 않으며 현재 계약은 `world_size=1`, `rank=0`만 허용한다.

## Resume

향후 resume에는 current epoch, sampler seed, draw-order fingerprint가 필요하다. 이 상태의 완전한 복원 검증 전에는 자동 resume를 허용하지 않는다.

## Sampling Simulation

모델과 token payload를 읽지 않고 Sidecar의 길이·범주·품질 metadata로 10 epoch, 총 103,740 draw를 검증한다. 정책 기대 분포 대비 길이와 category의 최대 절대 오차는 각각 1.5 percentage points 이하여야 한다. epoch coverage 0.45 미만 또는 단일 row 최대 draw 12 초과는 readiness 경고다.

## QLoRA v0.2 초안

- Epoch: 2
- Per-device batch: 1
- Gradient accumulation: 16
- Draws per epoch: 10,374
- Optimizer steps: `ceil(10,374 / 16) × 2 = 1,298`
- Base model, 4-bit NF4, LoRA target, learning rate: v0.1 계약 유지
- Training approval: 없음

Generation-aware checkpoint 평가는 category·length 균형의 deterministic record hash 20개만 선정한다. validation token-weighted loss, Character F1, ROUGE-L, EOS termination, repetition, incomplete metric 계약을 사용하되 실제 generation은 이번 단계에서 수행하지 않는다. 점수 가중치는 후속 학습 승인 전에 확정하며 Character F1/ROUGE-L baseline 하락, 50% 초과 반복, special token 노출, empty output은 hard blocker다.

## Fail Closed

Source checksum, tokenizer/config, 행 정렬, EOS·mask, weight 순서, validation 비가중 정책, sampler 결정성, simulation 허용 오차, artifact checksum/reload 중 하나라도 실패하면 QLoRA readiness를 부여하지 않는다.

```yaml
v2_tokenization: ready_for_single_execution_after_merge
weighted_sampler: implemented
sampling_simulation: ready_for_single_execution_after_merge
qlora_training: not_approved
training_started: false
optimizer_steps: 0
execution_allowed: false
```
