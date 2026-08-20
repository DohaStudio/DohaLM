# DohaLM Architecture Decision Records

- 문서 상태: `review`
- 마지막 검토일: 2026-08-20

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
| ADR-018 | [Composition-root-owned Training Execution Decision Source](./ADR-018-composition-root-owned-training-execution-decision-source.md) | `draft` | 미결정 | [ADR-016](./ADR-016-generic-training-execution-approval-boundary.md), [ADR-017](./ADR-017-production-training-execution-issuer-trust-anchor.md) | same-process trusted decision submission·single-use claim·concurrency·retry 경계 제안; 실행 영향 없음 | durable decision supply, cross-process orchestration 또는 authorization lifecycle 변경 시 |
| ADR-019 | [Production Full Pretraining Host와 Trusted Decision Input](./ADR-019-production-full-pretraining-host-and-trusted-decision-input.md) | `draft` | 미결정 | [ADR-016](./ADR-016-generic-training-execution-approval-boundary.md), [ADR-017](./ADR-017-production-training-execution-issuer-trust-anchor.md), [ADR-018](./ADR-018-composition-root-owned-training-execution-decision-source.md) | non-CLI same-process Host·trusted input·7-field authority·restart/crash 경계 제안; 실행 영향 없음 | production resolver·durable journal·Host 구현과 별도 activation 승인 시 |
| ADR-020 | [Production Training Orchestration Ownership Seams](./ADR-020-production-training-orchestration-ownership-seams.md) | `draft` | 미결정 | [ADR-019](./ADR-019-production-full-pretraining-host-and-trusted-decision-input.md), [Full Pretraining 실행 계획](../training/full-pretraining-execution-plan.md) | construction-bound prerequisite resolver·immutable resolved schema·package-private backend lifecycle seam 제안; 실행 영향 없음 | PR S 구현·production adapters·별도 activation 승인 전 |
| ADR-021 | [Production Training Adapters와 Durable Journal Authority](./ADR-021-production-training-adapters-and-durable-journal.md) | `approved` | 2026-08-13 | [ADR-019](./ADR-019-production-full-pretraining-host-and-trusted-decision-input.md), [ADR-020](./ADR-020-production-training-orchestration-ownership-seams.md), [ADR-022](./ADR-022-c1-ephemeral-postgresql-test-image-security-policy.md) | supported PostgreSQL authority event/projection·durable journal과 C1→Corrective C1.1→C1.2 alignment→C2→C3→Activation 순서 승인; C1/C1.1 병합 | C1.2/C2 contract 독립 Gate, C2/C3 독립 Gate, image security 결정과 별도 activation 승인 시 |
| ADR-022 | [C1 Ephemeral PostgreSQL Test Image Security Policy](./ADR-022-c1-ephemeral-postgresql-test-image-security-policy.md) | `approved` | 2026-08-15 | [ADR-021](./ADR-021-production-training-adapters-and-durable-journal.md), [종료된 16.15 record](../security/c1-postgres-image/C1-PG16-ALPINE-1615-20260814-01/evidence-summary.md), [current accepted Decision Packet](../security/c1-postgres-image/C1-PG16-ALPINE-1615-20260815-02/evidence-summary.md) | A/B/C drift 정책 승인; raw C2/H21·adjudicated 7·residual C1/H15 Option B를 local/CI isolated ephemeral C1 test로 30일 승인 | early termination·만료·C1 독립 검증 Gate |
| ADR-023 | [C1 Repository-Owned PostgreSQL Client Runner Supply Chain](./ADR-023-c1-repository-owned-postgresql-client-runner-supply-chain.md) | `approved` | 2026-08-15 | [ADR-021](./ADR-021-production-training-adapters-and-durable-journal.md), [ADR-022](./ADR-022-c1-ephemeral-postgresql-test-image-security-policy.md) | Practical Profile에서는 official `psycopg[binary] 3.3.4` 직접 소비; repository-owned runner·GHCR는 선택 hardening | C1 독립 Gate; C2/C3·Activation 별도 승인 |
| ADR-024 | [AI Music Director 제품 방향과 지속 학습 경계](./ADR-024-ai-music-director-product-boundary.md) | `draft` | 미결정 | [Project Definition](../project/overview.md), [ADR-014](./ADR-014-dataset-product-governance-boundary.md), [ADR-021](./ADR-021-production-training-adapters-and-durable-journal.md) | current Common ownership을 보존한 product direction·Foundation/product learning 분리 제안; 실행 영향 없음 | 제품 방향·cross-repository mapping·promotion 계약 승인 시 |
| ADR-025 | [DatasetVersion Proposal Authority 계약](./ADR-025-dataset-version-proposal-authority-contract.md) | `draft` | 미결정 | [ADR-014](./ADR-014-dataset-product-governance-boundary.md), [ADR-015](./ADR-015-dataset-version-publication-contract.md), [제품 지속 학습 경계](../project/ai-music-director-continuous-learning.md) | mandatory atomic create·replay·conflict와 proposal-time current evidence 재검증 port 제안; persistence·publication·Training 없음 | architecture 승인 또는 proposal lifecycle 의미 변경 시 |

- [확정] 승인 ADR-001부터 ADR-010과 ADR-021~023, draft ADR-011·013~020·024·025를 등록했다.
- [제안] Open Draft PR #103이 ADR-012 번호를 사용하므로 충돌을 피하고자 Common AI Contract 소비 경계 제안을 ADR-013으로 등록했다.
- [제안] ADR-014는 특정 Common resource를 선택하지 않고 ADR-013에 선행하는 Dataset product governance ownership을 제안한다.
- [제안] ADR-015는 ADR-014의 첫 Gate로 DatasetVersion·DatasetManifest resource pair와 publication transaction을 설계하며 구현·consumer 활성화는 승인하지 않는다.
- [제안] ADR-016은 Common Dataset permission과 별개인 generic full-pretraining request·external issuer·single-use execution approval 경계를 제안하며 실제 실행은 승인하지 않는다.
- [제안] ADR-017은 ADR-016의 미결정 issuer security boundary를 same-process composition-root registration으로 제한하며 adapter 구현·CLI activation·실제 execution은 승인하지 않는다.
- [제안] ADR-018은 ADR-017 adapter에 construction-time 결속되는 composition-root-owned DecisionSource와 trusted submission·authorization claim lifecycle을 정의하며 production 구현은 승인하지 않는다.
- [제안] ADR-019는 production full-pretraining object graph의 non-CLI Host와 trusted decision input·field authority·crash 경계를 정의하며 Host 구현이나 실제 execution은 승인하지 않는다.
- [제안] ADR-020은 ADR-019 후속으로 prerequisite resolution과 approval-consume/backend-entry 관찰의 ownership seam을 정의하며 구현이나 실제 execution을 승인하지 않는다.
- [확정] ADR-021은 PR #126 사용자 승인·squash merge로 production authority event/current projection, approved/denied decision, durable journal evidence·recovery와 C1/C2/C3 순서를 승인했으며 dependency·adapter·composition 구현이나 실제 execution은 승인하지 않는다.
- [확정] ADR-022의 16.14 exact-image risk acceptance는 fixed 16.15 image 공개로 조기 종료됐고 historical approval만 보존한다.
- [확정] 16.15의 이전 accepted record는 severity/advisory drift로 종료됐고 재사용할 수 없다.
- [확정] 새 Option B record는 raw C2/H21·adjudicated 7·residual C1/H15를 결속하고 DDORINY 승인 시각부터 정확히 30일간
  exact manifest의 local/CI isolated ephemeral C1 test만 허용한다.
- [확정] ADR-023 Practical Security Profile amendment는 official `psycopg[binary] 3.3.4` 직접 소비를 C1에 허용하고
  repository-owned runner·GHCR를 선택 hardening으로 재분류한다. C2/C3·Production Activation·실제 Training은 미승인이다.
- [제안] ADR-024는 PR #103의 유효한 제품 방향만 현행 Common ownership과 구현 상태에 맞춰 이관하고 Foundation training과 product/adapter continuous learning을 분리한다. 실행·Training·promotion은 승인하지 않는다.
- [제안] ADR-025는 DatasetVersion proposal의 authoritative lookup을 생략 불가능한 atomic compare-and-create port로 고정하고 current Rights·Eligibility evidence를 매 adjudication마다 재검증한다.
- [확정] ADR-002는 ADR-001의 Tiny 세부 미정 사항을 후속 결정하지만 Tiny 우선 범위 결정을 대체하지 않는다.
- [확정] deprecated ADR이 생기면 대체 ADR과 사유를 양쪽 문서 및 이 표에 기록한다.
- [확정] Foundation Model·Model Family·Domain 확장 문서는 현재 `review` 단계의 장기 제안이다. 승인된 아키텍처·데이터·평가·Gate 정책을 변경하는 구현 결정이 생길 때 별도 ADR을 작성한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-21 | [제안] DatasetVersion proposal의 atomic create·replay·conflict와 current evidence 재검증 계약을 ADR-025로 등록 |
| 2026-08-20 | [제안] stale PR #103에서 현행 authority와 양립하는 AI Music Director 방향을 ADR-024로 이관하고 Foundation/product learning 경계를 등록 |
| 2026-08-15 | [확정] ADR-021 Corrective C1.1 reservation architecture, transaction ownership와 upgrade/logical-restore contract 동기화 |
| 2026-08-15 | [확정] C1 Practical Security Profile로 official Psycopg binary 직접 소비와 loopback-only local fixture를 승인하고 custom runner를 선택 hardening으로 재분류 |
| 2026-08-15 | [확정] ADR-023과 current PostgreSQL 16.15 Option B risk record 사용자 승인, C1 구현 Draft 착수 권한을 동기화 |
| 2026-08-15 | [제안] ADR-023 repository-owned C1 PostgreSQL client runner 공급망과 GHCR same-digest parity 계약 등록 |
| 2026-08-15 | [제안] 이전 16.15 authorization 종료, raw C2/H21·adjudicated 7·residual C1/H15 새 proposed record와 Psycopg provenance blocker 등록 |
| 2026-08-14 | [확정] PostgreSQL 16.15 exact Option B 승인과 30일 local/CI ephemeral image test 범위 동기화; C1 구현·Psycopg는 별도 Gate 유지 |
| 2026-08-14 | [제안] 16.14 record 조기 종료와 16.15 proposed/unapproved Decision Packet·승인 전 fail-closed Gate 동기화 |
| 2026-08-14 | [확정] ADR-022 security evidence를 세 CVE adjudication과 layered manifest로 보완 |
| 2026-08-14 | [확정] ADR-022 선택지 B와 C1-PG16-ALPINE-20260814-01 immutable risk-acceptance record 승인 |
| 2026-08-13 | [제안] ADR-022 C1 Ephemeral PostgreSQL Test Image Security Policy Decision Packet 등록 |
| 2026-08-13 | [확정] PR #126 승인·squash merge provenance에 맞춰 ADR-021 상태를 `approved`로 동기화 |
| 2026-08-13 | [제안] ADR-021 C1 잔여 Gate의 policy provenance ordering, exact producer identifier, state effective-time·supersession, family envelope NOT NULL 계약 확정 |
| 2026-08-13 | [제안] ADR-021 journal·phase-event exact schema, UUID authority identity와 commit outcome 계약 확정 |
| 2026-08-13 | [제안] ADR-021의 authority event/projection, journal evidence, transaction failure, C1/C2/C3와 accountable role 계약 보완 |
| 2026-08-13 | [제안] ADR-021 Production Training Adapters와 Durable Journal Authority contract draft 등록 |
| 2026-08-13 | [제안] ADR-020 Production Training Orchestration Ownership Seams contract draft 등록 |
| 2026-08-13 | [제안] ADR-019 Production Full Pretraining Host와 Trusted Decision Input contract draft 등록 |
| 2026-08-12 | [제안] ADR-018 Composition-root-owned Training Execution Decision Source contract draft 등록 |
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
