# DohaLM Distribution and Integration

- 문서 상태: `review`
- 마지막 검토일: 2026-08-05
- 공식 Phase: `phase_3: distribution_and_integration`
- Cloud 배포: `out_of_scope`

## 1. 목적과 흐름

Phase 3는 승인된 DohaLM 모델과 Runtime을 외부 저장소가 안정적으로 소비할 수 있는 로컬 배포·통합 표면으로 제공합니다.

```text
DohaLM model
  → runtime server
  → REST / Streaming
  → Python SDK
  → Integration Guide
  → Versioned Release
```

## 2. 산출물과 상태

| 산출물 | 현재 상태 |
|---|---|
| REST·Streaming API | `MVP implemented` |
| Base Qwen local E2E | `implemented_verified` |
| Python SDK | `not_started` |
| Integration Guide | `planned` |
| Versioned Model Release | `planned` |
| Docker·Cloud deployment | `out_of_scope` |

현재 API 구현은 [FastAPI Backend MVP](../service/dohalm-backend-mvp.md)를 따릅니다. MVP 검증 UI는 서비스 계약의
소비 예시일 뿐, Reference Application이나 공식 SDK를 대체하지 않습니다.

## 3. 배포 계약

- API·SDK·model manifest의 호환 version을 명시합니다.
- release는 model identity, runtime dependency와 evaluation evidence를 포함합니다.
- 승인 artifact가 없으면 Adapter endpoint를 READY로 표시하지 않습니다.
- local versioned release까지만 현재 범위이며 인증·SLA·Cloud 운영은 포함하지 않습니다.

## 4. 외부 통합

외부 Reference Application은 versioned API 또는 SDK만 사용하며 모델 경로·checkpoint 내부 구조에 의존하지 않습니다.
첫 소비자는 별도 저장소의 [DohaMusic](./domain-model-strategy.md)입니다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | REST·Streaming·SDK·Guide·local versioned release를 Phase 3로 정의 |
