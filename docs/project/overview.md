# DohaLM Project Definition

- 문서 상태: `review`
- 마지막 검토일: 2026-08-05
- 기준 문서: [저장소 README](../../README.md)

## 1. 정의

DohaLM은 한국어 LLM 연구 결과를 재사용 가능한 모델·Runtime·통합 계약으로 제공하는 **LLM 모델 제공자**입니다.
최종 사용자용 UI나 도메인 비즈니스 로직은 이 저장소의 제품 범위가 아닙니다.

```text
project_definition: reusable_llm_model_provider
```

## 2. 공식 제공물

1. Foundation Model
2. fine-tuned model, Adapter 또는 merged model
3. inference runtime
4. REST·Streaming API
5. Python SDK
6. Model Manifest와 versioning
7. Integration Guide

각 산출물의 현재 상태는 [Current Project Status](./current-project-status.md), 범위와 완료 조건은
[범위와 목표](./scope-and-goals.md)를 따릅니다.

## 3. 저장소 책임 경계

| DohaLM 소유 | 외부 소비자 프로젝트 소유 |
|---|---|
| 모델 학습·평가·선정 | 최종 사용자 UI |
| 모델·Adapter 로딩과 추론 | 도메인 비즈니스 로직 |
| streaming과 prompt 처리 | 사용자 workflow와 프로젝트 데이터 |
| manifest·versioning·호환성 | DohaLM API·SDK 통합 |

DohaMusic, DohaWriter와 DohaCode는 별도 저장소의 소비자입니다. 첫 Reference Application인 DohaMusic의 상세 경계는
[Reference Applications](./domain-model-strategy.md)에 정의합니다.

## 4. Phase 관계

- Phase 1은 Dataset부터 Foundation Base까지 직접 구현 모델 연구를 수행합니다.
- Phase 2는 Qwen 계보를 포함할 수 있는 재사용 모델 artifact와 Runtime을 만듭니다.
- Phase 3는 Runtime을 REST·Streaming·SDK·Integration Guide와 versioned release로 배포합니다.
- Phase 1과 Phase 2는 계보가 다른 병행 가능 트랙이며, 현재 우선순위만 Phase 1입니다.
- Reference Application은 저장소 밖에서 Phase 3 인터페이스를 검증합니다.

세부 흐름은 [Roadmap](./model-family-roadmap.md)을 따릅니다.

## 5. 비목표

- ChatGPT 대체 또는 상용 수준 범용 챗봇 보장
- 7B 이상 모델의 from-scratch pretraining
- Cloud·Kubernetes 운영 배포
- DohaMusic UI·음악 비즈니스 로직·오디오·MIDI 생성
- 별도 승인 없는 model·checkpoint·dataset·Adapter 공개

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | 프로젝트를 reusable LLM model provider로 정의하고 산출물·소비자·Phase 경계 재정렬 |
| 2026-08-04 | 초기 목적과 구현 상태 동기화 |
