# DohaLM

## 프로젝트 소개

DohaLM은 한국어 소형 Decoder-only Transformer와 학습·평가·추론 파이프라인을 PyTorch 기반으로 직접 구현하고 단계적으로 검증하는 교육·연구·포트폴리오 프로젝트입니다. 모든 자원 계획은 단일 `RTX 3060 Ti 8GB` 환경을 기준으로 합니다.

## 현재 상태

현재 저장소는 Gate 0 승인과 Gate 1~7 통과 상태입니다. 운영 16k v2 Unigram, DohaLM-Tiny, Trainer, 실제 corpus overfit, canonical pilot-v2 100-step, Candidate A/B 학습과 Evaluation Framework를 완료했습니다. ADR-009에 따라 Candidate B가 current Base baseline이고 Candidate A는 historical baseline입니다. ADR-010으로 DohaLM Instruct 설계·Readiness를 마련했고 AIHUB-71748 SFT Component는 조건부 선정됐지만 Dataset Processing·Backend·SFT 실행은 승인되지 않았습니다.

| 영역 | 상태 |
|---|---|
| 문서화 | 진행 및 검토 단계 |
| Phase 0 환경·설정 기반 | 구현·검증 완료, Gate 1 `passed` |
| Phase 1 데이터 파이프라인 | DATA-001~016 `verified`, Gate 2 `passed` |
| 모델 코드 | Phase 3 구성요소와 Phase 4 전체 forward·loss·greedy generation 구현·검증, Gate 4·5 `passed` |
| 학습 기반 | Trainer와 실제 Tiny 규모 sampler·cosine·FP16 AMP·checkpoint/resume·VRAM 측정, 제한 실제 corpus 1,000-step packed overfit 검증 완료, Gate 6·7 `passed` |
| 데이터 | AIHUB-71748 학생·비상업 연구 범위; SFT Component `CONDITIONALLY_SELECTED`, Processing·원래 Validation·재배포 미승인 |
| 토크나이저 | 운영 `operating-16k-v2/unigram-16k` 승인, vocabulary 16,000·Gate 3 `passed` |
| 사전학습 | canonical Pilot 100-step과 Candidate A 10M Token 완료; 추가 학습 미승인 |
| SFT | AIHUB-71748 조건부 선정, Processing·Backend·Training 미승인·미실행 |
| 추론 API | 스캐폴드만 존재, 미구현 |
| Frontend | 안내 스캐폴드만 존재, 미구현 |

Gate 4·5·6은 evidence bundle과 514개 테스트를 근거로 2026-07-24, Gate 3은 승인된 v2 Unigram을 근거로 2026-07-26 `passed`가 됐습니다. Gate 7은 동일 64문서의 packed top-1 99.9047%, 네 prefix exact continuation, checkpoint/resume와 571개 테스트를 근거로 2026-07-27 사용자 승인되어 `passed`입니다. 이 결과는 memorization 검증이며, 이후 별도 승인으로 canonical Pilot과 Candidate A를 완료했습니다.

현재 상태의 단일 요약은 [Current Project Status](docs/project/current-project-status.md)를 따릅니다. 장기 방향은 [Foundation Model Strategy](docs/project/foundation-model-strategy.md), [Model Family Roadmap](docs/project/model-family-roadmap.md), [Model Lineage](docs/project/model-lineage.md), [Domain Model Strategy](docs/project/domain-model-strategy.md)에 정리되어 있습니다. 이 문서들은 장기 제안이며 승인된 Tiny 사양이나 Candidate A baseline, Candidate B 실행 권한을 변경하지 않습니다.

## DohaLM Model Family

DohaLM은 한국어 Foundation Model 기반과 재현 가능한 학습·평가·계보 체계를 장기 목표로 합니다. 현재 공식 Base는 Candidate B이며 [DohaLM Instruct](docs/instruct/README.md)는 설계 완료·실행 미승인 상태입니다. Chat, Code, SQL, Recruit, Game, Agent는 아직 시작하지 않았고 Vision/Multimodal은 장기 계획입니다.

자세한 내용은 [Foundation Model Strategy](docs/project/foundation-model-strategy.md), [Model Family Roadmap](docs/project/model-family-roadmap.md), [Model Lineage](docs/project/model-lineage.md), [Domain Model Strategy](docs/project/domain-model-strategy.md), [Current Project Status](docs/project/current-project-status.md)를 참조하세요.

## 프로젝트 목표

- 한국어 SentencePiece 토크나이저를 직접 학습합니다.
- Decoder-only Transformer 핵심 구성요소와 학습 루프를 직접 구현합니다.
- 사전학습, SFT, 평가, 체크포인트 복원과 자기회귀 생성을 재현 가능하게 검증합니다.
- 핵심 모델 검증 이후 FastAPI 추론 서버와 Next.js 채팅 화면의 연결을 검토합니다.
- 최종 결과를 바탕으로 AI Hub K-AI Leaderboard 제출 가능성을 검토합니다.

## 비목표

- A100·H100·멀티 GPU·대규모 분산 학습을 전제로 하지 않습니다.
- 7B 이상 모델을 처음부터 사전학습하지 않습니다.
- 상용 수준 LLM, ChatGPT 대체 또는 높은 Benchmark 성능을 보장하지 않습니다.
- DohaLM-Tiny 검증 전에 서비스·배포 개발을 우선하지 않습니다.

## DohaLM-Tiny 핵심 사양

| 항목 | 승인 사양 |
|---|---|
| 구조 | Decoder-only Transformer |
| Transformer Layer | 6 |
| Hidden Size | 384 |
| Attention Head / Head Dimension | 6 / 64 |
| FFN Size | 1,536 |
| Context Length | 256 |
| Vocabulary Size | 16,000 |
| Normalization | Pre-LayerNorm |
| Position Embedding | 학습형 absolute positional embedding |
| Token Embedding–LM Head | Weight tying 사용 |
| Precision | FP16 mixed precision |
| 예상 파라미터 | 16,889,856 |

- [검증 필요] Dropout 확률과 파라미터 초기화 방식
- [확정] 통합 모델의 실제 고유 파라미터 수가 승인 산식 `16,889,856`과 일치

## 개발 단계

개발은 저장소·환경 기반부터 데이터, 토크나이저, 모델, 학습, 평가, SFT, 서비스 순서로 진행합니다. 각 단계는 문서·구현·테스트 증거를 요구하는 Gate로 관리합니다. Gate 0은 `approved`, Gate 1과 Gate 2는 `passed`로 확정됐습니다. 이는 토크나이저·모델·학습·서비스 구현 완료를 의미하지 않습니다.

## 저장소 구조

```text
configs/       검증 가능한 모델·실행 설정
data/          원본·정제·토큰화·SFT 데이터 경로
docs/          프로젝트 기준 문서와 ADR
scripts/       실행 스크립트 스캐폴드
server/        FastAPI 서버 스캐폴드
src/           Phase 0 기반과 Phase 1 최소 데이터 파이프라인 구현
frontend/      Frontend 안내 스캐폴드
tests/         테스트 경로
checkpoints/   로컬 체크포인트 경로
```

## 문서 안내

- [문서 안내서](docs/README.md)
- [전체 문서 인덱스](docs/index.md)
- [프로젝트 개요](docs/project/overview.md)
- [범위와 목표](docs/project/scope-and-goals.md)
- [개발 로드맵](docs/quality/development-roadmap.md)
- [개발 규칙](docs/governance/development-rules.md)
- [Evaluation Framework](docs/evaluation/README.md)

## 환경 요구사항

- 단일 NVIDIA `RTX 3060 Ti 8GB`
- Python 3.10 이상 3.13 미만(현재 검증: 3.12.5)
- PyTorch 2.7 계열 선택 GPU 의존성(현재 검증: 2.7.1+cu118)
- Windows PowerShell을 포함한 로컬 개발 환경

[검증 필요] Linux와 다른 PyTorch·CUDA 조합은 해당 환경에서 별도 검증해야 합니다. PyTorch 설치 방식은 플랫폼별 공식 설치 안내를 따릅니다.

현재 로컬 검증 snapshot은 다음과 같습니다. 프로젝트의 영구 고정값이 아니라 Gate 1 승인 근거입니다.

- Windows 11, Python 3.12.5
- PyTorch 2.7.1+cu118, PyTorch CUDA build 11.8, cuDNN 90100
- NVIDIA GeForce RTX 3060 Ti, 8,192 MiB, Driver 610.62
- CUDA 사용 가능, 단일 CUDA tensor 생성·해제 성공
- [확정] CUDA toolkit compiler(`nvcc`)는 현재 PATH에서 확인되지 않지만 표준 PyTorch 구현·학습의 차단 사항은 아니며, 사용자 정의 CUDA 확장 또는 소스 빌드가 필요할 때 재검토함
- [확정] 전역 환경의 프로젝트 외 패키지 충돌과 분리된 `.venv`에서 `pip check`, editable 설치, 전체 테스트와 CPU·CUDA smoke를 통과함

## 빠른 시작

Phase 0 도구와 합성 token 기반 모델·학습 smoke는 다음과 같이 실행합니다. 실제 corpus용 Pilot·Candidate 실행 backend는 별도 fail-closed 승인 계약을 따르며, SFT 실행은 아직 승인되지 않았습니다.

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pip install -e . --no-deps
```

Linux 후보 환경:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pip install -e . --no-deps
```

GPU용 PyTorch는 운영체제와 CUDA 조합에 맞춰 [PyTorch 공식 설치 안내](https://pytorch.org/get-started/locally/)에서 먼저 설치한 뒤 `python -m pip install -e ".[gpu]"`로 나머지 GPU 선택 의존성을 설치합니다.

```powershell
python -m src.cli.main environment --cuda-smoke
python -m src.cli.main config validate
python -m src.cli.main config resolve --run configs/pretrain.yaml --allow-incomplete
python -m src.cli.main paths
python -m src.cli.main data validate --config tests/fixtures/data/phase1-cli.yaml
python -m src.cli.main data build --config tests/fixtures/data/phase1-cli.yaml
python -m scripts.model.inspect_model
python -m scripts.model.run_model_smoke --device cpu --dtype float32
python -m scripts.model.generate_smoke
python -m scripts.training.run_training_smoke --help
python -m scripts.training.inspect_checkpoint --help
python -m scripts.training.resume_training_smoke --help
python -m scripts.training.probe_tiny_batch_sizes --help
python -m scripts.training.run_tiny_validation --help
python -m scripts.training.inspect_tiny_validation --help
python -m scripts.training.validate_gate_evidence --help
python -m scripts.training.validate_pilot_readiness --help
python -m scripts.training.inspect_gate_proposal --help
python -m pytest -q
```

`pretrain.yaml`과 `sft.yaml`의 미결정값은 실행 전에 확정해야 하며, `--allow-incomplete`는 상태 점검용 출력에만 사용합니다.

## 구현 예정 순서

1. 저장소·환경·설정 계약 검증
2. 최소 데이터 파이프라인과 데이터 승인 절차 검증
3. SentencePiece 토크나이저 학습·복원 검증
4. DohaLM-Tiny 구성요소와 통합 모델 구현·테스트
5. 학습 루프·체크포인트·재개 검증
6. 극소 데이터 과적합과 GPU 메모리 실측
7. 승인 데이터 기반 사전학습, 평가와 SFT
8. 검증된 최소 추론 인터페이스 이후 API·Frontend 검토

## 데이터 및 라이선스

AIHUB-71748은 학생·비상업 연구 범위로 승인됐고, 고정된 canonical `pilot-v2` 파생 corpus는 별도 승인 아래 Pilot과 Candidate A에 사용됐습니다. 다만 source package registry는 제공자 version·취득 증빙 미확정으로 `reviewing`이며, 상업 이용과 원본·파생 데이터 재배포 및 새로운 목적의 데이터 사용은 승인되지 않았습니다. 원본 데이터와 대용량 파생 산출물은 Git에 커밋하지 않습니다. 세부 기준은 [데이터 전략](docs/data/data-strategy.md), [데이터셋 레지스트리](docs/data/dataset-registry.md), [데이터 라이선스 정책](docs/data/data-license-policy.md)을 따릅니다.

## 제한 사항

- DohaLM-Tiny 전체 forward·shifted loss·greedy generation, 운영 tokenizer, 실제 corpus Tiny Overfit, canonical Pilot과 Candidate A 10M 실행은 검증됐습니다. 이 결과는 단일 8GB GPU의 제한된 내부 실험이며 장시간·대규모 운영 안정성이나 일반 성능을 보장하지 않습니다.
- 학습 hyperparameter, 토크나이저 세부 옵션과 정량 평가 합격선은 아직 확정되지 않았습니다.
- DohaLM-Small 상세 구조, API·Frontend·배포 설계 및 외부 제출은 후순위입니다.
- 테스트와 재현 증거 없이 구현 또는 학습 완료로 처리하지 않습니다.
