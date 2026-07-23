# DohaLM 버전 계획

- 문서 상태: `review`
- 마지막 검토일: 2026-07-23
- 선행 문서: [개발 로드맵](../quality/development-roadmap.md), [Definition of Done](../governance/definition-of-done.md), [테스트 전략](../quality/test-strategy.md), [위험 등록부](../governance/risk-register.md)
- 후속 문서: 실제 릴리스 계획 및 태그 정책 `[검증 필요]`
- 구현 전 필수 여부: 릴리스 계획 수립 시 필수

## 1. 목적과 적용 원칙

- [확정] 이 문서는 구현 순서와 품질 게이트를 버전 이정표로 연결한다.
- [확정] 아래 버전은 계획상 권장 이정표이며, 실제 Git 태그나 릴리스가 생성되었다는 뜻이 아니다.
- [확정] 버전 완료는 [Definition of Done](../governance/definition-of-done.md)과 해당 단계 게이트를 모두 통과한 경우에만 선언한다.
- [확정] `DohaLM-Tiny`의 재현 가능한 학습 파이프라인을 먼저 완성한 뒤 추론 API와 채팅 UI를 진행한다.
- [검증 필요] 실제 배포 전 버전 규칙, 변경 로그 형식, 호환성 보장 범위는 별도로 승인한다.

## 2. 권장 버전 이정표

| 버전 | 목적 | 포함 범위 | 제외 범위 | 완료 조건 | 필수 문서 | 필수 테스트 | 예상 릴리스 산출물 |
|---|---|---|---|---|---|---|---|
| `v0.1` | 문서·환경 기반 확립 | 프로젝트 기준 문서, 저장소 구조, 개발 규칙, 환경 진단, 설정 loader·validation, 경로 정책, 기본 logging, CLI | 데이터 처리와 모델 구현 | Gate 0 `approved`, Gate 1 `passed` | [프로젝트 개요](./overview.md), [범위와 목표](./scope-and-goals.md), [개발 규칙](../governance/development-rules.md), [문서 인덱스](../index.md), [ADR 인덱스](../decisions/README.md), [저장소 구조](../architecture/repository-structure.md), [산출물 및 설정 정책](../governance/artifact-and-configuration-policy.md), [Definition of Ready](../governance/definition-of-ready.md), [Definition of Done](../governance/definition-of-done.md), [테스트 전략](../quality/test-strategy.md), [위험 등록부](../governance/risk-register.md), [버전 계획](./version-plan.md), [Codex 작업 절차](../governance/codex-workflow.md) | 자동 테스트 43개, CPU·CUDA smoke, CLI·설정·경로·artifact 검사 | 승인된 기준 문서, 환경 snapshot과 Gate 1 검증 기록 |
| `v0.2` | 최소 데이터 파이프라인 | UTF-8 TXT·JSONL reader, schema validation, NFC 정규화, SHA-256 checksum·ID, exact dedup, deterministic group split, leakage 검사, manifest·statistics·lineage, CLI와 synthetic fixture 테스트 | 실제 외부 학습 데이터, 대규모 수집·streaming, near dedup과 tokenizer | Gate 2 `passed` | [Phase 1 데이터 계약](../data/phase1-data-contract.md), [데이터 전략](../data/data-strategy.md), [데이터 전처리](../data/preprocessing.md), [데이터셋 등록부](../data/dataset-registry.md), [데이터 라이선스 정책](../data/data-license-policy.md), [데이터 품질 체크리스트](../data/data-quality-checklist.md), [데이터 분할 및 누수 정책](../data/data-split-and-leakage-policy.md), ADR-004 | 전체 75개 테스트, CLI validate/build, 원본 불변·누수·결정론·atomic write 검사 | 검증 revision과 synthetic fixture manifest 근거 |
| `v0.3` | 토크나이저 확립 | SentencePiece Unigram 학습·저장·복원·특수 토큰 | 모델 학습 | Gate 3 통과 | [토크나이저 설계](../training/tokenizer-design.md), ADR-003 | round-trip, ID, OOV·coverage 검사 | 버전 고정 토크나이저와 메타데이터 |
| `v0.4` | 모델 구성요소 검증 | embedding, attention, FFN, block, normalization | 전체 학습 루프 | Gate 4 통과 | [모델 아키텍처](../architecture/model-architecture.md), ADR-002 | shape, causal mask, 파라미터 구성요소 단위 테스트 | 구성요소 테스트 결과 |
| `v0.5` | 모델 통합과 생성 검증 | DohaLM-Tiny 통합, loss 연결, 자기회귀 생성 | 장시간 사전학습 | Gate 5 통과 | [모델 아키텍처](../architecture/model-architecture.md), `11-inference-design.md` 초안 | 파라미터 수, forward/backward, weight tying, 생성 smoke | 통합 모델 검증 기록 |
| `v0.6` | 학습·체크포인트 기반 | FP16, 누적, clipping, 저장·복원·재개 | 본 사전학습 | Gate 6 통과 | [사전학습 계획](../training/pretraining-plan.md), [실험 관리](../training/experiment-management.md), [GPU 메모리 전략](../training/gpu-memory-strategy.md), [산출물 및 설정 정책](../governance/artifact-and-configuration-policy.md), [재현성 정책](../quality/reproducibility-policy.md) | AMP, optimizer step, checkpoint round-trip·resume | 재개 가능한 학습 smoke 산출물 |
| `v0.7` | Tiny overfit 검증 | 극소 데이터 과적합과 loss 감소 확인 | 장시간 학습 | Gate 7 통과 | [사전학습 계획](../training/pretraining-plan.md), [평가 계획](../evaluation/evaluation-plan.md), [테스트 체크리스트](../quality/testing-checklist.md), [실험 템플릿](../training/experiment-template.md) | tiny overfit, NaN/Inf, 재현성 검사 | overfit 실험 기록과 체크포인트 |
| `v0.8` | Tiny 사전학습 | 승인 데이터와 token budget으로 사전학습 | SFT와 서비스 | Gate 8 승인 후 실행, 사전 정의 완료 조건 충족 | [사전학습 계획](../training/pretraining-plan.md), [평가 계획](../evaluation/evaluation-plan.md), [실험 관리](../training/experiment-management.md), [GPU 메모리 전략](../training/gpu-memory-strategy.md), [재현성 정책](../quality/reproducibility-policy.md), [실험 템플릿](../training/experiment-template.md) | validation perplexity, checkpoint 복구, VRAM 실측 | DohaLM-Tiny 기반 체크포인트와 실험 보고서 |
| `v0.9` | SFT 검증 | 승인된 질문·답변 데이터, 대화 템플릿, SFT | API·UI | Gate 9 통과 | [SFT 계획](../training/sft-plan.md), [평가 계획](../evaluation/evaluation-plan.md), [생성 평가](../evaluation/generation-evaluation.md), [실험 템플릿](../training/experiment-template.md) | template, loss mask, 생성 품질·회귀 검사 | SFT 체크포인트와 평가 기록 |
| `v1.0` | 재현 가능한 DohaLM-Tiny 완성 | 데이터 계보부터 평가까지 재현 가능한 전체 핵심 파이프라인 | 서비스·외부 제출 | 모든 Tiny 필수 Done 조건 충족 | 핵심 설계·데이터·학습·평가·품질 문서 | 전체 필수 회귀·GPU 검증 | 모델 카드 초안, 체크포인트, tokenizer, 설정, 평가·재현 기록 |
| `v1.1` | 추론 API | FastAPI 모델 로딩·생성 계약 | 채팅 UI | Gate 10의 API 조건 통과 | `11-inference-design.md`, `12-api-specification.md`, `19-deployment-plan.md` 초안 | API schema, 오류·동시성·로딩 smoke | 로컬 추론 API 릴리스 후보 |
| `v1.2` | 채팅 UI | Next.js 채팅 화면과 API 연결 | 공개 배포 보장 | Gate 10의 UI 조건 통과 | `12-api-specification.md`, `13-frontend-specification.md`, `19-deployment-plan.md` | UI 흐름, 오류 표시, API 통합 검사 | 로컬 채팅 애플리케이션 릴리스 후보 |
| `v1.3` | 벤치마크·모델 카드 | 벤치마크 결과 정리, 모델 카드, 제출 가능성 검토 | 제출 자체와 성능 보장 | Gate 11 사용자 승인 및 정책 확인 | `20-leaderboard-strategy.md`, [Benchmark 정책](../evaluation/benchmark-policy.md), [생성 평가](../evaluation/generation-evaluation.md), `19-deployment-plan.md` | benchmark 재현성, 라이선스·공개 범위 검사 | 모델 카드와 벤치마크 보고서 |

- [확정] `v0.1` 권장 이정표의 Phase 0 구현·검증과 Gate 0·1 조건은 충족했다. 이는 실제 Git 태그나 릴리스가 생성되었다는 뜻이 아니다.
- [확정] `v0.2` 권장 이정표의 Phase 1 구현·검증과 Gate 2 조건은 충족했다. 실제 Git 태그나 릴리스는 생성하지 않았다.

## 3. 버전 승격 규칙

- [확정] 이전 버전의 필수 게이트가 실패한 상태에서 다음 버전을 완료 처리하지 않는다.
- [확정] 문서 승인과 구현 완료를 구분하며, `approved` 문서만으로 버전 구현 완료를 선언하지 않는다.
- [확정] 장시간 학습, 외부 공개, 배포, 리더보드 제출은 사용자의 명시적 승인을 별도로 받는다.
- [확정] 실패 시 [개발 로드맵](../quality/development-roadmap.md)의 복구 경로와 [위험 등록부](../governance/risk-register.md)의 대응을 적용한다.
- [검증 필요] 각 버전의 실제 일정, 담당자, 정량 합격 임계값은 해당 구현 작업 전에 정한다.

## 4. 핵심 미결정 사항

- [검증 필요] Semantic Versioning 적용 범위와 pre-release 표기 방식
- [검증 필요] 체크포인트·토크나이저·API의 호환성 보장 범위
- [검증 필요] 릴리스 산출물 저장소와 보존 기간
- [검증 필요] `v1.0` 이후 DohaLM-Small을 별도 major/minor 버전으로 관리할지 여부

## 5. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] Gate 2 승인에 따라 v0.2 권장 이정표에 DATA-001~016과 75개 테스트·CLI 검증 범위를 반영함; tag·release는 생성하지 않음 |
| 2026-07-23 | [확정] Gate 1 승인에 따라 v0.1 권장 이정표에 Phase 0 기반·43개 테스트·CPU/CUDA smoke 근거를 반영함 |
| 2026-07-23 | [확정] 단계별 권장 버전 이정표와 승격 원칙 초안 작성 |
