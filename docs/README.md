# DohaLM 문서 안내서

- 문서 상태: `review`
- 마지막 검토일: 2026-08-05
- 기준 문서: [저장소 README](../README.md)
- 전체 목록: [문서 인덱스](./index.md)

## 1. 공식 읽기 순서

```text
README
  → Project Definition
  → Foundation Strategy
  → Current Status
  → Foundation Readiness
  → Reusable Model Strategy
  → Runtime
  → Distribution and Integration
  → Reference Applications
  → Roadmap
```

1. [README](../README.md): reusable LLM model provider 정의와 공식 Phase
2. [Project Definition](./project/overview.md): 산출물·소비자·저장소 책임
3. [Foundation Strategy](./project/foundation-model-strategy.md): Candidate B/C와 Foundation Instruct 연구 계보
4. [Current Status](./project/current-project-status.md): 코드·synthetic·실제 artifact 상태 분리
5. [Foundation Readiness](./training/base-training-readiness.md): Candidate C 진입 조건과 blocker
6. [Reusable Model Strategy](./project/reusable-model-strategy.md): Qwen 계보 model artifact와 Runtime
7. [Runtime](./service/dohalm-backend-mvp.md): provider와 local inference 계약
8. [Distribution and Integration](./project/distribution-and-integration.md): REST·Streaming·SDK·Guide·release
9. [Reference Applications](./project/domain-model-strategy.md): 별도 저장소의 DohaMusic 등 소비자
10. [Roadmap](./project/model-family-roadmap.md): 비직렬 Phase 관계와 다음 작업

## 2. Phase와 진입점

| 분류 | 범위 | 우선 문서 |
|---|---|---|
| Phase 1 — Foundation Model Development | Dataset, Tokenizer, Tiny, Base pretraining, Evaluation, Foundation Base | [Foundation Strategy](./project/foundation-model-strategy.md), [Evaluation](./evaluation/README.md) |
| Phase 2 — Reusable Model and Runtime | Qwen SFT, Adapter·merged model, evaluation, versioned model, Runtime | [Reusable Model Strategy](./project/reusable-model-strategy.md), [Instruct](./instruct/instruct-strategy.md), [Adapter Runtime](./service/dohalm-adapter-runtime.md) |
| Phase 3 — Distribution and Integration | REST·Streaming, Python SDK, Integration Guide, local release | [Distribution and Integration](./project/distribution-and-integration.md), [Backend](./service/dohalm-backend-mvp.md) |
| Reference Applications | 별도 저장소의 DohaMusic·DohaWriter·DohaCode | [Reference Applications](./project/domain-model-strategy.md) |

현재 우선순위는 Phase 1이지만 Phase 2는 Qwen 기반 별도 계보로 병행할 수 있습니다. Phase 3는 승인된 Phase 2 model·Runtime을
노출하며, Reference Application은 저장소 밖에서 API·SDK를 소비합니다.

## 3. 핵심 상태 경계

- Candidate B는 current Foundation Base baseline입니다.
- Candidate C contract design은 완료됐지만 execution은 blocked·false·not_started입니다.
- EOS-DIAG-R1/R2는 synthetic 검증됐고 실제 Candidate B identity와 진단 Gate 1·2는 미완료입니다.
- General Instruct Adapter는 eligible candidate가 없으며 actual Adapter Runtime은 unavailable입니다.
- REST·Streaming MVP는 구현됐고 Python SDK는 `not_started`, versioned release는 `planned`입니다.
- DohaMusic은 `planned, separate repository`인 첫 Reference Application입니다.
- Cloud deployment는 `out_of_scope`입니다.

## 4. 거버넌스와 품질

- [ADR 인덱스](./decisions/README.md)
- [Definition of Ready](./governance/definition-of-ready.md)
- [Definition of Done](./governance/definition-of-done.md)
- [테스트 전략](./quality/test-strategy.md)
- [테스트 체크리스트](./quality/testing-checklist.md)

문서 생명주기 상태와 구현 상태를 혼합하지 않습니다. 승인 ADR과 일반 문서가 충돌하면 승인된 최신 ADR을 우선하며,
Candidate C·Foundation Instruct의 후속 방향은 기존 ADR을 소급 수정하지 않고 별도 결정으로 처리합니다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | Project Definition부터 Roadmap까지 공식 연결과 세 Phase·외부 Reference Application 분류 반영 |
