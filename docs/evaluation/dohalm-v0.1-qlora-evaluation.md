# DohaLM v0.1 QLoRA 독립 평가 계약

- 문서 상태: `review`
- 마지막 검토일: 2026-08-01
- 태그: `instruct`, `qlora`, `evaluation`, `privacy`
- 관련 결정: [ADR-005](../decisions/ADR-005-evaluation-and-experiment-policy.md), [ADR-010](../decisions/ADR-010-dohalm-instruct-strategy.md)

## 목적과 범위

[확정] 완료된 DohaLM v0.1 QLoRA Adapter를 Base와 동일 조건으로 비교한다. 이 경로는
`model.eval()`과 inference-only forward/generation만 허용하며 `Trainer.train()`, optimizer,
backward, checkpoint·adapter 쓰기와 Dataset 재토큰화를 수행하지 않는다.

## 평가 대상과 손실

- Base `Qwen/Qwen2.5-1.5B-Instruct`
- `checkpoint-1750`
- `checkpoint-1947`
- `final-adapter`

[확정] 네 대상은 동일 base revision, tokenizer, tokenized validation 1,287행과
`DynamicSFTCollator`를 사용한다. Assistant label과 EOS만 유효하며 prompt·padding label은
`-100`이다. 품질 비교는 전체 유효 label token NLL의 token-weighted mean을 사용하고,
Trainer 경로 재현을 위해 batch-size 1의 batch-mean도 함께 기록한다.

## 생성·Category·안전성

[확정] 생성 평가는 공개 합성 한국어 QA 30개와 category-balanced held-out validation hash
50개를 사용한다. Greedy decoding, `max_new_tokens=256`, `repetition_penalty=1.05`를 고정한다.
원문 prompt·reference·generation text와 token 배열은 artifact에 저장하지 않는다. 결과에는
sample hash와 집계 지표만 남긴다.

[확정] 처리된 JSONL에는 category가 없으므로 승인된 SFT Validation ZIP metadata의
`data_category.middle`을 process-local hash join으로 연결한다. ZIP을 추출하거나 수정하지
않으며 metadata 값과 원문은 결과에 기록하지 않는다.

## 실행과 산출물

공개 설정은 다음 두 파일이다.

- `configs/evaluation/dohalm-v0.1-qlora-evaluation.yaml`
- `configs/evaluation/dohalm-v0.1-synthetic-prompts.yaml`

실제 로컬 경로는 CLI 인자로만 전달하며 Git에 하드코딩하지 않는다. 실행 결과는 Git 외부의
`<evaluation-root>/DOHALM-V0.1-EVAL-20260801-0001`에 atomic publish한다. 기존 output이
있으면 덮어쓰지 않고 실패한다.

```text
python -m scripts.evaluation.run_qlora_sft_evaluation \
  --config configs/evaluation/dohalm-v0.1-qlora-evaluation.yaml \
  --qlora-config configs/training/dohalm-v0.1-qlora.yaml \
  --prompt-config configs/evaluation/dohalm-v0.1-synthetic-prompts.yaml \
  --repository <repository> \
  --training-run-root <training-run-root> \
  --tokenized-root <tokenized-root> \
  --processed-root <processed-run-root> \
  --raw-dataset-root <raw-dataset-root> \
  --model-cache-root <model-cache-root> \
  --output-root <evaluation-root> \
  --evaluation-id DOHALM-V0.1-EVAL-20260801-0001 \
  --expected-head <immutable-develop-head> \
  --execute
```

## Fail Closed

- artifact·Dataset·tokenizer·config·Git identity 불일치
- 네 모델의 동일 batch checksum 불일치
- adapter 비활성 또는 Base와 동일 logits
- `model.eval()`·dropout 비활성 계약 위반
- 두 회차 metric fingerprint 불일치
- 원문·token ID 저장 설정 활성화
- output 충돌 또는 checksum/reload 실패

위 조건에서는 품질 판정을 만들지 않고 추가 학습도 시작하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-01 | QLoRA Base·checkpoint·final 동일 손실·생성 평가와 privacy·재현성 계약 작성 |
