# Candidate C EOS Root Cause Hypothesis 계약

- 문서 상태: `review`
- 마지막 검토일: 2026-08-05
- 계약 설계: `completed`
- 가설 승인: `not_approved`
- 진단 실행: `not_started`
- 대상 artifact: Candidate B Final checkpoint, read-only

## 1. 목적과 확정 사실

이 계약은 Candidate C 변경 축을 선택하기 전에 Candidate B의 EOS 현상을 반증 가능한 가설로 분리합니다. 실제 진단,
코드·데이터·설정 변경, GPU 실행과 학습을 포함하지 않습니다.

[확정] Candidate A/B는 pure greedy 16/32/64/128-token에서 EOS 0%, maximum-length 100%였습니다. Candidate B는
teacher-forced EOS가 개선됐고 EOS target·loss 포함과 packing boundary가 정상입니다. Assisted decoding에서만 일부
종료가 관찰됐으며 32-token 이상 pure greedy loop는 A/B 모두 100%였습니다.

## 2. 가설 목록

`Candidate C 반영`은 승인 전 제안이며 사실이나 실행 결정을 뜻하지 않습니다.

| ID | 가설 | 근거 | 반증 가능 조건 | 필요한 진단 | 코드 변경 | 데이터 변경 | 학습 변경 | Candidate C 반영 | 위험 | 승인 상태 |
|---|---|---|---|---|---|---|---|---|---|---|
| H1 | EOS logit calibration 부족 | B의 teacher-forced rank는 개선됐지만 greedy 선택은 0% | EOS rank·확률이 종료 직전에도 충분히 높고 경쟁 token과 격차가 작지 않음 | step별 EOS logit·rank·확률·top competitor trajectory | 진단 계측 필요 가능 | 없음 | 미정 | 우선 진단 후보 | 확률만 보고 원인으로 오판 | `reviewing` |
| H2 | Autoregressive exposure mismatch | teacher-forced 개선이 free generation으로 전이되지 않음 | teacher-forced prefix와 generated prefix의 EOS gap이 일관되지 않음 | 동일 문맥의 teacher-forced/autoregressive logit 비교 | 진단 계측 필요 가능 | 없음 | 미정 | 우선 진단 후보 | prefix identity 불일치 | `reviewing` |
| H3 | Sequence boundary frequency 부족 | EOS target은 존재하지만 boundary 노출 빈도 효과는 미측정 | boundary proximity와 EOS rank·loss 사이 관계가 없음 | boundary 거리별 target 수·loss·rank·generation | 진단 계측 필요 가능 | 진단은 없음; 반영 시 revision | sampling 변경 가능 | 결과 후 판단 | reweighting이 비교 identity 변경 | `reviewing` |
| H4 | Packing objective 영향 | packing boundary는 보존되지만 packed context가 선택 경쟁에 미치는 영향은 미확인 | packed/rebased·boundary 조건의 EOS 차이가 없음 | packed/rebased, 직전 boundary 거리별 EOS 비교 | 진단 계측 필요 가능 | 진단은 없음; 반영 시 revision | sequence construction 변경 가능 | 결과 후 판단 | sequence construction 변경은 Dataset revision | `reviewing` |
| H5 | Decoding parameter 영향 | sampling·no-repeat bigram에서 일부 종료 | 보조 profile에서도 EOS가 재현되지 않거나 종료가 forced heuristic에만 의존 | greedy·temperature·top-p·no-repeat 분리 비교 | 기존 진단 재사용 가능 | 없음 | 없음 | 진단 전용, 학습 변경 근거 아님 | assisted 성공을 pure 성공으로 오인 | `reviewing` |
| H6 | Training budget 부족 | A 10M보다 B 25M의 teacher-forced 지표·반복은 개선 | checkpoint trajectory가 plateau 또는 악화하고 budget과 EOS 개선 관계가 없음 | A-equivalent·late·final EOS trajectory | 기존 평가 재사용 가능 | 없음 | budget 변경 가능 | 후순위 후보 | 추가 token이 원인 분리를 못 할 수 있음 | `reviewing` |
| H7 | Repetition loop 경쟁 | loop 시작 뒤 EOS rank·확률이 악화되고 no-repeat에서 B 종료 관찰 | loop 전후 EOS 경쟁 token·확률이 유의미하게 달라지지 않음 | loop token 빈도, n-gram, EOS competitor와 onset 비교 | 진단 계측 필요 가능 | 없음 | regularization/loss 변경 가능 | 우선 진단 후보 | repetition 억제가 일반 품질 저하 가능 | `reviewing` |

어느 가설도 현재 root cause로 확정하지 않습니다. Candidate C에는 승인된 하나의 주가설과 명시적 control만 반영하며,
복수 가설을 동시에 바꾸려면 별도 factorial 설계와 승인이 필요합니다.

## 3. Candidate B 진단 계획

모든 입력은 Candidate B Final checksum `sha256:f3edc978db9d88e9de8e2e423a28291e9f35e2e163f0413c0e27e95facc55395`와
승인된 Tokenizer·prompt/config identity를 사용합니다. 원문과 전체 token ID는 저장하지 않습니다.

| 진단 | 입력 | 산출물 | 통과·판정 기준 | Candidate C config 영향 |
|---|---|---|---|---|
| EOS logit rank trajectory | 고정 prompt, greedy 16/32/64/128 | step별 aggregate rank quantile·fingerprint | finite·재현 가능·length/category 분리; 수치 threshold 없음 | H1 채택 여부 |
| EOS probability trajectory | 동일 generation prefix | step별 EOS probability와 competitor gap 집계 | loop 전후·종료 유도 전후 비교 가능 | loss weighting/calibration 검토 여부 |
| Greedy vs temperature/top-p | 승인된 기존 profile | profile별 EOS/max-length/loop·seed | pure와 assisted를 분리하고 forced EOS 제외 | decoding은 진단값으로만 유지 |
| Repetition loop token frequency | greedy token fingerprint·n-gram aggregate | onset·빈도·dominant competitor 통계 | 32/64/128과 category별 loop onset 보고 | H7 및 regularization 검토 여부 |
| Prompt length별 EOS | 고정 prompt의 길이 bucket | 길이별 EOS rank·확률·termination | prompt identity와 context truncation 기록 | context는 고정, sampling만 검토 |
| Category별 EOS | 승인된 15 category | category별 teacher/free generation 지표 | 평균만 사용하지 않고 category 누락 0 | 특정 데이터 증강의 필요성 판단 |
| Position별 EOS | evaluation position bucket | position별 EOS loss·rank·Top-k | 기존 Full position identity와 일치 | position-aware 변경 검토 여부 |
| Boundary proximity | EOS target과 직전 boundary 거리 | 거리 bucket별 target count·loss·rank | target/masking/packing 보존 재확인 | H3/H4, Dataset 선택지 판단 |
| Teacher-forced vs autoregressive gap | 동일 prefix pair | EOS logit·rank·probability delta | 동일 token position·prefix identity 보장 | H2 채택 여부 |
| 16/32/64/128 비교 | pure·assisted trajectory | 길이별 EOS/max-length/loop | 기존 ADR-008 길이 모두 완료 | short-horizon 가설 판정 |
| Assisted decoding 영향 분리 | sampling·no-repeat profile | pure 대비 delta와 termination reason | forced EOS·외부 stop을 성공에서 제외 | 학습 목표와 서비스 decoding 분리 |

여기서 “통과”는 진단 산출물의 무결성·재현성·분리 보고가 충족됐다는 뜻입니다. 특정 가설이 참이거나 Candidate C가
성공했다는 의미가 아닙니다. 가설 채택은 진단 결과를 검토한 별도 사용자 승인으로 결정합니다.

## 4. 중단과 불변 조건

- checkpoint·model·Tokenizer·Dataset artifact가 평가 전후 달라지면 진단은 `invalid`입니다.
- prompt/config fingerprint가 기존 비교 identity와 다르면 historical 결과와 직접 비교하지 않습니다.
- 진단 중 optimizer, backward, parameter update, Tokenization과 Dataset 재생성을 금지합니다.
- 새 수치 threshold, forced EOS와 서비스 decoding 기본값을 이 계약에서 만들지 않습니다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | H1~H7 반증 가능 가설과 Candidate B read-only EOS 진단 입력·산출물·판정·Candidate C 영향 계약 작성 |
