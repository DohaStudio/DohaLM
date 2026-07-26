# DohaLM 저장소 구조

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-26 |
| 선행 문서 | [프로젝트 개요](../project/overview.md), [개발 규칙](../governance/development-rules.md), [시스템 아키텍처](./system-architecture.md) |
| 후속 문서 | [핵심 개발 기능명세서](./core-development-feature-specification.md), [산출물 및 설정 정책](../governance/artifact-and-configuration-policy.md), [실험 관리 정책](../training/experiment-management.md) |
| 구현 전 필수 여부 | 예 |

- [확정] 이 문서는 현재 저장소에 실제로 존재하는 구조와 향후 후보 구조를 구분한다.
- [확정] 디렉터리가 존재한다는 사실은 해당 기능이 구현됐다는 뜻이 아니다.
- [확정] Phase 0·1 기반, 승인 corpus 기반 운영 `operating-16k-v2/unigram-16k`, Phase 3·4 model, Phase 5 Trainer Foundation과 실제 Tiny 규모 합성 sampler·cosine·CUDA validation 도구 및 테스트는 구현됐다. 실제 사전학습·서비스 기능은 미구현이다.

## 2. 구조 운영 원칙

- [확정] 설정, 소스 코드, 데이터, 실험 기록, 장기 보관 산출물의 책임을 서로 다른 경로로 분리한다.
- [확정] 대용량 데이터와 체크포인트는 Git에 커밋하지 않는다.
- [확정] 사용 시점이 오기 전에 빈 디렉터리와 예시 파일을 대량 생성하지 않는다.
- [확정] 동일한 책임을 여러 디렉터리에 중복 배치하지 않는다.
- [확정] 저장소 최상위 규칙은 루트 `AGENTS.md`가 정의하고, 하위 `AGENTS.md`는 해당 범위의 규칙을 구체화하되 상위 규칙을 완화하지 않는다.
- [검증 필요] `experiments/`와 `artifacts/`의 실제 생성 시점 및 내부 스키마는 실험 관리 문서 작성 후 결정한다.

## 3. 현재 실제 구조

아래 트리는 2026-07-23 Phase 0 구현 후 구조를 요약한다. `.git/`과 파일 단위의 세부 목록은 생략했다.

```text
DohaLM/
├── .agents/
├── checkpoints/
├── configs/
├── data/
│   ├── raw/
│   ├── cleaned/
│   ├── tokenized/
│   └── sft/
├── docs/
│   └── decisions/
├── frontend/
├── scripts/
├── server/
├── src/
│   ├── cli/
│   ├── config/
│   ├── data/
│   ├── evaluation/
│   ├── inference/
│   ├── model/
│   ├── runtime/
│   ├── tokenizer/
│   └── training/
├── tests/
├── AGENTS.md
├── README.md
├── requirements-dev.txt
├── pyproject.toml
├── requirements.txt
└── .editorconfig
```

- [확정] `data/`의 하위 디렉터리와 `checkpoints/`는 자리 유지를 위한 파일만 포함하며 데이터나 체크포인트가 생성된 상태가 아니다.
- [확정] `experiments/`는 추적 구조로 존재하지 않으며 `artifacts/`는 Git에서 제외되는 로컬 실행 경로일 수 있다. AI Hub 분석 산출물은 저장소 밖의 로컬 analysis root에 둔다.
- [확정] `frontend/`에는 현재 Next.js 애플리케이션이 구현돼 있지 않다.
- [확정] `server/` 파일이 존재하지만 FastAPI 서비스가 구현 완료된 상태는 아니다.
- [확정] `logs/`, `artifacts/`, `experiments/`는 경로 정책과 Git 제외 규칙만 정의하며 필요 시점 전에는 만들지 않는다.

## 4. 계획 구조 후보

다음은 시스템 책임을 기준으로 한 목표 구조 후보이다. 현재 존재하지 않는 경로는 이번 단계에서 생성하지 않는다.

```text
DohaLM/
├── configs/       # 버전 관리 가능한 실행 설정
├── docs/          # 기준 문서와 ADR
├── src/           # 토크나이저·데이터·모델·학습·평가·추론 소스
├── server/        # FastAPI 서비스 계층
├── frontend/      # Next.js 채팅 화면
├── tests/         # 단위·통합·회귀 테스트
├── scripts/       # 재현 가능한 작업 진입점
├── experiments/   # [검증 필요] 실험별 적용 설정과 메타데이터
├── artifacts/     # [검증 필요] 배포·평가용 선별 산출물
├── checkpoints/   # 로컬 모델·옵티마이저 복원 상태
└── data/          # 원천·정제·토큰화·SFT 데이터
```

## 5. 디렉터리 책임과 Git 정책

| 경로 | 목적 | 포함할 항목 | 포함하지 않을 항목 | Git 추적 원칙 | 하위 `AGENTS.md` | 생성 시점/선행 조건 |
|---|---|---|---|---|---|---|
| `configs/` | 실행 설정의 단일 기준 제공 | 모델·학습·평가 설정, 외부 데이터 경로·수동 mapping 예시 | 실제 개인 절대 경로, 승인자 정보, 체크포인트, 데이터 | 예시는 추적하고 `local-datasets.yaml`과 실제 mapping YAML은 제외 | 현재 없음, 필요 시 검토 | 실제 설정 구현 단계 |
| `docs/` | 기준 문서와 결정 이력 | 설계, 기능명세, 정책, ADR | 실행 산출물 | 추적 | 존재 | 기능 구현 전 |
| `docs/training/phase2-tokenizer-contract.md` | Phase 2 구현 계약 | corpus·SentencePiece·artifact·API·평가·호환성 기준 | 실제 설정·코드·artifact | 추적 | `docs/AGENTS.md` 적용 | 토크나이저 구현 전 |
| `src/config/` | YAML 설정 로딩·검증·병합 | schema, Tiny 불변 조건, CLI override | 모델·학습 구현 | 소스만 추적 | 현재 없음 | Phase 0 구현 |
| `src/runtime/` | 환경·경로·로깅 기반 제공 | 환경 진단, 저장소 경로, 기본 로깅 | 학습 metric logger | 소스만 추적 | 현재 없음 | Phase 0 구현 |
| `src/cli/` | Phase 0 진단 진입점 | 환경·설정·resolved config·경로 명령 | 학습·추론 명령 | 소스만 추적 | 현재 없음 | Phase 0 구현 |
| `src/tokenizer/` | 토크나이저 학습·래퍼 | SentencePiece 연동 소스 | 학습 corpus, 생성 모델 | 소스만 추적 | 필요 시 검토 | 토크나이저 구현 단계 |
| `src/data/` | 정제·중복 제거·데이터셋 구성 | 탐색·reader·validation·정규화·checksum/ID·exact dedup·split/leakage·artifact·pipeline·dataset adapter 소스 | 실제 대용량 데이터 | 소스만 추적 | Phase 1 최소 파이프라인 구현 | Gate 2 승인 전 synthetic fixture 검증 |
| `src/model/` | Decoder-only Transformer | Config·구성요소·전체 forward·shifted loss·greedy generation·state round-trip helper·parameter count | 완성형 외부 GPT 모델, trainer·checkpoint manager | 소스만 추적 | 존재 | Phase 3 구성요소와 Phase 4 통합 구현 |
| `src/training/` | 합성 Trainer Foundation과 Tiny 실규모 검증 | config·dataset/collator/loader·stateful sampler·AdamW·linear/cosine 후보·AMP·accumulation·metric·memory/throughput·checkpoint/resume | 실제 corpus 사전학습, SFT, 운영 실험 registry | 소스만 추적 | Phase 5 합성 범위 구현 및 Gate 6 `passed` | Gate 3·7과 실제 데이터·Pilot 승인 전 |
| `src/evaluation/` | 정량·정성 평가 | 평가 로직 | 대용량 결과 원본 | 소스만 추적 | 필요 시 검토 | 평가 계획 승인 후 |
| `src/inference/` | 생성과 채팅 템플릿 | 로컬 추론 로직 | 서버 라우팅, UI | 소스만 추적 | 필요 시 검토 | 추론 설계 승인 후 |
| `server/` | FastAPI 경계 | 스키마, 라우팅, 모델 서비스 | 모델 핵심 구현 | 소스만 추적 | 필요 시 검토 | API 명세 승인 후 |
| `frontend/` | Next.js 채팅 화면 | UI 소스와 정적 자산 | 모델 체크포인트 | 소스만 추적 | 필요 시 검토 | 프론트엔드 명세 승인 후 |
| `tests/` | 검증 자동화 | 단위·통합·회귀 테스트 | 실제 개인정보 데이터 | 테스트 소스·소형 fixture만 추적 | 필요 시 검토 | 각 구현과 함께 |
| `scripts/` | 반복 작업 진입점 | 모델·합성 학습 smoke와 checkpoint 검사·재개, 외부 데이터 구조 분석·안전 표본·수동 mapping·bounded JSON·prefix review·record 경계 분석 | 실제 원본·개인 절대 경로, 추출 표본·record 원문, 핵심 학습 모델 | 추적 | 필요 시 검토 | 해당 작업 구현과 함께 |
| `data/` | 단계별 데이터 보관 | raw, cleaned, tokenized, sft | 소스 코드, 비밀값 | 대용량 데이터 제외 | 불필요, 정책 문서 우선 | 라이선스 확인 후 |
| `checkpoints/` | 학습 재개 상태 보관 | 모델·옵티마이저·스케줄러·AMP 상태 | 소스 코드 | 본체 제외 | 불필요 | 첫 학습 실행 시 |
| `experiments/` | 실험별 메타데이터와 적용 설정 | [검증 필요] 실험 manifest, 설정 snapshot | 원천 데이터, 대형 체크포인트 | 소형 기록만 추적 후보 | 필요 시 검토 | 실험 관리 스키마 승인 후 |
| `artifacts/` | 공유·배포 대상으로 선별한 결과 | [검증 필요] 모델 카드, 평가 요약, 배포 묶음; tokenizer bundle 논리 경로 후보 | 모든 중간 산출물 | 항목별 결정, binary tokenizer는 제외 | 필요 시 검토 | 산출물 정책 승인 후 |

## 6. 설정·소스·산출물·실험 기록의 경계

| 구분 | 기준 위치 | 식별 기준 | 예시 |
|---|---|---|---|
| 설정 | `configs/` | 실행 전에 사람이 검토하고 버전 관리할 입력 | 모델 구조, 학습 기본값 |
| 소스 | `src/`, `server/`, `frontend/`, `scripts/` | 동작을 정의하는 코드 | 모델 계층, 데이터 처리, API |
| 데이터 | `data/` | 학습·평가의 입력 또는 변환 결과 | 원천 문서, token IDs |
| 실험 기록 | `experiments/` 후보 | 한 실행의 설정·환경·결과를 연결하는 메타데이터 | experiment ID, 적용 설정 |
| 산출물 | `artifacts/` 후보, `checkpoints/` | 실행으로 생성되며 소비자에게 전달되거나 복원에 사용 | 체크포인트, 모델 카드 |

- [확정] 실행 시 적용된 최종 설정은 체크포인트 또는 실험 manifest와 연결해야 한다.
- [확정] Phase 1~6 구현의 기능 경계, 입력·출력·오류와 테스트 계약은 [핵심 개발 기능명세서](./core-development-feature-specification.md)를 공통 기준으로 사용한다.
- [검증 필요] `experiments/`와 `artifacts/` 사이에서 평가 결과와 생성 샘플을 어느 쪽에 둘지는 [실험 관리 정책](../training/experiment-management.md)에 따라 구현 전에 확정한다.

## 7. `AGENTS.md` 적용 범위

1. [확정] 루트 `AGENTS.md`는 저장소 전체에 적용한다.
2. [확정] `docs/AGENTS.md`는 `docs/` 하위 문서에 추가 적용한다.
3. [확정] `src/data/AGENTS.md`, `src/model/AGENTS.md`, `src/training/AGENTS.md`는 각 디렉터리의 작업에 추가 적용한다.
4. [확정] 하위 규칙이 상위 규칙과 충돌하면 더 엄격한 규칙을 우선하며, 해석으로 해결할 수 없는 충돌은 작업을 중단하고 기록한다.
5. [확정] 사용자 또는 시스템의 명시적 지시가 저장소 안내 문서보다 우선한다.

## 8. 미결정 사항

- [검증 필요] `experiments/` 내부 경로 규칙과 experiment ID 형식
- [검증 필요] `artifacts/`에 포함할 최소 배포 묶음과 외부 저장소 사용 여부
- [검증 필요] 소형 fixture와 평가 결과의 Git 추적 크기 한도
- [검증 필요] 추가 하위 `AGENTS.md`가 필요한 시점과 범위
- [검증 필요] 기존 빈 스캐폴드 파일과 과거 문서의 정리·이동 계획

## 9. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-26 | [확정] 외부 artifact root의 운영 `operating-16k-v2/unigram-16k` 승인과 Gate 3 완료 상태를 반영하고 실제 사전학습 미구현 경계를 유지함 |
| 2026-07-24 | [확정] stateful sampler·cosine 후보·memory/throughput·Tiny validation과 probe/inspection CLI 책임을 반영함 |
| 2026-07-24 | [확정] Phase 5 합성 Trainer Foundation과 training smoke·checkpoint 검사·재개 CLI 책임을 반영함 |
| 2026-07-24 | [확정] Phase 4 전체 model·loss·generation·state helper와 model smoke CLI 책임을 반영함 |
| 2026-07-24 | [확정] Phase 3 직접 구현 모델 구성요소와 Phase 4 통합 모델의 경계를 반영함 |
| 2026-07-24 | [확정] `src/data/adapters/`의 공통 계약과 AIHUB-71748 synthetic adapter 책임을 반영함 |
| 2026-07-24 | [확정] Synthetic SentencePiece smoke core·CLI·fixture와 운영 tokenizer 미구현 경계를 반영함 |
| 2026-07-24 | [확정] 승인 정책·redaction·수동 review·삭제 manifest를 갖춘 비공개 최소 preview 도구 책임을 반영함 |
| 2026-07-24 | [확정] ZIP JSON record state machine과 값 비노출 manifest 책임을 scripts 경계에 반영함 |
| 2026-07-24 | [확정] 대용량 JSON bounded streaming inspector와 원문 비노출 prefix review 책임을 scripts 경계에 반영함 |
| 2026-07-24 | [확정] Git 제외 실제 mapping 설정과 별도 수동 prefix mapping 구현 책임을 configs·scripts 경계에 반영함 |
| 2026-07-23 | [확정] docs 책임과 Phase 1~6 구현 기준에 핵심 개발 기능명세서를 연결함 |
| 2026-07-23 | [확정] Phase 2 토크나이저 계약 문서와 versioned tokenizer artifact의 논리 경계·Git 제외 원칙을 연결함 |
| 2026-07-23 | [확정] 현재 구조와 계획 구조, 디렉터리 책임, Git 및 `AGENTS.md` 적용 원칙의 초안 작성 |
