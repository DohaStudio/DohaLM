# DohaLM Reference Applications

- 문서 상태: `review`
- 마지막 검토일: 2026-08-05
- 저장소 경계: `external_repositories_only`

## 1. 역할

Reference Application은 DohaLM의 model·Runtime·API·SDK가 실제 소비자 경계에서 재사용 가능한지 검증하는 외부 프로젝트입니다.
DohaLM 내부 Phase나 모델 계보가 아니며, 이 저장소에 애플리케이션 코드를 추가하지 않습니다.

```text
dohamusic_role: external_reference_application
```

## 2. 첫 Reference Application — DohaMusic

DohaMusic은 별도 저장소에서 개발하며 DohaLM REST·Streaming API 또는 Python SDK를 호출합니다.

| DohaMusic 소유 | DohaLM 소유 |
|---|---|
| UI와 사용자 interaction | model·Adapter loading |
| 음악 비즈니스 로직과 음악 프로젝트 | inference와 streaming |
| 가사 작성·편집 workflow | prompt processing |
| 개인화 기능과 사용자 데이터 정책 | model manifest·versioning·호환성 |

DohaMusic integration은 현재 `planned, separate repository`입니다. DohaLM 안에서 Music Adapter, Lyrics 또는 Prompt를
독립 내부 구현 단계로 만들지 않습니다. 필요한 음악 특화 모델이나 Adapter가 제안되면 Phase 2 artifact 계약과 별도
데이터·저작권·개인정보 승인을 먼저 충족해야 합니다.

## 3. 통합 경계

```text
DohaMusic UI · Business Logic
             ↓
  DohaLM REST/Streaming · SDK
             ↓
 Versioned Model · Runtime
```

- API·SDK version과 model manifest를 명시적으로 고정합니다.
- 외부 앱 장애나 데이터 정책을 Runtime 성공으로 합치지 않습니다.
- DohaMusic 구현 상태를 DohaLM Phase 완료로 간주하지 않습니다.
- 오디오·보컬·MIDI 생성은 현재 DohaLM 범위 밖입니다.

## 4. 후속 소비자

DohaWriter와 DohaCode도 같은 외부 소비자 원칙을 적용할 수 있지만 현재는 제안 단계입니다. 새 Reference Application은
[Distribution and Integration](./distribution-and-integration.md)의 공개 인터페이스와 release identity를 재사용해야 합니다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | DohaMusic을 별도 저장소의 첫 Reference Application으로 재정의하고 책임·통합 경계 명시 |
| 2026-08-04 | 초기 domain 후보와 위험 경계 기록 |
