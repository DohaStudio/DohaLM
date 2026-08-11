# ADR-012: DohaLM AI Music Director 제품 방향

- 상태: `draft`
- 결정일: 미결정
- 마지막 검토일: 2026-08-11
- 관련 문서: [제품 재편 조사](../product-reorganization/README.md), [목표 아키텍처](../product-reorganization/target-architecture.md)

## 배경

현재 승인·검토 문서는 DohaLM을 범용 reusable LLM model provider로 정의하고 DohaMusic을 외부 Reference Application으로 둔다. 새 제품 방향은 DohaLM을 음악 제작의 계획·편집 의도·prompt·QA·분석 해석을 담당하는 AI Music Director 지능 계층으로 재정의한다. 이는 저장소 범위, 데이터 목적, 평가, Runtime과 외부 프로젝트 책임에 영향을 주므로 문서 추가만으로 승인할 수 없다.

## 제안 결정

1. DohaLM의 목표 제품을 `ai_music_director_intelligence_provider`로 정의한다.
2. DohaLM은 Lyrics Generation을 포함하되 Song Planning, Genre/Structure Recommendation, Music/Provider Prompt, Track/Section Edit Intent, Composition Operation, Mix Direction, Music QA, Reference/Similarity Interpretation까지 확장한다.
3. DohaMusic은 UI·project state·workflow·사용자 승인을, DohaAudio/DohaVocal은 분석·실행을 소유한다.
4. 원본 reference audio는 직접 학습하지 않는다. 승인된 분석 결과와 사용자 결과·수정·선호만 Learning Candidate가 될 수 있다.
5. 기존 Foundation·Qwen·Adapter·평가 계보는 폐기하지 않고 새로운 product track의 기반/실험 자산으로 보존한다.
6. Dataset과 Model 승격은 review·evaluation·명시 승인 gate를 거치며 Runtime 자동 승격을 금지한다.

## 비결정 사항

- [검증 필요] Foundation 연구 우선순위와 Music Director product track의 예산·일정.
- [검증 필요] 음악 feature schema, similarity metric/threshold, 법무·저작권 검토.
- [검증 필요] DohaMusic/DohaAudio/DohaVocal API version과 배포 topology.
- [검증 필요] 사용자 데이터 consent, retention, deletion과 opt-out 정책.

## 영향

### 장점

- 제품 capability와 기존 범용 인프라의 목적이 명확해진다.
- 사용자 수정과 평가를 통제된 학습 흐름으로 연결할 수 있다.
- 원본 reference와 학습 데이터의 경계를 분리한다.

### 비용·위험

- 기존 README·Roadmap·Domain Strategy와 후속 ADR을 갱신해야 한다.
- 음악용 Dataset·평가·Provider prompt 계약이 전무하여 구현 범위가 크다.
- feature와 similarity 설계가 저작권·privacy·재식별 위험을 만든다.

## 승인 전 경계

이 ADR이 `approved`가 되기 전에는 기존 Project Definition을 변경하거나 코드·디렉터리·데이터·model/Adapter를 이동하지 않는다. 이번 문서의 목표 구조는 검토 제안이다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-11 | 제품 방향 변경을 승인 가능한 결정 단위로 분리한 초안 작성 |
