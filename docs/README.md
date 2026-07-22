# DohaLM 문서 안내서

- 문서 상태: `review`
- 마지막 검토일: 2026-07-23
- 기준 인덱스: [문서 인덱스](./index.md)

## 1. 안내 목적과 독자

이 문서는 현재 DohaLM 기준 문서의 위치, 상태와 권장 읽기 순서를 안내한다.

| 독자 | 우선 확인할 내용 |
|---|---|
| 처음 저장소를 보는 사람 | 프로젝트 목적, 범위, 시스템 흐름과 개발 순서 |
| 프로젝트 설계를 검토하는 사람 | 확정·미결정 사항, ADR, 품질 Gate와 위험 |
| 모델을 구현할 개발자 | Tiny 승인 사양, GPU 제약, 모델·테스트 완료 조건 |
| 데이터 파이프라인 담당자 | 데이터 승인, 라이선스, 계보, 전처리·분할·누수 정책 |
| 학습·평가 담당자 | 사전학습·SFT, 평가, 실험 관리와 재현성 정책 |
| Codex 작업을 요청하는 사용자 | 개발 규칙, Ready·Done, Codex 표준 절차와 Git 제한 |

## 2. 권장 읽기 순서

### 2.1 처음 보는 사람

[프로젝트 개요](./project/overview.md) → [범위와 목표](./project/scope-and-goals.md) → [시스템 아키텍처](./architecture/system-architecture.md) → [개발 로드맵](./quality/development-roadmap.md)

### 2.2 모델 개발

[모델 아키텍처](./architecture/model-architecture.md) → [ADR-002](./decisions/ADR-002-tiny-model-architecture.md) → [GPU 메모리 전략](./training/gpu-memory-strategy.md) → [테스트 체크리스트](./quality/testing-checklist.md)

### 2.3 데이터 작업

[데이터 전략](./data/data-strategy.md) → [데이터 전처리](./data/preprocessing.md) → [데이터셋 레지스트리](./data/dataset-registry.md) → [데이터 라이선스 정책](./data/data-license-policy.md) → [데이터 분할 및 누수 방지](./data/data-split-and-leakage-policy.md)

### 2.4 학습과 평가

[사전학습 계획](./training/pretraining-plan.md) → [평가 계획](./evaluation/evaluation-plan.md) → [실험 관리](./training/experiment-management.md) → [재현성 정책](./quality/reproducibility-policy.md)

### 2.5 Codex 작업

[개발 규칙](./governance/development-rules.md) → [Definition of Ready](./governance/definition-of-ready.md) → [Definition of Done](./governance/definition-of-done.md) → [Codex 작업 절차](./governance/codex-workflow.md)

작업 시에는 문서 외에도 루트 [AGENTS.md](../AGENTS.md)와 작업 경로에 가장 가까운 하위 `AGENTS.md`를 먼저 확인한다.

## 3. 문서 상태

| 상태 | 의미 |
|---|---|
| `planned` | 파일이 없거나 목차·작성 계획만 존재함 |
| `draft` | 초안은 있으나 핵심 미결정 사항이 남아 있음 |
| `review` | 필수 내용이 작성되어 검토를 기다리거나 검토 중임 |
| `approved` | 프로젝트 기준 또는 결정으로 승인됨 |
| `implemented` | 승인 내용이 코드·설정·테스트에 반영되고 검증됨 |
| `deprecated` | 후속 문서나 결정으로 대체됨 |

- [확정] `approved`는 설계·정책 승인이며 구현 완료를 의미하지 않는다.
- [확정] 문서 상태와 본문의 `[확정]`, `[가정]`, `[검증 필요]`, `[후순위]`, `[제외]` 태그는 서로 다른 축이다.
- [확정] 상태의 단일 기준과 전체 선후 관계는 [문서 인덱스](./index.md)를 따른다.

## 4. 범주별 안내

이 문서는 범주별 진입점만 제공한다. 모든 기준 문서의 상태·선행·후속·필수 여부·미결정 사항은 [문서 인덱스](./index.md)를 단일 기준으로 사용한다.

| 범주 | 설명 | 우선 진입 문서 |
|---|---|---|
| 프로젝트 | 목적, 범위와 버전 방향 | [프로젝트 개요](./project/overview.md), [범위와 목표](./project/scope-and-goals.md) |
| 거버넌스 | 개발 규칙, Ready·Done과 Codex 절차 | [개발 규칙](./governance/development-rules.md), [Definition of Ready](./governance/definition-of-ready.md), [Codex 작업 절차](./governance/codex-workflow.md) |
| 아키텍처 | 시스템·모델·저장소 구조 | [시스템 아키텍처](./architecture/system-architecture.md), [모델 아키텍처](./architecture/model-architecture.md), [저장소 구조](./architecture/repository-structure.md) |
| 데이터 | 데이터 승인, 전처리, 라이선스와 품질 | [데이터 전략](./data/data-strategy.md), [데이터 전처리](./data/preprocessing.md), [데이터셋 레지스트리](./data/dataset-registry.md) |
| 학습 | 토크나이저, 사전학습·SFT와 실험 관리 | [토크나이저 설계](./training/tokenizer-design.md), [사전학습 계획](./training/pretraining-plan.md), [실험 관리](./training/experiment-management.md) |
| 평가 | 평가 계약, Benchmark와 생성 품질 | [평가 계획](./evaluation/evaluation-plan.md), [Benchmark 정책](./evaluation/benchmark-policy.md), [생성 평가](./evaluation/generation-evaluation.md) |
| 품질 | 로드맵, 테스트와 재현성 | [개발 로드맵](./quality/development-roadmap.md), [테스트 전략](./quality/test-strategy.md), [테스트 체크리스트](./quality/testing-checklist.md) |
| 결정 기록 | 승인된 결정과 재검토 조건 | [ADR 인덱스](./decisions/README.md) |

## 5. ADR 안내

- ADR은 모델, 데이터, 평가, 품질 Gate처럼 장기간 영향을 주는 결정의 배경·대안·결과를 기록한다.
- 관련 구현을 시작하거나 승인 사양을 변경할 때 적용되는 ADR을 먼저 읽는다.
- 일반 문서와 승인 ADR이 충돌하면 현재 상태가 `approved`인 최신 ADR을 우선하고 충돌을 보고한다.
- 전체 목록과 상태는 [ADR 인덱스](./decisions/README.md)를 따른다.
- 모델 구조·파라미터·Vocabulary·Context·Normalization·위치 표현·weight tying, 데이터 거버넌스, 평가 방식, checkpoint schema, 공개 API, 저장소 핵심 구조와 승인 정책 변경은 새 ADR 후보이다.
- 오탈자, 링크 수정과 의미를 바꾸지 않는 설명 보완에는 ADR이 필요하지 않다.

| ADR | 결정 | 상태 |
|---|---|---|
| [ADR-001](./decisions/ADR-001-initial-model-scope.md) | Tiny 우선 모델 범위 | `approved` |
| [ADR-002](./decisions/ADR-002-tiny-model-architecture.md) | DohaLM-Tiny 아키텍처 | `approved` |
| [ADR-003](./decisions/ADR-003-tokenizer-method.md) | SentencePiece Unigram 방식 | `approved` |
| [ADR-004](./decisions/ADR-004-data-governance.md) | 데이터 거버넌스 | `approved` |
| [ADR-005](./decisions/ADR-005-evaluation-and-experiment-policy.md) | 평가·실험 관리 정책 | `approved` |
| [ADR-006](./decisions/ADR-006-development-quality-gates.md) | 개발 단계와 품질 Gate | `approved` |

## 6. 현재 상태

- [확정] 현재는 기준 문서를 정리하고 검토하는 문서화 단계다.
- [확정] `src/`, `server/`, `configs/`의 파일은 제목 수준의 스캐폴드이며 실행 가능한 모델·학습·평가·서비스 코드는 구현되지 않았다.
- [검증 필요] 실제 학습 데이터 후보와 목적별 승인·라이선스 검토는 완료되지 않았다.
- [확정] `DohaLM-Tiny` 설계는 ADR-002에서 승인됐지만 코드·테스트 반영은 완료되지 않았다.
- [검증 필요] `DohaLM-Small`의 Layer, Hidden Size, Head, FFN, 정밀도와 배치는 확정되지 않았다.
- [확정] 다음 예정 단계는 문서 검토와 Gate 0 승인 이후 Phase 0 저장소·환경 기반 구현이다.
- [후순위] FastAPI, Next.js, 배포와 외부 평가는 Tiny 학습·평가 검증 이후 진행한다.

## 7. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] 범주별 진입점과 문서 생명주기 인덱스의 역할을 분리함 |
| 2026-07-23 | [확정] 독자별 읽기 순서, 문서 지도, ADR 안내와 실제 저장소 상태를 반영한 문서 안내서 작성 |
