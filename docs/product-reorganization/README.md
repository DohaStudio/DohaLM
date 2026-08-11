# DohaLM Product Reorganization 조사 보고서

- 문서 상태: `review`
- 마지막 검토일: 2026-08-11
- 조사 기준: `develop`의 `1b88864`
- 변경 범위: 조사·구조 설계·마이그레이션 계획만 포함

## 1. 결론

- [확정] 현재 DohaLM은 직접 구현 Foundation 연구, Qwen 기반 QLoRA 이력, Provider Runtime, REST/SSE를 한 저장소에 보유한 **재사용 LLM 모델 제공자**다.
- [제안] 목표 제품은 음악 제작 전 과정을 계획·지시·검토하는 **AI Music Director**다. 제품 방향 변경은 [ADR-012](../decisions/ADR-012-dohalm-ai-music-director-product-direction.md) 승인 전까지 제안이다.
- [확정] 이번 변경은 코드, 설정, 데이터, 모델, Adapter, checkpoint와 로컬 자산을 이동·수정하지 않는다.
- [확정] 원본 reference audio를 직접 학습하지 않는다. 분석 feature와 사용자가 만든 결과·수정·선호만 승인 흐름을 거쳐 학습 후보가 된다.

## 2. 문서 지도

| 문서 | 내용 |
|---|---|
| [Inventory](./inventory.md) | Repository, 로컬 자산, Dataset, Model, Checkpoint, Prompt, DB·metadata 조사 |
| [Current Architecture](./current-architecture.md) | 학습·추론·REST·Streaming·Provider의 현재 연결 |
| [Target Architecture](./target-architecture.md) | AI Music Director 정의, capability matrix, DohaMusic·DohaAudio·DohaVocal 관계 |
| [Continuous Learning](./continuous-learning.md) | Learning Candidate, 검토·승인, Dataset·Model lifecycle |
| [Reference and Similarity](./reference-and-similarity.md) | Reference 분석, feature record, similarity·risk·revision 구조 |
| [Directory and Migration](./directory-and-migration.md) | 현행/목표 디렉터리, 재사용 판정, PR 단위 이행 계획 |

## 3. 현재와 목표 요약

| 축 | 현재 | 목표 | 이번 PR |
|---|---|---|---|
| 제품 | reusable LLM model provider | AI Music Director intelligence provider | 제안 문서화 |
| 데이터 | AIHUB 중심 Foundation·General SFT | task별 음악 제작 candidate dataset | schema·lifecycle 설계 |
| 모델 | Tiny Foundation + Qwen QLoRA 별도 계보 | capability별 approved adapter/model | lifecycle 설계 |
| Runtime | mock/base-qwen/dohalm-adapter 단일 active provider | capability router + approved artifact registry | 인터페이스 방향만 정의 |
| API | chat, models, health, REST/SSE | planning·editing·QA·analysis interpretation | 변경 없음 |
| Reference | 외부 DohaMusic reference application | DohaMusic이 orchestration, DohaLM이 지능 계약 | 책임 경계 제안 |
| 학습 | 수동 run·manifest·평가 gate | candidate→review→dataset→training→evaluation→runtime | 공식 흐름 설계 |

## 4. 종합 Blocker와 Warning

### BLOCKER

1. [확정] README·Project Definition·ADR-001·ADR-010은 현재 범용 reusable provider 및 기존 모델 계보를 기준으로 한다. ADR-012 승인 없이 기준 정의를 교체할 수 없다.
2. [확정] 음악 task용 승인 Dataset, evaluation suite, eligible Adapter가 없다.
3. [확정] Python SDK와 versioned release가 없으므로 DohaMusic과 안정적인 공개 통합 계약이 없다.
4. [확정] GitHub CLI 인증 토큰은 조사 시점에 유효하지 않아 push·Draft PR 생성에 재인증이 필요하다.

### WARNING

1. 로컬 데이터 루트에는 제한 라이선스·비공개 자산이 있으므로 실제 경로·원문·생성 원문을 Git에 기록하지 않는다.
2. 기존 `data/`, `checkpoints/`, `artifacts/` 이름과 외부 자산 루트가 중복되어 저장 위치를 오해하기 쉽다.
3. smoke Adapter checkpoint의 존재는 승인 Adapter 또는 Runtime 사용 가능성을 의미하지 않는다.
4. 음악 유사도는 저작권 침해의 법적 판정기가 아니라 재검토 우선순위를 주는 위험 신호여야 한다.

## 5. 권장 다음 PR

`PR-02: AI Music Director contracts and registries`를 권장한다. ADR-012 승인 후 capability request/response, Learning Candidate manifest, Dataset Version manifest, Feature Record와 Similarity Risk Report의 schema만 구현하고 학습·자산 이동·Provider 교체는 계속 제외한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-11 | develop 기준 제품 재편·지속 학습 아키텍처 조사 보고서 최초 작성 |
