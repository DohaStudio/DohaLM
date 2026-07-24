# DohaLM 문서 안내서

- 문서 상태: `review`
- 마지막 검토일: 2026-07-24
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

### 2.2 핵심 구현과 모델 개발

[모델 아키텍처](./architecture/model-architecture.md) → [ADR-002](./decisions/ADR-002-tiny-model-architecture.md) → [핵심 개발 기능명세서](./architecture/core-development-feature-specification.md) → [GPU 메모리 전략](./training/gpu-memory-strategy.md) → [테스트 체크리스트](./quality/testing-checklist.md)

### 2.3 데이터 작업

[데이터 전략](./data/data-strategy.md) → [데이터셋 후보 등록부](./data/dataset-candidate-registry.md) → [구조 분석 요약](./data/analysis/dataset-analysis-summary.md) → [안전 표본 추출](./data/analysis/safe-sampling.md) → [수동 경로 mapping](./data/analysis/manual-path-mapping.md) → [대용량 JSON 제한 검사](./data/analysis/large-json-inspection.md) → [데이터셋 라이선스 검토](./data/dataset-license-review.md) → [데이터셋 승인 로그](./data/dataset-approval-log.md) → [평가 제외 목록](./data/evaluation-exclusion-list.md) → [실제 데이터셋 레지스트리](./data/dataset-registry.md) → [Phase 1 데이터 계약](./data/phase1-data-contract.md)·처리 → [Corpus Adapter 계약](./data/corpus-adapter-contract.md) → [Phase 2 토크나이저 계약](./training/phase2-tokenizer-contract.md)

### 2.4 Phase 2 토크나이저 구현

[Phase 1 데이터 계약](./data/phase1-data-contract.md) → [Phase 2 토크나이저 상세 계약](./training/phase2-tokenizer-contract.md) → [토크나이저 설계](./training/tokenizer-design.md) → Phase 2 구현·테스트

### 2.5 학습과 평가

[Trainer Foundation](./training/trainer-foundation.md) → [체크포인트·재개](./training/checkpoint-and-resume.md) → [Trainer 테스트](./quality/trainer-testing.md) → [사전학습 계획](./training/pretraining-plan.md) → [평가 계획](./evaluation/evaluation-plan.md) → [실험 관리](./training/experiment-management.md) → [재현성 정책](./quality/reproducibility-policy.md)

### 2.6 Codex 작업

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
| 아키텍처 | 시스템·모델·저장소 구조와 핵심 기능 계약 | [시스템 아키텍처](./architecture/system-architecture.md), [모델 아키텍처](./architecture/model-architecture.md), [핵심 개발 기능명세서](./architecture/core-development-feature-specification.md), [저장소 구조](./architecture/repository-structure.md) |
| 데이터 | 후보, 구조·안전 표본 분석, 라이선스·목적별 승인, Phase 1·adapter 계약과 품질 | [데이터 전략](./data/data-strategy.md), [데이터셋 후보 등록부](./data/dataset-candidate-registry.md), [구조 분석](./data/analysis/README.md), [안전 표본 추출](./data/analysis/safe-sampling.md), [수동 경로 mapping](./data/analysis/manual-path-mapping.md), [라이선스 검토](./data/dataset-license-review.md), [승인 로그](./data/dataset-approval-log.md), [Phase 1 데이터 계약](./data/phase1-data-contract.md), [Corpus Adapter 계약](./data/corpus-adapter-contract.md) |
| 학습 | 토크나이저, 합성 Trainer Foundation, 사전학습·SFT와 실험 관리 | [Phase 2 토크나이저 상세 계약](./training/phase2-tokenizer-contract.md), [토크나이저 설계](./training/tokenizer-design.md), [Trainer Foundation](./training/trainer-foundation.md), [체크포인트·재개](./training/checkpoint-and-resume.md), [사전학습 계획](./training/pretraining-plan.md), [실험 관리](./training/experiment-management.md) |
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

- [확정] Gate 1을 통과했고 Phase 0 환경·설정·경로·로깅·CLI 기반은 구현·검증 완료됐다.
- [확정] Gate 2를 통과했고 Phase 1 DATA-001~016 최소 데이터 파이프라인은 구현·검증 완료됐다.
- [확정] Phase 3 모델 구성요소, Phase 4 전체 모델 통합과 Phase 5 합성 Trainer Foundation은 구현·테스트됐다. 실제 tokenizer·승인 corpus 사전학습, 평가와 서비스는 구현 또는 실행되지 않았다.
- [확정] AI Hub 데이터셋 5개의 로컬 제한 package 구조를 읽기 전용으로 확인했지만 공식 다운로드 계보는 미검증이다. 등록부의 `registered`, `pending_terms_review`, `not_requested`와 목적별 `pending` 상태는 자동 변경하지 않았다.
- [확정] AIHUB-71748 안전 dry-run은 1,610개 absolute entry를 모두 거부해 추출 0건이며 수동 검토가 필요하다.
- [확정] 명시적 수동 mapping 기능과 합성 검증을 구현했고 사용자가 승인한 로컬 mapping으로 실제 dry-run을 수행했다. 이는 목적별 데이터 승인이 아니다.
- [확정] 이후 승인된 mapping dry-run에서 rule별 매칭 573/0·선택 1·추출 0을 확인했고 대용량 JSON 5개 제한 streaming·prefix 1,610개 hash 집계를 수행했다. 데이터 목적별 승인은 그대로 pending이다.
- [확정] `DohaLM-Tiny` 설계는 ADR-002에서 승인됐고 Phase 3·4 코드와 합성 테스트에 반영됐다. Gate 4·5 승인과 실제 학습 검증은 별도다.
- [검증 필요] `DohaLM-Small`의 Layer, Hidden Size, Head, FFN, 정밀도와 배치는 확정되지 않았다.
- [확정] Gate 0은 `approved`, Gate 1·2는 `passed`이며 Phase 2 토크나이저 계약·구현 준비가 허용됐다. Gate 3은 `planned`다.
- [후순위] FastAPI, Next.js, 배포와 외부 평가는 Tiny 학습·평가 검증 이후 진행한다.

## 7. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-24 | [확정] Phase 5 합성 Trainer Foundation·checkpoint/resume·테스트 문서를 학습 흐름에 연결하고 실제 사전학습과 구분함 |
| 2026-07-24 | [확정] Corpus Adapter 공통 계약과 synthetic AIHUB-71748 구현 문서를 데이터 안내 경로에 연결함 |
| 2026-07-24 | [확정] 수동 mapping 관측성, 대용량 JSON 5개 제한 검사와 RaG prefix hash·Unicode 비교 결과를 반영함 |
| 2026-07-24 | [확정] 일반 sampler와 분리된 수동 mapping 계약·AIHUB-71748 pending 후보 문서를 데이터 읽기 흐름에 연결함 |
| 2026-07-23 | [확정] ZIP 안전 표본 추출 정책과 AIHUB-71748 dry-run 결과 진입점을 추가함 |
| 2026-07-23 | [확정] AI Hub 후보 5종의 읽기 전용 구조 분석 진입점과 승인 상태 비변경 원칙을 반영함 |
| 2026-07-23 | [확정] 데이터 작업 읽기 순서에 Phase 1 데이터 계약과 후속 정책·구현 흐름을 연결함 |
| 2026-07-23 | [확정] 데이터 전략→후보→라이선스→승인 로그→실제 registry→Phase 1→Phase 2 corpus 읽기 흐름을 반영함 |
| 2026-07-23 | [확정] Phase 1 데이터 계약→Phase 2 토크나이저 계약→상위 설계→구현 읽기 흐름과 Gate 2 상태를 반영함 |
| 2026-07-23 | [확정] 개발자 읽기 순서에 핵심 개발 기능명세서를 추가하고 Phase 0·Gate 1 실제 상태를 동기화함 |
| 2026-07-23 | [확정] 범주별 진입점과 문서 생명주기 인덱스의 역할을 분리함 |
| 2026-07-23 | [확정] 독자별 읽기 순서, 문서 지도, ADR 안내와 실제 저장소 상태를 반영한 문서 안내서 작성 |
