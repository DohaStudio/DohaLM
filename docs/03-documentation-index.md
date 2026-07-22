# DohaLM 문서 인덱스

## 1. 문서 상태 체계

문서 자체의 생명주기 상태는 다음 영문 값만 사용한다.

| 상태 | 의미 |
|---|---|
| `planned` | 파일이 없거나 목차·작성 계획만 존재함 |
| `draft` | 초안이 작성되었으나 핵심 미결정 사항이 남아 있음 |
| `review` | 필수 내용이 작성되어 검토를 기다리거나 검토 중임 |
| `approved` | 프로젝트 기준 문서 또는 결정으로 승인됨. 구현 완료를 뜻하지 않음 |
| `implemented` | 승인된 문서가 코드·설정·테스트에 반영되고 검증됨 |
| `deprecated` | 후속 문서나 결정으로 대체되어 더 이상 현재 기준이 아님 |

- [확정] `approved`는 설계 승인이고 `implemented`는 구현 및 검증 완료다.
- [확정] 구현되지 않은 문서에 `implemented`를 사용하지 않는다.
- [확정] 문서 상태와 본문의 `[확정]`, `[가정]`, `[검증 필요]`, `[후순위]`, `[제외]` 태그는 서로 다른 축이다.
- [확정] 예를 들어 문서 상태가 `review`여도 본문 안에는 이미 결정된 `[확정]` 항목과 아직 남은 `[검증 필요]` 항목이 함께 있을 수 있다.

## 2. 전체 문서 현황

| 파일명 | 문서 목적 | 선행 문서 | 후속 문서 | 현재 상태 | 구현 전 필수 여부 | 마지막 검토일 | 핵심 미결정 사항 |
|---|---|---|---|---|---|---|---|
| `00-project-overview.md` | 프로젝트 최상위 목적과 완료 조건 정의 | 없음 | `01`, `02`, 전체 설계 문서 | `review` | 예 | 2026-07-23 | 처리량, 학습 시간, 데이터 규모 |
| `01-scope-and-goals.md` | MVP와 Tiny/Small 범위 및 성공 기준 정의 | `00` | `04`, `08`, `09`, `16` | `review` | 예 | 2026-07-23 | 정량 합격선, Small 진행 기준 |
| `02-development-rules.md` | 개발·재현성·설정·데이터·Git·테스트 규칙 정의 | `00`, `01`, ADR-002 | 모든 구현 문서 | `review` | 예 | 2026-07-23 | 학습 hyperparameter, 실제 VRAM, 데이터 라이선스 |
| `03-documentation-index.md` | 문서 상태·의존성·작성 순서 관리 | `00`, `01`, `02` | 전체 문서 | `review` | 예 | 2026-07-23 | 계획 문서 작성 일정 |
| `decisions/README.md` | ADR 목록과 상태 관리 | ADR 전체 | 후속 ADR | `review` | 예 | 2026-07-23 | 없음 |
| `decisions/ADR-001-initial-model-scope.md` | Tiny 우선 개발과 모델 규모 범위 결정 | `00`, `01` | ADR-002, `04`, `16` | `approved` | 예 | 2026-07-23 | Tiny 실측과 Small 진행 여부 |
| `decisions/ADR-002-tiny-model-architecture.md` | DohaLM-Tiny 세부 구조 결정 | ADR-001, `04` | 구현, `08`, `16` | `approved` | 예 | 2026-07-23 | Dropout, 초기화 방식 |
| `decisions/ADR-003-tokenizer-method.md` | SentencePiece Unigram 및 어휘 정책 결정 | `01`, `05` | `06`, `07`, `08`, `09` | `approved` | 예 | 2026-07-23 | character coverage, normalization, byte fallback |
| `03-system-architecture.md` | 데이터→학습→평가→서버→UI 시스템 경계 정의 | `00`, `01`, `02`, ADR-001 | `21`, `22`, `04`, `11`, `12` | `review` | 예 | 2026-07-23 | serialization, 실험 metadata, 서비스 schema |
| `04-model-architecture.md` | Tiny 계산 구조, shape와 파라미터 산식 정의 | `01`, ADR-001, ADR-002 | `08`, `09`, `11`, `16`, `18` | `review` | 예 | 2026-07-23 | Dropout, 초기화, padding mask 세부 규칙 |
| `05-tokenizer-design.md` | 한국어 SentencePiece 토크나이저 설계 | `01`, ADR-003 | `06`, `07`, `08`, `09` | `review` | 예 | 2026-07-23 | character coverage, normalization, byte fallback, corpus |
| `06-data-strategy.md` | 데이터 후보·라이선스·품질·분할 정책 정의 | `01`, `02`, `05` | `07`, `08`, `09` | `planned` | 예 | — | 데이터 후보와 사용 허가 |
| `07-data-preprocessing.md` | 정제·중복 제거·필터·샤딩·계보 명세 | `05`, `06` | `08`, `09`, `18` | `planned` | 예 | — | packing, 경계, 필터 임계치 |
| `08-pretraining-plan.md` | 사전학습 절차, 자원, 복원 계획 정의 | `04`, `05`, `07`, `16` | `10`, `15`, `17`, `18` | `draft` | 예 | 2026-07-23 | LR, warmup, weight decay, token budget, batch, 저장 주기 |
| `09-sft-plan.md` | 질문·답변 SFT 형식과 loss 정책 정의 | `05`, `07`, `08` | `10`, `11`, `15`, `18` | `draft` | SFT 전 필수 | 2026-07-23 | 데이터, system 문구, truncation, hyperparameter |
| `10-evaluation-plan.md` | 공통 정량·정성 평가 기준 정의 | `04`, `05`, `08`, `09` | `11`, `15`, `17`, `20` | `planned` | 학습 전 필수 | — | 지표, 데이터셋, 합격선 |
| `11-inference-design.md` | 자기회귀 생성과 모델 로딩 설계 | `04`, `09`, `10`, `16` | `12`, `13`, `19` | `planned` | 추론 구현 전 필수 | — | sampling, KV cache, latency 정책 |
| `12-api-specification.md` | FastAPI 요청·응답 계약 정의 | `03`, `11` | `13`, `14`, `19` | `planned` | API 구현 전 필수 | — | streaming, 오류, lifecycle |
| `13-frontend-specification.md` | Next.js 채팅 화면과 상태 흐름 정의 | `12` | `14`, `19` | `planned` | UI 구현 전 필수 | — | 화면·오류·접근성 세부사항 |
| `14-database-design.md` | 영속화 필요성과 데이터 구조 결정 | `03`, `12`, `13` | `19` | `planned` | 조건부 | — | DB 사용 여부, 보존·삭제 정책 |
| `15-experiment-management.md` | 실험 ID, 로그, config, checkpoint 관리 | `02`, `08`, `10` | `17`, `18`, `20` | `planned` | 본 학습 전 필수 | — | 저장 경로, 보존 정책, 추적 형식 |
| `16-gpu-memory-strategy.md` | 8GB VRAM 산식·측정·OOM 대응 정의 | `04`, ADR-001, ADR-002 | `08`, `11`, `17`, `18` | `draft` | 학습 구현 전 필수 | 2026-07-23 | micro-batch, accumulation, checkpointing, 실측값 |
| `17-development-roadmap.md` | 단계별 구현 순서와 통과 게이트 정의 | 핵심 설계 문서 | 구현 작업 | `planned` | 본 구현 전 필수 | — | milestone과 중단 시점 |
| `18-testing-checklist.md` | 단위·통합·재현성·성능 검증 기준 정의 | 구현 대상별 설계 문서 | 구현 완료 판정 | `planned` | 각 구현 전 필수 | — | test matrix와 합격 기준 |
| `19-deployment-plan.md` | 로컬·컨테이너 실행과 배포 계획 정의 | `11`, `12`, `13`, `14`, `18` | `20` | `planned` | 배포 전 필수 | — | 환경, monitoring, rollback |
| `20-leaderboard-strategy.md` | K-AI Leaderboard 제출 가능성 검토 | `10`, `15`, `19` | 제출 결정 ADR | `planned` | 아니요 | — | 최신 규정, 형식, 라이선스, 성능 격차 |
| `21-repository-structure.md` | 현재·계획 저장소 구조와 디렉터리 책임 정의 | `02`, `03` | `22`, `15`, 구현 작업 | `review` | 예 | 2026-07-23 | experiments/artifacts 스키마, 추가 AGENTS 범위 |
| `22-artifact-and-configuration-policy.md` | 설정 우선순위와 산출물 추적·보존·호환성 원칙 정의 | `02`, `03`, `21` | `15`, `19`, 구현 작업 | `review` | 예 | 2026-07-23 | 설정 schema, artifact ID, checkpoint migration |

## 3. 2단계 문서 상태 판단

| 문서 | 상태 | 판단 근거 |
|---|---|---|
| `04-model-architecture.md` | `review` | Tiny 구조와 산식이 작성되고 ADR-002에 반영되었으나 구현·테스트 전임 |
| `05-tokenizer-design.md` | `review` | 방식과 special token은 결정되었으나 corpus 기반 세부 검증 전임 |
| `08-pretraining-plan.md` | `draft` | 필수 흐름은 있으나 학습 hyperparameter와 데이터 계획이 미정임 |
| `09-sft-plan.md` | `draft` | 템플릿은 정의되었으나 데이터·truncation·평가 기준이 미정임 |
| `16-gpu-memory-strategy.md` | `draft` | 이론 전략은 작성되었으나 RTX 3060 Ti 8GB 실측 전임 |

- [확정] 위 다섯 문서는 모두 존재하고 인덱스에 반영되었다.
- [확정] 어느 문서도 구현과 테스트가 완료되지 않았으므로 `implemented`가 아니다.

## 4. 권장 작성·승인 순서

1. [확정] 시스템·저장소·산출물 기준: `03-system-architecture.md` → `21-repository-structure.md` → `22-artifact-and-configuration-policy.md`
2. [확정] 모델·토크나이저: `04-model-architecture.md` → `05-tokenizer-design.md`
3. [확정] 데이터: `06-data-strategy.md` → `07-data-preprocessing.md`
4. [확정] 자원·학습·평가: `16-gpu-memory-strategy.md` → `08-pretraining-plan.md` → `10-evaluation-plan.md` → `15-experiment-management.md`
5. [확정] SFT·추론: `09-sft-plan.md` → `11-inference-design.md`
6. [확정] 실행 계획과 검증: `17-development-roadmap.md` → `18-testing-checklist.md`
7. [후순위] 서비스: `12-api-specification.md` → `13-frontend-specification.md` → `14-database-design.md` → `19-deployment-plan.md`
8. [후순위] 외부 제출: `20-leaderboard-strategy.md`

## 5. 현재 저장소 문서와의 관계

- [확정] 기존 `01-project-plan.md`, `02-model-architecture.md`, `03-data-policy.md`, `04-training-plan.md`, `05-evaluation-plan.md`, `06-deployment-plan.md`은 영문 제목만 있는 스캐폴드이며 현재 기준 문서가 아니다.
- [검증 필요] 기존 스캐폴드의 유지·이동·대체 여부는 별도 문서 정리 작업에서 결정한다.
- [확정] 번호가 같은 `03-documentation-index.md`와 계획 문서 `03-system-architecture.md`는 역할이 다르다.
- [확정] `21`, `22` 번호는 기존 `00`~`20` 문서 번호를 변경하지 않고 운영 기준 문서를 추가하기 위해 사용한다.

## 6. 공통 작성 규칙

- [확정] 모든 문서는 한국어 Markdown으로 작성한다.
- [확정] 모델명과 하드웨어 표기는 `DohaLM-Tiny`, `DohaLM-Small`, `RTX 3060 Ti 8GB`로 통일한다.
- [확정] 목표, 문서 승인, 구현 및 검증 완료를 서로 구분한다.
- [확정] 확인되지 않은 내용에는 본문 상태 태그와 검증 방법을 기록한다.
- [확정] 존재하지 않는 계획 문서는 Markdown 링크 대신 파일명을 코드 형식으로 표시한다.

## 7. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] 시스템 아키텍처, 저장소 구조, 산출물·설정 정책 문서 상태와 선후 관계를 반영함 |
| 2026-07-23 | [확정] 문서 생명주기 상태 체계를 도입하고 2단계 문서 및 ADR 상태를 실제 저장소에 맞게 동기화함 |
