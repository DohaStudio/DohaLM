# DohaLM 문서 안내서

- 문서 상태: `review`
- 마지막 검토일: 2026-08-05
- 기준 문서: [저장소 README](../README.md)
- 전체 목록: [문서 인덱스](./index.md)

## 1. 문서 역할과 읽기 순서

프로젝트의 범위·우선순위는 루트 README를 기준으로 합니다. 중복된 상태 설명 대신 다음 순서로 읽습니다.

```text
README
  → Foundation Model Strategy
  → Current Project Status
  → Roadmap
  → Runtime 문서
  → Application 문서
```

1. [README](../README.md): Foundation 우선 Phase 1→2→3과 프로젝트 범위
2. [Foundation Model Strategy](./project/foundation-model-strategy.md): Base·Candidate B/C·Foundation Instruct 핵심 목표와 Runtime 경계
3. [Current Project Status](./project/current-project-status.md): 실제 코드·테스트·실측 기준 상태
4. [Roadmap](./project/model-family-roadmap.md): Foundation → Runtime → Application 공식 개발 순서
5. [Runtime](./service/dohalm-backend-mvp.md), [Base Qwen Provider](./service/dohalm-base-qwen-provider.md), [Adapter Runtime 설계](./service/dohalm-adapter-runtime.md), [Frontend](./service/dohalm-frontend-mvp.md): 실제 서비스용 Runtime 실행·후속 구현 계약
6. [Application](./project/domain-model-strategy.md): Runtime을 사용하는 DohaMusic → Music Adapter → Lyrics → Prompt

[Domain Model Strategy](./project/domain-model-strategy.md)는 DohaMusic과 장기 Domain 후보를,
[Instruct Strategy](./instruct/instruct-strategy.md)는 Candidate C 기반 Foundation Instruct 공식 목표, 현재 Candidate B 기반 승인 설계와
Qwen 기반 Runtime Adapter를 구분합니다.

## 2. 트랙별 진입점

| 트랙 | 현재 범위 | 우선 문서 |
|---|---|---|
| Phase 1 Foundation | Base 본훈련 준비, Candidate B/C, Foundation Instruct | [Foundation Strategy](./project/foundation-model-strategy.md), [Evaluation](./evaluation/README.md), [Model Lineage](./project/model-lineage.md) |
| Phase 2 Runtime | Qwen v0.3 Recovery, Manifest, Runtime, Adapter | [Instruct 안내](./instruct/README.md), [FastAPI](./service/dohalm-backend-mvp.md), [Adapter Runtime](./service/dohalm-adapter-runtime.md) |
| Runtime 확장 | Memory, RAG, Tool Calling, Agent | [Roadmap](./project/model-family-roadmap.md), [Tool Calling 전략](./instruct/tool-calling-strategy.md) |
| Phase 3 Application | DohaMusic, Music Adapter, Lyrics, Prompt | [Domain Strategy](./project/domain-model-strategy.md) |

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

- Foundation의 Candidate B가 current Base baseline이고 Candidate C는 다음 핵심 목표이며 Candidate A는 historical baseline입니다.
- 공식 목표는 Candidate C 기반 Foundation Instruct입니다. 현재 ADR-010의 Candidate B 기반 승인 설계는 후속 ADR 전까지 유지됩니다.
- Runtime은 Base Qwen Chat·Streaming까지 로컬 검증됐습니다. Adapter manifest·Validator·PEFT Loader·Provider 통합은 mock 검증됐고 실제 승인 Adapter/GPU는 미검증입니다.
- Runtime은 Foundation 완료 이후의 실제 서비스용 병행 트랙이고, DohaMusic은 Runtime을 사용하는 Application입니다.
- Memory, RAG, Tool Calling, Agent와 DohaMusic·Music Adapter·Lyrics·Prompt는 계획 상태입니다.
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
| 2026-08-05 | README → Foundation Strategy → Current Status → Roadmap → Runtime → Application 읽기 순서와 Foundation 우선 Phase 구조 반영 |
| 2026-08-04 | Runtime 1차 진입점에 General Instruct Adapter Runtime 설계 추가 |
| 2026-08-04 | README → Strategy → Current Status → Roadmap → Service 읽기 흐름과 트랙별 진입점으로 재구성 |
| 2026-07-28 | Model Family·Instruct 문서 진입점 추가 |
