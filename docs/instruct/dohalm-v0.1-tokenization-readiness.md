# DohaLM v0.1 Tokenization 및 QLoRA 준비

- 문서 상태: `review`
- 마지막 검토일: 2026-07-30
- Tokenization 상태: `completed`
- QLoRA Training 상태: `not_started_not_approved`

## 범위

[확정] 이 작업은 Run `AIHUB-71748-SFT-PROCESSING-20260730-0015`의 확정된
`train.jsonl`과 `validation.jsonl`을 읽어 tokenized Dataset을 만드는 범위다. 원본 JSONL,
Processing 산출물과 통계 값은 수정하거나 재해석하지 않았다. `statistics.json`의
`pii.training_excluded`는 전역 PII 우선 제외 집계이며, tokenization 대상 행 수는 확정된 두
JSONL을 기준으로 검증했다.

[확정] 모델 weight 로드, `Trainer.train()`, optimizer step, LoRA adapter 생성, checkpoint,
inference는 실행하지 않았다.

## Base와 Tokenizer

[확정] DohaLM v0.1은 `Qwen/Qwen2.5-1.5B-Instruct` revision
`989aa7980e4cf806f80c7fef2b1adb7bc71aa306`을 외부 Base로 사용한다. 이는 ADR-010의
Candidate B parent를 변경하지 않는 별도 derivative 선택이다. 모델 카드와 라이선스에 따라
Apache-2.0 조건을 기록했다.

- 공식 모델 카드: <https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct>
- 공식 라이선스: <https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct/blob/main/LICENSE>
- Tokenizer: `Qwen2TokenizerFast`
- Vocabulary 범위: 151,665개 ID (`vocab_size` 151,643 + added tokens)
- EOS: `<|im_end|>` / 151645
- PAD: `<|endoftext|>` / 151643
- BOS / UNK: 없음
- padding / truncation side: right / right
- 공식 `chat_template`: 사용

## Formatting과 Loss

[확정] `instruction`은 user content가 되고, `input`이 있으면 단일 구분자 `\n\n` 뒤에
붙인다. `system`이 있으면 system message로 먼저 배치하고 `output`은 assistant response로
사용한다. Qwen 공식 template에는 assistant mask marker가 없으므로 공식 template로 generation
prompt 경계를 만들고 response token과 공식 EOS를 별도 결합한다. prompt label은 모두 `-100`이며
assistant response와 마지막 EOS만 학습 label이다.

[확정] packing은 사용하지 않는다. source text는 tokenized artifact에 중복 저장하지 않으며
`input_ids`, `attention_mask`, `labels`만 저장한다.

## 길이 분석

| 구분 | 최소 | 평균 | 중앙값 | P90 | P95 | P99 | 최대 | 합계 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 전체 | 54 | 433.085842 | 460 | 617 | 664 | 757 | 1,150 | 5,050,214 |
| prompt | 33 | 49.506732 | 49 | 56 | 59 | 67 | 90 | 577,298 |
| assistant | 9 | 383.579110 | 411 | 566 | 611 | 704 | 1,094 | 4,472,916 |
| user content | 4 | 20.506732 | 20 | 27 | 30 | 38 | 61 | 239,129 |

| 후보 | truncation 레코드 | assistant truncation 레코드 | 판정 |
|---:|---:|---:|---|
| 512 | 4,054 | 3,338 | 제외 |
| 1,024 | 2 | 2 | 95% 기준은 충족하지만 response 손실 존재 |
| 1,536 | 0 | 0 | 선택 |
| 2,048 | 0 | 0 | 불필요한 초기 메모리 증가 |

[확정] 초기 `max_seq_length`는 1,536이다. 전체 11,661행을 보존하면서 2,048보다 메모리
부담이 낮다.

## Tokenized Dataset

- Run ID: `DOHALM-TOKENIZATION-20260730-0001`
- 외부 위치: `<processed_root>/tokenized/AIHUB-71748/DOHALM-TOKENIZATION-20260730-0001`
- Train: 10,374행 / 4,481,321 tokens
- Validation: 1,287행 / 568,893 tokens
- 전체: 11,661행 / 5,050,214 tokens / 65,808,053 bytes
- Dataset fingerprint: `b6848e9413ecd0f63008cf18f505dda0b3197e562b5c6a9f955c1a7d41bc98a0`
- Artifact fingerprint: `f626e00c2c4cfc065623f857e4655865f793fc8781a319200bc81bb0489d6045`
- Tokenizer fingerprint: `ad0a85da869c2e4577b9409df0c91e35be70f0395a20c94765c6f4fa02ea6a55`
- Config fingerprint: `5d6358d30bfea5891d3c02beaf12e6896f8c9881e2aa361cb1f07cf5947f13db`

[확정] 전체 reload 검증에서 invalid sequence, empty label, token range, prompt mask, EOS 오류는
모두 0건이다. 내부 decode sample 10건과 deterministic sample 재계산이 통과했다. 원문은 보고서나
Git 산출물에 출력하지 않았다.

## QLoRA 준비

[확정] 설정은 4-bit NF4, double quantization, BF16 compute, LoRA `r=16`, `alpha=32`,
`dropout=0.05`이며 attention과 MLP projection을 대상으로 한다. 3 epochs, micro batch 1,
gradient accumulation 16 기준 예상 optimizer step은 1,947이다. `eval_steps=100`,
`save_steps=250`, 최대 보존 checkpoint 2개로 설정했다.

[검증 필요] VRAM 5.0~7.5 GiB는 모델을 로드하지 않은 사전 추정치다. 실제 QLoRA 승인 후 별도
allocation smoke로 확인해야 한다.

## Fail Closed 상태

```yaml
tokenized_dataset: completed_and_validated
qlora_config: ready_not_approved
model_loaded: false
adapter_created: false
training_started: false
execution_allowed: false
```

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-30 | Run 0015 기반 Tokenization 완료, Qwen tokenizer 계약과 QLoRA 준비 설정 기록 |
