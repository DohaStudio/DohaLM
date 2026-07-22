# DohaLM 모델 아키텍처

- 문서 상태: `review`
- 마지막 검토일: 2026-07-23

## 1. 문서 목적과 현재 상태

- [확정] 이 문서는 `DohaLM-Tiny`의 구현 전 모델 구조, 텐서 shape 및 파라미터 산식을 정의한다.
- [확정] 모델은 PyTorch 기반 Decoder-only Transformer이며 핵심 구성요소를 직접 구현한다.
- [확정] 현재 저장소에는 실행 가능한 모델 구현이 없다. 아래 내용은 구현 완료 보고가 아니라 구현 기준이다.
- [검증 필요] `DohaLM-Small`의 상세 구조는 Tiny의 정확성, VRAM 및 처리량 실측 후 확정한다.

기존 범위 결정은 [범위와 목표](../project/scope-and-goals.md)와 [ADR-001](../decisions/ADR-001-initial-model-scope.md)을 따른다.

## 2. 기호

| 기호 | 의미 |
|---|---|
| `B` | micro-batch 크기 |
| `T` | 현재 sequence length, 모델 context 이하 |
| `V` | vocabulary size |
| `D` | hidden size |
| `H` | attention head 수 |
| `Dh` | head dimension, `D / H` |
| `F` | FFN intermediate size |
| `L` | Transformer block 수 |

## 3. DohaLM-Tiny 확정 설계

| 항목 | 값 | 상태 |
|---|---:|---|
| Transformer 형식 | Decoder-only | [확정] |
| Layer `L` | 6 | [확정] |
| Hidden Size `D` | 384 | [확정] |
| Attention Head `H` | 6 | [확정] |
| Head Dimension `Dh` | 64 | [확정] `384 / 6` |
| Context Length | 256 | [확정] |
| Vocabulary Size `V` | 16,000 | [확정] special token 포함 |
| 학습 계산 정밀도 | FP16 mixed precision | [확정] |
| FFN Size `F` | 1,536 | [확정] `4 × D` |
| 위치 표현 | 학습형 absolute positional embedding | [확정] |
| Block 순서 | Pre-LayerNorm | [확정] |
| FFN 활성화 | GELU | [확정] |
| Linear bias | 사용 | [확정] |
| LayerNorm affine | weight와 bias 사용 | [확정] |
| Embedding–LM Head | weight tying | [확정] |
| LM Head bias | 사용하지 않음 | [확정] |
| Dropout 확률 | 미정 | [검증 필요] 파라미터 수에는 영향 없음 |
| 초기화 방식 | 미정 | [검증 필요] 구현 전 확정 |

Pre-LayerNorm block은 다음 순서를 따른다.

1. `x = x + Attention(LayerNorm(x))`
2. `x = x + FFN(LayerNorm(x))`

마지막 block 뒤에 final LayerNorm을 적용한 후 tied LM Head로 logits를 계산한다.

## 4. 파라미터 수 산식

### 4.1 공통 산식

Linear bias와 LayerNorm affine을 포함하고 LM Head bias는 제외한다.

| 구성요소 | 파라미터 수 |
|---|---:|
| Token Embedding | `V × D` |
| Positional Embedding | `Context × D` |
| QKV projection weight+bias | `3D² + 3D` |
| Attention output projection weight+bias | `D² + D` |
| FFN 두 Linear weight+bias | `2DF + F + D` |
| Block 내 LayerNorm 2개 | `4D` |
| Transformer block 1개 | `4D² + 2DF + F + 9D` |
| Final LayerNorm | `2D` |
| LM Head | `0`개 추가: Token Embedding과 공유 |

따라서 전체 파라미터 수는 다음과 같다.

`P = VD + Context×D + L×(4D² + 2DF + F + 9D) + 2D`

### 4.2 DohaLM-Tiny 계산

`V=16,000`, `D=384`, `Context=256`, `L=6`, `F=1,536`을 대입한다.

| 구성요소 | 계산 | 파라미터 수 |
|---|---:|---:|
| Token Embedding | `16,000 × 384` | 6,144,000 |
| Positional Embedding | `256 × 384` | 98,304 |
| Attention/block | `4×384² + 4×384` | 591,360 |
| FFN/block | `2×384×1,536 + 1,536 + 384` | 1,181,568 |
| LayerNorm/block | `4×384` | 1,536 |
| Block 1개 | 위 세 항목의 합 | 1,774,464 |
| Block 6개 | `1,774,464 × 6` | 10,646,784 |
| Final LayerNorm | `2 × 384` | 768 |
| LM Head 추가분 | weight tying, bias 없음 | 0 |
| **합계** |  | **16,889,856** |

- [확정] 설계상 예상 파라미터는 `16,889,856`, 약 `16.89M`이다.
- [확정] 약 15M~25M 목표 범위 안에 있으므로 기존 확정값과 계산 충돌이 없다.
- [검증 필요] 구현 후 실제 `sum(p.numel())` 결과가 위 계산과 정확히 일치해야 한다.
- [검증 필요] weight tying을 제거하면 `6,144,000`개가 추가되어 `23,033,856`개가 된다. 현재 설계는 tying 사용이므로 이 값은 비교용이다.

### 4.3 DohaLM-Small 비구속 검토안

기존 문서에서 Small의 Layer, Hidden, Head 및 FFN은 Tiny 실측 전까지 미정이다. 따라서 다음 값은 사양 확정이 아닌 산식과 목표 범위 검증을 위한 `[가정]`이다.

| 항목 | 검토안 | 상태 |
|---|---:|---|
| Layer | 10 | [가정] |
| Hidden Size | 640 | [가정] |
| Attention Head | 10 | [가정] |
| Head Dimension | 64 | [가정] 계산 결과 |
| FFN Size | 2,560 | [가정] `4 × D` |
| Context Length | 512 | [가정] 확정 상한 사용 |
| Vocabulary Size | 16,000 | [가정] Tiny 토크나이저 재사용 시 |
| Weight tying / bias / norm | Tiny와 동일 | [가정] |

계산 결과는 다음과 같다.

| 구성요소 | 파라미터 수 |
|---|---:|
| Token Embedding | 10,240,000 |
| Positional Embedding | 327,680 |
| Block 1개 | 4,923,520 |
| Block 10개 | 49,235,200 |
| Final LayerNorm | 1,280 |
| **합계** | **59,804,160** |

- [가정] 검토안은 약 `59.80M`으로 Small 목표 약 50M~80M 안에 있다.
- [확정] 이 계산은 Small 사양을 확정하지 않는다.
- [검증 필요] Tiny 벤치마크 후 Layer, Hidden, Head, FFN, 실제 training sequence length와 정밀도를 결정하고 다시 계산한다.

## 5. 전체 텐서 shape

### 5.1 Embedding과 block 입출력

| 단계 | 입력 shape | 출력 shape | 설명 |
|---|---|---|---|
| Token IDs | - | `[B, T]` | 정수 token ID |
| Token Embedding | `[B, T]` | `[B, T, D]` | `D=384` |
| Position IDs | - | `[T]` 또는 `[B, T]` | `0..T-1` |
| Position Embedding | position IDs | `[T, D]` 또는 `[B, T, D]` | batch에 broadcast 가능 |
| Embedding 합 | 두 embedding | `[B, T, D]` | block 입력 `x` |
| Transformer Block | `[B, T, D]` | `[B, T, D]` | residual로 shape 유지 |
| Final LayerNorm | `[B, T, D]` | `[B, T, D]` | LM Head 직전 |
| LM Head | `[B, T, D]` | `[B, T, V]` | `V=16,000` |

### 5.2 Multi-Head Causal Self-Attention

| 단계 | 입력 shape | 출력 shape |
|---|---|---|
| QKV projection | `[B, T, D]` | `[B, T, 3D]` |
| Q, K, V 분리 | `[B, T, 3D]` | 각각 `[B, T, D]` |
| Head 분할·transpose | `[B, T, D]` | 각각 `[B, H, T, Dh]` |
| `Q @ Kᵀ / sqrt(Dh)` | Q, K | `[B, H, T, T]` |
| Causal mask 적용 | scores | `[B, H, T, T]` |
| Softmax | masked scores | `[B, H, T, T]` |
| Attention probability @ V | probabilities, V | `[B, H, T, Dh]` |
| Head 결합 | `[B, H, T, Dh]` | `[B, T, D]` |
| Output projection | `[B, T, D]` | `[B, T, D]` |

### 5.3 Feed-Forward Network

| 단계 | 입력 shape | 출력 shape |
|---|---|---|
| 첫 Linear | `[B, T, D]` | `[B, T, F]` |
| GELU | `[B, T, F]` | `[B, T, F]` |
| 두 번째 Linear | `[B, T, F]` | `[B, T, D]` |
| Residual 합 | 두 `[B, T, D]` | `[B, T, D]` |

## 6. Causal Mask 적용 위치

- [확정] causal mask는 scaled dot-product attention score `QKᵀ / sqrt(Dh)`를 계산한 직후, softmax 직전에 적용한다.
- [확정] 미래 위치 `j > i`의 score를 dtype에서 안전한 매우 작은 값으로 바꿔 softmax 확률이 0이 되게 한다.
- [확정] mask의 논리 shape은 `[T, T]`이며 `[1, 1, T, T]`로 확장해 `[B, H, T, T]`에 broadcast한다.
- [확정] padding이 있는 SFT batch에서는 causal mask와 key padding mask를 함께 적용한다.
- [확정] loss mask는 causal mask와 다른 개념이다. loss mask는 어떤 target token이 Cross-Entropy에 기여하는지를 정한다.
- [검증 필요] FP16에서 mask 값 선택 후 NaN이 발생하지 않는지 단위 테스트한다.

## 7. 학습 데이터 흐름

1. `[B, T+1]` 길이의 token sequence를 준비한다.
2. `input_ids = tokens[:, :-1]`, `labels = tokens[:, 1:]`로 나눠 각각 `[B, T]`로 만든다.
3. embedding과 6개 Transformer block을 거쳐 logits `[B, T, V]`를 계산한다.
4. logits를 `[B×T, V]`, labels를 `[B×T]`로 펼친다.
5. padding 또는 SFT prompt처럼 제외할 label은 `ignore_index`로 표시한다.
6. Cross-Entropy loss scalar를 계산하고 FP16 mixed precision 규칙에 따라 역전파한다.

- [확정] target shift는 dataloader 또는 trainer 중 한 곳에서만 수행해 이중 shift를 방지한다.
- [검증 필요] 정확한 책임 위치는 구현 전에 dataloader 인터페이스와 함께 확정한다.

## 8. 추론 데이터 흐름

1. prompt를 토큰화해 `input_ids [B, T]`를 만든다.
2. 모델이 logits `[B, T, V]`를 출력한다.
3. 마지막 위치 `logits[:, -1, :]`에서 다음 token을 선택한다.
4. 선택 token을 `input_ids` 뒤에 붙이고 EOS, 대화 종료 token 또는 최대 생성 길이까지 반복한다.
5. 생성 token을 SentencePiece로 decode한다.

- [확정] 학습은 모든 위치의 다음 token loss를 병렬 계산하지만, 추론은 새 token을 순차 생성한다.
- [가정] 최초 구현은 정확성 검증을 위해 prefix 전체를 매 step 다시 계산할 수 있다.
- [후순위] KV cache를 추가하면 layer별 K/V shape은 각각 `[B, H, T_cached, Dh]`이며 정확성 비교 테스트가 필요하다.
- [검증 필요] sampling, EOS 처리 및 KV cache 정책은 `11-inference-design.md`에서 확정한다.

## 9. 구현 전 필수 검증

- [검증 필요] 파라미터 수 `16,889,856` 일치
- [검증 필요] 각 모듈의 입력·출력 shape와 residual shape 일치
- [검증 필요] 미래 token 변경이 이전 위치 logits에 영향을 주지 않는 causal mask 테스트
- [검증 필요] tied weight가 실제로 같은 parameter storage를 참조하는지 확인
- [검증 필요] FP16 순전파·역전파에서 NaN/Inf가 없는지 확인
- [검증 필요] 작은 데이터 과적합과 checkpoint round-trip 통과

## 10. 검토 필요 사항

- [검증 필요] Dropout 확률과 초기화 방식
- [검증 필요] Small 검토안의 실제 채택 여부
- [검증 필요] padding mask의 구체적 자료형과 broadcast 규칙
- [검증 필요] KV cache 구현 시 position ID와 최대 context 처리
