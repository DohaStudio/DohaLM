# Candidate C Evaluation Gate와 Candidate Selection 계약

- 문서 상태: `review`
- 마지막 검토일: 2026-08-05
- 계약 설계: `completed`
- 수치 threshold: `not_approved`
- Evaluation 실행: `not_started`
- Base 승격 승인: `not_approved`
- 비교 기준: Candidate B Final Full

## 1. 목적과 불변 비교 기준

이 계약은 Candidate C가 보고할 지표, 판정 역할과 결과 상태를 정의합니다. 새 threshold를 만들거나 Evaluation·학습을
실행하지 않습니다.

[확정] 공식 비교 기준은 Candidate B Final checkpoint
`sha256:f3edc978db9d88e9de8e2e423a28291e9f35e2e163f0413c0e27e95facc55395`와 Final Full result
`sha256:7b796f3abed0d6bd7a2426f9dff619f0609f59a4e1d04bf232545548d25d9df0`입니다.
Candidate A는 historical reference로만 유지합니다.

[확정] Candidate 공식 판정은 동일 artifact의 Quick reference를 거친 Full profile로 수행합니다. Dataset·split·Tokenizer·
model architecture·context·packing·masking identity가 다르면 같은 비교군으로 자동 판정하지 않습니다.

## 1.1 기존 Evaluation Framework 재사용

Candidate C는 [DohaLM Evaluation Framework](../evaluation/README.md)를 새로 구현하거나 복제하지 않습니다.

| Framework 구성 | Candidate C 재사용 방식 |
|---|---|
| Artifact registry·checkpoint validator | Candidate C identity·checksum·평가 전후 불변성 검사 |
| Quick profile | 동일 Candidate C artifact의 개발 회귀와 Full reference 준비 |
| Full profile | 공식 Candidate B/C 비교와 C-7 완료 근거 |
| Metrics | loss/PPL, Top-k, category, position, teacher-forced EOS, generation, stability 그대로 산출 |
| Privacy·lineage | 원문·전체 token ID 비저장, Dataset·split·Tokenizer·model fingerprint 검증 |
| Reporting | Candidate B Final Full과 동일 identity 비교 package 생성 |

이 계약이 추가하는 것은 metric 구현이 아니라 `must_not_regress`·`must_improve`·`diagnostic_only`·
`approval_required` 역할과 C-8 Candidate Selection 상태입니다. Framework 코드·설정을 변경하지 않습니다.

## 2. 분류 의미

| 분류 | 의미 |
|---|---|
| `must_not_regress` | Candidate B 대비 악화 허용 폭을 실행 전에 승인해야 하며, 무승인 회귀는 승격 차단 |
| `must_improve` | Candidate C의 승인된 실험 목적상 방향 개선이 필요하나 정확한 수치선은 별도 승인 |
| `diagnostic_only` | 필수 보고하지만 단독 자동 합격·실패 또는 승격 조건으로 사용하지 않음 |
| `approval_required` | framework만으로 자동 판정하지 않고 결과와 trade-off를 사용자가 결정 |

`must_not_regress`와 `must_improve`는 새 숫자를 뜻하지 않습니다. 허용 오차·통계 판정·최소 개선 폭이 승인되지 않은 동안
C-4와 최종 승격은 차단됩니다.

## 3. 필수 지표 분류

| 항목 | 분류 | 비교·보고 계약 | 승격 역할 |
|---|---|---|---|
| Full loss | `must_not_regress` | Candidate B 5.591160과 동일 Full identity 비교 | 허용 회귀 폭 승인 필요 |
| Perplexity | `must_not_regress` | Candidate B 268.0464와 loss 일관성 확인 | 허용 회귀 폭 승인 필요 |
| Top-1/5/10 | `must_not_regress` | B 21.8782/36.8569/43.9577% 기준 방향 비교 | 허용 회귀 폭 승인 필요 |
| Category metrics | `must_not_regress` | Korean·English·number·symbol·byte fallback 모두 보고 | category별 회귀 검토 필수 |
| Position metrics | `must_not_regress` | packed/rebased·bucket·position gap 보고 | 위치 회귀 검토 필수 |
| Teacher-forced EOS | `must_not_regress` | loss·Top-1/5/10·median/p90 rank·target/masking 보고 | free generation 개선의 대가인지 확인 |
| Pure greedy EOS termination | `approval_required` | 16/32/64/128, category별 EOS rate | Candidate C 목적상 개선 방향을 검토하되 ADR-008에 따라 0%만으로 Base 자동 실패 금지 |
| Pure greedy maximum-length | `approval_required` | 길이·category별 max-length rate | EOS와 함께 사용자 승격 판단 |
| Pure greedy repetition·loop | `must_improve` | adjacent/n-gram/degenerate loop와 onset 보고 | 승인된 EOS/loop 주가설이면 방향 개선 필요; 최소 폭은 미승인 |
| Assisted generation | `diagnostic_only` | temperature·top-p·no-repeat을 pure와 분리 | 보조 종료를 모델 자체 성공으로 간주하지 않음 |
| EOS logit/rank trajectory | `diagnostic_only` | step·length·category·loop 전후 집계 | root cause 해석과 후속 설계 입력 |
| Stability | `must_not_regress` | finite, deterministic repeat, FP16/FP32, NaN/Inf·OOM·AMP skip | 실패 시 승격 차단 |
| Privacy | `must_not_regress` | 원문·전체 token ID 비저장, special exposure·PII 상태 | 위반 시 평가 invalid·승격 차단 |
| Lineage | `must_not_regress` | Dataset·split·Tokenizer·model·config·commit fingerprint | 불일치 시 비교·평가 invalid |
| Checkpoint checksum | `must_not_regress` | 평가 전후 checksum 동일 | mutation 시 평가 invalid |
| Reproducibility | `must_not_regress` | seed·환경·config·result fingerprint와 repeat 결과 | 재현 불가 시 승격 차단 |
| Resource | `diagnostic_only` | runtime·VRAM·CPU·disk·throughput | 안전 상한 위반은 실행 실패, 성능 점수에는 합치지 않음 |

Pure greedy EOS와 maximum-length는 **필수 보고 및 사용자 승격 판단 항목**입니다. ADR-008에 따라 greedy EOS 0%만을
Base의 단독 자동 실패 조건으로 만들지 않습니다. 다만 Candidate C의 실험 목적이 EOS/loop 개선이므로 승인된 주가설과
직접 연결된 반복·loop 방향 개선이 없으면 `approved_as_base_baseline`을 자동 제안하지 않고 `experimental_only` 또는
`rejected`를 검토합니다.

## 4. 필수 Evaluation package

- 동일 Candidate C artifact의 Quick와 Full manifest·result fingerprint
- Candidate B/C Full 비교표와 identity compatibility report
- loss, PPL, Top-1/5/10, category와 position 결과
- teacher-forced EOS target·loss·Top-k·rank·masking·packing 결과
- pure greedy 16/32/64/128 generation과 assisted profile 분리 결과
- EOS termination, maximum-length, generation length, repetition·distinct-n·loop 결과
- stability, privacy, lineage, checkpoint 전후 checksum, 환경·resource와 reproducibility 결과
- 원문·전체 token ID를 포함하지 않는 immutable evidence inventory

임의 종합 점수는 만들지 않습니다. Quick는 개발 진단이며 Candidate Selection을 대신하지 않습니다.

## 5. Fail Closed

다음 중 하나면 결과는 `evaluation_incomplete` 또는 `invalid`이며 승격 판단에 사용하지 않습니다.

- Full 또는 같은 artifact Quick reference 누락
- Dataset·split·Tokenizer·model·context·packing·masking identity 불일치
- checkpoint checksum·model state의 평가 전후 변경
- 필수 metric/category/length/profile 누락 또는 non-finite 값
- privacy·lineage·원문 비저장 계약 위반
- result/config/prompt/environment fingerprint 누락
- 승인되지 않은 threshold·forced EOS·assisted 결과를 pure 성공으로 사용

## 6. Candidate Selection 상태 모델

| 상태 | 조건 | Candidate B 영향 |
|---|---|---|
| `evaluation_incomplete` | 필수 Full/evidence 누락 또는 invalid | B current baseline 유지 |
| `rejected` | 승인 hard blocker 위반 또는 목적상 개선 근거 없음 | B current baseline 유지 |
| `experimental_only` | 유효한 연구 결과지만 승격 계약 미충족·trade-off 미승인 | B current baseline 유지 |
| `approved_as_successor_candidate` | 후속 연구 parent 자격을 사용자 승인 | B current baseline 유지 |
| `approved_as_base_baseline` | 모든 필수 계약 검토 뒤 사용자가 별도 공식 승격 승인 | 그 결정 시점에만 B를 historical baseline으로 전환 가능 |

학습 완료나 `completed` Evaluation은 어떤 selection 상태도 자동 부여하지 않습니다. `approved_as_successor_candidate`와
`approved_as_base_baseline`은 서로 다른 승인입니다. Publication도 별도입니다.

## 7. C-4에 남은 승인 항목

- loss/PPL/Top-k·category·position의 허용 회귀 폭
- pure greedy EOS·maximum-length의 승격 판단 방식
- repetition·loop의 최소 개선 폭 또는 사용자 정성 판정 방식
- 복수 지표 trade-off 승인 규칙
- Candidate C의 주가설과 `must_improve` 지표 연결

이 항목을 임의 수치로 채우지 않았으므로 Evaluation 계약은 `review`, C-4는 `blocked`입니다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | 기존 Evaluation Framework의 registry·Quick/Full·metrics·privacy·lineage 재사용과 Candidate C 계약의 추가 책임 분리 |
| 2026-08-05 | Candidate B Final Full 기준 필수 지표를 must-not-regress·must-improve·diagnostic-only·approval-required로 분류하고 selection 상태 모델 작성 |
