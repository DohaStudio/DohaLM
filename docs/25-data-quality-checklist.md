# DohaLM 데이터 품질 체크리스트

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-23 |
| 선행 문서 | [데이터 전략](./06-data-strategy.md), [데이터 전처리](./07-data-preprocessing.md), [데이터 라이선스 정책](./24-data-license-policy.md), [데이터 분할 및 누수 방지](./26-data-split-and-leakage-policy.md) |
| 후속 문서 | [사전학습 계획](./08-pretraining-plan.md), [SFT 계획](./09-sft-plan.md), `10-evaluation-plan.md` 작성 예정 |
| 구현 전 필수 여부 | 예 |

- [확정] 현재 실제 데이터 검사 결과는 없다. 이 문서는 검사 양식이다.
- [확정] 정확한 수치 임계치는 실제 분포와 표본 검토 전 확정하지 않는다.

## 2. 결과 상태

| 상태 | 의미 |
|---|---|
| `pass` | 승인된 기준을 충족하고 증거가 기록됨 |
| `warning` | 사용 가능성은 있으나 위험·편향·추가 검토가 필요함 |
| `fail` | 필수 기준 미달로 다음 단계 또는 해당 목적 사용 불가 |
| `not_checked` | 아직 검사하지 않음; 필수 항목이면 승인 불가 |
| `not_applicable` | 해당 데이터 유형에 적용되지 않으며 사유가 기록됨 |

- [확정] 자동 검사가 완료돼도 승인 기준이 미정이면 자동으로 `pass` 처리하지 않는다.
- [확정] `warning` 수용에는 책임자, 근거와 사용 제한을 기록한다.

## 3. 체크리스트

| 범주 | 점검 목적 | 점검 방법 | 통과 기준 상태 | 실패 시 조치 | 기록 위치 |
|---|---|---|---|---|---|
| 파일 무결성 | 원본 손상·누락 방지 | registry checksum, 파일 수·크기·parse 결과 비교 | 승인 checksum과 일치하면 `pass` | 취득 중단·원본 재확인 | dataset registry·raw manifest |
| 인코딩 | decode 손상 방지 | encoding별 decode 오류·대체 문자 통계와 표본 | 승인된 오류 정책 충족 시 `pass` | 격리·decoder 규칙 재검토 | preprocessing report |
| Unicode | 의미 손실·비정상 code point 확인 | 문자군·정규화 전후 diff·제어문자 검사 | 승인 rule과 회귀 표본 충족 | normalization 변경·문서 제외 | normalization report |
| 한국어 비율 | 목적에 맞는 언어 구성 확인 | 문자·문서·출처 단위 비율 분포 | 목적별 임계치 승인 후 `pass` | 필터·층화·후보 재검토 | language statistics |
| 문서 길이 | 빈 문서·조각·과대 문서 탐지 | 문자·문장·token 길이 분포 | 경계와 분포 검토 완료 | 제외·chunk 정책 적용 | length report |
| 문법적 품질 | 손상·비문·기계 번역 흔적 점검 | 층화 표본 수동 검토와 설명 가능한 feature | 표본 기준 승인 후 `pass` | 출처 제한·점수 조정·제외 | quality review |
| 반복 문자열 | 문자·문장 반복과 생성 오류 탐지 | 반복 run·n-gram·문단 패턴 검사 | 정상 강조와 이상 반복 구분 | 축약 후보 검토·제외 | repetition report |
| 광고·스팸 | 홍보·키워드 나열 오염 축소 | rule hit·분류 score·표본 precision 검토 | 승인 오탐·누락 범위 충족 | rule 조정·문서 제외 | spam report |
| exact duplicate | 동일 문서 과대표집 방지 | canonical fingerprint 그룹 비교 | split 전 중복 그룹 처리 완료 | 대표 선정·계보 기록 | dedup manifest |
| near duplicate | 유사 문서·복제 기사 누수 방지 | 후보 알고리즘·유사도 그룹·표본 검토 | 승인 방식과 임계치 충족 | 그룹 단위 처리·재분할 | near-dedup manifest |
| 개인정보 | 개인 식별·재식별 위험 축소 | 탐지 rule·모델 후보와 제한된 수동 검토 | 고위험 미검토 항목 없음 | 격리·삭제·비식별·후보 제외 | restricted risk report |
| 민감정보 | 건강·금융·인증·계정 정보 보호 | 유형별 탐지와 맥락 검토 | 목적상 허용 정책 충족 | 격리·제외·추가 검토 | restricted risk report |
| 유해 콘텐츠 | 안전·법적·품질 위험 파악 | 범주별 flag와 층화 표본 검토 | 목적별 허용 범위 승인 | 제외·가중치 제한·경고 기록 | harmful-content report |
| 저작권 위험 | 사용·수정·공개 조건 위반 방지 | 공식 조건과 출처·version 대조 | 라이선스 검토 완료 시 `pass` | `rejected` 또는 `[법률 검토 필요]` | registry·license record |
| 평가 데이터 오염 | 과대평가 방지 | benchmark·고정 prompt fingerprint와 유사도 비교 | 금지 overlap 처리 완료 | train 제외·split 재생성 | leakage report |
| 토큰화 효율 | context 낭비·unknown 문제 파악 | 문자당 token, unknown, 길이·vocab 사용 분포 | corpus 기반 기준 승인 후 `pass` | tokenizer 옵션·corpus 재검토 | tokenizer evaluation |
| 특수문자 비율 | markup·깨진 text·희귀 문자 과다 탐지 | Unicode category·문서별 비율 | 도메인별 기준 검토 완료 | 정제·분리·제외 | character report |
| 코드·표·수식 처리 | 구조 손상과 도메인 편향 파악 | 형식 탐지·전후 표본·token 길이 비교 | 보존/변환 정책과 일치 | parser·정책 수정 | structure report |
| train/validation/test 분리 | 평가 독립성 보장 | document/source group·fingerprint 교차 비교 | 직접·근사 누수 검사 통과 | 그룹 재할당·split 재생성 | split manifest·leakage report |
| 통계 재현성 | 동일 입력에서 같은 판단 재생성 | 설정·seed·version 고정 후 통계 재실행 | 허용 차이 정책 충족 | 원인 분석·version 고정 | run manifest·statistics |

## 4. 검사 실행 기록 양식

| 필드 | 설명 |
|---|---|
| dataset ID·source version | 검사 대상 |
| preprocessing·split version | 변환·분할 기준 |
| check ID·check version | 검사 종류와 구현 version |
| executed at·owner | 실행 시각과 책임자 |
| config·seed·code revision | 재현 정보 |
| 대상·통과·경고·실패 수 | 집계 |
| result status | 정의된 상태 중 하나 |
| evidence location | 통계·표본·manifest 위치 |
| accepted exception | 경고 수용 근거와 제한 |
| follow-up | 재처리·재검토 작업 |

## 5. 목적별 필수 점검

- [확정] 토크나이저 corpus: 라이선스, 개인정보, Unicode, 문자군, 중복, 토큰화 효율 검사가 필요하다.
- [확정] 사전학습: 위 항목에 spam, 유해성, 문서 경계, split·평가 오염 검사를 추가한다.
- [확정] SFT: role 구조, 질문·답변 중복, 개인정보, 정답 누수와 truncation 결과를 추가 점검한다.
- [확정] validation/test: train과의 exact·near·semantic leakage 검사와 접근·사용 기록이 필요하다.

## 6. 미결정 사항

- [검증 필요] 모든 정량 임계치와 표본 수
- [검증 필요] 개인정보·유해성 자동 탐지 도구와 사람 검토 범위
- [검증 필요] 품질 점수 가중치와 `warning` 승인 책임자
- [검증 필요] near-duplicate 및 semantic leakage 검사 방식
- [검증 필요] 품질 보고서와 제한 정보의 실제 저장 위치

## 7. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] 20개 품질 범주, 결과 상태, 조치와 기록 기준 정의 |
