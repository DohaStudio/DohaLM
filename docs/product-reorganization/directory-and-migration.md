# Directory Proposal, Reuse and Migration Plan

- 문서 상태: `draft`
- 마지막 검토일: 2026-08-11
- 실행 상태: `proposal_only`; 실제 이동·rename 없음

## 1. 현재 구조와 목표 구조

| 현재 | 목표 | 조치 |
|---|---|---|
| `src/model` | `src/model` | 유지; Foundation 계보 보존 |
| `src/training` | `src/training` + `src/learning/training` | 공통 trainer 유지, orchestration 분리 |
| `src/data` | `src/data` + `src/learning/candidates` + `src/learning/datasets` | 검증 재사용, candidate/lifecycle 추가 |
| `src/evaluation` | `src/evaluation` + `src/music/evaluation` | 공통 metric 유지, 음악 metric 추가 |
| `src/inference` | `src/inference` + `src/director/runtime` | provider 유지, capability router 추가 |
| `server/api/v1/chat.py` | `server/api/v1/chat.py` + `server/api/v1/director/*` | 호환 유지 후 typed API 추가 |
| `configs/training` | `configs/training` + `configs/tasks` + `configs/learning` | 기존 실행 identity 보존 |
| 분산 manifest | `schemas/*` + artifact registry | 단계별 점진 통합 |
| 외부 dataset/model roots | `assets.yaml`의 logical roots | 실제 자산 이동 없이 binding 정리 |

목표 proposal:

```text
src/
  director/
    capabilities/
    planning/
    prompting/
    editing/
    qa/
    runtime/
  music/
    features/
    reference/
    similarity/
    evaluation/
  learning/
    candidates/
    review/
    datasets/
    training/
    promotion/
  inference/        # existing provider layer
  model/            # existing Foundation model
  data/             # existing generic data governance
schemas/
  capabilities/
  learning/
  features/
  similarity/
configs/
  tasks/
  learning/
  providers/
```

## 2. Reuse Plan

| 분류 | 대상 | 이유 |
|---|---|---|
| 유지 | manifest/checksum/lineage, config loader, runtime path/logging | 도메인 독립 계약 |
| 유지 | FastAPI lifecycle, REST/SSE transport, provider cancellation/timeout | typed payload로 확장 가능 |
| 유지 | Tiny Foundation, checkpoint/resume, historical evaluation | 연구 계보·회귀 기준 보존 |
| 리팩터링 | ProviderRegistry | single active provider에서 capability별 approved artifact 선택으로 확장 |
| 리팩터링 | Adapter manifest | capability, task schema, dataset/evaluation identity 추가 |
| 리팩터링 | Prompt 처리 | Qwen chat template 결합을 versioned Prompt Engine으로 분리 |
| 리팩터링 | Dataset registry | source dataset 중심에서 task/version/candidate lineage 추가 |
| 신규 | Learning Candidate·review·promotion | 현재 개념 없음 |
| 신규 | Reference Feature Record·Similarity Risk Report | 현재 구현 없음 |
| 사용 중단 후보 | local chat frontend의 제품 UI 해석 | 검증 UI로만 유지하거나 DohaMusic으로 책임 이동 |
| 삭제 금지 | failed run, historical docs/configs, Candidate A/B evidence | 재현·감사 계보 |

## 3. Migration Plan — PR 단위

| PR | 범위 | 포함 | 금지 |
|---|---|---|---|
| PR-01 | 조사·설계 | 본 문서와 Draft ADR | 코드·자산 이동·runtime 변경 |
| PR-02 | Core contracts | capability, candidate, dataset version, feature, risk schemas·validator | 학습·Provider 교체 |
| PR-03 | Registry | logical asset bindings, artifact/candidate indexes, migration reader | 실물 자산 이동·DB 도입 |
| PR-04 | Learning intake | candidate writer, review evidence, consent/rights gates | 자동 승인·학습 |
| PR-05 | Reference context | DohaAudio/DohaVocal Feature Record adapter | 원본 audio 저장·학습 |
| PR-06 | Similarity | metric interface, catalog policy, risk report | 법률 판정·미보정 production threshold |
| PR-07 | Director runtime | capability router, Prompt Engine, typed API/SSE | 미승인 Adapter production 승격 |
| PR-08 | Dataset builder | task별 frozen dataset·leakage tests | 실제 음악 data 승인 없는 build |
| PR-09 | Training/evaluation | QLoRA run contract, music capability evaluation | 장시간 학습 자동 시작 |
| PR-10 | Promotion/integration | approved artifact promotion, rollback, DohaMusic SDK contract | cloud deployment |
| PR-11 | Physical cleanup | import/config compatibility 후 directory rename·deprecated shim 제거 | 계보 artifact 삭제 |

순서는 Directory → Config → Runtime → Prompt → Dataset → Model/Adapter/Checkpoint의 물리 이동이 아니라, **계약 → logical binding → compatibility → 소비자 전환 → 마지막 물리 정리** 순서다.

## 4. 문서 충돌 조사

| 문서군 | 현재 주장 | 목표와 충돌 | 처리 |
|---|---|---|---|
| Root README, Project Overview | reusable LLM model provider | AI Music Director 정의와 직접 충돌 | ADR-012 승인 후 별도 PR에서 갱신 |
| Domain Model Strategy | DohaMusic은 외부 reference application, 음악 특화 내부 단계 금지 | 목표의 음악 지능 계층과 충돌 | 저장소 책임 경계 재승인 필요 |
| Roadmap | Phase 1 Foundation 우선 | 음악 capability 우선순위와 충돌 가능 | 기존 계보 보존 + 새 product track 병행 제안 |
| ADR-001·010 | Tiny/Instruct scope와 parent 고정 | 제품 목적 변경이 자동 대체하지 않음 | ADR-012은 비소급, 후속 ADR 필요 |
| Validation/Evaluation | 한국어 Foundation·General QA/EOS 중심 | 음악 planning/edit/QA 측정 불가 | metric suite 신규 설계 |
| Architecture | model→runtime→external app | feature/context/learning feedback loop 없음 | 목표 architecture 추가 |
| MASTER_ROADMAP | 파일 없음 | 요청 명칭과 저장소 불일치 | `model-family-roadmap.md`, `development-roadmap.md`가 실제 기준 |

## 5. Migration Gate

각 PR은 기존 import/API/config identity 회귀 테스트, 새 schema negative tests, Markdown link·status 정합성을 통과해야 한다. 실제 data/model/checkpoint 이동은 checksum 전후 동일성, 원자적 publish, rollback과 여유 공간을 별도 승인한 뒤에만 수행한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-11 | 현행/목표 디렉터리 비교, 재사용 판정과 PR 단위 마이그레이션 계획 작성 |
