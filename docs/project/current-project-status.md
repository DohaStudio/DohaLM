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

## 2. 통합 상태

### Foundation Model Track

| 구성 | 상태 | 근거와 경계 |
|---|---|---|
| Gate 0 | `approved` | 프로젝트 범위 사용자 승인 |
| Gate 1~7 | `passed` | 환경, 데이터, Tokenizer, 모델, Trainer, 실제 corpus overfit evidence |
| DohaLM-Tiny | `implemented_verified` | PyTorch 직접 구현, forward/loss/generation, 16,889,856 parameters |
| 운영 Tokenizer | `implemented_verified` | `operating-16k-v2/unigram-16k`, vocab 16,000 |
| Candidate A | `implemented_verified` | 10M token 학습 완료; historical Base baseline |
| Candidate B | `implemented_verified` | 25M token Run 0002·Full 평가 완료; current Base baseline |
| Evaluation Framework | `implemented_verified` | Quick·Full·EOS·position·category·stability·privacy·lineage |
| Foundation Instruct | `design_complete` | ADR-010; Candidate B parent 설계만 완료, artifact 없음 |
| Foundation Chat·Small 이상 | `planned` | 구조·데이터·실행 승인 없음 |

Candidate B의 historical 평가 계약 판정 `evaluated_contract_not_passed`는 유지합니다. ADR-009의 현재 판정은
`approved_as_base_baseline`이며 derivative parent 적격성은 `approved_experimental`입니다. 이는 후속 학습 또는 공개 승인이 아닙니다.
Candidate B의 teacher-forced 지표는 Candidate A보다 개선됐지만 pure-greedy 생성의 EOS 종료율은 0%, maximum-length
종료율은 100%였습니다. 이 한계는 Base 진단 결과로 보존하며 숨기거나 Runtime readiness로 해석하지 않습니다.

### Runtime/Application Track — 1차 목표

| 구성 | 상태 | 근거와 경계 |
|---|---|---|
| Qwen Base loader | `implemented_verified` | 고정 revision·local-only·lazy load, BF16 CUDA smoke |
| General Instruct QLoRA backend | `implemented_not_integrated` | v0.1/v0.2 학습·평가 코드와 기록 존재; 현재 API가 Adapter를 load하지 않음 |
| Runtime / Provider Registry | `implemented_verified` | Mock, Base Qwen, fail-closed Adapter provider |
| Adapter Loader | `implementation_in_progress` | [Manifest·strict loader와 정적 Artifact Validator](../service/dohalm-adapter-runtime.md)는 `implemented_synthetic_validated`; 실제 Base·Tokenizer·PEFT Loader·Provider 연결은 미착수이며 Provider는 항상 `ADAPTER_NOT_AVAILABLE` |
| Chat API | `implemented_verified` | health/readiness/models, 일반 Chat, 오류·timeout 계약 |
| Streaming | `implemented_verified` | SSE, cancellation, semaphore, worker join |
| Prompt Engine | `design_complete` | Base Qwen 공식 chat template 적용만 구현; 독립 engine은 없음 |
| Next.js UI | `implemented_verified` | HTTP/SSE, 취소·재시도, Base Qwen Chrome E2E |

현재 서비스는 기본 `mock` 또는 명시적 `base-qwen` Provider를 사용하는 로컬 MVP입니다. `dohalm-adapter`는 선택 가능한
이름만 등록돼 있고 실제 Adapter를 읽지 않습니다.

### 2·3차 목표

| 단계 | 구성 | 상태 |
|---|---|---|
| 2차 | Memory, RAG, Tool Calling, Agent | `planned` |
| 3차 | DohaMusic, Lyrics Search, Style Analysis, Personal Music Adapter | `planned` |
| 제외 | Docker, Kubernetes, Cloud, 운영 배포 | `out_of_scope` |

DohaMusic의 곡 기획·가사·음악 생성 prompt는 General Instruct Runtime의 응용 후보입니다. 실제 오디오·보컬·MIDI 생성은
DohaLM의 책임이 아니며 별도 음악 생성 모델의 범위입니다.

## 3. QLoRA와 Instruct 현재 상태

두 Instruct 계보를 혼동하지 않습니다.

| 계보 | Parent | 현재 상태 | Runtime 연결 |
|---|---|---|---|
| Foundation Instruct Tiny v1 | Candidate B Final | 설계 완료, 학습·artifact 미생성 | 없음 |
| Runtime General Instruct v0.1 | Qwen2.5-1.5B-Instruct | 학습 완료 Adapter와 독립 평가 이력이 문서화됨 | 미연결 |
| Runtime General Instruct v0.2 | 같은 Qwen Base | 2 epoch·1,298 step 완료 기록; terminal 평가 recovery 계약 존재 | 미연결, deployment ready 아님 |
| Runtime General Instruct v0.3 | 같은 Qwen Base 후보 | Dataset full 생성 전; Tokenization publish 실패 보존, 재시도 미승인 | 없음 |

저장소에는 외부 학습 artifact 자체가 없으므로 Runtime은 경로·fingerprint·승인 검증 없이는 Adapter를 자동 탐색하지 않습니다.
v0.1/v0.2의 학습 완료 기록도 `Adapter Loader 완료`나 `deployment_ready=true`로 승격하지 않습니다. Loader는 Adapter 학습에
사용한 동일 Qwen Base revision, Tokenizer와 Chat Template의 일치를 강제해야 합니다.

## 4. 데이터와 공개 경계

- AIHUB-71748은 학생·비상업 연구 범위이며 상업 이용과 원본·파생 데이터 재배포는 미승인입니다.
- Foundation Base와 Runtime SFT 데이터 계보는 분리합니다.
- AIHUB-71748 SFT Processing Run 0015와 v0.1 Tokenization 완료 기록은 후속 학습·재처리의 포괄 승인으로 사용하지 않습니다.
- 모델, checkpoint, Adapter, Tokenizer와 Dataset publication은 각각 별도 승인 대상입니다.

## 5. 완료된 현재 기능과 남은 1차 작업

현재 사용자 경로는 다음까지 동작합니다.

```text
Browser → Next.js → FastAPI → BaseQwenProvider → local Qwen snapshot
                  ↘ SSE streaming / cancellation / retry
```

1차 목표를 끝내려면 다음이 남습니다.

1. 배포 후보 General Instruct Adapter를 명시적으로 선정하고 Adapter config·weight, Base·Tokenizer·Chat Template,
   generation config와 평가 fingerprint를 하나의 manifest로 고정
2. 정적 Artifact Validator 이후 fail-closed PEFT Adapter Loader 구현과 실제 Base/Tokenizer/Adapter 조합 검증
3. Adapter를 통한 일반 Chat·SSE·취소·unload 회귀 및 GPU·브라우저 smoke
4. Prompt Engine의 template/version/system policy 경계 구현

## 6. 과거 계획과 보존 기록

- Candidate A를 current baseline으로 보던 문서는 historical context이며 현재 기준은 Candidate B입니다.
- Candidate B 첫 Run 0001 실패와 lexicographic checkpoint 정렬 버그는 실패 계보로만 보존합니다.
- AIHUB-71748 Processing Run 0001~0014의 preflight·retirement 과정은 감사 이력이며 현재 실행 계획이 아닙니다.
- v0.1 Windows QLoRA stall과 v0.2 terminal checkpoint failure는 원인·복구 계약을 위한 이력이며 자동 retry 근거가 아닙니다.
- 기존 Model Family의 Code·SQL·Recruit·Game·Vision 계획은 현재 1~3차 실행 순서에서 제외된 장기 후보입니다.

## 7. 다음 권장 작업

1. General Instruct Adapter 선정·평가 상태를 하나의 manifest로 고정
2. Adapter Loader 구현
3. Prompt Engine 최소 계약 확정
4. 1차 Runtime end-to-end 검증 후 Memory 설계 시작

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | Adapter Manifest·strict loader·정적 Artifact Validator synthetic 검증 완료와 PEFT Loader·Runtime 연결 미착수 상태 반영 |
| 2026-08-04 | General Instruct Adapter Runtime 설계 완료와 Loader 구현 미착수 상태 반영 |
| 2026-08-04 | 원격 7383f84의 Candidate B 생성 한계, Qwen compatibility와 DohaMusic 오디오 범위를 통합 |
| 2026-08-04 | Foundation과 Runtime 상태 분리, Base Qwen/API/Streaming 현행 구현 및 Adapter Loader 미구현 반영 |
| 2026-07-29 | Gate 0~7과 Candidate A/B·Evaluation 통합 snapshot 작성 |
