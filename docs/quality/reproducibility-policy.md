# DohaLM 재현성 정책

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-23 |
| 선행 문서 | [개발 규칙](../governance/development-rules.md), [평가 계획](../evaluation/evaluation-plan.md), [실험 관리](../training/experiment-management.md), [산출물 및 설정 정책](../governance/artifact-and-configuration-policy.md), [ADR-005](../decisions/ADR-005-evaluation-and-experiment-policy.md) |
| 후속 문서 | [실험 템플릿](../training/experiment-template.md), [테스트 체크리스트](./testing-checklist.md) |
| 구현 전 필수 여부 | 본 학습 전 예 |

- [확정] 재현 가능성은 같은 근거와 절차로 결과를 검토할 수 있다는 뜻이며 모든 GPU 실행의 bitwise 동일성을 보장하지 않는다.
- [확정] 현재 실제 환경 snapshot, 실행 명령, checkpoint와 재현 결과는 없다.

## 2. 재현에 필요한 정보

| 정보 | 기록 내용 | 주의점 |
|---|---|---|
| Git commit SHA | 전체 commit hash | dirty 변경은 commit만으로 재현 불가 |
| 브랜치 | branch 또는 detached 상태 | branch명만으로 revision을 대신하지 않음 |
| 작업 트리 clean 여부 | clean/dirty와 검사 시각 | dirty면 patch·diff 보존 방법 [검증 필요] |
| Python 버전 | 전체 version·구현 | 환경별 차이 기록 |
| PyTorch 버전 | package version·build | CUDA build와 함께 기록 |
| CUDA 버전 | runtime·PyTorch build CUDA | driver와 구분 |
| NVIDIA Driver 버전 | driver version | `nvidia-smi` snapshot 후보 |
| GPU 모델 | 정확한 이름·VRAM | 기준은 `RTX 3060 Ti 8GB` |
| 운영체제 | OS·version·architecture | Windows·shell 정보 포함 후보 |
| 모델 설정 | resolved config·architecture version | 기본값이 아닌 최종값 |
| 학습 설정 | optimizer·LR·batch·precision·step 등 | 단위·parameter group 포함 |
| 토크나이저 fingerprint | tokenizer ID·model/vocab hash·special token | 동일 이름만으로 동일 판단 금지 |
| 데이터 fingerprint | dataset·preprocessing manifest hash | 원본 공개 없이 계보 가능해야 함 |
| split version | split manifest·seed·hash | validation/test 고정 |
| seed | 역할별 seed map | 하나의 숫자로 모든 RNG를 가정하지 않음 |
| 실행 명령 | 인자·작업 디렉터리·entry point | 비밀값과 개인 절대경로 제외 |
| 환경 변수 이름 | 결과에 영향 주는 변수명·비밀 여부 | 실제 secret 값은 기록·공개하지 않음 |
| checkpoint hash | checkpoint ID·format·checksum | parent experiment와 연결 |

## 3. Seed 정책

| Seed 종류 | 역할 | 기록 원칙 |
|---|---|---|
| Python seed | 표준 라이브러리 난수 | 명시적 값 |
| NumPy seed | NumPy sampling | generator 방식·값 |
| PyTorch CPU seed | CPU tensor 난수 | 값과 호출 시점 후보 |
| PyTorch CUDA seed | GPU 난수 | device별 적용 방식 |
| DataLoader worker seed | worker별 샘플·변환 | base seed와 파생 공식·worker 수 |
| 데이터 shuffle seed | epoch·sampler 순서 | sampler version·epoch 재개 상태 |
| split seed | train/validation/test 할당 | split version과 고정 |
| generation seed | sampling 생성 | prompt·sample별 seed |

- [확정] seed는 실행 전에 설정하고 checkpoint에 RNG state와 sampler 위치를 저장한다.
- [확정] 분할 seed와 학습 shuffle seed를 같은 개념으로 취급하지 않는다.
- [확정] seed가 같아도 GPU kernel, library version, 연산 순서와 병렬성 차이로 결과가 달라질 수 있다.
- [가정] 결정론 옵션은 정확성·회귀 진단에서 우선 검토하되 처리량 저하와 지원되지 않는 연산을 기록한다.
- [검증 필요] 기본 deterministic 설정과 허용되는 비결정 연산 목록은 구현·성능 실측 후 확정한다.

## 4. 재현 가능성과 완전 동일 결과

- [확정] 재현 가능성은 동일 계보와 설정으로 학습 흐름·지표 범위·결론을 다시 검토할 수 있는 상태다.
- [확정] bitwise 동일 재현은 모든 tensor·checkpoint byte가 동일한 더 강한 조건이다.
- [확정] 성능을 위해 결정론을 완화하면 적용 옵션, 이유와 결과 변동을 기록한다.
- [확정] bitwise 불일치만으로 학습 실패를 단정하지 않고 loss·metric·생성·구조 허용 범위를 별도로 평가한다.
- [검증 필요] 지표 근사 재현의 허용 오차는 기준 반복 실험 전 확정하지 않는다.

## 5. 환경 기록 명령 계획

실험 시작·종료 시 다음 정보를 기록하되 이번 문서화 단계에서는 명령을 실행하지 않는다.

| 정보 | 명령·수집 방식 후보 | 저장 원칙 |
|---|---|---|
| Python 버전 | `python --version` | stdout·exit code·실행 시각 |
| Python package | `pip freeze` | 전체 snapshot, 민감 URL·token 정제 |
| GPU·Driver | `nvidia-smi` | GPU 이름·VRAM·driver·process 상태 |
| PyTorch CUDA 상태 | Python에서 PyTorch·CUDA·cuDNN·device 정보 조회 [구현 예정] | 조회 코드 version과 결과 |
| Git commit | `git rev-parse HEAD` 후보 | 전체 SHA |
| Git 상태 | `git status --porcelain` 후보 | clean 여부, dirty면 안전한 diff 참조 |

- [확정] 명령 문자열, stdout/stderr, exit code와 실행 시각을 연결한다.
- [확정] 환경 기록에 API key, credential, 사용자 토큰과 불필요한 개인 경로를 포함하지 않는다.
- [검증 필요] 정확한 수집 script와 `environment.txt` schema는 구현 전에 확정한다.

## 6. 재현 수준

| 수준 | 정의 | 최소 증거 | 현재 상태 |
|---|---|---|---|
| 구조 재현 | 같은 모델 구조·parameter shape 구현 | ADR·model config·parameter count | [검증 필요] 미구현 |
| 설정 재현 | 최종 적용 설정을 복원 | resolved config·override·schema | [검증 필요] 미구현 |
| 데이터 재현 | 같은 논리 데이터와 split 생성 | registry·checksum·preprocess/split manifest | [검증 필요] 데이터 없음 |
| 학습 흐름 재현 | 같은 단계·checkpoint 재개·평가 실행 | command·환경·seed·RNG·checkpoint | [검증 필요] 미실행 |
| 지표 근사 재현 | 반복 실행이 합의된 허용 범위에 있음 | 복수 run·지표 분포·환경 차이 | [검증 필요] 허용 범위 미정 |
| bitwise 동일 재현 | tensor·checkpoint byte가 동일 | deterministic 환경·hash 일치 | [후순위] 모든 GPU 학습에 보장하지 않음 |

- [확정] 각 실험은 목표 재현 수준과 실제 달성 수준을 구분해 기록한다.
- [확정] 상위 수준이 자동으로 달성됐다고 추정하지 않는다.

## 7. 평가 재현성

- [확정] validation split, tokenizer, context·packing, loss mask, evaluation mode와 집계 방식을 고정한다.
- [확정] generation 평가는 prompt version, template, system message, sampling, seed와 stop 조건을 기록한다.
- [확정] 성능 평가는 warm-up, 동기화, 측정 구간, batch·context와 GPU process 상태를 기록한다.
- [확정] 외부 Benchmark는 데이터·코드·규정 version과 zero/few-shot 조건을 기록한다.

## 8. 재현 실패 처리

1. [확정] code·config·tokenizer·data·split·environment·seed·checkpoint hash를 순서대로 대조한다.
2. [확정] bitwise 차이, metric 차이, 기능 실패를 구분한다.
3. [확정] 최초 divergence 지점과 관측 범위를 기록한다.
4. [확정] 원 결과를 덮어쓰지 않고 재현 attempt를 새 run으로 연결한다.
5. [확정] 데이터 누수·잘못된 설정이면 관련 결과를 `invalid`로 전환한다.
6. [검증 필요] 허용 오차를 넘는 비결정 차이의 중단·수정 기준은 기준 반복 후 확정한다.

## 9. 미결정 사항

- [검증 필요] 기본 deterministic 옵션과 처리량 비용
- [검증 필요] 지표 근사 재현 허용 오차와 반복 횟수
- [검증 필요] dirty working tree patch 보존 방식
- [검증 필요] 환경 snapshot schema와 package lock 전략
- [검증 필요] 제한 데이터·비밀정보를 제외한 재현 bundle 범위

## 10. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] 재현 정보·역할별 seed·환경 기록·6단계 재현 수준과 실패 처리 정책 정의 |
