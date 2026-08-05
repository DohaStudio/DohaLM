# DohaLM v0.3 Tokenization 및 QLoRA Readiness

- 문서 상태: `review`
- 마지막 검토일: 2026-08-05
- 학습 상태: `not_started`
- 실행 권한: `false`

## 범위

이 문서는 생성·checksum 검증된 `DOHALM-V0.3-SHORT-ANSWER-DATASET-20260802-0001`의 원본·short 계보를 보존한
assistant-only tokenization, 세 sampler의 모델 비사용 simulation, QLoRA 설정 초안을 정의한다.
모델 weight 로드, backward, optimizer step, checkpoint, QLoRA 학습과 generation 평가는 범위 밖이다.

## Tokenization 계약

Qwen2.5 1.5B Instruct의 고정 revision과 공식 chat template를 사용한다. Prompt와 padding label은
`-100`, assistant와 정확히 하나의 마지막 EOS는 학습 label이다. 1024, 1152, 1280, 1536 후보 중
전체 prompt·assistant·EOS를 자르지 않는 가장 작은 값을 artifact에 확정한다.

기존 v0.1 artifact는 source record, 순서, tokenizer, template, max length와 모든 설정이 일치할 때만
재사용할 수 있다. 하나라도 다르면 original 10,374행과 validation 1,287행도 새로 tokenization한다.
Short 7,265행은 항상 새로 tokenization한다.

## 정렬과 검증

Train은 original 10,374행 뒤에 short 7,265행이 위치한다. Row alignment에는 record hash, parent hash,
variant, row index, token-row fingerprint와 길이만 저장하며 원문과 token sequence를 저장하지 않는다.
Validation 1,287행은 순차·비가중·short 미포함 정책을 유지한다.

## Sampler

`standard_shuffle`, 50:50 `variant_balanced`, `parent_group_shuffle`를 10 epoch simulation한다.
기본 추천은 replacement 없는 parent-group shuffle이다. epoch seed는 `42 + epoch`이며, shuffled group의
첫 variant를 모두 배치한 뒤 나머지 variant를 배치한다. 내부 우선순위는 짝수 epoch original→short,
홀수 epoch short→original이므로 parent·child가 바로 이웃하지 않는다. Coverage 1.0, duplicate 0, unsampled 0과
결정성을 모두 통과해야 한다.

## QLoRA 초안

- Epoch: 1
- Learning rate: `1e-4`
- Batch / gradient accumulation: `1 / 16`
- 예상 optimizer step: `ceil(17,639 / 16) = 1,103`
- Checkpoint·generation evaluation: 220, 440, 660, 880, 1,103 step
- Generation subset: category·length 균형 deterministic 40 prompts

실제 `max_seq_length`와 token budget은 병합 후 단일 tokenization artifact에서 확정한다. QLoRA 실행은
별도 승인 전까지 허용하지 않는다.

```yaml
tokenization: failed_publish_observability_loss_identity_review_required
tokenization_failure_contract: implemented_synthetic_validated
canonical_tokenized_artifact: absent
original_run_identity_reusable: false
sampler_simulation: blocked_until_verified_tokenization
qlora_training: not_approved
training_started: false
optimizer_steps: 0
execution_allowed: false
```

Publish 실패 보존과 Run identity 재사용 정책은
[v0.3 Tokenization publish 실패 보존 계약](./dohalm-v0.3-tokenization-publish-failure.md)을 따른다.
새 identity 기반 복구 Gate와 QLoRA 준비 조건은
[v0.3 학습 재개 Readiness](./dohalm-v0.3-training-readiness.md)를 따른다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | 실제 Dataset checksum 유효·canonical tokenized artifact 부재·기존 Run identity 비재사용 상태 반영 |
