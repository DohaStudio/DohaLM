# DohaLM Current Project Status

- 문서 상태: `current`
- 기준 시점: 2026-08-04
- 기준 브랜치: `develop`
- 관련 문서: [개발 Roadmap](../quality/development-roadmap.md), [Model Family Roadmap](./model-family-roadmap.md), [DohaLM Instruct](../instruct/README.md), [Backend MVP](../service/dohalm-backend-mvp.md), [Frontend MVP](../service/dohalm-frontend-mvp.md)

## 1. 프로젝트 정의

DohaLM은 다음 두 축을 함께 검증하는 로컬 AI 프로젝트다.

1. 한국어 소형 Decoder-only Transformer를 직접 구현·학습·평가하는 Foundation Model 연구 트랙
2. Qwen Base와 QLoRA Adapter를 이용해 다른 프로젝트에서 재사용할 수 있는 로컬 Instruct Runtime을 만드는 응용 트랙

두 트랙의 모델 계보는 분리한다.

- `DohaLM-Tiny Candidate B`: 직접 구현하고 사전학습한 현재 공식 Tiny Base baseline
- `Qwen Base + DohaLM General Instruct Adapter`: 실제 서비스 기능에 사용할 재사용형 Instruct Runtime 후보

Qwen 기반 Adapter는 DohaLM-Tiny에 연결되는 Adapter가 아니다. 학습에 사용한 동일 Qwen Base·Tokenizer·Chat Template과 함께 사용한다.

## 2. 통합 상태

| 영역 | 상태 | 핵심 결과 |
|---|---|---|
| Gate 0 | `approved` | 프로젝트 범위 승인 |
| Gate 1~7 | `passed` | 환경·데이터·Tokenizer·모델·Trainer·Tiny Overfit 검증 완료 |
| 운영 Tokenizer | `approved` | `operating-16k-v2/unigram-16k`, vocabulary 16,000 |
| DohaLM-Tiny | `completed` | forward·loss·generation·Trainer·checkpoint/resume 구현 |
| Tiny Overfit | `passed` | 64문서 1,000-step packed memorization 검증 |
| Pilot / Candidate A | `completed` | canonical Pilot 100-step, Candidate A 10M token |
| Candidate B | `current_base_baseline` | 25,001,984 token 학습·Final Quick/Full 평가 완료 |
| Candidate B 생성 종료 | `diagnostic_limit` | pure greedy EOS 0%, maximum-length 종료 100%; Base 진단 결과로 보존 |
| Evaluation Framework | `completed` | Quick·Full·EOS·position·category·stability·privacy·lineage |
| AIHUB-71748 SFT Processing | `completed` | Processing Run 0015 완료 |
| Qwen SFT Tokenization | `completed` | DohaLM v0.1 Qwen tokenization 완료 |
| QLoRA Training | `not_started` | 설정 준비, 실제 General Instruct Adapter 미생성 |
| FastAPI MVP | `implemented` | Mock·Base Qwen Provider, Chat API, SSE, cancellation 구현 |
| Base Qwen Provider | `verified_local_only` | lazy load·일반 Chat·SSE·Chrome E2E 검증 |
| DohaLM Adapter Provider | `placeholder` | Adapter artifact 부재로 실제 로딩 미구현 |
| Next.js Frontend | `implemented` | HTTP·SSE·취소·재시도·반응형 Chrome E2E 통과 |
| 배포 | `out_of_scope` | 로컬 전용 프로젝트로 유지 |

## 3. 완료된 Foundation Model 트랙

### 3.1 기반과 데이터

- Gate 0 승인, Gate 1~7 통과
- 환경·설정·경로·데이터 lineage·split·PII·checksum 계약 검증
- 운영 16k Unigram Tokenizer 승인
- 직접 구현한 Decoder-only Transformer와 Trainer 검증
- FP16 AMP, scheduler, gradient clipping, checkpoint와 resume 검증

### 3.2 학습과 평가

- canonical Pilot 100-step 완료
- Candidate A 10M token 완료
- Candidate B 25M token 완료
- Candidate B를 ADR-009 기준 현재 공식 Base baseline으로 사용
- Candidate A는 historical regression baseline으로 보존
- Candidate B 추가 training·resume·extension·Candidate C는 현재 범위에 포함하지 않음

Candidate B의 teacher-forced 지표는 Candidate A보다 개선됐지만 pure greedy EOS 종료 문제는 남아 있다. 이 결과는 실패를 숨기지 않고 Base 모델의 실험·평가 결과로 보존한다.

## 4. 현재 1차 목표: 재사용 가능한 DohaLM Runtime

현재 최우선 목표는 Qwen Base 기반 General Instruct Adapter를 완성하고 로컬 Runtime에 연결하는 것이다.

```text
DohaLM Runtime
├── Runtime
├── Adapter Loader
├── Chat API
├── Streaming
└── Prompt Engine
```

### 4.1 General Instruct Adapter

남은 작업:

1. Processing Run 0015 산출물 최종 검증
2. Prompt serialization·Chat Template·assistant loss mask·EOS 계약 확정
3. QLoRA CPU/GPU smoke training
4. 소규모 overfit 검증
5. 본 QLoRA 학습
6. Adapter artifact와 metadata 생성
7. Base Qwen 대비 Instruct 평가

완성 artifact는 최소 다음을 포함한다.

```text
dohalm-general-instruct-adapter/
├── adapter_config.json
├── adapter_model.safetensors
├── tokenizer / chat template reference
├── generation_config.json
├── model_metadata.json
└── README.md
```

### 4.2 Runtime 연결

Adapter 생성 후 다음을 구현한다.

- `DohaLMAdapterProvider` 실제 로딩
- 동일 Qwen Base·Tokenizer·Chat Template 강제 검증
- lazy loading과 readiness
- 일반 Chat과 SSE streaming
- cancellation·timeout·오류 계약
- Adapter 버전과 model metadata 표시
- Frontend 실제 브라우저 E2E

## 5. 1차 목표의 활용 범위

General Instruct Runtime은 다음과 같은 텍스트 기능에 공통으로 재사용한다.

- 게시판 글 작성과 제목 자동 생성
- 요약·교정·번역
- 아이디어와 프롬프트 생성
- 일반 질의응답
- LogLens·ERP 등 다른 로컬 프로젝트의 LLM 기능
- DohaMusic의 곡 기획·가사 보조·음악 생성 프롬프트 작성

Adapter는 특정 프로젝트 코드에 종속시키지 않고 공통 Runtime을 통해 호출하는 구조를 우선한다.

## 6. 후속 목표

### 6.1 2차 목표: Memory와 확장 기능

1차 Runtime 완료 이후 검토한다.

```text
DohaLM Extended Runtime
├── Memory
├── RAG
├── Tool Calling
└── Agent
```

Memory는 1차 완료 조건이 아니다. 대화 기록, 사용자 취향, 프로젝트 지식을 장기적으로 참조해야 할 때 별도 설계한다.

### 6.2 3차 목표: DohaMusic

DohaMusic은 DohaLM을 활용하는 개인 전용 로컬 응용 프로젝트다.

```text
DohaMusic
├── 곡 콘셉트 생성
├── 가사 구조·초안·수정
├── 음악 생성 모델용 프롬프트
├── 개인 가사 저장·검색
├── 가사 스타일 분석
└── 개인 Music Adapter
```

초기에는 General Instruct Runtime과 저장된 가사 검색을 사용한다. 본인이 작성한 가사가 충분히 축적되면 별도 Music Adapter를 QLoRA로 추가 학습한다. 실제 오디오·MIDI 생성은 DohaLM의 역할이 아니며 별도의 음악 생성 모델이 담당한다.

## 7. 현재 범위 밖

- 클라우드·외부 공개 배포
- Docker·Nginx·도메인·HTTPS·CI/CD 배포 파이프라인
- 다중 사용자 계정과 운영 인증
- 상용 공개 API
- Candidate B 추가 학습, Candidate C
- RLHF와 Preference Training
- 실제 음원·보컬·MIDI 생성 모델 개발
- Model/checkpoint/tokenizer/dataset 공개 배포

로컬 실행 재현, 테스트, 문서, 시연 영상은 포트폴리오 완성 범위에 포함한다.

## 8. 다음 작업 순서

1. 현재 문서와 코드 상태 동기화
2. SFT Processing Run 0015 산출물 검증
3. QLoRA 학습 계약과 smoke 확정
4. General Instruct Adapter 학습
5. Instruct 전후 평가
6. `DohaLMAdapterProvider` 구현
7. Frontend Adapter 연결과 E2E
8. 공통 Runtime 사용 예제와 README 정리
9. DohaMusic에서 Runtime 연동
10. 개인 가사 저장·검색 후 Music Adapter 확장

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-04 | Foundation 연구 트랙과 Qwen 기반 응용 트랙 분리 명시 |
| 2026-08-04 | 현재 상태를 Processing Run 0015·Qwen tokenization·Base Qwen E2E 기준으로 갱신 |
| 2026-08-04 | 1차 목표를 General Instruct Adapter와 Runtime·Adapter Loader·Chat API·Streaming·Prompt Engine으로 확정 |
| 2026-08-04 | Memory를 2차 목표로 이동하고 DohaMusic을 3차 개인 응용 프로젝트로 정의 |
| 2026-08-04 | 클라우드·외부 배포를 프로젝트 범위 밖으로 확정 |
| 2026-07-28 | Candidate B current Base baseline과 평가 상태 기록 |
