# DohaLM 데이터 분할 및 누수 방지 정책

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-23 |
| 선행 문서 | [데이터 전략](./data-strategy.md), [데이터 전처리](./preprocessing.md), [데이터셋 레지스트리](./dataset-registry.md), [ADR-004](../decisions/ADR-004-data-governance.md) |
| 후속 문서 | [사전학습 계획](../training/pretraining-plan.md), [SFT 계획](../training/sft-plan.md), [데이터 품질 체크리스트](./data-quality-checklist.md), [평가 계획](../evaluation/evaluation-plan.md) |
| 구현 전 필수 여부 | 예 |

- [확정] 현재 split 또는 실제 평가 데이터는 없다.
- [확정] 분할은 데이터 비율을 만드는 절차이고 누수 검사는 분할 간 내용·출처·정답 관계를 검증하는 별도 절차다.

## 2. 기본 분할 원칙

- [확정] train, validation, test는 문서 단위로 분리하며 한 문서의 chunk를 여러 split에 배치하지 않는다.
- [확정] 동일 출처·series·thread·원문 파생본은 가능한 한 group key로 묶어 같은 split에 배치한다.
- [확정] exact duplicate는 split 전에 그룹화·제거하고 대표 문서와 제외 mapping을 남긴다.
- [확정] near duplicate는 split 전에 그룹 후보를 만들고 그룹 단위 분할을 우선한다.
- [확정] split 후에도 split 간 exact·near fingerprint를 다시 비교한다.
- [확정] seed, 분할 알고리즘, group key, 입력 manifest와 split version을 기록한다.
- [확정] split 결과는 문서 ID만 포함한 manifest로 저장하고 원본 본체와 분리한다.
- [검증 필요] train/validation/test 비율은 실제 데이터 규모와 평가 계획 전 확정하지 않는다.

## 3. 분할 절차

1. [확정] 승인된 특정 dataset·preprocessing version을 입력으로 고정한다.
2. [확정] 문서 ID, source group, time, exact·near-duplicate group과 목적 label을 준비한다.
3. [확정] 평가 전용·고정 prompt·금지 benchmark 관련 문서를 먼저 격리한다.
4. [확정] exact duplicate group을 대표 문서 기준으로 정리한다.
5. [확정] near duplicate와 동일 원천 파생 그룹이 split을 넘지 않도록 group key를 구성한다.
6. [검증 필요] 무작위·층화·시간 기준 후보 중 데이터 목적에 맞는 방식을 선택한다.
7. [확정] 고정 seed와 versioned 알고리즘으로 문서 그룹을 할당한다.
8. [확정] split 간 fingerprint·source group·금지 항목 교차 검사를 수행한다.
9. [확정] 통계와 예외를 검토한 뒤 split manifest를 승인한다.

## 4. 동일 출처와 중복 처리

| 상황 | 처리 원칙 | 이유 |
|---|---|---|
| byte·정규화 결과가 동일 | exact group에서 대표 1개 또는 승인된 가중치 정책 | 과대표집·직접 누수 방지 |
| 제목·본문 일부만 다른 복제 기사 | near-duplicate group으로 같은 split | 표현 차이로 누수 회피 방지 |
| 하나의 긴 문서에서 나온 chunk | parent document ID로 같은 split | 문맥·문장 교차 누수 방지 |
| 같은 thread·질문에 여러 답변 | conversation/problem group으로 같은 split | 정답 관계 누수 방지 |
| 같은 제공처지만 독립 문서 | 도메인 편향과 시간·series 관계 검토 | 무조건 같은 split이면 대표성 저하 가능 |

- [검증 필요] near-duplicate 알고리즘과 임계치는 실제 표본 precision/recall을 보고 결정한다.

## 5. 누수 수준

| 수준 | 정의 | 예시 위험 | 기본 조치 |
|---|---|---|---|
| 직접 중복 | 정규화 후 동일한 문서·질문·답변 | 지표 암기 | train에서 제외 또는 그룹 재분할 |
| 근사 중복 | 일부 편집·형식·문장 차이만 있는 내용 | 사실상 같은 표본 학습 | 동일 group 처리·수동 검토 |
| 동일 문제의 표현 변경 | 질문 표현은 다르나 해결해야 할 문제가 같음 | 평가 문제 구조 암기 | semantic/problem group 후보로 격리 |
| 답변 포함 문서 | 평가 질문의 정답이 본문에 명시됨 | 정답 직접 학습 | train 제외 또는 평가 적합성 재검토 |
| benchmark 해설 포함 문서 | 문제·정답·풀이를 설명하는 자료 | benchmark 오염 | 금지 목록·fingerprint로 제외 |
| SFT 답변과 평가 정답 중복 | SFT target과 평가 reference가 동일·유사 | SFT 성능 과대평가 | SFT train 제외·평가 set 교체 검토 |

- [확정] 표현만 바뀐 semantic leakage는 hash만으로 완전히 탐지할 수 없으므로 자동 후보와 표본 검토를 구분한다.
- [검증 필요] semantic leakage 자동 탐지 범위와 비용을 평가 계획에서 정한다.

## 6. 목적별 누수 방지

### 6.1 토크나이저 corpus와 평가 데이터

- [확정] tokenizer 학습은 label을 학습하지 않지만 평가 원문 포함은 vocabulary·segmentation에 영향을 줄 수 있으므로 관계를 기록한다.
- [가정] 공개 일반 텍스트의 tokenizer corpus 포함은 모델 train 누수와 동일하게 보지 않되, 고정 prompt·benchmark 원문은 가능한 한 제외한다.
- [검증 필요] 특정 평가 데이터가 tokenizer corpus에 포함됐을 때 평가 공정성 영향은 평가별 정책을 따른다.

### 6.2 사전학습과 평가

- [확정] 고정 prompt, 평가 질문·정답, benchmark 해설과 식별 가능한 파생문을 사전학습 train에서 검사한다.
- [확정] validation/test의 문서와 parent·duplicate group은 train에 들어가지 않는다.

### 6.3 SFT와 평가

- [확정] SFT 질문·답변과 validation/test 질문·정답을 각각 비교한다.
- [확정] 동일 문제의 paraphrase와 답변 포함 문서는 직접 중복과 별도로 후보화한다.
- [확정] SFT 데이터가 바뀌면 SFT split과 고정 평가 오염 검사를 다시 실행한다.

### 6.4 고정 정성 평가 프롬프트

- [확정] 고정 프롬프트는 versioned 목록과 fingerprint로 관리하고 train corpus 생성 시 차단 목록으로 사용한다.
- [확정] 프롬프트 결과를 보고 학습 데이터를 반복 수정하면 테스트 역할을 잃을 수 있으므로 validation용과 최종 정성 test용을 구분한다.

### 6.5 외부 benchmark와 리더보드

- [확정] 공개 benchmark 문제·정답·해설의 포함 여부를 가능한 범위에서 검사하고 검사 범위와 한계를 보고한다.
- [제외] 리더보드 비공개 평가 데이터를 복원·추정하거나 요청·출력 패턴으로 문제를 추출하려는 시도를 금지한다.
- [확정] 당시 공식 규정이 별도 오염 기준을 제공하면 적용 시점에 다시 검토한다.

## 7. 시간 기준 분할

- [가정] 시계열 데이터에서 미래 일반화가 목적이면 timestamp를 기준으로 과거 train, 이후 validation/test를 구성하는 방식을 검토한다.
- [확정] timestamp의 의미가 게시·수정·취득 중 무엇인지 기록한다.
- [검증 필요] 날짜 누락·변조·복제 기사와 출처 분포 변화가 있는지 확인한다.
- [검증 필요] 현재 실제 후보가 없으므로 시간 기준 분할 채택 여부를 확정하지 않는다.

## 8. Split manifest 최소 항목

- [확정] split version, 생성 시각, 입력 dataset·preprocessing version
- [확정] 알고리즘·seed·group key·층화 기준
- [확정] 문서 ID, parent ID, source group, duplicate group, 할당 split
- [확정] split별 문서·문자·token 추정 통계와 제외 수
- [확정] exact·near·금지 목록 교차 검사 결과
- [확정] 코드 revision, 설정 snapshot과 checksum
- [확정] 예외와 승인자

## 9. 데이터 변경과 split 재생성

다음 변경은 새 split version 또는 명시적 호환성 검토를 요구한다.

- [확정] 문서 추가·삭제·수정 또는 삭제 요청 반영
- [확정] normalization·filter·dedup 방식 변경
- [확정] group key·seed·비율·층화·시간 기준 변경
- [확정] 평가 set·고정 prompt·benchmark 차단 목록 변경
- [확정] SFT template으로 논리 sample 경계가 달라짐
- [검증 필요] tokenizer만 변경된 경우 text split은 유지할 수 있으나 token 통계와 tokenized artifact는 재생성해야 한다.

- [확정] 기존 split manifest를 덮어쓰지 않고 새 version과 변경 사유를 연결한다.

## 10. 미결정 사항

- [검증 필요] split 비율, seed와 층화 기준
- [검증 필요] near duplicate 및 semantic leakage 알고리즘·임계치
- [검증 필요] 시간 기준 분할 적용 여부
- [검증 필요] 고정 prompt와 외부 benchmark 차단 목록 관리 위치
- [검증 필요] 최종 test 접근 권한과 사용 횟수 기록 방식
- [검증 필요] split manifest의 실제 schema와 저장 위치

## 11. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] 문서·그룹 단위 분할, 누수 수준, 목적별 오염 방지와 split 재생성 기준 정의 |
