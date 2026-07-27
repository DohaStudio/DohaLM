# DohaLM Definition of Ready

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-23 |
| 선행 문서 | [개발 규칙](./development-rules.md), [개발 로드맵](../quality/development-roadmap.md), [ADR-006](../decisions/ADR-006-development-quality-gates.md) |
| 후속 문서 | [Definition of Done](./definition-of-done.md), [테스트 전략](../quality/test-strategy.md), [Codex 작업 절차](./codex-workflow.md) |
| 구현 전 필수 여부 | 모든 작업 시작 전 예 |

- [확정] Ready는 작업을 시작해도 되는지 판단하는 조건이며 결과 완료를 뜻하지 않는다.
- [확정] 필수 조건이 충족되지 않으면 임의 가정으로 구현하지 않고 확인 결과와 차단 사유를 보고한다.

## 2. 공통 Ready 조건

| ID | 조건 | 확인 증거 | 미충족 시 조치 |
|---|---|---|---|
| R-COM-01 | 작업 목적이 명확함 | 요청·issue·문서의 한 문장 목표 | 목표 확인 요청 |
| R-COM-02 | 포함 범위가 명확함 | 기능·파일·행위 목록 | 범위 구분 후 중단 |
| R-COM-03 | 제외 범위가 명확함 | 금지 행위·비목표 | 위험한 확장 금지 |
| R-COM-04 | 수정 대상 파일이 정해짐 | 실제 경로와 존재 여부 | 저장소 구조 확인·보고 |
| R-COM-05 | 관련 설계 문서를 읽음 | 읽은 파일 목록 | 문서 확인 후 진행 |
| R-COM-06 | 관련 ADR을 읽음 | 적용·대체 ADR 목록 | 결정 충돌 검토 |
| R-COM-07 | 선행 작업이 완료됨 | Gate·test·artifact 증거 | 선행 단계로 복귀 |
| R-COM-08 | 입력과 출력이 정의됨 | schema·shape·path·상태 | 계약 정의 요청 |
| R-COM-09 | 완료 기준이 정의됨 | [Definition of Done](./definition-of-done.md) 항목 | Done 기준 작성 |
| R-COM-10 | 테스트 방법이 정의됨 | test 수준·명령·예상 결과 | 테스트 계획 작성 |
| R-COM-11 | 작업 트리가 clean | `git status` 확인 | 예상하지 못한 변경 파일만 보고 |
| R-COM-12 | 적절한 branch에 있음 | branch 확인, `main` 직접 개발 금지 | 안전한 branch 지시 요청 |

## 3. 문서 작업 Ready

- [확정] 작성·수정할 문서 경로와 문서별 필수 목차가 명시돼 있다.
- [확정] 읽을 기준 문서·ADR과 용어의 단일 기준이 식별돼 있다.
- [확정] 변경 가능한 문서 상태와 `planned/review/approved/implemented` 경계가 명확하다.
- [확정] 문서·ADR 인덱스 및 상대 링크 갱신 범위가 정해져 있다.
- [확정] 수정 금지 문서와 예정 문서 생성 금지가 명시돼 있다.
- [확정] 구현되지 않은 기능을 완료로 표현하지 않는 검토 방법이 있다.

## 4. 코드 작업 Ready

- [확정] 관련 모델·데이터·학습 사양과 ADR이 승인 또는 명시적 검토 상태다.
- [확정] 설정의 단일 위치·객체와 override 정책이 정해져 있다.
- [확정] 새·수정 test의 위치, fixture와 예상 실패 조건이 정해져 있다.
- [확정] `RTX 3060 Ti 8GB`, 단일 GPU, Tiny 우선 제약을 확인했다.
- [확정] 외부 의존성의 필요성·라이선스·호환성과 대체 가능성을 검토했다.
- [확정] 현재 구현을 검색하고 중복 구조를 만들지 않을 근거가 있다.
- [확정] 적용 경로의 하위 `AGENTS.md`를 확인했다.

## 5. 학습 작업 Ready

| 조건 | 필수 증거 |
|---|---|
| 데이터 `approved` | dataset registry·라이선스 검토·목적별 승인 |
| 라이선스 검토 완료 | 공식 조건·취득일·사용/수정/공개 범위 |
| split 고정 | split version·seed·fingerprint·누수 검사 |
| tokenizer 고정 | tokenizer ID·hash·16,000 vocab·special ID 검사 |
| model config 고정 | resolved config·ADR-002 호환·parameter count 검사 |
| smoke test 통과 | forward/backward·AMP·checkpoint·resume |
| checkpoint 경로 확인 | 쓰기 가능성·atomic save·보존 정책 |
| 저장공간 확인 | 데이터·로그·checkpoint 예상과 여유 실측 |
| 중단 조건 확인 | OOM·NaN/Inf·loss·시간·데이터·복원 기준 |
| 실험 준비 | experiment ID·metadata·평가·고정 validation |

- [확정] 장시간 학습은 Gate 8 또는 Gate 9의 사용자 명시 승인 없이 시작하지 않는다.

### Candidate B 추가 Ready

- [확정] 승인된 [ADR-007](../decisions/ADR-007-evaluation-baseline-and-candidate-comparison.md), Candidate A Final Full baseline과 [Candidate B 평가 계약](../evaluation/candidate-b-evaluation-contract.md)을 고정한다.
- [확정] Candidate B design·training은 평가 계약 승인과 별개의 사용자 승인이 필요하다.
- [확정] Quick v2는 `planned_awaiting_separate_approval`이며 승인 전 입력으로 사용하지 않는다.

## 6. Ready 미충족 보고

다음 형식으로 안전하게 가능한 확인 결과만 보고한다.

1. 미충족 Ready ID·조건
2. 확인한 branch·Git 상태·관련 파일
3. 누락·충돌·권한·라이선스 등 차단 원인
4. 수행하지 않은 변경·실행
5. 진행에 필요한 사용자 결정 또는 선행 작업
6. 범위 안에서 완료한 비변경 검토 결과

- [확정] 작업 트리에 예상하지 못한 변경이 있으면 파일을 덮어쓰거나 정리하지 않는다.
- [확정] 사양 충돌·라이선스 불명확·비밀정보 발견 시 해당 범위의 변경을 중단한다.
- [확정] Ready 미충족을 `blocked`와 자동으로 동일시하지 않고 확인 가능한 선행 작업이 있으면 먼저 수행한다.

## 7. 미결정 사항

- [검증 필요] Ready 검토 기록 schema와 승인자
- [검증 필요] 작업 유형별 자동 점검 항목
- [검증 필요] dirty worktree를 허용할 수 있는 명시적 예외 절차

## 8. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | Candidate B 평가 계약 승인과 design·training·Quick v2 별도 승인 Ready 경계 추가 |
| 2026-07-23 | [확정] 공통·문서·코드·학습 작업의 시작 조건과 미충족 보고 방식 정의 |
