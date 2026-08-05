# DohaLM Current Project Status

- 문서 상태: `review`
- 기준 시점: 2026-08-05
- 기준 브랜치: `develop`
- 기준 문서: [README](../../README.md)
- 관련 근거: [Foundation Strategy](./foundation-model-strategy.md), [Roadmap](./model-family-roadmap.md), [Evaluation Framework](../evaluation/README.md), [Service 문서](../service/dohalm-backend-mvp.md)

## 1. 판정 기준

이 문서는 저장소 코드, 테스트, 추적 문서와 기록된 로컬 실측만 현재 상태로 인정합니다. 설계 문서 존재, backend 구현,
학습 완료, 평가 완료, Runtime 통합과 배포 준비는 서로 다른 상태입니다. 세부 실험 수치는 각 결과 문서에 두고 여기서는
통합 상태만 유지합니다.

## 2. 현재 개발 우선순위

현재 구현 상태와 별개로 공식 개발 순서는 다음과 같습니다.

1. **Phase 1 — DohaLM Foundation**
   - Base 본훈련 준비: Base Training Readiness → Publish Recovery → Tokenization → Evaluation → EOS 분석
   - Candidate C: EOS 문제 해결 → Base 재학습 → Candidate C Evaluation
   - Foundation Instruct: Candidate C 기반 SFT → Evaluation → Candidate Selection
2. **Phase 2 — Runtime**
   - Qwen General Instruct v0.3 Recovery → Manifest → Runtime → Adapter
3. **Phase 3 — Application**
   - DohaMusic → Music Adapter → Lyrics → Prompt

[확정] Candidate B는 current Base baseline이자 Candidate C 비교 기준으로 유지합니다. Runtime은 삭제되지 않으며 Foundation
완료 이후 진행할 실제 서비스용 병행 트랙입니다. DohaMusic은 Runtime을 사용하는 Application입니다.

[검증 필요] 현재 승인된 ADR-010은 Candidate B 기반 Foundation Instruct 설계입니다. Candidate C 기반 SFT를 실행하려면
parent 결정을 다루는 후속 ADR이 필요합니다.

## 3. 통합 상태

### Foundation Model Track

| 구성 | 상태 | 근거와 경계 |
|---|---|---|
| Gate 0 | `approved` | 프로젝트 범위 사용자 승인 |
| Gate 1~7 | `passed` | 환경, 데이터, Tokenizer, 모델, Trainer, 실제 corpus overfit evidence |
| DohaLM-Tiny | `implemented_verified` | PyTorch 직접 구현, forward/loss/generation, 16,889,856 parameters |
| 운영 Tokenizer | `implemented_verified` | `operating-16k-v2/unigram-16k`, vocab 16,000 |
| Candidate A | `implemented_verified` | 10M token 학습 완료; historical Base baseline |
| Candidate B | `implemented_verified` | 25M token Run 0002·Full 평가 완료; current Base baseline |
| Base Training Readiness | `blocked` | [통합 Readiness](../training/base-training-readiness.md): ADR 정합성·EOS root cause·config/evaluation freeze 미완료 |
| Candidate C | `not_started` | C-1~C-5와 새 single-use 승인 전 학습 금지 |
| Evaluation Framework | `implemented_verified` | Quick·Full·EOS·position·category·stability·privacy·lineage |
| Foundation Instruct | `design_complete` | ADR-010 Candidate B parent 설계 상태 유지; Candidate C 기반 공식 목표는 후속 ADR·artifact 필요 |
| Foundation Chat·Small 이상 | `planned` | 구조·데이터·실행 승인 없음 |

Candidate B의 historical 평가 계약 판정 `evaluated_contract_not_passed`는 유지합니다. ADR-009의 현재 판정은
`approved_as_base_baseline`이며 derivative parent 적격성은 `approved_experimental`입니다. 이는 후속 학습 또는 공개 승인이 아닙니다.
Candidate B의 teacher-forced 지표는 Candidate A보다 개선됐지만 pure-greedy 생성의 EOS 종료율은 0%, maximum-length
종료율은 100%였습니다. 이 한계는 Base 진단 결과로 보존하며 숨기거나 Runtime readiness로 해석하지 않습니다.

### Phase 2 — Runtime 서비스 트랙

| 구성 | 상태 | 근거와 경계 |
|---|---|---|
| Qwen Base loader | `implemented_verified` | 고정 revision·local-only·lazy load, BF16 CUDA smoke |
| General Instruct QLoRA backend | `implemented_not_integrated` | v0.1/v0.2 학습·평가 완료 이력은 있으나 canonical 평가 적격 후보 없음 |
| Runtime / Provider Registry | `implemented_verified` | Mock, Base Qwen, fail-closed Adapter provider |
| Adapter Loader | `implementation_in_progress` | Manifest·Validator·PEFT Loader·Provider lifecycle은 mock 검증 완료; [후보 선정](../instruct/general-instruct-adapter-candidate-selection.md)은 `no_eligible_candidate`, GPU 미실행 |
| Chat API | `implemented_verified` | health/readiness/models, 일반 Chat, 오류·timeout 계약 |
| Streaming | `implemented_verified` | SSE, cancellation, semaphore, worker join |
| Prompt Engine | `design_complete` | Base Qwen 공식 chat template 적용만 구현; 독립 engine은 없음 |
| Next.js UI | `implemented_verified` | HTTP/SSE, 취소·재시도, Base Qwen Chrome E2E |

현재 서비스는 기본 `mock`, 명시적 `base-qwen` 또는 `dohalm-adapter` Provider를 사용하는 로컬 MVP입니다.
Adapter Provider는 명시된 manifest를 preflight하고 첫 요청에서 lazy load하지만 저장소에는 승인 artifact가 없습니다.
구현 사실은 유지하지만 현재 프로젝트 실행 우선순위는 Phase 1 Foundation입니다.

### Phase 3 Application과 Runtime 확장

| 구분 | 구성 | 상태 |
|---|---|---|
| Runtime 확장 | Memory, RAG, Tool Calling, Agent | `planned` |
| Application | DohaMusic → Music Adapter → Lyrics → Prompt | `planned` |
| 제외 | Docker, Kubernetes, Cloud, 운영 배포 | `out_of_scope` |

DohaMusic의 곡 기획·가사·음악 생성 prompt는 General Instruct Runtime의 응용 후보입니다. 실제 오디오·보컬·MIDI 생성은
DohaLM의 책임이 아니며 별도 음악 생성 모델의 범위입니다.

## 4. QLoRA와 Instruct 현재 상태

두 Instruct 계보를 혼동하지 않습니다.

| 계보 | Parent | 현재 상태 | Runtime 연결 |
|---|---|---|---|
| Foundation Instruct Tiny v1 | Candidate B Final | 설계 완료, 학습·artifact 미생성 | 없음 |
| Runtime General Instruct v0.1 | Qwen2.5-1.5B-Instruct | 학습·평가 완료; decoding hard blocker 통과 후보 없음 | 부적격, manifest 없음 |
| Runtime General Instruct v0.2 | 같은 Qwen Base | 2 epoch·1,298 step·recovery 완료; eligible candidate 0건 | 부적격, deployment ready 아님 |
| Runtime General Instruct v0.3 | 같은 Qwen Base 후보 | `ready_for_recovery_design`; V03-R1 evidence와 V03-R2 scanner·review·exclusion 계약 synthetic 검증 완료, 실제 data evidence pending, fresh Tokenization 미승인 | 없음 |

저장소에는 외부 학습 artifact 자체가 없으므로 Runtime은 경로·fingerprint·승인 검증 없이는 Adapter를 자동 탐색하지 않습니다.
v0.1/v0.2의 학습 완료 기록도 `Adapter Loader 완료`나 `deployment_ready=true`로 승격하지 않습니다. Loader는 Adapter 학습에
사용한 동일 Qwen Base revision, Tokenizer와 Chat Template의 일치를 강제해야 합니다.

V03-R1 구현과 실제 evidence 상태는 다음처럼 분리합니다.

```yaml
v03_r1_evidence_schema: implemented_synthetic_validated
v03_r1_atomic_writer: implemented_synthetic_validated
v03_r1_bundle_finalizer: implemented_synthetic_validated
v03_r2_scanner_contract: implemented_synthetic_validated
v03_r2_review_contract: implemented_synthetic_validated
v03_r2_exclusion_builder: implemented_synthetic_validated
v03_r3_identity_schema: implemented_synthetic_validated
v03_r3_ledger_validator: implemented_synthetic_validated
v03_r3_reservation_writer: implemented_synthetic_validated
v03_r4_approval_schema: implemented_synthetic_validated
v03_r4_approval_lifecycle: implemented_synthetic_validated
v03_r5_request_schema: implemented_synthetic_validated
v03_r5_request_writer: implemented_synthetic_validated
actual_v03_run_reserved: false
actual_v03_approval_issued: false
actual_v03_request_created: false
actual_v03_evidence_bundle: not_created
actual_pii_scan: not_started
actual_safety_scan: not_started
actual_leakage_scan: not_started
actual_review_evidence: not_created
v03_data_evidence: pending
v03_fresh_tokenization: not_approved
execution_allowed: false
```

위 구현 상태는 synthetic fixture에 대한 schema·writer·finalizer 검증만 뜻합니다. 실제 license·PII·Safety·Leakage
evidence, readiness 승인, Dataset payload scan, Run 예약, Tokenization 또는 GPU 실행을 뜻하지 않습니다.

## 5. 데이터와 공개 경계

- AIHUB-71748은 학생·비상업 연구 범위이며 상업 이용과 원본·파생 데이터 재배포는 미승인입니다.
- Foundation Base와 Runtime SFT 데이터 계보는 분리합니다.
- AIHUB-71748 SFT Processing Run 0015와 v0.1 Tokenization 완료 기록은 후속 학습·재처리의 포괄 승인으로 사용하지 않습니다.
- 모델, checkpoint, Adapter, Tokenizer와 Dataset publication은 각각 별도 승인 대상입니다.

## 6. 완료된 현재 기능과 남은 Runtime 작업

현재 사용자 경로는 다음까지 동작합니다.

```text
Browser → Next.js → FastAPI → BaseQwenProvider → local Qwen snapshot
                  └→ DohaLMAdapterProvider → manifest/validator/PEFT loader
                  ↘ SSE streaming / cancellation / retry
```

Phase 2 Runtime을 끝내려면 다음이 남습니다. 이 목록은 Phase 1 Foundation보다 앞선 현재 우선순위가 아닙니다.

1. 배포 후보 General Instruct Adapter를 명시적으로 선정하고 Adapter config·weight, Base·Tokenizer·Chat Template,
   generation config와 평가 fingerprint를 하나의 manifest로 고정
2. 승인 후보와 exact PEFT dependency를 고정하고 구현된 Loader로 실제 Base/Tokenizer/Adapter 조합과 GPU 검증
3. Adapter를 통한 일반 Chat·SSE·취소·unload 회귀 및 GPU·브라우저 smoke
4. Prompt Engine의 template/version/system policy 경계 구현

## 7. 과거 계획과 보존 기록

- Candidate A를 current baseline으로 보던 문서는 historical context이며 현재 기준은 Candidate B입니다.
- Candidate B 첫 Run 0001 실패와 lexicographic checkpoint 정렬 버그는 실패 계보로만 보존합니다.
- AIHUB-71748 Processing Run 0001~0014의 preflight·retirement 과정은 감사 이력이며 현재 실행 계획이 아닙니다.
- v0.1 Windows QLoRA stall과 v0.2 terminal checkpoint failure는 원인·복구 계약을 위한 이력이며 자동 retry 근거가 아닙니다.
- 기존 Model Family의 Code·SQL·Recruit·Game·Vision 계획은 현재 1~3차 실행 순서에서 제외된 장기 후보입니다.

## 8. 다음 권장 작업

1. ADR-009의 `candidate_c: not_required`와 새 공식 우선순위 충돌을 해소하는 Candidate C 후속 ADR 검토
2. EOS root cause 가설·변경 범위와 Candidate C Evaluation Gate 승인
3. Dataset·Tokenizer·Training Config를 Candidate C identity로 freeze해 C-1~C-4 완료
4. 별도 승인 뒤 exact config의 C-5 GPU Smoke 수행; 이 전에는 Candidate C 학습 금지
5. Candidate C 평가 뒤 Foundation Instruct parent 변경을 위한 후속 ADR 검토
6. Phase 1 완료 뒤 Runtime, Runtime 완료 뒤 DohaMusic 진행

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | Base Training Readiness `blocked`, Candidate C `not_started`와 C-1~C-5 선행 조건·다음 Task 반영 |
| 2026-08-05 | 구현 상태를 유지하면서 Foundation 우선 공식 순서, Candidate C·Foundation Instruct 핵심 목표, Runtime 후속 서비스 트랙과 DohaMusic Application 위치를 반영 |
| 2026-08-05 | V03-R4 Tokenization Approval lifecycle과 V03-R5 Runtime Execution Request를 synthetic-only로 구현·검증; 실제 Approval·Request·Run 예약·실행은 수행하지 않음 |
| 2026-08-05 | V03-R3 Run Identity schema·ledger validator·reservation writer synthetic 검증 완료; 실제 ledger migration·Run 예약·Approval·Request·실행은 수행하지 않음 |
| 2026-08-05 | V03-R2 scanner·review·exclusion 및 R1 payload 변환 synthetic 검증 완료; actual scan `not_started`, review evidence `not_created`, execution 금지 유지 |
| 2026-08-05 | V03-R1 strict evidence schema·loader, atomic no-replace writer, bundle finalizer synthetic 검증 완료; actual bundle `not_created`, data evidence `pending`, execution 금지 유지 |
| 2026-08-05 | V03-1·V03-2 recovery contract 설계 완료, license evidence 부족·data evidence pending·fresh Tokenization 미승인 상태 반영 |
| 2026-08-05 | v0.3 Dataset 생성·checksum 유효, canonical tokenized artifact 부재와 recovery-design 상태 반영 |
| 2026-08-05 | v0.1~v0.3 후보 조사에서 `no_eligible_candidate` 판정, manifest·GPU·Provider smoke 미실행 상태 반영 |
| 2026-08-05 | Adapter Provider startup preflight·lazy load·Chat/SSE·shutdown mock 통합과 실제 artifact/GPU 미검증 상태 반영 |
| 2026-08-05 | local-only PEFT Adapter Loader mock 검증 완료와 실제 Adapter/GPU·Provider 연결 미검증 상태 반영 |
| 2026-08-05 | Adapter Manifest·strict loader·정적 Artifact Validator synthetic 검증 완료와 PEFT Loader·Runtime 연결 미착수 상태 반영 |
| 2026-08-04 | General Instruct Adapter Runtime 설계 완료와 Loader 구현 미착수 상태 반영 |
| 2026-08-04 | 원격 7383f84의 Candidate B 생성 한계, Qwen compatibility와 DohaMusic 오디오 범위를 통합 |
| 2026-08-04 | Foundation과 Runtime 상태 분리, Base Qwen/API/Streaming 현행 구현 및 Adapter Loader 미구현 반영 |
| 2026-07-29 | Gate 0~7과 Candidate A/B·Evaluation 통합 snapshot 작성 |
