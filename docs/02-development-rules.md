# DohaLM 개발 규칙

## 1. 코드 작성 원칙

- [확정] 기능은 데이터, 토크나이저, 모델, 학습, 평가, 추론, 서버 순으로 작은 단위로 구현한다.
- [확정] 핵심 계산의 입력·출력 shape, dtype, device 및 마스킹 규칙을 코드와 테스트에서 명시한다.
- [확정] 하나의 모듈은 가능한 한 하나의 책임을 갖고, 설정값을 코드에 중복 하드코딩하지 않는다.
- [확정] 오류를 숨기는 광범위한 예외 처리나 확인되지 않은 자동 보정은 사용하지 않는다.
- [확정] 현재 구현 상태와 문서 상태를 일치시키며 스캐폴드를 구현 완료로 간주하지 않는다.

## 2. 문서 우선 원칙

- [확정] 구현 전에 관련 설계 문서의 필수 결정을 작성하고 `[확정]`, `[가정]`, `[검증 필요]`, `[후순위]`, `[제외]`로 상태를 표시한다.
- [확정] 모델 사양, 데이터 정책, 학습 방식 또는 공개 인터페이스가 바뀌면 코드와 같은 변경 단위에서 문서를 갱신한다.
- [확정] 중요한 선택과 대안은 `docs/decisions/`의 ADR에 남긴다.
- [확정] 중복 설명 대신 [프로젝트 개요](./00-project-overview.md), [범위와 목표](./01-scope-and-goals.md) 및 세부 기준 문서를 링크한다.

## 3. 직접 구현 범위

다음은 PyTorch 연산을 사용해 프로젝트 코드로 직접 구현한다.

- [확정] Token Embedding, Positional Embedding
- [확정] Causal Self-Attention, Multi-Head Attention
- [확정] Feed-Forward Network, Layer Normalization, Residual Connection
- [확정] Decoder Transformer Block, Language Modeling Head
- [확정] Cross-Entropy Loss 연결
- [확정] Autoregressive Text Generation
- [확정] 학습 루프, 체크포인트 저장·복원, 평가 루프

- [확정] PyTorch의 tensor 연산, autograd, optimizer, AMP 및 기본 레이어는 사용할 수 있다.
- [제외] Hugging Face의 완성된 GPT 계열 모델 클래스를 핵심 모델 구현으로 사용하는 것은 허용하지 않는다.
- [검증 필요] 직접 구현과 프레임워크 기능 사용의 경계가 모호하면 구현 전에 모델 아키텍처 문서 또는 ADR에서 결정한다.

## 4. 외부 라이브러리 사용 기준

| 도구 | 허용 목적 | 상태 |
|---|---|---|
| Python | 전체 구현 언어 | [확정] |
| PyTorch | tensor, autograd, GPU 연산 및 학습 기반 | [확정] |
| SentencePiece | 토크나이저 학습 및 실행 | [확정] |
| NumPy, Pandas | 데이터 처리와 분석 | [확정] |
| FastAPI | 추론 API | [후순위] |
| Next.js | 채팅 화면 | [후순위] |
| Docker | 재현 가능한 실행·배포 환경 | [후순위] |

- [확정] 새 의존성은 필요성, 라이선스, 버전 호환성 및 대체 가능성을 확인한 뒤 추가한다.
- [확정] 외부 코드를 복사할 경우 출처와 라이선스를 기록한다.
- [제외] 라이선스를 확인할 수 없는 데이터, 모델 또는 코드는 사용하지 않는다.

## 5. 실험 재현성 규칙

- [확정] 각 실험은 설정 스냅샷, 코드 버전, 데이터 버전, 토크나이저 버전, seed 및 실행 환경을 기록한다.
- [확정] Python, NumPy, PyTorch 및 CUDA 관련 seed를 설정하되 GPU 연산의 완전 결정성이 보장되지 않을 수 있음을 기록한다.
- [확정] 학습 로그에는 step, epoch 또는 token 진행량, loss, learning rate, 처리량, 경과 시간 및 최대 GPU 메모리를 남긴다.
- [확정] 체크포인트에는 모델, optimizer, scheduler, AMP scaler, 진행 step 및 재현에 필요한 상태를 저장한다.
- [검증 필요] 정확한 로그 형식, 실험 ID 및 산출물 디렉터리 규칙은 계획 문서 `15-experiment-management.md`에서 확정한다.

## 6. 설정값 관리 규칙

- [확정] 모델·데이터·학습·평가 설정은 버전 관리되는 YAML에 둔다.
- [확정] 비밀값과 로컬 경로는 설정 파일에 커밋하지 않고 환경 변수 또는 로컬 전용 파일로 분리한다.
- [확정] CLI override가 있다면 최종 적용 설정을 실행 로그에 저장한다.
- [확정] `DohaLM-Tiny` 기준값을 변경할 때는 이유와 영향 및 전후 비교를 ADR 또는 실험 기록에 남긴다.
- [검증 필요] `DohaLM-Small`의 Layer, Hidden Size, Attention Head 및 FFN 크기는 Tiny 실측 후 확정한다.

### 6.1 DohaLM-Tiny 확정 사양

다음 값은 [모델 아키텍처](./04-model-architecture.md)와 [ADR-002](./decisions/ADR-002-tiny-model-architecture.md)를 기준으로 관리한다.

| 항목 | 값 | 상태 |
|---|---:|---|
| 모델 구조 | Decoder-only Transformer | [확정] |
| Transformer Layer | 6 | [확정] |
| Hidden Size | 384 | [확정] |
| Attention Head | 6 | [확정] |
| Head Dimension | 64 | [확정] |
| Context Length | 256 | [확정] |
| Vocabulary Size | 16,000 | [확정] |
| FFN Size | 1,536 | [확정] |
| Block 정규화 | Pre-LayerNorm | [확정] |
| 위치 표현 | 학습형 absolute positional embedding | [확정] |
| Linear bias | 사용 | [확정] |
| Token Embedding–LM Head | weight tying | [확정] |
| LM Head bias | 미사용 | [확정] |
| 학습 계산 정밀도 | FP16 mixed precision | [확정] |
| 예상 파라미터 수 | 16,889,856 | [확정] 설계 산식 기준 |

- [확정] 구현 후 실제 파라미터 수와 checkpoint 구조가 기준 문서와 일치하는지 테스트한다.
- [확정] 위 사양을 변경하려면 영향과 checkpoint 호환성을 기록한 후속 ADR이 필요하다.

### 6.2 학습 전 미결정 설정

- [검증 필요] Dropout 확률
- [검증 필요] 파라미터 초기화 방식
- [검증 필요] 실제 micro-batch
- [검증 필요] Gradient Accumulation 횟수
- [검증 필요] Gradient Checkpointing 기본 활성화 여부
- [검증 필요] Learning Rate
- [검증 필요] Warmup step 또는 비율
- [검증 필요] Weight Decay
- [검증 필요] Token Budget
- [검증 필요] Checkpoint 주기

## 7. 데이터 라이선스 기록 규칙

- [확정] 데이터셋마다 이름, 원본 URL 또는 제공처, 취득일, 버전, 라이선스, 사용 조건 및 저장 위치를 기록한다.
- [확정] 학습 허용, 수정 허용, 재배포 허용 및 결과물 공개 조건을 구분한다.
- [확정] 원본 데이터와 정제·토큰화 산출물의 계보 및 처리 스크립트 버전을 연결한다.
- [확정] 개인정보, 민감정보, 유해 콘텐츠 및 저작권 위험에 대한 점검 결과를 남긴다.
- [제외] 출처 또는 라이선스를 확인할 수 없는 데이터는 학습에 사용하지 않는다.
- [검증 필요] 세부 승인 기준은 계획 문서 `06-data-strategy.md`와 `07-data-preprocessing.md`에서 확정한다.

## 8. Git 브랜치 및 커밋 규칙

- [확정] `main`은 검증된 변경만 유지하고 기능 개발은 목적별 브랜치에서 수행한다.
- [확정] 브랜치명은 `docs/`, `feat/`, `fix/`, `test/`, `experiment/` 접두어와 짧은 목적을 조합한다.
- [확정] 커밋은 하나의 논리적 변경을 담고, 메시지에 `docs:`, `feat:`, `fix:`, `test:`, `refactor:`, `chore:` 유형을 사용한다.
- [확정] 데이터 원본, 비밀값, 대용량 체크포인트 및 불필요한 생성 파일은 Git에 커밋하지 않는다.
- [확정] `main` 병합 전 관련 문서, 테스트 및 재현 명령을 검토한다.
- [검증 필요] 원격 저장소의 보호 규칙과 대용량 산출물 저장 방식은 저장소 운영 환경이 준비된 뒤 결정한다.

## 9. 테스트 없이 완료 처리하지 않는 규칙

- [확정] 기능은 관련 자동 테스트가 통과하고 재현 명령이 기록되어야 완료로 표시할 수 있다.
- [확정] 모델 구성요소는 shape, causal mask, dtype/device, 순전파·역전파 및 오류 조건을 테스트한다.
- [확정] 학습은 작은 배치 과적합, checkpoint round-trip 및 재개 동작을 테스트한다.
- [확정] 데이터는 정제 규칙, 중복 제거, 분할 누수 및 토큰 경계를 테스트한다.
- [확정] 문서는 링크, 용어, 상태 및 실제 구현 상태를 검토한다.
- [검증 필요] 통합 테스트의 구체적 합격 기준은 계획 문서 `18-testing-checklist.md`에서 확정한다.

## 10. 임의 추정을 금지하는 규칙

- [확정] 확인되지 않은 수치, 성능, 학습 시간, 비용, 데이터 규모 및 Leaderboard 가능성을 사실처럼 작성하지 않는다.
- [확정] 미확정 값은 `[가정]` 또는 `[검증 필요]`로 표시하고 검증 방법을 함께 기록한다.
- [확정] 계산상 모순이나 하드웨어 충돌이 발견되면 기준값을 임의 변경하지 않고 `검토 필요 사항` 또는 ADR로 올린다.
- [확정] 실험 결과를 일반화할 때 실행 환경, 데이터, 설정 및 측정 방법을 함께 제시한다.
- [확정] 외부 규정과 API처럼 변할 수 있는 정보는 적용 시점에 공식 출처로 다시 확인한다.

## 검토 필요 사항

- [검증 필요] 패키지 버전과 CUDA·PyTorch 호환 조합
- [검증 필요] Tiny의 Dropout 확률과 파라미터 초기화 방식
- [검증 필요] 실제 micro-batch, Gradient Accumulation 횟수 및 Gradient Checkpointing 기본 활성화 여부
- [검증 필요] Learning Rate, Warmup, Weight Decay, Token Budget 및 Checkpoint 주기
- [검증 필요] FP16 학습의 수치 안정성과 실제 VRAM 상한
- [검증 필요] 데이터셋별 라이선스와 공개 가능 범위
- [검증 필요] 정량 평가 합격선과 Small 진행 여부 판단 기준

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] ADR-002에 따라 DohaLM-Tiny 구조를 동기화하고 학습 관련 미결정 항목을 분리함 |
