# 모델 영역 작업 규칙

루트 `AGENTS.md`, [모델 아키텍처](../../docs/04-model-architecture.md), ADR-002를 함께 적용한다.

## DohaLM-Tiny 승인 사양

- 구조: Decoder-only Transformer
- Transformer Layer: 6
- Hidden Size: 384
- Attention Head: 6
- Head Dimension: 64
- FFN Size: 1,536
- Context Length: 256
- Vocabulary Size: 16,000
- Normalization: Pre-LayerNorm
- Position Embedding: 학습형 absolute positional embedding
- Linear bias: 사용
- LM Head bias: 미사용
- Token Embedding–LM Head weight tying: 사용
- Precision: FP16 mixed precision
- 예상 파라미터 수: 16,889,856

## 구현과 검증

- 승인 사양을 임의 변경하지 않으며 구조·수치 변경에는 후속 ADR이 필요하다.
- Dropout 확률과 파라미터 초기화 방식은 `[검증 필요]`이므로 임의로 결정하지 않는다.
- 각 구성요소와 통합 경로의 input/output shape, dtype, device를 코드와 테스트에 명시한다.
- causal mask 적용 위치·shape·broadcast와 미래 정보 차단을 테스트한다.
- 실제 파라미터 수가 16,889,856과 일치하는지 자동 테스트한다.
- embedding과 LM Head가 같은 parameter storage를 사용하는지 weight tying을 테스트한다.
- 정상·경계 입력의 forward와 finite gradient를 포함한 backward를 테스트한다.
- 잘못된 shape, token ID, context length와 config에는 명시적으로 실패한다.
- 학습 경로와 추론 경로의 계약을 구분한다.
- Hugging Face 등 외부 완성형 GPT 모델 클래스로 핵심 구현을 대체하지 않는다.
