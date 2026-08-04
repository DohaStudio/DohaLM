# DohaLM 문서 안내서

- 문서 상태: `review`
- 마지막 검토일: 2026-08-04
- 기준 문서: [저장소 README](../README.md)
- 전체 목록: [문서 인덱스](./index.md)

## 1. 문서 역할과 읽기 순서

프로젝트의 범위·우선순위는 루트 README를 기준으로 합니다. 중복된 상태 설명 대신 다음 순서로 읽습니다.

```text
README
  → Foundation Model Strategy
  → Current Project Status
  → Roadmap
  → Service 문서
```

1. [README](../README.md): 두 트랙, 1·2·3차 목표와 제외 범위
2. [Foundation Model Strategy](./project/foundation-model-strategy.md): Foundation 연구와 Runtime/Application의 계보 경계
3. [Current Project Status](./project/current-project-status.md): 실제 코드·테스트·실측 기준 상태
4. [Roadmap](./project/model-family-roadmap.md): 남은 작업과 진입 순서
5. [FastAPI Runtime](./service/dohalm-backend-mvp.md), [Base Qwen Provider](./service/dohalm-base-qwen-provider.md), [Frontend](./service/dohalm-frontend-mvp.md): 현재 서비스 실행 계약

[Domain Model Strategy](./project/domain-model-strategy.md)는 DohaMusic과 장기 Domain 후보를,
[Instruct Strategy](./instruct/instruct-strategy.md)는 Candidate B 기반 Foundation Instruct와 Qwen 기반 Runtime Adapter를 구분합니다.

## 2. 트랙별 진입점

| 트랙 | 현재 범위 | 우선 문서 |
|---|---|---|
| Foundation Model | DohaLM-Tiny, Tokenizer, Candidate A/B, Evaluation Framework | [모델 아키텍처](./architecture/model-architecture.md), [Evaluation](./evaluation/README.md), [Model Lineage](./project/model-lineage.md) |
| Runtime 1차 | Qwen Base, General Instruct Adapter, Runtime, Loader, Chat API, Streaming, Prompt Engine | [Instruct 안내](./instruct/README.md), [FastAPI](./service/dohalm-backend-mvp.md), [Base Qwen](./service/dohalm-base-qwen-provider.md) |
| Runtime 2차 | Memory, RAG, Tool Calling, Agent | [Roadmap](./project/model-family-roadmap.md), [Tool Calling 전략](./instruct/tool-calling-strategy.md) |
| Application 3차 | DohaMusic, Lyrics Search, Style Analysis, Personal Music Adapter | [Domain Strategy](./project/domain-model-strategy.md) |

## 3. 상태 표기

문서 생명주기와 구현 상태를 혼합하지 않습니다.

| 문서 상태 | 의미 |
|---|---|
| `planned` | 파일이 없거나 작성 계획만 존재 |
| `draft` | 초안이며 핵심 미결정 사항 존재 |
| `review` | 필수 내용 작성 후 검토 중 |
| `approved` | 정책·결정 승인; 구현 완료 아님 |
| `implemented` | 승인 내용이 코드·설정·테스트에 반영·검증됨 |
| `deprecated` | 후속 문서나 결정으로 대체 |

본문 구현 상태는 README의 `implemented_verified`, `implemented_not_integrated`, `design_complete`, `planned`,
`out_of_scope`를 사용합니다. 문서가 `review`여도 본문 기능은 구현 완료일 수 있고, ADR이 `approved`여도 실행은 미완료일 수 있습니다.

## 4. 현재 핵심 경계

- Foundation Model Track의 Candidate B가 current Base baseline이고 Candidate A는 historical baseline입니다.
- ADR-010은 Candidate B 기반 Foundation Instruct 설계 승인이지 Qwen Adapter 실행 승인이 아닙니다.
- Runtime은 Base Qwen Chat·Streaming까지 로컬 검증됐지만 Adapter Loader는 placeholder입니다.
- Memory, RAG, Tool Calling, Agent와 DohaMusic은 계획 상태입니다.
- Docker, Kubernetes, Cloud와 운영 배포는 현재 범위 밖입니다.
- 실제 데이터, checkpoint, Adapter와 로컬 경로는 Git과 문서에 포함하지 않습니다.

## 5. 거버넌스와 품질

- [ADR 인덱스](./decisions/README.md)
- [개발 규칙](./governance/development-rules.md)
- [Definition of Ready](./governance/definition-of-ready.md)
- [Definition of Done](./governance/definition-of-done.md)
- [테스트 전략](./quality/test-strategy.md)
- [테스트 체크리스트](./quality/testing-checklist.md)

작업 전에는 루트 [AGENTS.md](../AGENTS.md)와 작업 경로의 하위 `AGENTS.md`를 함께 확인합니다. 승인 ADR과 일반 문서가
충돌하면 승인된 최신 ADR을 우선하고, 현재 방향은 계보를 분리해 충돌 없이 기록합니다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-04 | README → Strategy → Current Status → Roadmap → Service 읽기 흐름과 트랙별 진입점으로 재구성 |
| 2026-07-28 | Model Family·Instruct 문서 진입점 추가 |
