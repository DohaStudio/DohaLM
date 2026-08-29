# DohaLM

DohaLM은 최종 사용자 애플리케이션이 아니라, 다른 프로젝트가 재사용할 수 있는 **LLM 모델·추론 제공자**입니다.

```text
project_definition: reusable_llm_model_provider
phase_1: foundation_model_development
phase_2: reusable_model_and_runtime
phase_3: distribution_and_integration
dohamusic_role: external_reference_application
cloud_deployment: out_of_scope
```

DohaLM이 제공하는 공식 산출물은 Foundation Model, fine-tuned model 또는 Adapter, inference runtime,
REST/Streaming API, Python SDK, Model Manifest·versioning과 Integration Guide입니다. DohaMusic, DohaWriter,
DohaCode 같은 소비자 프로젝트는 별도 저장소에서 DohaLM API 또는 SDK를 호출합니다.

```text
DohaMusic / DohaWriter / DohaCode
              ↓ API · SDK
            DohaLM
```

기준 하드웨어는 단일 `RTX 3060 Ti 8GB`입니다.

## 기준 문서 읽기 순서

이 README가 프로젝트 정의와 Phase 분류의 기준 문서입니다.

1. [Project Definition](docs/project/overview.md)
2. [Foundation Strategy](docs/project/foundation-model-strategy.md)
3. [Current Status](docs/project/current-project-status.md)
4. [Foundation Readiness](docs/training/base-training-readiness.md)
5. [Reusable Model Strategy](docs/project/reusable-model-strategy.md)
6. [Runtime](docs/service/dohalm-backend-mvp.md)
7. [Distribution and Integration](docs/project/distribution-and-integration.md)
8. [Reference Applications](docs/project/domain-model-strategy.md)
9. [Roadmap](docs/project/model-family-roadmap.md)

[범위와 목표](docs/project/scope-and-goals.md), [Instruct Strategy](docs/instruct/instruct-strategy.md),
[Candidate C Design](docs/training/candidate-c-design.md)과 [전체 문서 인덱스](docs/index.md)는 각 단계의 상세 계약을 제공합니다.

## 공식 Phase 구조

| Phase | 공식 흐름 | 핵심 산출물 |
|---|---|---|
| Phase 1 — Foundation Model Development | Dataset → Tokenizer → DohaLM-Tiny → Base Pretraining → Evaluation → Foundation Base | 직접 구현 Foundation Base, Candidate 평가·선정 근거, Foundation Instruct 연구 계보 |
| Phase 2 — Reusable Model and Runtime | Qwen Base/Instruct → Korean·General SFT → QLoRA Adapter·merged model → Evaluation → Versioned DohaLM Model → Inference Runtime | 재사용 가능한 모델 artifact, manifest, validator, loader와 runtime |
| Phase 3 — Distribution and Integration | DohaLM model → runtime server → REST/Streaming → Python SDK → Integration Guide → Versioned Release | 로컬 배포 가능한 API·SDK·통합 문서·버전 릴리스 |

Phase 1과 Phase 2는 엄격한 직렬 단계가 아닙니다. Phase 1은 직접 구현 모델 연구이고, Phase 2는 별도 Qwen 계보를
사용할 수 있는 재사용 모델·Runtime 트랙입니다. 두 계보는 공통 manifest·평가·versioning 체계로 수렴하며 Phase 3가
승인된 Phase 2 모델과 Runtime을 외부 소비자에게 노출합니다. 현재 개발 우선순위는 Phase 1이지만, 이미 완료된 Phase 2·3
구현 이력은 유효합니다.

## 현재 산출물 상태

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

### Phase 1 상세 상태

- Candidate B는 current Foundation Base baseline이며 Candidate A는 historical baseline입니다.
- Base Training Readiness review와 Candidate C contract design은 완료됐습니다.
- Candidate C readiness는 `blocked`, execution allowed는 `false`, training started는 `false`입니다.
- EOS-DIAG-R1/R2 backend는 synthetic 검증됐지만 실제 Candidate B identity는 불완전하고 Gate 1·2는 통과하지 않았습니다.
- Candidate C와 Foundation Instruct 실행·승격·공개에는 각각 별도 승인이 필요합니다.

### Phase 2·3 상세 상태

- General Instruct Adapter manifest·validator는 구현됐고 PEFT loader와 provider lifecycle은 mock 검증됐습니다.
- v0.3 recovery 이력은 보존되지만 현재 eligible Adapter candidate가 없어 실제 Adapter Runtime은
  `unavailable_without_approved_artifact`입니다.
- Base Qwen local end-to-end와 FastAPI REST·SSE MVP는 검증됐습니다.
- Python SDK는 `not_started`, 로컬 versioned release는 `planned`, Cloud 배포는 `out_of_scope`입니다.

## Reference Application 경계

DohaMusic은 별도 저장소에서 개발할 첫 Reference Application입니다. DohaMusic은 UI, 음악 비즈니스 로직, 음악 프로젝트,
가사 편집과 개인화 기능을 소유합니다. DohaLM은 모델 로딩, 추론, streaming, prompt 처리, Adapter와 versioning을 소유합니다.
이 저장소에는 DohaMusic 코드를 추가하지 않습니다.

## 비목표

- ChatGPT 대체 또는 상용 수준 성능 보장
- 7B 이상 모델의 from-scratch 사전학습
- Docker, Kubernetes, Cloud와 운영 배포
- DohaMusic UI·비즈니스 로직 또는 오디오·MIDI 생성
- 승인되지 않은 모델·checkpoint·dataset·tokenizer·Adapter 공개

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
server/        REST·Streaming API
src/           Foundation, training, evaluation, inference 코드
frontend/      로컬 Runtime 검증 UI
tests/         Python 테스트
scripts/       검증·학습·평가 실행 진입점
```

## 데이터와 공개 경계

AIHUB-71748은 학생·비상업 연구 범위입니다. 상업 이용과 원본·파생 데이터 재배포는 승인되지 않았으며 대용량 데이터,
checkpoint와 Adapter는 Git에 포함하지 않습니다. 모델·checkpoint·tokenizer·dataset publication과 배포는 각각 별도 승인 대상입니다.

<!-- C2 always-present cheap-path simulation; draft-only and not intended for merge. -->
