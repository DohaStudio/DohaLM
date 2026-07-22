# DohaLM Architecture Decision Records

## 목적

- [확정] 이 디렉터리는 프로젝트의 중요한 기술·범위 결정을 ADR로 관리한다.
- [확정] 문서 상태는 [문서 인덱스](../index.md)의 생명주기 상태를 사용한다.
- [확정] `approved`는 결정이 채택되었다는 뜻이며 코드 구현이나 테스트 완료를 뜻하지 않는다.

## ADR 인덱스

| ADR 번호 | 제목 | 상태 | 결정일 | 관련 문서 | 구현 영향 | 재검토 필요 여부 |
|---|---|---|---|---|---|---|
| ADR-001 | [초기 모델 범위와 DohaLM-Tiny 우선 개발](./ADR-001-initial-model-scope.md) | `approved` | 2026-07-23 | [프로젝트 개요](../project/overview.md), [범위와 목표](../project/scope-and-goals.md) | Tiny 우선, Small 후속, 대형·분산 전제 제외 | 예: 하드웨어·목적·실측 결과 변경 시 |
| ADR-002 | [DohaLM-Tiny 모델 아키텍처](./ADR-002-tiny-model-architecture.md) | `approved` | 2026-07-23 | [모델 아키텍처](../architecture/model-architecture.md), [GPU 메모리 전략](../training/gpu-memory-strategy.md) | 모델 구조, parameter count, state shape와 checkpoint 호환성 고정 | 예: count 불일치, 학습 불안정, OOM 또는 구조 변경 시 |
| ADR-003 | [SentencePiece Unigram 토크나이저 방식](./ADR-003-tokenizer-method.md) | `approved` | 2026-07-23 | [토크나이저 설계](../training/tokenizer-design.md), [SFT 계획](../training/sft-plan.md) | vocabulary, special-token ID, embedding/LM Head 의미와 데이터 형식 고정 | 예: corpus 평가, 라이선스 또는 tokenizer 호환성 문제 시 |
| ADR-004 | [데이터 거버넌스 기준](./ADR-004-data-governance.md) | `approved` | 2026-07-23 | [데이터 전략](../data/data-strategy.md), [데이터 전처리](../data/preprocessing.md), [데이터셋 레지스트리](../data/dataset-registry.md), [데이터 라이선스 정책](../data/data-license-policy.md), [데이터 분할 및 누수 방지](../data/data-split-and-leakage-policy.md) | 원본 불변, 승인 상태, version·checksum·manifest와 split 누수 방지 계약 | 예: 실제 조건 표현 불가, 계보 추적 실패, 외부 공개 요건 변경 시 |
| ADR-005 | [평가 및 실험 관리 정책](./ADR-005-evaluation-and-experiment-policy.md) | `approved` | 2026-07-23 | [평가 계획](../evaluation/evaluation-plan.md), [실험 관리](../training/experiment-management.md), [Benchmark 정책](../evaluation/benchmark-policy.md), [생성 평가](../evaluation/generation-evaluation.md), [재현성 정책](../quality/reproducibility-policy.md) | validation·perplexity·prompt 비교 조건, experiment 계보와 실패 보존 계약 | 예: metric 표현 부족, 재현 불가, 외부 평가 조건 변경 시 |
| ADR-006 | [개발 단계와 품질 게이트](./ADR-006-development-quality-gates.md) | `approved` | 2026-07-23 | [개발 로드맵](../quality/development-roadmap.md), [테스트 체크리스트](../quality/testing-checklist.md), [Definition of Ready](../governance/definition-of-ready.md), [Definition of Done](../governance/definition-of-done.md), [테스트 전략](../quality/test-strategy.md), [Codex 작업 절차](../governance/codex-workflow.md) | 단계별 진입·통과 기준, 필수 테스트, 실패 시 복구와 승인 경계 고정 | 예: 게이트가 결함을 놓치거나 과도하게 차단함, 하드웨어·범위·자동화 변경 시 |

- [확정] 현재 `docs/decisions/`에 존재하는 ADR-001부터 ADR-006까지 모두 등록했다.
- [확정] ADR-002는 ADR-001의 Tiny 세부 미정 사항을 후속 결정하지만 Tiny 우선 범위 결정을 대체하지 않는다.
- [확정] deprecated ADR이 생기면 대체 ADR과 사유를 양쪽 문서 및 이 표에 기록한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] ADR-006 개발 단계와 품질 게이트 등록 |
| 2026-07-23 | [확정] ADR-005 평가 및 실험 관리 정책 등록 |
| 2026-07-23 | [확정] ADR-004 데이터 거버넌스 기준 등록 |
| 2026-07-23 | [확정] ADR-001, ADR-002, ADR-003 인덱스 최초 작성 |
