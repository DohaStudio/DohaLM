# Candidate C EOS 주가설 선택 정책

- 문서 상태: `review`
- 마지막 검토일: 2026-08-05
- 정책 설계: `design_completed`
- 주가설: `not_selected`
- 선택 승인: `not_approved`
- EOS-DIAG-R4 D1~D8 backend: `implemented_synthetic_verified`
- EOS-DIAG-R5 Hypothesis Assessor: `implemented_synthetic_verified`
- 실제 Candidate B 진단: `not_run`
- 실제 Candidate B hypothesis assessment: `not_run`
- Proposed Candidate C hypothesis: `none`
- 선행 계약: [Candidate B Final Read-only EOS 진단](./candidate-b-eos-diagnostic-contract.md)
- 가설 정의: [Candidate C EOS 가설](../training/candidate-c-eos-hypotheses.md)

## 1. 목적과 원칙

이 정책은 완료·검증된 D1~D8 artifact를 H1~H7의 지지·반증 근거로 연결하고 Candidate C의 단일 EOS-focused
intervention을 검토하기 위한 상태를 만듭니다. 진단 설계 완료, artifact 생성 또는 assessor 출력은 사용자 선택 승인이 아니며
Candidate C config·학습·승격을 자동 승인하지 않습니다.

새 수치 threshold를 만들지 않습니다. Candidate A/B의 고정 상대 비교, profile·길이·category·position에 걸친 명백한 방향성,
지지와 반증 artifact의 동시 검토를 사용합니다. 기존 계약에 없는 수치 경계가 선택에 필수라면 `approval_required`로 남깁니다.

## 2. H1~H7 지지·반증 매핑

| 가설 | Supporting signal | Contradictory signal | Insufficient evidence | Primary / Secondary artifact | Candidate C intervention 후보 유형 | 추가 승인 |
|---|---|---|---|---|---|---|
| H1 EOS calibration 부족 | teacher-forced에서도 EOS rank/probability가 일관되게 낮고 loop 전부터 경쟁력이 낮음 | teacher-forced는 양호하고 autoregressive에서만 붕괴 | paired position 또는 EOS trajectory 불완전 | D2 `teacher-autoregressive-gap` / D1 `eos-rank-trajectory` | EOS loss/calibration 단일 축 | C-4 config·평가 승인 |
| H2 Autoregressive exposure mismatch | teacher-forced 양호, 생성 진행 중 gap 증가·EOS 급락 | 같은 prefix/position에서 gap이 없고 teacher/free 모두 낮음 | prefix identity·position pairing 미증명 | D2 / D5 `prompt-category-position-analysis` | exposure-aware 단일 학습 축 | Dataset/학습 의미에 따라 C-2·C-4 승인 |
| H3 Boundary frequency 부족 | boundary-adjacent evidence가 부족하고 distance에 따라 EOS 성능 방향이 일관됨 | 충분한 boundary 노출과 distance 무관 성능 | boundary count·distance·target identity 누락 | D4 `boundary-analysis` / D8 `budget-proxy-analysis` | boundary sampling/weighting 단일 축 | Dataset revision이면 C-2와 C-4 승인 |
| H4 Packing objective 영향 | packed/비경계 또는 distance 조건 사이 EOS degradation | packing 조건별 차이가 없고 보존 검증과 성능이 일관됨 | 비-packed 비교군 또는 boundary metadata 없음 | D4 / D2 | packing/objective 단일 축 | Dataset revision·ADR 영향 검토와 C-2·C-4 승인 |
| H5 Decoding parameter 영향 | pure greedy 실패가 유지되지만 작은 승인 profile에서 category·길이 전반 종료가 일관됨 | assisted profile에서도 회복 없거나 forced heuristic에만 의존 | pure/assisted 분리 또는 seed/profile identity 불완전 | D7 `decoding-ablation` / D6 `length-matrix` | 학습 개입 아님; Candidate C 필요성 재검토 | service decoding 및 Candidate C 진행 별도 승인 |
| H6 Training budget 부족 | A→B budget 증가와 teacher-forced·autoregressive 종료·반복이 함께 개선 | teacher-forced만 개선되고 pure greedy 종료는 개선 없음 또는 plateau | A/B 동일 identity·budget·step 비교 불충분 | D8 / D6 | budget-only successor; EOS intervention과 분리 | C-4 budget·GPU·실행 승인 |
| H7 Repetition loop 경쟁 | loop onset 뒤 EOS rank 급락, 특정 HMAC n-gram 고착, loop 방지 profile에서 회복 | loop 전후 EOS 경쟁 변화가 없거나 loop 없는 경우에도 같은 미종료 | onset 전후 trajectory·competitor record 불완전 | D3 `loop-analysis` / D7 | repetition-focused 단일 축 | C-4 config·평가 승인 |

H3·H4는 같은 boundary artifact를 사용하지만 frequency와 objective 효과를 같은 가설로 합치지 않습니다. D4 비교군이 없으면 둘 다
`undetermined`이며 임의로 하나를 고르지 않습니다. H5의 지지는 학습 root cause의 지지가 아닙니다. H6는 현재 B의 pure-greedy
비개선과 함께 검토하며 teacher-forced 개선만으로 `selected`가 될 수 없습니다.

## 3. 선택 상태와 규칙

진단 후 상태는 다음 중 하나입니다.

| 상태 | 조건 |
|---|---|
| `selected` | 정확히 하나의 가설에 충분한 지지·반증 검토가 있고 대안보다 직접적인 단일 intervention 연결이 사용자 승인됨 |
| `conditionally_selected` | 한 가설이 우세하지만 기존 계약에 없는 수치 판정이나 제한된 추가 evidence 승인이 필요함 |
| `no_hypothesis_selected` | 모든 가설이 반증됐거나 Candidate C 학습 개입 근거가 없음 |
| `multiple_hypotheses_unresolved` | 둘 이상이 동등하게 얽혀 단일 축을 정당화할 수 없음 |
| `diagnostic_incomplete` | exact artifact·completion evidence·identity 또는 필수 D1~D8 검증이 불완전 |

`selected`는 정확히 하나만 허용합니다. 각 가설은 supporting artifact와 contradictory review를 모두 가져야 하며, 미관측을 반증으로
간주하지 않습니다. H5만 강하면 Candidate C 학습 자체를 재검토하고, H6만 강하면 budget-only successor와 EOS intervention을
서로 다른 실험으로 분리합니다. 선택 가설과 단일 intervention 사이 직접 연결이 없으면 `selected`가 아닙니다. 실제 intervention
값과 resolved config는 후속 C-4에서만 확정합니다.

## 4. Decision artifact

`hypothesis-assessment.json`은 최소 다음을 포함합니다.

- `selection_status`, `selected_hypothesis` (`selected`가 아니면 null)
- rejected와 undetermined alternatives 및 각각의 이유
- supporting·contradictory artifact ID와 checksum
- confidence status: `supported`, `limited`, `inadequate` 중 하나
- unresolved questions와 `approval_required` 항목
- `allowed_next_action`과 `prohibited_next_action`
- diagnostic completion evidence·identity·matrix fingerprint
- assessor source commit·policy version·artifact fingerprint·checksum

자동 assessor는 후보 상태만 만들 수 있습니다. 사용자 승인 전 `candidate_c_primary_hypothesis`는 `not_selected`, 허용 다음 행동은
`review_evidence_only`, 금지 행동은 Candidate C config freeze·GPU·training입니다.

EOS-DIAG-R4의 synthetic `diagnostic-summary.json`에 있는 `hypothesis_selection_allowed`는 D1~D8의 complete/limited coverage만
검사하는 backend 신호입니다. H1~H7 supporting·contradictory mapping, confidence와 단일 가설 선택은 수행하지 않으며 R5 assessor와
사용자 승인 전에는 이 정책의 `selected` 상태로 변환할 수 없습니다. Synthetic result는 실제 Candidate B evidence가 아닙니다.

### 4.1 EOS-DIAG-R5 구현 경계

[확정] R5는 D1~D8 semantic artifact fingerprint에 결속된 metric-only Evidence Signal을 strict 검증하고 H1~H7별
supporting·contradictory·insufficient evidence, coverage, confidence와 intervention category를 계산합니다. Signal의 방향과 강도는
기존 계약에 없는 수치 threshold로 추론하지 않고 caller가 명시하며, assessor는 허용 diagnostic mapping과 fingerprint를
검증합니다. Contradictory signal은 결과에서 제거하거나 supporting으로 덮어쓰지 않습니다.

[확정] R5 selection은 ranking이 아니라 synthetic proposed eligibility입니다. H3/H4와 H2/H7의 인과 분리가 없으면
`multiple_hypotheses_unresolved`, H6는 최대 `conditionally_selected`, H5는 `decoding_policy` review만 허용합니다. 모든 결과에서
`training_intervention_allowed=false`, actual project decision 변경 false입니다.

[확정] D1~D8 중 하나라도 incomplete·insufficient·incompatible·blocked·schema-only이면, 또는 contradiction review를 포함한 overall
coverage가 `complete`가 아니면 proposed selection을 만들지 않고 `diagnostic_incomplete`로 닫습니다. `strong`이라는 caller 선언만으로
`high` confidence를 만들지 않으며 현재 schema에는 승인 provenance가 없으므로 confidence 상한은 H6 `low`, 나머지 `medium`입니다.

[제외] 실제 Candidate B result, 실제 주가설 승인, Candidate C config·GPU·training과 ADR 승인을 입력하거나 생성하지 않았습니다.
`hypothesis-assessment.json`과 summary 연결은 synthetic rehearsal 전용이며 actual project 상태는 계속 미선택입니다.

## 5. 현재 상태

```text
candidate_b_eos_diagnostic_execution_allowed: false
eos_diag_r4_diagnostic_backend: implemented_synthetic_verified
eos_diag_r5_hypothesis_assessor: implemented_synthetic_verified
actual_candidate_b_diagnostics: not_run
actual_candidate_b_hypothesis_assessment: not_run
proposed_candidate_c_hypothesis: none
candidate_c_primary_hypothesis: not_selected
candidate_c_execution_allowed: false
candidate_c_readiness: blocked
gate_c1: review
gate_c4: blocked
```

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | R5 독립 감사 보완으로 incomplete diagnostic selection 차단, deterministic aggregation, high confidence 제한과 R1 exact linkage 반영 |
| 2026-08-05 | R5 synthetic Evidence Signal·H1~H7 assessor·coverage·proposed selection과 R1 payload 연결 구현; actual assessment·주가설 승인 미실행 유지 |
| 2026-08-05 | R4 synthetic D1~D8 completeness 신호와 R5 실제 hypothesis assessment·사용자 선택 책임을 분리; 주가설 미선택 유지 |
| 2026-08-05 | H1~H7 지지·반증·불충분 조건, 단일 주가설 상태와 decision artifact 계약 설계 |
