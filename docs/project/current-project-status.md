# DohaLM Current Project Status

- 문서 상태: `review`
- 마지막 검토일: 2026-08-05
- 기준 시점: 현재 `develop` 구현·문서·검증 근거
- 프로젝트 정의: [DohaLM Project Definition](./overview.md)

## 1. 판정 기준

코드 존재, synthetic·mock 검증, 실제 artifact 검증, model approval과 publication approval을 서로 다른 상태로 기록합니다.
현재 우선순위는 Phase 1이지만 이미 존재하는 Phase 2·3 구현 이력을 낮추거나 삭제하지 않습니다.

```text
project_definition: reusable_llm_model_provider
phase_1: foundation_model_development
phase_2: reusable_model_and_runtime
phase_3: distribution_and_integration
dohamusic_role: external_reference_application
cloud_deployment: out_of_scope
```

## 2. 통합 산출물 상태

| 산출물 | Phase | 현재 상태 |
|---|---|---|
| DohaLM-Tiny Foundation Base | Phase 1 | Candidate B current baseline |
| Candidate C | Phase 1 | contract design, execution blocked |
| Foundation Instruct | Phase 1 | planned, parent decision pending |
| General Instruct Adapter | Phase 2 | no eligible candidate |
| Adapter Runtime | Phase 2 | code implemented, actual artifact unavailable |
| REST/Streaming API | Phase 3 | MVP implemented |
| Python SDK | Phase 3 | not_started |
| Versioned Model Release | Phase 3 | planned |
| DohaMusic integration | Reference Application | planned, separate repository |

## 3. Phase 1 — Foundation Model Development

| 구성 | 상태 | 근거와 제한 |
|---|---|---|
| Dataset·Tokenizer pipeline | `implemented_verified` | lineage·split·packing·운영 16k tokenizer 계약과 historical evidence 보존 |
| DohaLM-Tiny·Trainer | `implemented_verified` | 직접 구현 decoder, checkpoint/resume, 실제 corpus overfit |
| 기존 Gate 1~7 | `passed` | 저장소 Foundation capability와 historical Tiny 검증; Candidate C gate 자동 통과 아님 |
| Candidate A | historical baseline | 기존 artifact·평가 판정 보존 |
| Candidate B | current baseline | ADR-009 승인; pure greedy EOS·loop 제한도 함께 보존 |
| Evaluation Framework | `implemented_verified` | Quick·Full·EOS·position·category·stability·privacy·lineage |
| Base Training Readiness review | `completed` | A/B·EOS·Dataset·Tokenizer·Config 근거 검토 완료 |
| Candidate C contract design | `completed` | C-1~C-8, EOS 가설, freeze·평가·selection 계약 작성 |
| Candidate C readiness | `blocked` | ADR-011 draft, 단일 주가설·freeze·resolved config·실행 승인 미완료 |
| Candidate C execution | `false / not_started` | GPU Smoke·Training 실행 없음 |
| Foundation Instruct | `planned` | ADR-010은 Candidate B parent 승인; 차기 parent 결정 pending |

```text
base_training_readiness_review: completed
candidate_c_contract_design: completed
candidate_c_readiness: blocked
candidate_c_execution_allowed: false
candidate_c_training_started: false
```

### EOS Diagnostic 상태

| 범위 | 상태 | 의미 |
|---|---|---|
| Candidate B EOS 현상·기존 진단 | `confirmed` | teacher-forced 지표 개선과 pure greedy EOS 0%·장기 loop 현상 확인 |
| 단일 root cause | `unconfirmed` | 관측 현상을 하나의 원인으로 확정하지 않음 |
| EOS-DIAG-R1 artifact system | `implemented_synthetic_verified` | strict 18-artifact schema·validator·writer·completion evidence |
| EOS-DIAG-R2 identity·matrix freezer | `implemented_synthetic_verified` | immutable explicit-input identity, generation matrix, R1 payload 연결 |
| 실제 Candidate B identity freeze | `incomplete` | checkpoint manifest fingerprint, prompt identity, source/backend/dependency evidence 미동결 |
| EOS Diagnostic Gate 1·2 | `not_passed` | 실제 artifact·승인 입력의 gate evidence 없음 |

R1/R2는 실제 checkpoint load, tokenizer load, GPU, generation 또는 EOS 계산 완료를 의미하지 않습니다.

## 4. Phase 2 — Reusable Model and Runtime

| 구성 | 상태 | 근거와 제한 |
|---|---|---|
| Qwen Base provider | `implemented_verified` | 고정 local snapshot, lazy load, Base Qwen local E2E |
| General Instruct QLoRA 이력 | `implemented_not_integrated` | v0.1/v0.2 학습·평가와 v0.3 recovery 기록 보존 |
| General Instruct Adapter candidate | `no_eligible_candidate` | 이용조건·artifact·평가 evidence를 모두 충족한 후보 없음 |
| Adapter Manifest·Validator | `implemented_verified` | strict·fail-closed identity 검증 |
| PEFT Loader·Provider lifecycle | `implemented_mock_verified` | mock 통합 완료, 실제 승인 Adapter·GPU READY 미검증 |
| Adapter Runtime | `unavailable_without_approved_artifact` | 코드 구현과 실제 artifact 사용 가능성을 분리 |
| Prompt serialization | `implemented_partial` | Qwen chat template 사용; 독립 prompt policy engine은 미구현 |

Phase 2는 Phase 1 Candidate B/C의 자동 파생물이 아닙니다. Qwen lineage가 별도로 진행될 수 있으며 양쪽은 manifest,
evaluation evidence와 versioning 계약을 공유합니다.

## 5. Phase 3 — Distribution and Integration

| 구성 | 상태 | 근거와 제한 |
|---|---|---|
| FastAPI REST API | `MVP implemented` | chat, health, readiness, models |
| SSE Streaming | `MVP implemented` | timeout, cancellation, worker cleanup |
| Local validation UI | `implemented_verified` | Base Qwen browser E2E; 외부 Reference Application 아님 |
| Python SDK | `not_started` | 공개 surface·versioning 미정 |
| Integration Guide | `planned` | API·SDK·manifest 호환 계약 필요 |
| Versioned Model Release | `planned` | eligible artifact·evaluation·release 승인 필요 |
| Cloud deployment | `out_of_scope` | Docker·Kubernetes·Cloud 운영 제외 |

## 6. Reference Applications

DohaMusic integration은 `planned, separate repository`입니다. DohaMusic의 UI·비즈니스 로직·음악 프로젝트·가사 편집·개인화는
외부 저장소가 소유하고, DohaLM은 model loading·inference·streaming·prompt processing·Adapter·versioning을 제공합니다.
이 저장소에는 DohaMusic 구현이 없습니다.

## 7. 공개와 데이터 경계

- AIHUB-71748은 학생·비상업 연구 범위이며 재배포·상업 이용은 승인되지 않았습니다.
- model, checkpoint, tokenizer, dataset, Adapter publication은 각각 별도 승인 대상입니다.
- 실제 로컬 경로, 비밀, 대용량 artifact를 Git이나 문서에 포함하지 않습니다.
- 학습 완료, model selection, Runtime READY와 release 승인을 동일 상태로 취급하지 않습니다.

## 8. 다음 권장 작업

현재 우선순위에서 다음 후보는 실제 Candidate B identity와 승인 입력을 대상으로 하는 `EOS-DIAG-R3`입니다. 시작 전
R3 계약·허용 입력·실제 checkpoint read-only 접근 승인과 선행 Gate를 확인해야 합니다. Candidate C 학습, Qwen recovery,
Python SDK 또는 DohaMusic 구현으로 자동 전환하지 않습니다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | reusable provider 정의, 세 Phase 산출물 상태, 외부 Reference Application과 lineage 병행 관계 반영 |
| 2026-08-05 | EOS-DIAG-R1/R2 synthetic 상태와 실제 identity·Gate 미완료 상태 반영 |
