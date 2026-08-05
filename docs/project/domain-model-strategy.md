# DohaLM Domain Model Strategy

- 문서 상태: `review`
- 마지막 검토일: 2026-08-05
- 기준 문서: [README](../../README.md)
- 선행 문서: [Foundation Strategy](./foundation-model-strategy.md), [Roadmap](./model-family-roadmap.md)
- 현재 실행 권한 영향: 없음

## 1. 현재 Domain 우선순위

현재 Application 우선순위는 Phase 3의 **DohaMusic**입니다. 기존 Code, SQL, Recruit, Game과
Vision/Multimodal 제안은 삭제하지 않지만 현행 Roadmap 밖의 장기 후보로 보존합니다.

DohaMusic은 Foundation이나 Runtime 자체가 아니라 Phase 2 Runtime을 사용하는 Application입니다. Application 기능은
Foundation Model을 자동으로 확장하지 않으며, 별도 Foundation derivative가 필요하면 데이터·학습·평가 승인과 lineage가 필요합니다.

## 2. DohaMusic

```text
General Instruct Runtime
  → DohaMusic
      → Music Adapter
      → Lyrics
      → Prompt
```

| 구성 | 목적 | 필수 선행 조건 | 핵심 위험 | 현재 상태 |
|---|---|---|---|---|
| DohaMusic | 음악 질의·탐색 Application shell | Phase 2 Runtime | 모델 한계 오표현, 출처 불명확 | `planned` |
| Music Adapter | 음악 도메인·개인 선호 적응 | DohaMusic, Adapter Loader, 데이터 권리·동의·삭제·격리 | 개인정보, preference leakage, adapter 혼선 | `planned` |
| Lyrics | 가사 검색·분석·근거 제시 | Music Adapter, RAG, 합법적 source, citation 정책 | 저작권, 과도한 가사 노출, 검색 누수 | `planned` |
| Prompt | 음악·가사 작업용 versioned prompt 정책 | Lyrics, Runtime Prompt Engine | 아티스트 모방, prompt injection, 정책 혼선 | `planned` |

### 데이터 경계

- Music Adapter와 Lyrics source의 수집·저장·학습·색인·표시 권한을 각각 확인합니다.
- 검색 근거가 있어도 허용 범위를 넘는 가사 원문을 반환하지 않습니다.
- 개인 청취·선호 데이터는 명시적 동의, 사용자별 격리, 삭제와 export 정책 없이는 사용하지 않습니다.
- Foundation pretraining corpus, General Instruct SFT data와 Personal Adapter data를 별도 lineage로 관리합니다.

### 평가 경계

- Music Adapter: 음악 질의 적합성, 일반 응답 회귀, 사용자 간 누수, 삭제 후 재현 불가 확인
- Lyrics: retrieval recall/precision, citation 정확성, source freshness, 저작권 응답 제한
- Prompt: template 일관성, 근거성, 불확실성, prompt injection과 아티스트 모방 안전성

Domain 점수는 Base/Runtime 회귀와 안전 검증을 대체하지 않습니다.

## 3. Phase 2 Runtime과의 의존성

- Lyrics는 RAG가 선행됩니다.
- 외부 음악 서비스 호출이 필요하면 Tool Calling의 schema·권한·confirmation 계약이 선행됩니다.
- 개인화 Memory는 보존 기간, 삭제와 사용자 격리를 먼저 해결해야 합니다.
- Agent는 DohaMusic의 필수 조건이 아니며 제한된 workflow가 실제로 필요한 경우에만 도입합니다.

## 4. 장기 후보 보존

| 후보 | 기존 목적 | 현재 처리 |
|---|---|---|
| Code | 생성·설명·debug·test | 장기 후보; 현재 실행 순서 밖 |
| SQL | query 생성·수정·교육 | 장기 후보; 실제 DB·PII 계약 필요 |
| Recruit | JD·지원 문서·면접 보조 | 장기 후보; privacy·bias 고위험 |
| Game | NPC·quest·lore·state | 장기 후보; IP·일관성 계약 필요 |
| Vision/Multimodal | image-text 이해 | 현재 범위 밖 |

이 표는 구현 계획이나 학습 승인이 아닙니다. 후보가 활성화될 때 목적, parent, data, evaluation, safety와 publication을
별도 문서와 필요한 ADR로 결정합니다.

## 5. 공통 Release 조건

Domain/Application 공개에는 최소한 다음이 필요합니다.

1. 승인된 Runtime 및 parent Adapter lineage
2. 목적별 데이터 이용조건·PII·누수 검토
3. Domain 평가와 공통 Runtime 회귀
4. 실패·한계·안전 경계 문서화
5. 모델·Adapter·Dataset·Application 각각의 publication 또는 운영 승인

Docker, Kubernetes, Cloud 배포는 이 문서의 범위 밖입니다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | DohaMusic을 Runtime 사용 Application으로 재배치하고 공식 순서를 DohaMusic → Music Adapter → Lyrics → Prompt로 정리 |
| 2026-08-04 | DohaMusic을 3차 우선 Domain으로 지정하고 Lyrics Search·Style Analysis·Personal Music Adapter 경계 작성 |
| 2026-07-28 | Code·SQL·Recruit·Game·Chat·Agent 장기 Domain 초안 작성 |
