# DohaLM

DohaLM은 **Foundation을 먼저 완성하고 Runtime과 Application으로 확장하는** 한국어 LLM 연구·개발 프로젝트입니다.

- **Phase 1 — DohaLM Foundation**: Base 본훈련 준비, Candidate C, Foundation Instruct를 핵심 목표로 진행합니다.
- **Phase 2 — Runtime**: 고정된 Qwen Base와 General Instruct Adapter를 사용하는 실제 서비스용 트랙입니다.
- **Phase 3 — Application**: Runtime을 사용하는 DohaMusic과 음악 특화 기능을 개발합니다.

[확정] 현재 최우선 순위는 Foundation입니다. Runtime Track은 삭제하지 않으며, Foundation 완료 이후 독립 계보를 유지하며
진행하는 병행 트랙으로 배치합니다. Qwen Runtime이 동작해도 DohaLM Foundation 완료를 뜻하지 않고, Foundation artifact가
있어도 Runtime Adapter 통합 완료를 뜻하지 않습니다.
Foundation Candidate B, Candidate C와 Foundation Instruct는 프로젝트의 핵심 모델 목표입니다.
기준 하드웨어는 단일 `RTX 3060 Ti 8GB`입니다.

## 문서 읽기 순서

이 README가 프로젝트 범위와 우선순위의 기준 문서입니다.

1. [Foundation Model Strategy](docs/project/foundation-model-strategy.md) — Foundation 핵심 목표와 Runtime 경계
2. [Current Project Status](docs/project/current-project-status.md) — 코드·실측 기준 현재 상태
3. [Base Training Readiness](docs/training/base-training-readiness.md) — Candidate A/B 근거 조사와 Candidate C 진입 판정
4. [Candidate C Design](docs/training/candidate-c-design.md) — Candidate C C-1~C-8 계약과 실행 경계
5. [Model Family Roadmap](docs/project/model-family-roadmap.md) — Phase 1→2→3 공식 개발 순서
6. [Runtime 문서](docs/service/dohalm-backend-mvp.md) — 실제 서비스용 로컬 Runtime과 UI 실행 계약
   - [Adapter Runtime 설계](docs/service/dohalm-adapter-runtime.md) — General Instruct Adapter manifest·검증·lifecycle·구현 계획
7. [Application 문서](docs/project/domain-model-strategy.md) — Runtime을 사용하는 DohaMusic과 음악 특화 기능

Domain 확장 원칙은 [Domain Model Strategy](docs/project/domain-model-strategy.md), Instruct의 두 계보는
[Instruct Strategy](docs/instruct/instruct-strategy.md), 전체 문서 목록은 [문서 안내서](docs/README.md)를 따릅니다.
현재 최우선 작업의 상세 진입 판단은 [Base Training Readiness](docs/training/base-training-readiness.md)를 기준으로 합니다.
Candidate C 계약 초안은 [Candidate C 설계](docs/training/candidate-c-design.md),
[EOS 가설](docs/training/candidate-c-eos-hypotheses.md),
[Evaluation 계약](docs/training/candidate-c-evaluation-contract.md)과 [ADR-011 제안](docs/decisions/ADR-011-candidate-c-experimental-successor.md)에 있습니다.

## 현재 구현 상태

상태 용어는 다음처럼 사용합니다.

| 상태 | 의미 |
|---|---|
| `implemented_verified` | 코드가 있고 관련 자동 테스트 또는 명시적 로컬 실측 근거가 있음 |
| `implemented_not_integrated` | 코드·학습 산출 이력은 있으나 현재 Runtime 경로에 연결되지 않음 |
| `design_complete` | 설계·계약은 있으나 실행 또는 통합 완료가 아님 |
| `completed` | 해당 범위의 기존 artifact와 검증 근거가 완료됨 |
| `reviewing` | 기존 근거를 다음 실행 계약에 채택할지 검토 중 |
| `blocked` | 필수 결정·승인·근거가 없어 다음 단계로 진행 불가 |
| `not_started` | 해당 후보 전용 작업이나 실행이 시작되지 않음 |
| `planned` | 목표만 확정됐고 구현 완료 근거가 없음 |
| `out_of_scope` | 현재 범위에서 제외 |

### Phase 1 — DohaLM Foundation

| 구성 | 현재 상태 | 비고 |
|---|---|---|
| DohaLM-Tiny | `implemented_verified` | Decoder-only Transformer, Trainer, checkpoint/resume, 실제 corpus overfit 검증 |
| Tokenizer | `implemented_verified` | 운영 `operating-16k-v2/unigram-16k`, vocab 16,000, Gate 3 통과 |
| Candidate A/B | `implemented_verified` | Candidate B가 current Base baseline이자 Candidate C의 비교 기준, Candidate A는 historical baseline |
| Base Training Readiness review | `completed` | A/B evidence·EOS 현상·Dataset·Tokenizer·Config 조사와 Candidate C readiness 판정 완료 |
| Candidate C contract design | `completed` | C-1~C-8, EOS 가설, freeze·Evaluation·Selection 계약 초안 작성 완료 |
| Candidate C readiness | `blocked` | ADR·단일 root cause 가설·freeze·평가 승인과 resolved config 미완료 |
| Candidate C | `not_started` | C-1~C-4 동결과 C-5 GPU Smoke·별도 single-use 승인 전 학습 금지 |
| Evaluation Framework | `implemented_verified` | Quick·Full·EOS·position·category·stability·privacy·lineage |
| Foundation Instruct | `design_complete` | 현재 ADR-010은 Candidate B 파생 설계; 공식 차기 목표는 Candidate C 기반이며 후속 ADR·학습·publication 승인 필요 |

Gate 0은 `approved`, Gate 1~7은 `passed`입니다. 세부 수치와 실행 이력은
[Current Project Status](docs/project/current-project-status.md)와 [Evaluation 문서](docs/evaluation/README.md)에만 둡니다.

### Phase 2 — Runtime

| 구성 | 현재 상태 | 비고 |
|---|---|---|
| Qwen Base | `implemented_verified` | 고정 local snapshot, lazy load, BF16 GPU·브라우저 smoke 통과 |
| General Instruct Adapter (QLoRA) | `implemented_not_integrated` | 학습·평가 backend와 v0.1/v0.2 실행 이력 존재; 배포 승인 Adapter 없음 |
| Runtime / Provider Registry | `implemented_verified` | Mock·Base Qwen·fail-closed Adapter provider 경계 |
| Adapter Loader | `implementation_in_progress` | Manifest·Validator·PEFT Loader·Provider lifecycle은 mock 검증 완료; 실제 승인 Adapter/GPU READY는 미검증 |
| Chat API | `implemented_verified` | FastAPI 일반 Chat, health/readiness/models |
| Streaming | `implemented_verified` | SSE, timeout, cancellation, worker 정리 |
| Prompt Engine | `design_complete` | Qwen 공식 chat template 직렬화는 구현; 독립 정책·template engine은 미구현 |
| Web UI | `implemented_verified` | Next.js HTTP·SSE·취소·재시도, Base Qwen Chrome E2E |

Runtime은 현재 **로컬 개발·검증용**입니다. 인증, 영구 저장과 운영 배포를 제공하지 않습니다.
이 트랙은 실제 서비스 제공을 목적으로 하지만 Phase 1 Foundation보다 앞서지 않습니다.

## 공식 개발 순서

### Phase 1 — DohaLM Foundation

1. **현재 근거 조사**: Candidate A/B Evidence → Candidate B EOS Diagnostic Review → Dataset·Tokenizer·Config Review → Candidate C Readiness Decision
2. **향후 Candidate C 실행**: Dataset Freeze → Tokenizer Freeze → Training Config Freeze → GPU Smoke → Training → Evaluation → Candidate Selection
3. **Foundation Instruct**: Candidate C 기반 SFT → Evaluation → Candidate Selection

Candidate B는 완료된 current Base baseline이자 Candidate C의 필수 비교 기준으로 보존합니다. Candidate C 기반 Foundation
Instruct로 parent를 바꾸려면 현재 승인된 ADR-010을 대체하거나 개정하는 후속 결정이 먼저 필요합니다.
[Base Training Readiness](docs/training/base-training-readiness.md)의 C-1~C-4가 통과하기 전에는 GPU Smoke나 Candidate C
학습으로 넘어가지 않습니다.

```text
base_training_readiness_review: completed
candidate_c_contract_design: completed
candidate_c_readiness: blocked
candidate_c_execution_allowed: false
candidate_c_training_started: false
```

### Phase 2 — Runtime

Qwen General Instruct v0.3 Recovery → Manifest → Runtime → Adapter 순서입니다. Foundation 완료 이후 착수하는 실제
서비스용 병행 트랙이며, 현재 구현과 복구 계약은 그대로 보존합니다.

### Phase 3 — Application

DohaMusic → Music Adapter → Lyrics → Prompt 순서입니다. DohaMusic은 Phase 2 Runtime을 사용하는 Application이며
Foundation 또는 Runtime 자체로 분류하지 않습니다.

Phase 3의 네 항목은 모두 `planned`입니다. 데이터 라이선스, 가사 저작권, 개인정보와 평가 계약을 확정하기 전에는
학습·수집·공개를 시작하지 않습니다.

## 현재 범위 밖

- Docker, Kubernetes, Cloud와 운영 배포
- 인증, DB, 영구 대화 저장과 다중 사용자 운영
- A100·H100·멀티 GPU·대규모 분산 학습
- 7B 이상 모델의 from-scratch 사전학습
- Vision/Multimodal 및 상용 수준 LLM 보장

## DohaLM-Tiny 승인 사양

| 항목 | 승인 사양 |
|---|---|
| 구조 | Decoder-only Transformer |
| Layer / Hidden / Head | 6 / 384 / 6 (`head_dim=64`) |
| FFN / Context / Vocabulary | 1,536 / 256 / 16,000 |
| Normalization / Position | Pre-LayerNorm / learned absolute position |
| Token Embedding–LM Head | weight tying |
| Precision | FP16 mixed precision |
| 고유 파라미터 | 16,889,856 |

`DohaLM-Small` 상세 구조, dropout과 초기화 정책은 후속 결정 전까지 `[검증 필요]`입니다.

## 저장소 구조

```text
configs/       모델·학습·평가·추론 설정
docs/          기준 문서와 ADR
server/        FastAPI Chat API
src/           Foundation, training, evaluation, inference 코드
frontend/      Next.js 채팅 UI
tests/         Python 테스트
scripts/       검증·학습·평가 실행 진입점
```

## 빠른 시작

Foundation CPU smoke와 전체 Python 테스트:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pip install -e . --no-deps
python -m scripts.model.run_model_smoke --device cpu --dtype float32
python -m pytest -q
```

로컬 Chat API와 Frontend:

```powershell
python -m pip install -r requirements-api.txt
uvicorn server.main:app --host 127.0.0.1 --port 8000
```

```powershell
cd frontend
npm install
npm run dev
```

Base Qwen은 [로컬 Provider 문서](docs/service/dohalm-base-qwen-provider.md)의 고정 snapshot과 명시적 설정이 있을 때만
활성화합니다. 기본 Provider는 `mock`이며 외부 다운로드나 자동 fallback은 하지 않습니다.

## 데이터와 공개 경계

AIHUB-71748은 학생·비상업 연구 범위입니다. 상업 이용과 원본·파생 데이터 재배포는 승인되지 않았으며 대용량 데이터,
checkpoint와 Adapter는 Git에 포함하지 않습니다. 모델·checkpoint·tokenizer·dataset publication과 배포는 각각 별도 승인 대상입니다.
