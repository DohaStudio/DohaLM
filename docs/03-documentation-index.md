# DohaLM 문서 인덱스

## 상태 기준

- [확정] `작성 완료`: 현재 단계에서 요구된 내용이 작성됨. 구현 완료를 의미하지 않는다.
- [확정] `기존 스캐폴드`: 파일은 있으나 제목 수준이므로 기준 문서로 사용하지 않는다.
- [확정] `작성 예정`: 아직 파일이 없거나 기준 내용이 작성되지 않음.
- [후순위] `후순위`: 선행 실험 또는 핵심 구현 이후 작성 가능함.

## 문서 계획

| 파일명 | 문서 목적 | 주요 내용 | 선행 문서 | 작성 상태 | 구현 전 필수 여부 |
|---|---|---|---|---|---|
| `00-project-overview.md` | 프로젝트 최상위 개요 정의 | 배경, 목적, 결과물, 개발 흐름, 완료 조건 | 없음 | [확정] 작성 완료 | 예 |
| `01-scope-and-goals.md` | 범위와 성공·중단 기준 정의 | MVP, Tiny, Small, 포함·제외 범위 | `00-project-overview.md` | [확정] 작성 완료 | 예 |
| `02-development-rules.md` | 개발 및 검증 규칙 정의 | 직접 구현, 재현성, Git, 테스트, 데이터 기록 | `00`, `01` | [확정] 작성 완료 | 예 |
| `03-documentation-index.md` | 문서 작성 순서와 상태 관리 | 전체 문서 목록, 의존성, 필수 여부 | `00`, `01`, `02` | [확정] 작성 완료 | 예 |
| `decisions/ADR-001-initial-model-scope.md` | 최초 모델 범위 결정 기록 | 8GB 제약, Tiny 우선, 모델 규모 역할 | `00`, `01` | [확정] 작성 완료 | 예 |
| `03-system-architecture.md` | 전체 시스템 경계와 흐름 정의 | 데이터→학습→평가→서버→UI, 모듈 책임 | `00`, `01`, `02`, ADR-001 | [검증 필요] 작성 예정 | 예 |
| `04-model-architecture.md` | 모델 계산 구조와 사양 확정 | shape, 파라미터 산식, attention, FFN, norm, init | `03-system-architecture.md`, ADR-001 | [검증 필요] 작성 예정 | 예 |
| `05-tokenizer-design.md` | 한국어 토크나이저 설계 | SentencePiece 방식, 정규화, special token, 평가 | `04-model-architecture.md` | [검증 필요] 작성 예정 | 예 |
| `06-data-strategy.md` | 데이터 선택 및 거버넌스 정의 | 후보, 라이선스, 품질, 분할, 제외 기준 | `01`, `02`, `05` | [검증 필요] 작성 예정 | 예 |
| `07-data-preprocessing.md` | 재현 가능한 전처리 명세 | 정제, 중복 제거, 필터, 샤딩, 계보 | `05`, `06` | [검증 필요] 작성 예정 | 예 |
| `08-pretraining-plan.md` | 사전학습 절차와 자원 계획 | objective, optimizer, schedule, batch, resume | `04`, `05`, `07`, `16` | [검증 필요] 작성 예정 | 예 |
| `09-sft-plan.md` | 질문·답변 SFT 설계 | 데이터 형식, chat template, loss mask, 비교 평가 | `05`, `07`, `08` | [검증 필요] 작성 예정 | SFT 전 필수 |
| `10-evaluation-plan.md` | 공통 평가 기준 정의 | loss, perplexity, 생성, 한국어 평가, 합격선 | `04`, `05`, `08`, `09` | [검증 필요] 작성 예정 | 학습 전 필수 |
| `11-inference-design.md` | 자기회귀 생성 및 모델 로딩 설계 | sampling, KV cache 검토, device, latency, 안전 제한 | `04`, `09`, `10`, `16` | [검증 필요] 작성 예정 | 추론 구현 전 필수 |
| `12-api-specification.md` | FastAPI 계약 정의 | endpoint, schema, 오류, streaming, lifecycle | `03`, `11` | [후순위] 작성 예정 | API 구현 전 필수 |
| `13-frontend-specification.md` | Next.js 채팅 화면 명세 | 화면 상태, 메시지 흐름, 오류 및 접근성 | `12` | [후순위] 작성 예정 | UI 구현 전 필수 |
| `14-database-design.md` | 영속화 필요성과 구조 판단 | 저장 대상, 스키마, 보존·삭제, 미사용 대안 | `03`, `12`, `13` | [후순위] 작성 예정 | 조건부 |
| `15-experiment-management.md` | 실험과 산출물 추적 규칙 정의 | experiment ID, config snapshot, 로그, checkpoint | `02`, `08`, `10` | [검증 필요] 작성 예정 | 본 학습 전 필수 |
| `16-gpu-memory-strategy.md` | 8GB VRAM 실행 전략 정의 | 메모리 산식, AMP, accumulation, checkpointing, OOM 절차 | `04`, ADR-001 | [검증 필요] 작성 예정 | 학습 구현 전 필수 |
| `17-development-roadmap.md` | 단계별 작업 순서와 게이트 정의 | milestone, 의존성, 산출물, 중단·재검토 시점 | 전체 설계 문서 초안 | [검증 필요] 작성 예정 | 본 구현 전 필수 |
| `18-testing-checklist.md` | 완료 판정용 테스트 체계 정의 | 단위, 통합, 재현성, 성능, API·UI 점검 | 구현 대상별 설계 문서 | [검증 필요] 작성 예정 | 각 구현 전 필수 |
| `19-deployment-plan.md` | 로컬·컨테이너 실행 및 배포 계획 | 환경, 이미지, 모델 배치, 모니터링, 롤백 | `11`, `12`, `13`, `14`, `18` | [후순위] 작성 예정 | 배포 전 필수 |
| `20-leaderboard-strategy.md` | K-AI Leaderboard 제출 가능성 검토 | 최신 규정, 형식, 라이선스, 평가, gap 분석 | `10`, `15`, `19` | [후순위] 작성 예정 | 아니요 |

## 권장 작성 순서

1. [확정] 시스템·모델·토크나이저: `03` → `04` → `05`
2. [확정] 데이터: `06` → `07`
3. [확정] 자원·학습·평가: `16` → `08` → `10` → `15`
4. [확정] SFT·추론: `09` → `11`
5. [확정] 실행 계획과 검증: `17` → `18`
6. [후순위] 서비스: `12` → `13` → `14` → `19`
7. [후순위] 외부 제출: `20`

## 현재 저장소 문서와의 관계

- [확정] 기존 `01-project-plan.md`, `02-model-architecture.md`, `03-data-policy.md`, `04-training-plan.md`, `05-evaluation-plan.md`, `06-deployment-plan.md`은 현재 영문 제목만 있는 스캐폴드다.
- [확정] 이번 단계에서는 기존 파일을 삭제·변경하지 않았다.
- [검증 필요] 후속 문서화 단계에서 기존 스캐폴드의 이름을 새 문서 계획에 맞게 유지, 이동 또는 대체할지 결정해야 한다. 결정 전에는 위 표의 정확한 파일명을 기준으로 사용한다.
- [확정] 번호가 같은 `03-documentation-index.md`와 계획 문서 `03-system-architecture.md`는 역할이 다르며 둘 다 유지한다.

## 공통 작성 규칙

- [확정] 모든 문서는 한국어 Markdown으로 작성한다.
- [확정] 모델명과 하드웨어 표기는 `DohaLM-Tiny`, `DohaLM-Small`, `RTX 3060 Ti 8GB`로 통일한다.
- [확정] 목표, 현재 구현 상태 및 검증 결과를 구분한다.
- [확정] 확인되지 않은 내용에는 상태를 표시하고 검증 방법 또는 선행 문서를 연결한다.
- [확정] 외부 규정과 라이선스는 적용 시점에 공식 출처로 다시 확인한다.
