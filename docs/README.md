# DohaLM 문서 안내서

- 문서 상태: `review`
- 마지막 검토일: 2026-07-23
- 기준 인덱스: [문서 인덱스](./03-documentation-index.md)

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

[프로젝트 개요](./00-project-overview.md) → [범위와 목표](./01-scope-and-goals.md) → [시스템 아키텍처](./03-system-architecture.md) → [개발 로드맵](./17-development-roadmap.md)

### 2.2 모델 개발

[모델 아키텍처](./04-model-architecture.md) → [ADR-002](./decisions/ADR-002-tiny-model-architecture.md) → [GPU 메모리 전략](./16-gpu-memory-strategy.md) → [테스트 체크리스트](./18-testing-checklist.md)

### 2.3 데이터 작업

[데이터 전략](./06-data-strategy.md) → [데이터 전처리](./07-data-preprocessing.md) → [데이터셋 레지스트리](./23-dataset-registry.md) → [데이터 라이선스 정책](./24-data-license-policy.md) → [데이터 분할 및 누수 방지](./26-data-split-and-leakage-policy.md)

### 2.4 학습과 평가

[사전학습 계획](./08-pretraining-plan.md) → [평가 계획](./10-evaluation-plan.md) → [실험 관리](./15-experiment-management.md) → [재현성 정책](./29-reproducibility-policy.md)

### 2.5 Codex 작업

[개발 규칙](./02-development-rules.md) → [Definition of Ready](./31-definition-of-ready.md) → [Definition of Done](./32-definition-of-done.md) → [Codex 작업 절차](./36-codex-workflow.md)

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
- [확정] 상태의 단일 기준과 전체 선후 관계는 [문서 인덱스](./03-documentation-index.md)를 따른다.

## 4. 문서 지도

아래 표에는 현재 실제 파일이 존재하는 기준 문서만 포함한다. 상태는 [문서 인덱스](./03-documentation-index.md)의 2026-07-23 기준값이다.

### 4.1 프로젝트·개발 운영

| 문서 | 목적 | 상태 | 주요 독자 | 선행 문서 |
|---|---|---|---|---|
| [프로젝트 개요](./00-project-overview.md) | 프로젝트 목적과 완료 조건 | `review` | 전체 | 없음 |
| [범위와 목표](./01-scope-and-goals.md) | MVP와 Tiny·Small 범위 | `review` | 전체 | `00` |
| [개발 규칙](./02-development-rules.md) | 개발·Git·재현성·테스트 원칙 | `review` | 개발자·Codex 사용자 | `00`, `01`, ADR-002 |
| [문서 인덱스](./03-documentation-index.md) | 문서 상태와 선후 관계 | `review` | 전체 | `00`, `01`, `02` |
| [개발 로드맵](./17-development-roadmap.md) | Phase 0~10과 Gate 0~11 | `review` | 전체 | 핵심 설계·ADR-006 |
| [Definition of Ready](./31-definition-of-ready.md) | 작업 시작 조건 | `review` | 개발자·Codex 사용자 | `02`, `17`, ADR-006 |
| [Definition of Done](./32-definition-of-done.md) | 검증 기반 완료 조건 | `review` | 개발자·검토자 | `17`, `31`, `33`, ADR-006 |
| [테스트 전략](./33-test-strategy.md) | 테스트 수준과 CPU·GPU 경계 | `review` | 개발자·검토자 | `02`, `10`, `17`, `31`, `32` |
| [위험 등록부](./34-risk-register.md) | 위험 예방·대응 관리 | `review` | 전체 | 핵심 설계·`17`, `33` |
| [버전 계획](./35-version-plan.md) | 권장 버전 이정표 | `review` | 프로젝트 검토자 | `17`, `32`, `33`, `34` |
| [Codex 작업 절차](./36-codex-workflow.md) | Codex 작업 전·중·후 절차 | `review` | Codex 사용자 | AGENTS·`31`, `32`, `33` |

### 4.2 시스템·모델·저장소

| 문서 | 목적 | 상태 | 주요 독자 | 선행 문서 |
|---|---|---|---|---|
| [시스템 아키텍처](./03-system-architecture.md) | 데이터부터 UI까지 시스템 경계 | `review` | 설계 검토자·개발자 | `00`, `01`, `02`, ADR-001 |
| [모델 아키텍처](./04-model-architecture.md) | Tiny 구조·shape·파라미터 산식 | `review` | 모델 개발자 | `01`, ADR-001·002 |
| [토크나이저 설계](./05-tokenizer-design.md) | SentencePiece 어휘·특수 토큰 정책 | `review` | 모델·데이터 개발자 | `01`, ADR-003 |
| [GPU 메모리 전략](./16-gpu-memory-strategy.md) | RTX 3060 Ti 8GB 측정·OOM 대응 | `draft` | 모델·학습 담당자 | `04`, ADR-001·002 |
| [저장소 구조](./21-repository-structure.md) | 현재·계획 경로와 책임 | `review` | 개발자·Codex 사용자 | `02`, `03` |
| [산출물·설정 정책](./22-artifact-and-configuration-policy.md) | 설정 우선순위와 산출물 계보 | `review` | 개발자·학습 담당자 | `02`, `03`, `21` |

### 4.3 데이터

| 문서 | 목적 | 상태 | 주요 독자 | 선행 문서 |
|---|---|---|---|---|
| [데이터 전략](./06-data-strategy.md) | 데이터 후보·승인·규모 원칙 | `review` | 데이터 담당자 | `01`, `02`, `05`, ADR-004 |
| [데이터 전처리](./07-data-preprocessing.md) | 정제·중복·분할·packing 명세 | `review` | 데이터 담당자 | `05`, `06`, `23`, `24` |
| [데이터셋 레지스트리](./23-dataset-registry.md) | 데이터 등록 필드와 승인 절차 | `review` | 데이터 담당자 | `06`, ADR-004 |
| [데이터 라이선스 정책](./24-data-license-policy.md) | 이용 조건과 공개 가능성 검토 | `review` | 데이터·검토 담당자 | `02`, `06`, `23`, ADR-004 |
| [데이터 품질 체크리스트](./25-data-quality-checklist.md) | 품질 검사·조치·기록 기준 | `review` | 데이터·평가 담당자 | `06`, `07`, `24`, `26` |
| [데이터 분할 및 누수 방지](./26-data-split-and-leakage-policy.md) | split과 평가 오염 방지 | `review` | 데이터·평가 담당자 | `06`, `07`, `23`, ADR-004 |

### 4.4 학습·평가·실험

| 문서 | 목적 | 상태 | 주요 독자 | 선행 문서 |
|---|---|---|---|---|
| [사전학습 계획](./08-pretraining-plan.md) | 사전학습 절차·자원·복원 계획 | `draft` | 학습 담당자 | `04`, `05`, `07`, `16` |
| [SFT 계획](./09-sft-plan.md) | 대화 형식과 SFT loss 정책 | `draft` | 학습 담당자 | `05`, `07`, `08` |
| [평가 계획](./10-evaluation-plan.md) | 학습·생성·자원 평가 계약 | `review` | 학습·평가 담당자 | `04`, `05`, `08`, `09`, `26` |
| [실험 관리](./15-experiment-management.md) | 실험 ID·상태·산출물 계보 | `review` | 학습·평가 담당자 | `02`, `08`, `10`, `22` |
| [테스트 체크리스트](./18-testing-checklist.md) | 구현별 테스트와 실패 조치 | `review` | 전체 개발자 | `17`, `31`, `32`, `33` |
| [Benchmark 정책](./27-benchmark-policy.md) | Benchmark 채택·누수·보고 원칙 | `review` | 평가 담당자 | `10`, `24`, `26`, ADR-005 |
| [생성 평가](./28-generation-evaluation.md) | 고정 prompt와 생성 품질 평가 | `review` | 평가·추론 담당자 | `05`, `09`, `10`, `26` |
| [재현성 정책](./29-reproducibility-policy.md) | 환경·seed·계보·실패 처리 | `review` | 학습·평가 담당자 | `02`, `10`, `15`, `22` |
| [실험 템플릿](./30-experiment-template.md) | 실험 계획·결과 기록 양식 | `review` | 학습·평가 담당자 | `10`, `15`, `29` |

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

기존 `01-project-plan.md`, `02-model-architecture.md`, `03-data-policy.md`, `04-training-plan.md`, `05-evaluation-plan.md`, `06-deployment-plan.md`은 제목만 있는 스캐폴드이며 현재 기준 문서가 아니다.

## 7. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] 독자별 읽기 순서, 문서 지도, ADR 안내와 실제 저장소 상태를 반영한 문서 안내서 작성 |
