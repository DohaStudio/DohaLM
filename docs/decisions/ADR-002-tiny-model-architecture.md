# ADR-002: DohaLM-Tiny 모델 아키텍처

- 문서 상태: `approved`
- 결정일: 2026-07-23
- 구현 상태: [검증 필요] 미구현
- 선행 결정: [ADR-001: 초기 모델 범위](./ADR-001-initial-model-scope.md)
- 기준 설계: [DohaLM 모델 아키텍처](../04-model-architecture.md)

## 결정 배경

ADR-001은 전체 파이프라인 검증을 위해 `DohaLM-Tiny`를 먼저 개발하고 Layer 6, Hidden Size 384, Attention Head 6, Context Length 256, Vocabulary Size 16,000, FP16을 사용하기로 결정했다. 이후 구현 전에 FFN 크기, 정규화 순서, 위치 표현, bias 및 LM Head 구조를 고정하고 예상 파라미터 수를 확인할 필요가 생겼다.

- [확정] 이 ADR은 ADR-001의 모델 범위를 변경하지 않고 당시 미정이던 Tiny 세부 구조를 후속 결정한다.
- [확정] 핵심 모델은 PyTorch로 직접 구현하는 Decoder-only Transformer다.
- [확정] Hugging Face 완성형 GPT 모델 클래스를 핵심 구현으로 사용하지 않는다.

## RTX 3060 Ti 8GB 제약

- [확정] 기준 장비는 단일 `RTX 3060 Ti 8GB`다.
- [확정] 모델 parameter 외에도 gradient, optimizer state, activation, attention 중간 tensor, logits 및 CUDA runtime이 VRAM을 사용한다.
- [확정] FP16 mixed precision을 기준 계산 정밀도로 사용한다.
- [확정] 약 15M~25M 범위 안에서 모델 용량과 반복 가능한 개발 속도를 함께 고려한다.
- [검증 필요] 실제 micro-batch, Gradient Accumulation 횟수, Gradient Checkpointing 기본값과 peak VRAM은 구현 후 측정한다.

## 고려한 모델 대안

| 결정 지점 | 고려한 대안 | 판단 |
|---|---|---|
| FFN Size | `4×D`, 더 작거나 큰 배율 | [확정] 단순하고 계산이 명확한 `4×D=1,536` 채택 |
| Block 정규화 | Pre-LayerNorm, Post-LayerNorm | [확정] Pre-LayerNorm 채택 |
| 위치 표현 | 학습형 absolute, sinusoidal, RoPE | [확정] 학습형 absolute positional embedding 채택 |
| LM Head | 입력 embedding과 공유, 별도 weight | [확정] weight tying 채택 |
| Linear bias | 사용, 미사용 | [확정] Attention과 FFN Linear에 bias 사용 |
| LM Head bias | 사용, 미사용 | [확정] 미사용 |
| Small 검토안 즉시 채택 | Tiny 우선, Small 동시 확정 | [제외] Small 상세 구조는 Tiny 실측 전 확정하지 않음 |

## 최종 Tiny 구조

| 항목 | 결정 | 상태 |
|---|---:|---|
| 모델 형식 | Decoder-only Transformer | [확정] |
| Transformer Layer | 6 | [확정] |
| Hidden Size | 384 | [확정] |
| Attention Head | 6 | [확정] |
| Head Dimension | 64 | [확정] |
| Context Length | 256 | [확정] |
| Vocabulary Size | 16,000 | [확정] |
| FFN Size | 1,536 | [확정] |
| 정규화 순서 | Pre-LayerNorm | [확정] |
| 위치 표현 | 학습형 absolute positional embedding | [확정] |
| Linear bias | 사용 | [확정] |
| LayerNorm affine | weight와 bias 사용 | [확정] |
| Token Embedding–LM Head | weight tying | [확정] |
| LM Head bias | 미사용 | [확정] |
| 학습 계산 정밀도 | FP16 mixed precision | [확정] |
| 예상 파라미터 수 | 16,889,856 | [확정] 설계 산식 기준 |

- [검증 필요] Dropout 확률과 파라미터 초기화 방식은 아직 결정하지 않았다.
- [검증 필요] 구현 후 실제 parameter count와 구조를 자동 테스트로 확인한다.

## 파라미터 계산 요약

| 구성요소 | 파라미터 수 |
|---|---:|
| Token Embedding | 6,144,000 |
| Positional Embedding | 98,304 |
| Transformer Block 6개 | 10,646,784 |
| Final LayerNorm | 768 |
| LM Head 추가분 | 0 |
| **합계** | **16,889,856** |

- [확정] 약 `16.89M`으로 목표 약 15M~25M 범위 안에 있다.
- [확정] 정확한 공통 산식과 bias 포함 범위는 [모델 아키텍처의 파라미터 수 산식](../04-model-architecture.md#4-파라미터-수-산식)을 단일 기준으로 사용한다.
- [검증 필요] 문서 산식은 구현 결과를 대신하지 않으며 `sum(p.numel())`로 검증해야 한다.

## Weight tying을 채택한 이유

- [확정] Token Embedding과 LM Head가 같은 vocabulary 표현을 공유하게 한다.
- [확정] 별도 LM Head weight를 둘 때 필요한 `16,000×384=6,144,000`개의 추가 parameter를 제거한다.
- [확정] Tiny의 파라미터 수와 checkpoint payload를 줄여 제한된 환경에서 반복하기 쉽다.
- [검증 필요] 실제 weight가 동일한 parameter storage를 참조하는지 구현 테스트가 필요하다.

## Pre-LayerNorm을 채택한 이유

- [확정] 각 Attention과 FFN sublayer 입력을 정규화하고 residual 경로를 직접 유지하는 구조를 사용한다.
- [가정] 랜덤 초기화 사전학습의 초기 최적화 안정성에 유리할 것으로 기대한다.
- [확정] block 계산 순서는 `x + Attention(LN(x))`, 이어서 `x + FFN(LN(x))`다.
- [검증 필요] FP16에서 gradient와 loss 안정성을 작은 데이터 과적합 및 pilot 학습으로 확인한다.

## 학습형 위치 임베딩을 채택한 이유

- [확정] Context Length 256의 고정된 Tiny 범위에서 구현과 파라미터 계산이 단순하고 명시적이다.
- [확정] Token Embedding과 동일한 hidden shape로 더해져 직접 구현과 shape 테스트가 쉽다.
- [가정] 파이프라인 검증이 우선인 Tiny 단계에 적합하다.
- [확정] 학습한 최대 위치를 넘어서는 외삽을 보장하지 않으며 Tiny 입력은 256 token을 넘지 않는다.

## Linear bias를 사용하는 이유

- [확정] Attention과 FFN projection의 affine 변환을 명시적으로 구현해 교육·검증 목적의 구조를 분명히 한다.
- [확정] bias를 포함한 산식과 구현 parameter count를 직접 대조할 수 있다.
- [가정] Tiny 규모에서 bias parameter 증가보다 구현 명확성을 우선한다.
- [확정] LM Head에는 별도 bias를 두지 않아 tied output 구조를 단순화한다.

## 장점

- [확정] 기존 Tiny 목표 범위 안에서 정확한 parameter count를 제공한다.
- [확정] Head Dimension 64와 FFN `4×D`로 tensor shape가 단순하다.
- [확정] weight tying으로 중복 output weight를 제거한다.
- [확정] Pre-LayerNorm으로 residual 경로와 정규화 위치가 명확하다.
- [확정] 고정 Context 256과 학습형 위치 embedding으로 MVP 구현 범위를 통제한다.

## 단점

- [확정] 학습형 absolute positional embedding은 학습한 context 밖으로 자연스럽게 확장되지 않는다.
- [확정] weight tying은 입력과 출력 표현을 독립적으로 학습할 자유도를 줄인다.
- [확정] Linear bias는 bias-free 구조보다 parameter와 연산을 소폭 늘린다.
- [검증 필요] Pre-LayerNorm과 선택 구조가 실제 한국어 생성 품질에 미치는 영향은 학습 전 알 수 없다.
- [검증 필요] Dropout과 초기화가 미정이므로 완전한 학습 설정은 아직 아니다.

## 구현에 미치는 영향

- [확정] 모델 config는 이 ADR의 구조 필드를 단일 객체로 관리해야 한다.
- [확정] Token Embedding, Positional Embedding, Pre-LN block 6개, final LayerNorm과 tied LM Head를 구현해야 한다.
- [확정] Attention과 FFN Linear는 bias를 포함하고 LM Head는 bias를 포함하지 않아야 한다.
- [확정] causal mask, shape, parameter count, weight alias, FP16 forward/backward를 테스트해야 한다.
- [확정] `DohaLM-Small` 비구속 검토안을 Tiny 구현에 섞지 않는다.

## 체크포인트 호환성에 미치는 영향

- [확정] checkpoint에는 전체 model config와 architecture/version 식별자를 저장해야 한다.
- [확정] Layer, Hidden, Head, FFN, Context, Vocabulary, bias, normalization 순서 또는 weight tying이 다른 checkpoint는 자동 호환으로 간주하지 않는다.
- [확정] load 후 Token Embedding과 LM Head의 weight alias가 유지되는지 확인한다.
- [확정] weight tying을 해제하거나 LM Head bias를 추가하면 state key·shape·parameter count가 달라질 수 있으므로 migration 또는 명시적 비호환 처리가 필요하다.
- [검증 필요] 초기화 방식이 확정되면 신규 checkpoint 생성과 복원 테스트에 해당 정보를 추가한다.

## 재검토 조건

- [검증 필요] 구현 parameter count가 `16,889,856`과 일치하지 않는다.
- [검증 필요] 작은 데이터 과적합 또는 causal mask·weight tying 검증에 실패한다.
- [검증 필요] FP16에서 반복적인 NaN/Inf가 발생한다.
- [검증 필요] OOM 대응 절차 후에도 Tiny가 `RTX 3060 Ti 8GB`에서 안정적으로 실행되지 않는다.
- [검증 필요] 학습형 위치 embedding 또는 weight tying이 측정 가능한 품질·호환성 문제를 만든다.
- [확정] 구조 변경 시 이 ADR을 조용히 수정하지 않고 후속 ADR에서 대체 또는 변경 범위를 기록한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] 2단계 모델 설계를 승인된 Tiny 구조 결정으로 기록함 |
