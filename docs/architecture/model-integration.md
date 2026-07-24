# DohaLM-Tiny 전체 모델 통합

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-24 |
| 선행 문서 | [모델 아키텍처](./model-architecture.md), [모델 구성요소](./model-components.md), [핵심 개발 기능명세서](./core-development-feature-specification.md), [ADR-002](../decisions/ADR-002-tiny-model-architecture.md) |
| 후속 문서·작업 | [통합 테스트](../quality/model-integration-testing.md), Gate 5 사용자 검토, Phase 5 학습 기반 |
| 구현 전 필수 여부 | Phase 5 전 예 |

- [확정] Phase 4에서 Phase 3 구성요소를 `DohaLMTiny` 전체 forward로 조립하고 shifted causal loss와 최소 greedy generation을 구현했다.
- [제외] Trainer, optimizer, scheduler, checkpoint manager, resume와 실제 학습은 구현하지 않았다.
- [제외] 실제 tokenizer artifact와 corpus는 연결하지 않았으며 합성 token ID만 사용했다.

## 2. 전체 구조와 Forward

```text
input_ids [B,S]
→ TokenEmbedding + LearnedPositionEmbedding
→ embedding dropout
→ TransformerBlock × 6
→ final LayerNorm
→ tied LM Head
→ logits [B,S,16000]
```

`forward()`는 필수 `input_ids [B,S]`와 선택 `attention_mask [B,S]`, `labels [B,S]`, `return_hidden_states`, `ignore_index`를 받는다. ID와 labels는 `torch.long`, attention mask는 `torch.bool`이며 모든 관련 tensor는 같은 device에 있어야 한다. 잘못된 rank·dtype·shape·device·token 범위와 context 초과는 조용히 보정하지 않고 명시적으로 실패한다.

- [확정] labels가 없으면 `DohaLMOutput.loss`는 `None`이다.
- [확정] labels가 있으면 logits와 loss scalar를 함께 반환한다.
- [확정] logits는 입력 batch·sequence와 device를 보존한다.
- [가정] `dropout=0.0`, `layer_norm_eps=1e-5`는 smoke 기본 후보이며 학습 설정 승인이 아니다.

## 3. Weight Tying과 파라미터 수

Token embedding과 LM Head는 값 복사가 아니라 동일 `Parameter` 객체를 공유한다. `ParameterCounter`는 객체 identity 기준으로 중복을 제외한다.

| 구성 | 고유 파라미터 |
|---|---:|
| Token Embedding | 6,144,000 |
| Learned Position Embedding | 98,304 |
| Transformer Block 6개 | 10,646,784 |
| Final LayerNorm | 768 |
| LM Head 고유 추가분 | 0 |
| 합계·trainable | 16,889,856 |
| tied reference 크기 | 6,144,000 |

- [확정] 실제 통합 객체의 고유 파라미터 수는 승인 산식 `16,889,856`과 정확히 일치한다.
- [확정] LM Head weight는 token embedding weight와 동일 객체·storage다.

## 4. Shifted Causal Language Modeling Loss

Loss 함수는 모델 출력 전체에서 다음 한 번의 shift를 수행한다.

```text
prediction = logits[:, :-1, :]
target     = labels[:, 1:]
```

기본 `ignore_index=-100`이며 그 외 음수 label이나 vocabulary 밖 label은 거부한다. sequence 길이 1과 shift 후 유효 target이 하나도 없는 경우 각각 `SEQUENCE_TOO_SHORT_FOR_LOSS`, `ALL_LABELS_IGNORED`로 실패한다. Flatten 전 contiguous tensor를 만들고 PyTorch Cross-Entropy를 사용한다.

- [확정] `labels=input_ids` 사용을 지원한다.
- [확정] 수동 계산과 일치하고 CPU·CUDA backward에서 finite gradient를 확인했다.
- [검증 필요] DataLoader 또는 trainer와의 shift 책임 경계는 Phase 5에서 이중 shift가 없도록 확정한다.

## 5. Hidden States

기본값은 메모리 절약을 위해 `hidden_states=None`이다. 요청 시 embedding 출력, 각 block 출력, final LayerNorm 출력을 tuple로 반환하므로 기본 Tiny에서는 총 8개 snapshot이다. 이 옵션은 관측·테스트용이며 학습 기본 활성화 정책이 아니다.

## 6. 최소 Greedy Generation

Generation은 매 step 전체 prefix를 다시 forward하고 마지막 logits의 `argmax`를 append한다. `eval()`과 `torch.no_grad()`를 사용한 뒤 원래 train/eval mode를 복원한다.

- [확정] batch, 선택 EOS와 attention mask를 지원한다.
- [확정] batch 일부가 먼저 EOS에 도달하면 직사각형 tensor를 유지하기 위해 해당 행에 EOS를 반복하며, 모든 행이 끝나면 조기 종료한다.
- [확정] `prompt_length + max_new_tokens <= context_length`를 실행 전에 요구한다. 자동 truncation은 없다.
- [제외] sampling, temperature, top-k, top-p, beam search, KV cache, streaming과 repetition penalty는 구현하지 않았다.
- [검증 필요] 무작위 초기 모델의 생성 token은 기능 검증일 뿐 언어 품질 근거가 아니다.

## 7. State Dict 경계

`state_dict_with_config()`와 `load_state_dict_with_config()`는 config 일치, strict key 검사, CPU tensor snapshot과 load 후 re-tying을 검증하기 위한 메모리 내 helper다. 동일 입력 logits round-trip, missing/unexpected key 오류, CPU snapshot의 CUDA load를 확인했다.

- [확정] 이 helper는 파일 저장, checksum, atomic publish, optimizer·RNG state 또는 resume를 제공하는 checkpoint manager가 아니다.
- [검증 필요] 영속 checkpoint schema와 호환성 정책은 Phase 5에서 구현한다.

## 8. 초기화와 Gate 경계

- [확정] 별도 GPT-2 초기화를 도입하지 않았고 현재 PyTorch module 기본 초기화를 사용한다.
- [검증 필요] 프로젝트 초기화 정책은 여전히 미정이다.
- [확정] 같은 seed는 같은 초기 weight, 다른 seed는 다른 weight를 만들며 NaN·Inf가 없음을 검증했다.
- [확정] embedding에 임의 `padding_idx`를 도입하지 않았다.
- [확정] Gate 3, Gate 4, Gate 5는 모두 `planned`를 유지한다. 구현·테스트 통과는 사용자 Gate 승인을 대신하지 않는다.

## 9. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-24 | [확정] 전체 forward, shifted loss, greedy generation, state round-trip와 정확한 parameter count 구현 경계를 기록함 |
