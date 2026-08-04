# DohaLM

DohaLM은 두 개의 독립된 트랙을 운영하는 한국어 LLM 연구·개발 프로젝트입니다.

- **Foundation Model Track**: `DohaLM-Tiny`, Tokenizer, Candidate A/B와 Evaluation Framework를 직접 구현·검증합니다.
- **Runtime/Application Track**: 고정된 Qwen Base와 General Instruct Adapter를 이용해 로컬 Runtime, Chat API와 Application을 만듭니다.

두 트랙은 코드와 평가 근거를 공유할 수 있지만 모델 계보와 완료 조건은 공유하지 않습니다. Qwen 기반 Runtime이 동작해도
DohaLM Foundation Model이 서비스 준비를 마친 것은 아니며, Foundation 연구 결과가 있어도 Runtime Adapter가 연결된 것은 아닙니다.
기준 하드웨어는 단일 `RTX 3060 Ti 8GB`입니다.

## 문서 읽기 순서

이 README가 프로젝트 범위와 우선순위의 기준 문서입니다.

1. [Foundation Model Strategy](docs/project/foundation-model-strategy.md) — 연구 트랙과 Runtime 트랙의 경계
2. [Current Project Status](docs/project/current-project-status.md) — 코드·실측 기준 현재 상태
3. [Model Family Roadmap](docs/project/model-family-roadmap.md) — 1·2·3차 목표와 진입 조건
4. [Service 문서](docs/service/dohalm-backend-mvp.md) — 현재 로컬 Runtime과 UI 실행 계약
   - [Adapter Runtime 설계](docs/service/dohalm-adapter-runtime.md) — General Instruct Adapter manifest·검증·lifecycle·구현 계획

Domain 확장 원칙은 [Domain Model Strategy](docs/project/domain-model-strategy.md), Instruct의 두 계보는
[Instruct Strategy](docs/instruct/instruct-strategy.md), 전체 문서 목록은 [문서 안내서](docs/README.md)를 따릅니다.

## 현재 구현 상태

상태 용어는 다음처럼 사용합니다.

| 상태 | 의미 |
|---|---|
| `implemented_verified` | 코드가 있고 관련 자동 테스트 또는 명시적 로컬 실측 근거가 있음 |
| `implemented_not_integrated` | 코드·학습 산출 이력은 있으나 현재 Runtime 경로에 연결되지 않음 |
| `design_complete` | 설계·계약은 있으나 실행 또는 통합 완료가 아님 |
| `planned` | 목표만 확정됐고 구현 완료 근거가 없음 |
| `out_of_scope` | 현재 범위에서 제외 |

### Foundation Model Track

| 구성 | 현재 상태 | 비고 |
|---|---|---|
| DohaLM-Tiny | `implemented_verified` | Decoder-only Transformer, Trainer, checkpoint/resume, 실제 corpus overfit 검증 |
| Tokenizer | `implemented_verified` | 운영 `operating-16k-v2/unigram-16k`, vocab 16,000, Gate 3 통과 |
| Candidate A/B | `implemented_verified` | Candidate B가 current Base baseline, Candidate A는 historical baseline |
| Evaluation Framework | `implemented_verified` | Quick·Full·EOS·position·category·stability·privacy·lineage |
| Foundation Instruct | `design_complete` | ADR-010의 Candidate B 파생 설계; 학습·publication 미승인 |

Gate 0은 `approved`, Gate 1~7은 `passed`입니다. 세부 수치와 실행 이력은
[Current Project Status](docs/project/current-project-status.md)와 [Evaluation 문서](docs/evaluation/README.md)에만 둡니다.

### Runtime/Application Track — 1차 목표

| 구성 | 현재 상태 | 비고 |
|---|---|---|
| Qwen Base | `implemented_verified` | 고정 local snapshot, lazy load, BF16 GPU·브라우저 smoke 통과 |
| General Instruct Adapter (QLoRA) | `implemented_not_integrated` | 학습·평가 backend와 v0.1/v0.2 실행 이력 존재; 배포 승인 Adapter 없음 |
| Runtime / Provider Registry | `implemented_verified` | Mock·Base Qwen·fail-closed Adapter provider 경계 |
| Adapter Loader | `implementation_in_progress` | Manifest·Artifact Validator는 synthetic, local-only PEFT Loader는 mock 검증 완료; 실제 Adapter/GPU와 Provider 연결은 미검증 |
| Chat API | `implemented_verified` | FastAPI 일반 Chat, health/readiness/models |
| Streaming | `implemented_verified` | SSE, timeout, cancellation, worker 정리 |
| Prompt Engine | `design_complete` | Qwen 공식 chat template 직렬화는 구현; 독립 정책·template engine은 미구현 |
| Web UI | `implemented_verified` | Next.js HTTP·SSE·취소·재시도, Base Qwen Chrome E2E |

Runtime은 현재 **로컬 개발·검증용**입니다. 인증, 영구 저장과 운영 배포를 제공하지 않습니다.

## 후속 목표

### 2차 목표

Memory → RAG → Tool Calling → Agent 순서로 진행합니다. 네 항목 모두 현재 `planned`이며, 문서에 설계 아이디어가
있다는 이유로 구현 완료로 간주하지 않습니다.

### 3차 목표 — DohaMusic

DohaMusic은 1차 General Instruct Runtime을 재사용하는 별도 Application/Domain 트랙입니다.

- General Instruct Runtime 재사용
- Lyrics Search
- Style Analysis
- Personal Music Adapter

모두 `planned`입니다. 데이터 라이선스, 가사 저작권, 개인정보와 평가 계약을 확정하기 전에는 학습·수집·공개를 시작하지 않습니다.

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
