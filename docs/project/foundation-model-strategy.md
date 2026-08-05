# DohaLM Foundation Model Strategy

- 문서 상태: `review`
- 마지막 검토일: 2026-08-05
- 기준 문서: [README](../../README.md)
- 현재 실행 권한 영향: 없음

## 1. 목적

이 문서는 프로젝트 최우선 Phase인 Foundation Model 연구의 범위와 Runtime/Application 개발의 경계를 정의합니다. 현재 구현 사실은
[Current Project Status](./current-project-status.md), 실행 순서는 [Model Family Roadmap](./model-family-roadmap.md)이 담당합니다.

## 2. 프로젝트 Phase와 우선순위

| Phase | 목적 | 모델 계보 | 우선순위 |
|---|---|---|---|
| Phase 1 — Foundation | 한국어 소형 Base·Instruct 모델을 직접 구현하고 학습·평가 체계를 검증 | DohaLM-Tiny → Candidate A/B → Candidate C → Foundation Instruct | 현재 최우선 |
| Phase 2 — Runtime | 실제 서비스용 로컬 Chat Runtime 구축 | Qwen Base → General Instruct Adapter → Runtime | Foundation 완료 이후 병행 트랙 |
| Phase 3 — Application | Runtime을 사용하는 제품·도메인 기능 구축 | Runtime → DohaMusic → Music Adapter·Lyrics·Prompt | Runtime 이후 |

[확정] Qwen Base는 DohaLM Foundation Base가 아니라 Runtime 검증용 upstream Instruct 모델입니다. Qwen 기반 Adapter를
`DohaLM-Tiny`, Candidate A/B 또는 ADR-009의 Base baseline으로 재명명하지 않습니다.

[확정] ADR-010의 `DohaLM Instruct Tiny v1`은 Candidate B를 immutable parent로 하는 Foundation 연구 설계입니다.
Qwen 기반 General Instruct Adapter는 별도 Runtime 계보이며 ADR-010의 실행 완료를 의미하지 않습니다.

[확정] 새로운 공식 개발 목표는 Candidate C 평가 완료 뒤 Candidate C 기반 Foundation Instruct를 개발하는 것입니다.
이는 현재 승인된 ADR-010의 parent 결정을 자동 변경하지 않습니다. 실제 SFT 전에 ADR-010을 대체하거나 개정하는 후속 ADR이 필요합니다.

## 3. Foundation Model Track

Foundation은 프로젝트의 핵심 목표이며 다음 순서로 진행합니다.

### 3.1 DohaLM Base 본훈련 준비

```text
Base Training Readiness
  → Publish Recovery
  → Tokenization
  → Evaluation
  → EOS 분석
```

현재까지 확보한 기반은 다음 네 축입니다.

1. `DohaLM-Tiny` 직접 구현과 Trainer·checkpoint/resume·generation 검증
2. 운영 SentencePiece Unigram Tokenizer와 고정 artifact identity
3. Candidate A/B 학습·평가와 immutable baseline 계보; Candidate B는 current Base baseline
4. Quick·Full·EOS·position·category·stability·privacy·lineage Evaluation Framework

Candidate B는 current Base baseline이며 Candidate A는 historical baseline입니다. Candidate B는 폐기되는 목표가 아니라
Candidate C의 핵심 비교 기준과 lineage parent 후보로 보존합니다. 이 완료는 제한된 Tiny 연구 계약에 대한 완료이고,
일반 성능·서비스 준비·publication 승인을 뜻하지 않습니다.

### 3.2 Candidate C

Candidate C는 다음 Foundation 핵심 목표입니다.

```text
EOS 문제 해결 → Base 재학습 → Candidate C Evaluation
```

현재 상태는 `planned`입니다. 구조·데이터·학습·평가 수치와 실행 승인은 후속 설계 및 ADR 전까지 확정하지 않습니다.

### 3.3 Foundation Instruct

공식 목표 순서는 다음과 같습니다.

```text
Candidate C 기반 SFT → Evaluation → Candidate Selection
```

현재 구현 상태는 ADR-010의 Candidate B 기반 설계가 `design_complete`인 상태로 유지됩니다. Candidate C 기반 SFT는
`planned`이며 parent 변경을 다루는 후속 ADR, Dataset·SFT·평가·publication 승인이 필요합니다.

Foundation Chat과 더 큰 scale은 별도 연구 결정입니다.

- Foundation Instruct: ADR-010 설계 완료, 실행·publication 미승인
- Foundation Chat: 미착수; 승인된 Foundation Instruct parent가 선행 조건
- DohaLM-Small 이상: 구조·데이터·자원·평가를 별도 ADR에서 결정하기 전까지 미확정

## 4. Phase 2 — Runtime

Runtime은 Foundation 완료 이후 진행하는 실제 서비스용 병행 트랙입니다. Foundation artifact와 자동 lineage 관계는 없으며,
고정 Qwen Base 위에서 다음 경로를 완성합니다.

```text
Qwen Base
  → General Instruct Adapter (QLoRA)
  → Adapter Loader
  → Runtime Provider
  → Prompt Engine
  → Chat API / SSE Streaming
  → Web UI
```

현재 Base Qwen Runtime, Provider Registry, Chat API, Streaming과 Web UI는 로컬 검증됐습니다. QLoRA 학습·평가 코드와
실행 이력은 존재하지만 배포 승인 Adapter가 없고 Loader는 placeholder이므로 end-to-end Adapter Runtime은 미완료입니다.
Prompt 직렬화는 Qwen 공식 chat template로 구현됐지만 독립적인 정책·version·template engine은 아직 없습니다.

## 5. 공통 불변 원칙

- 승인된 Base·Dataset·Tokenizer·checkpoint·Adapter artifact는 덮어쓰지 않습니다.
- 모든 derivative는 parent, revision, config, data, run과 evaluation fingerprint를 기록합니다.
- 학습 완료, 평가 완료, Runtime 통합, deployment readiness와 publication 승인을 각각 구분합니다.
- Domain 개선은 Foundation 회귀 통과나 Runtime 안전성을 자동으로 보장하지 않습니다.
- 단일 `RTX 3060 Ti 8GB`에서 검증하지 않은 규모와 성능 수치는 확정하지 않습니다.

## 6. Phase 3 — Application과 후속 경계

- Runtime 확장: Memory, RAG, Tool Calling, Agent — 모두 `planned`
- Application: DohaMusic → Music Adapter → Lyrics → Prompt — 모두 `planned`
- Docker, Kubernetes, Cloud와 운영 배포 — `out_of_scope`
- Vision/Multimodal — 현재 로드맵 범위 밖

세부 Domain 데이터·안전 경계는 [Domain Model Strategy](./domain-model-strategy.md)를 따릅니다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | Foundation을 최우선 Phase로 재배치하고 Base 본훈련 준비 → Candidate C → Foundation Instruct 순서, Runtime의 후속 서비스 트랙과 DohaMusic Application 경계를 명시 |
| 2026-08-04 | Foundation 연구와 Qwen 기반 Runtime/Application을 별도 트랙으로 분리하고 1·2·3차 목표 경계 반영 |
| 2026-07-28 | Foundation Model 장기 비전과 immutable Base 원칙 작성 |
