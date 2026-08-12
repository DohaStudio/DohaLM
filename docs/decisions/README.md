# DohaLM Architecture Decision Records

- 문서 상태: `review`
- 마지막 검토일: 2026-08-12

## 목적

- [확정] 이 디렉터리는 프로젝트의 중요한 기술·범위 결정을 ADR로 관리한다.
- [확정] 문서 상태는 [문서 인덱스](../index.md)의 생명주기 상태를 사용한다.
- [확정] `approved`는 결정이 채택되었다는 뜻이며 코드 구현이나 테스트 완료를 뜻하지 않는다.

## ADR 인덱스

| ADR 번호 | 제목 | 상태 | 결정일 | 관련 문서 | 구현 영향 | 재검토 필요 여부 |
|---|---|---|---|---|---|---|
| ADR-001 | [초기 모델 범위와 DohaLM-Tiny 우선 개발](./ADR-001-initial-model-scope.md) | `approved` | 2026-07-23 | [프로젝트 개요](../project/overview.md), [범위와 목표](../project/scope-and-goals.md) | Tiny 우선, Small 후속, 대형·분산 전제 제외 | 예: 하드웨어·목적·실측 결과 변경 시 |
| ADR-002 | [DohaLM-Tiny 모델 아키텍처](./ADR-002-tiny-model-architecture.md) | `approved` | 2026-07-23 | [모델 아키텍처](../architecture/model-architecture.md), [GPU 메모리 전략](../training/gpu-memory-strategy.md) | 모델 구조, parameter count, state shape와 checkpoint 호환성 고정 | 예: count 불일치, 학습 불안정, OOM 또는 구조 변경 시 |
| ADR-003 | [SentencePiece Unigram 토크나이저 방식](./ADR-003-tokenizer-method.md) | `approved` | 2026-07-26 | [Phase 2 계약](../training/phase2-tokenizer-contract.md), [운영 후보 평가](../training/aihub-71748-operating-tokenizer-evaluation.md) | v2 Unigram, vocabulary, special-token ID, artifact identity와 functional reproduction 고정 | 예: corpus 평가, 라이선스 또는 tokenizer 호환성 문제 시 |
| ADR-004 | [데이터 거버넌스 기준](./ADR-004-data-governance.md) | `approved` | 2026-07-23 | [데이터 전략](../data/data-strategy.md), [데이터 전처리](../data/preprocessing.md), [데이터셋 레지스트리](../data/dataset-registry.md), [데이터 라이선스 정책](../data/data-license-policy.md), [데이터 분할 및 누수 방지](../data/data-split-and-leakage-policy.md) | 원본 불변, 승인 상태, version·checksum·manifest와 split 누수 방지 계약 | 예: 실제 조건 표현 불가, 계보 추적 실패, 외부 공개 요건 변경 시 |
| ADR-005 | [평가 및 실험 관리 정책](./ADR-005-evaluation-and-experiment-policy.md) | `approved` | 2026-07-23 | [평가 계획](../evaluation/evaluation-plan.md), [실험 관리](../training/experiment-management.md), [Benchmark 정책](../evaluation/benchmark-policy.md), [생성 평가](../evaluation/generation-evaluation.md), [재현성 정책](../quality/reproducibility-policy.md) | validation·perplexity·prompt 비교 조건, experiment 계보와 실패 보존 계약 | 예: metric 표현 부족, 재현 불가, 외부 평가 조건 변경 시 |
| ADR-006 | [개발 단계와 품질 게이트](./ADR-006-development-quality-gates.md) | `approved` | 2026-07-23 | [개발 로드맵](../quality/development-roadmap.md), [테스트 체크리스트](../quality/testing-checklist.md), [Definition of Ready](../governance/definition-of-ready.md), [Definition of Done](../governance/definition-of-done.md), [테스트 전략](../quality/test-strategy.md), [Codex 작업 절차](../governance/codex-workflow.md) | 단계별 진입·통과 기준, 필수 테스트, 실패 시 복구와 승인 경계 고정 | 예: 게이트가 결함을 놓치거나 과도하게 차단함, 하드웨어·범위·자동화 변경 시 |
| ADR-007 | [Evaluation Baseline and Candidate Comparison Policy](./ADR-007-evaluation-baseline-and-candidate-comparison.md) | `approved` | 2026-07-27 | [EOS 진단](../evaluation/eos-incomplete-block-diagnostic.md), [Quick 대표성 정책](../evaluation/quick-full-representativeness-policy.md), [Candidate B 평가 계약](../evaluation/candidate-b-evaluation-contract.md) | Candidate A Full baseline, Quick 역할·등급, EOS·Candidate B 평가 계약 고정 | 예: evaluation identity·대표성·EOS 기준 충돌 시 |
| ADR-008 | [EOS Generation and Decoding Evaluation Policy](./ADR-008-eos-generation-and-decoding-evaluation-policy.md) | `approved` | 2026-07-28 | [EOS Success Policy](../evaluation/eos-success-policy.md), [EOS Generation·Decoding 정책](../evaluation/eos-generation-decoding-policy.md) | 모델 단계별 EOS 계약과 pure/assisted 분리; historical 결과 비소급 | 계약·사용 목적 충돌 시 |
| ADR-009 | [Candidate B Official Reassessment under ADR-008](./ADR-009-candidate-b-official-reassessment.md) | `approved` | 2026-07-28 | [Candidate A/B Full 비교](../evaluation/candidate-a-b-full-comparison.md), [리더보드](../evaluation/model-evaluation-leaderboard.md) | Candidate B 현재 Base baseline·experimental derivative parent 승인; historical 판정 보존 | 새 identity·파생 계약·심각한 회귀 확인 시 |
| ADR-010 | [DohaLM Instruct Strategy](./ADR-010-dohalm-instruct-strategy.md) | `approved` | 2026-07-28 | [Instruct 전략](../instruct/instruct-strategy.md), [Readiness](../instruct/instruction-readiness.md) | Candidate B immutable parent·SFT pipeline·Chat lineage·data/evaluation/safety 경계 | parent·schema·Chat lineage·실행 정책 변경 시 |
| ADR-011 | [Candidate C Experimental Successor 재개 제안](./ADR-011-candidate-c-experimental-successor.md) | `draft` | 미결정 | [Candidate C 설계](../training/candidate-c-design.md), [Base Readiness](../training/base-training-readiness.md) | ADR-009 보존, Candidate B baseline 유지, Candidate C 실행·승격 승인 분리 제안 | 사용자 승인·Candidate C 단일 intervention 결정 시 |
| ADR-013 | [초기 Common AI Contract 소비 경계](./ADR-013-initial-common-ai-contract-consumer-boundary.md) | `draft` | 미결정 | [Project Definition](../project/overview.md), [ADR-004](./ADR-004-data-governance.md) | producer 없는 초기 resource 선택·consumer 구현 보류 제안 | Common 객체 producer와 정확한 소비 boundary 승인 시 |
| ADR-014 | [Dataset product governance와 Common 객체 ownership 경계](./ADR-014-dataset-product-governance-boundary.md) | `draft` | 미결정 | [Project Definition](../project/overview.md), [ADR-004](./ADR-004-data-governance.md), [ADR-013](./ADR-013-initial-common-ai-contract-consumer-boundary.md) | DohaMusic candidate/evidence와 DohaLM DatasetVersion·publication ownership, legacy 분리 제안 | Owner별 실제 producer와 resource-specific boundary 구현 결정 시 |
| ADR-015 | [Common DatasetVersion·DatasetManifest publication 계약](./ADR-015-dataset-version-publication-contract.md) | `draft` | 미결정 | [ADR-004](./ADR-004-data-governance.md), [ADR-013](./ADR-013-initial-common-ai-contract-consumer-boundary.md), [ADR-014](./ADR-014-dataset-product-governance-boundary.md) | canonical resource pair, validation 순서와 atomic publication 설계; 구현 영향 없음 | 독립 검증·병합 후 실제 producer·consumer와 transaction 구현 진입 시 |
| ADR-016 | [Generic Training Execution Approval 경계](./ADR-016-generic-training-execution-approval-boundary.md) | `draft` | 미결정 | [ADR-014](./ADR-014-dataset-product-governance-boundary.md), [ADR-015](./ADR-015-dataset-version-publication-contract.md), [Dataset publication 구현 계획](../data/dataset-publication-implementation-plan.md) | external issuer accountability와 process-local request-bound single-use approval 제안; 실행 영향 없음 | production issuer adapter·cross-process trust 또는 consumption ordering 변경 시 |
| ADR-017 | [Production Training Execution Issuer Trust Anchor](./ADR-017-production-training-execution-issuer-trust-anchor.md) | `draft` | 미결정 | [ADR-016](./ADR-016-generic-training-execution-approval-boundary.md), [Full Pretraining 실행 계획](../training/full-pretraining-execution-plan.md) | same-process composition-root registered adapter principal·trust anchor·typed transport·process-local replay 제안; 실행 영향 없음 | cross-process topology, durable audit/replay 또는 production revoke exact contract 결정 시 |

- [확정] 승인 ADR-001부터 ADR-010과 draft ADR-011을 등록했다.
- [제안] Open Draft PR #103이 ADR-012 번호를 사용하므로 충돌을 피하고자 Common AI Contract 소비 경계 제안을 ADR-013으로 등록했다.
- [제안] ADR-014는 특정 Common resource를 선택하지 않고 ADR-013에 선행하는 Dataset product governance ownership을 제안한다.
- [제안] ADR-015는 ADR-014의 첫 Gate로 DatasetVersion·DatasetManifest resource pair와 publication transaction을 설계하며 구현·consumer 활성화는 승인하지 않는다.
- [제안] ADR-016은 Common Dataset permission과 별개인 generic full-pretraining request·external issuer·single-use execution approval 경계를 제안하며 실제 실행은 승인하지 않는다.
- [제안] ADR-017은 ADR-016의 미결정 issuer security boundary를 same-process composition-root registration으로 제한하며 adapter 구현·CLI activation·실제 execution은 승인하지 않는다.
- [확정] ADR-002는 ADR-001의 Tiny 세부 미정 사항을 후속 결정하지만 Tiny 우선 범위 결정을 대체하지 않는다.
- [확정] deprecated ADR이 생기면 대체 ADR과 사유를 양쪽 문서 및 이 표에 기록한다.
- [확정] Foundation Model·Model Family·Domain 확장 문서는 현재 `review` 단계의 장기 제안이다. 승인된 아키텍처·데이터·평가·Gate 정책을 변경하는 구현 결정이 생길 때 별도 ADR을 작성한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-12 | [제안] ADR-017 Production Training Execution issuer principal·trust anchor·authentication boundary draft 등록 |
| 2026-08-12 | [제안] ADR-016 generic Training Execution Approval 경계 draft 등록 |
| 2026-08-12 | [제안] ADR-015 Common DatasetVersion·DatasetManifest resource와 atomic publication 계약 draft 등록 |
| 2026-08-12 | [제안] ADR-014 Dataset product governance와 Common 객체 repository ownership 경계 draft 등록 |
| 2026-08-12 | [제안] ADR-013 초기 Common AI Contract resource·consumer boundary 보류 결정 draft 등록 |
| 2026-08-05 | [제안] ADR-011 Candidate C experimental successor 재개와 실행·승격 승인 분리 draft 등록 |
| 2026-07-28 | [확정] ADR-010 DohaLM Instruct 전략·Readiness 결정 등록 |
| 2026-07-28 | [확정] ADR-009 Candidate B 공식 재평가와 현재 Base baseline 결정 등록 |
| 2026-07-28 | [확정] ADR-008 모델 단계별 EOS generation·decoding 평가 정책 승인 |
| 2026-07-28 | [제안] ADR-008 EOS generation·decoding 평가 정책 초안 등록 |
| 2026-07-28 | [확정] 장기 Model Family 제안과 승인 ADR의 경계를 명시함 |
| 2026-07-27 | [확정] ADR-007 Evaluation baseline·Quick 대표성·Candidate B 평가 계약 등록 |
| 2026-07-26 | [확정] ADR-003에 v2 Unigram 운영 승인과 재현성 판정 기준을 반영함 |
| 2026-07-23 | [확정] ADR 인덱스 문서 상태 필드와 ADR-001 상태 표현을 표준화함 |
| 2026-07-23 | [확정] ADR-006 개발 단계와 품질 게이트 등록 |
| 2026-07-23 | [확정] ADR-005 평가 및 실험 관리 정책 등록 |
| 2026-07-23 | [확정] ADR-004 데이터 거버넌스 기준 등록 |
| 2026-07-23 | [확정] ADR-001, ADR-002, ADR-003 인덱스 최초 작성 |
