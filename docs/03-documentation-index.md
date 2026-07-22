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
| `decisions/ADR-004-data-governance.md` | 원본 불변·registry·라이선스·계보·누수 방지 결정 | `02`, `03`, `22` | `06`, `07`, `23`, `24`, `25`, `26` | `approved` | 예 | 2026-07-23 | manifest schema, 승인 책임, 실제 데이터 조건 |
| `decisions/ADR-005-evaluation-and-experiment-policy.md` | 고정 평가 조건·실험 계보·실패 보존 결정 | `02`, `08`, `09`, `22`, `26` | `10`, `15`, `27`, `28`, `29`, `30` | `approved` | 예 | 2026-07-23 | 합격선, 반복 seed, schema, Benchmark 후보 |
| `decisions/ADR-006-development-quality-gates.md` | 단계별 Ready·Done·테스트 기반 품질 게이트 결정 | `02`, `10`, `15`, `17`, `31`, `32`, `33` | `17`, `18`, `34`, `35`, `36`, 구현 작업 | `approved` | 예 | 2026-07-23 | 실제 명령, 정량 합격선, 단계별 승인 책임 |
| `03-system-architecture.md` | 데이터→학습→평가→서버→UI 시스템 경계 정의 | `00`, `01`, `02`, ADR-001 | `21`, `22`, `04`, `11`, `12` | `review` | 예 | 2026-07-23 | serialization, 실험 metadata, 서비스 schema |
| `04-model-architecture.md` | Tiny 계산 구조, shape와 파라미터 산식 정의 | `01`, ADR-001, ADR-002 | `08`, `09`, `11`, `16`, `18` | `review` | 예 | 2026-07-23 | Dropout, 초기화, padding mask 세부 규칙 |
| `05-tokenizer-design.md` | 한국어 SentencePiece 토크나이저 설계 | `01`, ADR-003 | `06`, `07`, `08`, `09` | `review` | 예 | 2026-07-23 | character coverage, normalization, byte fallback, corpus |
| `06-data-strategy.md` | 데이터 목적·후보 평가·승인 상태와 단계별 규모 정의 | `01`, `02`, `05`, ADR-004 | `23`, `24`, `07`, `25`, `26`, `08`, `09` | `review` | 예 | 2026-07-23 | 실제 후보, 승인 책임, 품질 임계치, token budget |
| `07-data-preprocessing.md` | 원본 불변·정제·중복 제거·분할·packing·계보 명세 | `05`, `06`, `23`, `24`, ADR-004 | `25`, `26`, `08`, `09`, `18` | `review` | 예 | 2026-07-23 | normalization, 필터·dedup 임계치, packing, manifest schema |
| `08-pretraining-plan.md` | 사전학습 절차, 자원, 복원 계획 정의 | `04`, `05`, `07`, `16` | `10`, `15`, `17`, `18` | `draft` | 예 | 2026-07-23 | LR, warmup, weight decay, token budget, batch, 저장 주기 |
| `09-sft-plan.md` | 질문·답변 SFT 형식과 loss 정책 정의 | `05`, `07`, `08` | `10`, `11`, `15`, `18` | `draft` | SFT 전 필수 | 2026-07-23 | 데이터, system 문구, truncation, hyperparameter |
| `10-evaluation-plan.md` | 구현·학습·SFT·생성·자원 평가 단계와 비교 계약 정의 | `04`, `05`, `08`, `09`, `26`, ADR-005 | `27`, `28`, `15`, `29`, `11`, `17`, `20` | `review` | 학습 전 필수 | 2026-07-23 | 합격선, 평가 주기, validation/test, 평가 dtype |
| `11-inference-design.md` | 자기회귀 생성과 모델 로딩 설계 | `04`, `09`, `10`, `16` | `12`, `13`, `19` | `planned` | 추론 구현 전 필수 | — | sampling, KV cache, latency 정책 |
| `12-api-specification.md` | FastAPI 요청·응답 계약 정의 | `03`, `11` | `13`, `14`, `19` | `planned` | API 구현 전 필수 | — | streaming, 오류, lifecycle |
| `13-frontend-specification.md` | Next.js 채팅 화면과 상태 흐름 정의 | `12` | `14`, `19` | `planned` | UI 구현 전 필수 | — | 화면·오류·접근성 세부사항 |
| `14-database-design.md` | 영속화 필요성과 데이터 구조 결정 | `03`, `12`, `13` | `19` | `planned` | 조건부 | — | DB 사용 여부, 보존·삭제 정책 |
| `15-experiment-management.md` | 실험 ID·metadata·상태·실패·산출물 계보 관리 | `02`, `08`, `10`, `22`, ADR-005 | `29`, `30`, `17`, `18`, `20` | `review` | 본 학습 전 필수 | 2026-07-23 | ID 발급, schema, 보존 기간, artifact backend |
| `16-gpu-memory-strategy.md` | 8GB VRAM 산식·측정·OOM 대응 정의 | `04`, ADR-001, ADR-002 | `08`, `11`, `17`, `18` | `draft` | 학습 구현 전 필수 | 2026-07-23 | micro-batch, accumulation, checkpointing, 실측값 |
| `17-development-roadmap.md` | Phase 0~10 구현 순서와 Gate 0~11 통과 기준 정의 | 핵심 설계·데이터·학습·평가 문서, ADR-006 | `18`, `31`, `32`, `33`, `34`, `35`, `36`, 구현 작업 | `review` | 본 구현 전 필수 | 2026-07-23 | 실제 일정, 정량 게이트, 단계별 승인 책임 |
| `18-testing-checklist.md` | 저장소부터 재현성까지 테스트 대상·실패 조치·상태 정의 | `17`, `31`, `32`, `33`, ADR-006, 구현 대상별 설계 문서 | 구현 완료 판정과 게이트 증거 | `review` | 각 구현 전 필수 | 2026-07-23 | 실제 테스트 명령, 구현 매핑, 정량 합격 기준 |
| `19-deployment-plan.md` | 로컬·컨테이너 실행과 배포 계획 정의 | `11`, `12`, `13`, `14`, `18` | `20` | `planned` | 배포 전 필수 | — | 환경, monitoring, rollback |
| `20-leaderboard-strategy.md` | K-AI Leaderboard 제출 가능성 검토 | `10`, `15`, `19` | 제출 결정 ADR | `planned` | 아니요 | — | 최신 규정, 형식, 라이선스, 성능 격차 |
| `21-repository-structure.md` | 현재·계획 저장소 구조와 디렉터리 책임 정의 | `02`, `03` | `22`, `15`, 구현 작업 | `review` | 예 | 2026-07-23 | experiments/artifacts 스키마, 추가 AGENTS 범위 |
| `22-artifact-and-configuration-policy.md` | 설정 우선순위와 산출물 추적·보존·호환성 원칙 정의 | `02`, `03`, `21` | `15`, `19`, 구현 작업 | `review` | 예 | 2026-07-23 | 설정 schema, artifact ID, checkpoint migration |
| `23-dataset-registry.md` | 데이터셋 등록 필드·상태·승인 절차 정의 | `06`, ADR-004 | `24`, `07`, `26` | `review` | 예 | 2026-07-23 | 저장 형식, ID 규칙, 실제 owner |
| `24-data-license-policy.md` | 데이터 이용조건·변경·삭제·공개 검토 원칙 정의 | `02`, `06`, `23`, ADR-004 | `07`, `25`, 모델 카드 | `review` | 예 | 2026-07-23 | 실제 조건, 법률 검토 절차, 조건 snapshot |
| `25-data-quality-checklist.md` | 데이터 품질 검사 상태·방법·조치·기록 기준 정의 | `06`, `07`, `24`, `26` | `08`, `09`, `10` | `review` | 예 | 2026-07-23 | 임계치, 탐지 도구, 사람 검토 범위 |
| `26-data-split-and-leakage-policy.md` | 문서·그룹 단위 분할과 평가 오염 방지 정의 | `06`, `07`, `23`, ADR-004 | `25`, `08`, `09`, `10` | `review` | 예 | 2026-07-23 | split 비율·seed, near/semantic 누수 검사 |
| `27-benchmark-policy.md` | 내부·외부 평가 구분과 Benchmark 채택·누수·보고 원칙 정의 | `10`, `24`, `26`, ADR-005 | `15`, `29`, `20` | `review` | Benchmark 적용 전 필수 | 2026-07-23 | 후보·version·라이선스, 오염 검사, 공식 규정 |
| `28-generation-evaluation.md` | 고정 prompt·생성 설정·붕괴 검사·사람 평가 정의 | `05`, `09`, `10`, `26` | `15`, `29`, `11` | `review` | 생성 평가 전 필수 | 2026-07-23 | 실제 prompt, 생성 기준값, 사람 평가 운영 |
| `29-reproducibility-policy.md` | 환경·seed·계보·재현 수준과 실패 처리 정의 | `02`, `10`, `15`, `22`, ADR-005 | `30`, `18` | `review` | 본 학습 전 필수 | 2026-07-23 | 결정론 설정, 허용 오차, 환경 schema |
| `30-experiment-template.md` | 새 실험의 목적·변수·환경·평가·결과 기록 양식 제공 | `10`, `15`, `29` | 실제 실험 기록 | `review` | 실험 시작 전 필수 | 2026-07-23 | 실제 운영 feedback과 schema 정합성 |
| `31-definition-of-ready.md` | 문서·코드·학습 작업의 착수 가능 조건 정의 | `02`, `17`, ADR-006 | `32`, `33`, `18`, 모든 구현 작업 | `review` | 각 작업 시작 전 필수 | 2026-07-23 | 작업 유형별 승인자, 실제 명령과 입력 계약 |
| `32-definition-of-done.md` | 문서·모델·학습·실험·서비스의 완료 증거 정의 | `17`, `31`, `33`, ADR-006 | `18`, `35`, 완료 판정 | `review` | 각 작업 완료 전 필수 | 2026-07-23 | 정량 합격선, 서비스 단계 세부 기준 |
| `33-test-strategy.md` | 테스트 수준, CPU/GPU 분리, 회귀와 실패 처리 정책 정의 | `02`, `10`, `17`, `31`, `32`, ADR-006 | `18`, 구현별 테스트 계획 | `review` | 테스트 구현 전 필수 | 2026-07-23 | 테스트 도구·명령, CI 구성, 성능 임계값 |
| `34-risk-register.md` | 기술·데이터·평가·운영 위험과 예방·대응 관리 | 핵심 설계 문서, `17`, `33`, ADR-006 | 단계별 작업 계획과 게이트 검토 | `review` | 각 단계 계획 전 필수 | 2026-07-23 | 위험 담당자, 정량 임계값, 검토 주기 |
| `35-version-plan.md` | v0.1~v1.3 권장 이정표와 승격 조건 정의 | `17`, `32`, `33`, `34` | 실제 릴리스 계획 | `review` | 릴리스 계획 전 필수 | 2026-07-23 | 버전 규칙, 호환성 범위, 일정과 보존 정책 |
| `36-codex-workflow.md` | Codex 작업 전·중·후 절차와 중단·보고 기준 정의 | AGENTS 지침, `31`, `32`, `33` | 개별 Codex 작업 | `review` | Codex 작업 전 필수 | 2026-07-23 | 표준 명령, 자동 보고 범위, 장시간 승인 정책 |

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
3. [확정] 데이터: `06-data-strategy.md` → `23-dataset-registry.md` → `24-data-license-policy.md` → `07-data-preprocessing.md` → `26-data-split-and-leakage-policy.md` → `25-data-quality-checklist.md`
4. [확정] 자원·학습·평가·실험: `16-gpu-memory-strategy.md` → `08-pretraining-plan.md` → `10-evaluation-plan.md` → `27-benchmark-policy.md`·`28-generation-evaluation.md` → `15-experiment-management.md` → `29-reproducibility-policy.md` → `30-experiment-template.md`
5. [확정] SFT·추론: `09-sft-plan.md` → `11-inference-design.md`
6. [확정] 실행 계획과 품질 관리: `17-development-roadmap.md` → `31-definition-of-ready.md` → `33-test-strategy.md` → `18-testing-checklist.md` → `32-definition-of-done.md` → `34-risk-register.md` → `35-version-plan.md` → `36-codex-workflow.md`
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
| 2026-07-23 | [확정] 개발 로드맵·품질 게이트·Ready·Done·테스트·위험·버전·Codex 절차 문서와 ADR-006 상태를 반영함 |
| 2026-07-23 | [확정] 평가·Benchmark·생성·실험 관리·재현성·템플릿 문서와 ADR-005 상태를 반영함 |
| 2026-07-23 | [확정] 데이터 전략·전처리·registry·라이선스·품질·누수 문서와 ADR-004 상태를 반영함 |
| 2026-07-23 | [확정] 시스템 아키텍처, 저장소 구조, 산출물·설정 정책 문서 상태와 선후 관계를 반영함 |
| 2026-07-23 | [확정] 문서 생명주기 상태 체계를 도입하고 2단계 문서 및 ADR 상태를 실제 저장소에 맞게 동기화함 |
