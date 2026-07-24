# DohaLM-Tiny 모델 구성요소 구현

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-24 |
| 선행 문서 | [모델 아키텍처](./model-architecture.md), [핵심 개발 기능명세서](./core-development-feature-specification.md), [ADR-002](../decisions/ADR-002-tiny-model-architecture.md) |
| 후속 문서·작업 | [Phase 4 전체 모델 통합](./model-integration.md), [통합 테스트](../quality/model-integration-testing.md), Gate 4 승인 기록 |
| 구현 전 필수 여부 | 구성요소 소비·통합 전 예 |

- [확정] 이 문서는 Phase 3 Decoder-only Transformer 구성요소 구현을 설명한다.
- [제외] 이 Phase 3 문서 범위에는 전체 6-layer forward, final loss와 generation이 포함되지 않는다. 해당 구현은 [Phase 4 문서](./model-integration.md)에 분리하며 trainer, checkpoint manager와 학습은 여전히 미구현이다.
- [확정] Hugging Face 완성형 GPT 모델 없이 PyTorch 구성요소를 직접 구현했다.

## 2. 구현 구성요소

| 구성요소 | 구현 symbol | 입력 | 출력 |
|---|---|---|---|
| Config | `ModelConfig` | 명시 설정 또는 Tiny 기본값 | immutable validated config |
| Token Embedding | `TokenEmbedding` | token IDs `[B,S]` long | `[B,S,H]` |
| Learned Position | `LearnedPositionEmbedding` | token IDs shape | position `0..S-1`, `[B,S,H]` |
| LayerNorm | `LayerNorm` | floating `[...,H]` | 동일 shape·dtype |
| Attention | `CausalMultiHeadAttention` | `[B,S,H]`, padding mask 후보 | `[B,S,H]` |
| FFN | `FeedForward` | `[B,S,H]` | `[B,S,H]` |
| Decoder Block | `TransformerBlock` | `[B,S,H]`, mask | `[B,S,H]` |
| LM Head | `LMHead` | `[B,S,H]` | `[B,S,V]` |
| Parameter Count | `ParameterCounter` | `nn.Module` | 전체·trainable·module별·tied 제외 수 |

## 3. ModelConfig

승인 Tiny 값은 vocabulary 16,000, context 256, layer 6, hidden 384, head 6, head dimension 64, FFN 1,536이다. `hidden_size % num_heads == 0`, head dimension 일치, 양의 크기, vocabulary가 8개 special token보다 큼, dropout 범위와 Tiny bias·tying 불변조건을 검사한다.

- [가정] 구성요소 smoke 기본 `dropout=0.0`은 결정론적 단위 검증을 위한 후보이며 학습 설정 승인이 아니다.
- [가정] `layer_norm_eps=1e-5`는 구성요소 smoke 후보다. 전체 모델·학습 설정 전에 재검토할 수 있다.
- [검증 필요] DohaLM 초기화 정책은 `None`으로 유지한다. PyTorch module 생성자의 기본 초기화 외에 GPT-2 초기화나 별도 정책을 적용하지 않았다.

## 4. Embedding과 LayerNorm

Token Embedding은 rank 2, `torch.long`, vocabulary 범위, context 길이와 device 일치를 확인한다. Position Embedding은 입력 shape에서 `0..S-1`을 같은 device에 자동 생성하고 batch로 broadcast한다.

LayerNorm은 마지막 hidden 차원의 평균과 분산을 직접 계산하며 affine weight·bias를 갖는다. FP16/BF16 통계는 float32에서 계산한 뒤 입력 dtype으로 되돌려 shape·gradient를 보존한다. Block은 반드시 Pre-LayerNorm을 사용한다.

## 5. Causal Multi-Head Attention

QKV projection은 `[B,S,384] → [B,S,1,152]`이고 head 분할 후 Q/K/V는 각각 `[B,6,S,64]`다. `QKᵀ/sqrt(64)` 직후, softmax 직전에 `[1,1,S,S]` causal boolean mask를 적용한다.

- [확정] 미래 위치 `j>i`는 score를 dtype의 최소 유한값으로 치환한다.
- [확정] 테스트는 mask shape만 보지 않고 미래 hidden state를 변경해도 이전 위치 attention·block 출력이 불변인지 확인한다.
- [가정] padding mask는 현재 `[B,S]` boolean이며 `True`가 유효 token이다. 잘못된 rank·shape·dtype·device는 실패한다.
- [확정] padding key를 attention에서 제외하고 padding query의 attention branch 출력은 0으로 만든다.

## 6. FFN과 Transformer Block

FFN은 `384 → 1,536 → 384`, GELU, 두 Linear bias와 후보 dropout을 사용한다. Block 순서는 다음과 같다.

1. `x = x + Attention(LayerNorm(x))`
2. `x = x + FeedForward(LayerNorm(x))`

Block은 입력 shape를 유지하고 CPU·CUDA backward에서 finite gradient를 생성해야 한다. eval mode에서는 동일 입력에 결정론적 결과를 반환한다.

## 7. LM Head와 Weight Tying

LM Head는 bias 없는 `384 → 16,000` projection이다. 생성자 또는 `tie_weights()`로 외부 `TokenEmbedding`을 연결하며 shape가 다르면 실패한다. Tying은 값을 복사하지 않고 동일 `Parameter` 객체와 storage를 참조한다.

## 8. Parameter Count

`ParameterCounter`는 동일 Parameter 객체를 한 번만 집계하고 total, trainable, leaf module별 수와 제외된 tied reference 크기를 반환한다. 구성요소-only container에서 다음을 확인했다.

| 항목 | 결과 |
|---|---:|
| 전체·trainable | 16,889,856 |
| tied LM Head 중복 제외 | 6,144,000 |
| Attention/block | 591,360 |
| FFN/block | 1,181,568 |
| LayerNorm 2개/block | 1,536 |
| Block 1개 | 1,774,464 |

- [확정] 구현 구성요소 집계는 ADR-002 산식과 일치한다.
- [확정] Phase 4 실제 통합 모델 객체에서도 `16,889,856`과 alias를 재검증했다.

## 9. 오류와 상태 경계

Config 불변조건, 잘못된 rank·dtype·device·token 범위·context 초과·mask shape/dtype·hidden shape·tying mismatch는 명시적으로 실패한다. 자동 dtype 변환, token clamp, sequence truncation 또는 mask broadcast fallback은 하지 않는다.

Gate 4는 통합 evidence와 2026-07-24 사용자 승인으로 `passed`다. Gate 3은 `planned`이며, Gate 4 통과는 tokenizer 승인이나 실제 데이터 연결을 의미하지 않는다.

## 10. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-24 | [확정] Phase 4 통합 count·alias 재검증 결과와 후속 문서 링크를 반영함 |
| 2026-07-24 | [확정] Phase 3 구성요소 구현, 16,889,856 parameter 집계와 CPU·CUDA 단위 검증 범위를 기록함 |
