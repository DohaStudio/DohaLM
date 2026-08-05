# ADR-011: Candidate C Experimental Successor 재개 제안

- 문서 상태: `draft`
- 마지막 검토일: 2026-08-05
- 결정 상태: `proposed`
- 실행 영향: 없음
- 선행 결정: [ADR-008](./ADR-008-eos-generation-and-decoding-evaluation-policy.md),
  [ADR-009](./ADR-009-candidate-b-official-reassessment.md)
- 관련 계약: [Candidate C 설계](../training/candidate-c-design.md),
  [EOS 가설](../training/candidate-c-eos-hypotheses.md),
  [Evaluation 계약](../training/candidate-c-evaluation-contract.md)

## Context

[확정] ADR-009는 2026-07-28 당시 Candidate B를 current Base baseline으로 승인하고 추가 Base pretraining과
Candidate C를 `not_required`로 결정했습니다. 그 결정은 당시 evidence와 승인 범위에서 유효하며 historical 상태를
변경해서는 안 됩니다.

[확정] 현재 공식 프로젝트 우선순위는 Base Training Readiness 다음에 Candidate C를 Foundation 핵심 목표로 둡니다.
이는 ADR-009의 revisit 조건인 “Candidate C 또는 추가 Base pretraining proposal이 별도 승인되는 경우”에 해당하는
새 제안이며, ADR-009 본문을 소급 수정할 사유가 아닙니다.

## 검토한 선택지

| 선택지 | 장점 | 문제 | 판정 |
|---|---|---|---|
| ADR-009 직접 수정 | 문서 수가 늘지 않음 | 당시 승인·historical 의미를 소급 변경 | 기각 제안 |
| ADR-009 폐기 | 새 우선순위만 남김 | Candidate B baseline 근거와 재평가 계보 손실 | 기각 제안 |
| 후속 ADR-011 작성 | 당시 결정 보존, 새 목적·승인 경계 명확 | 별도 사용자 승인 필요 | 권장 |

## Proposed Decision

다음 결정을 사용자 승인 대상으로 제안합니다.

```text
adr009_historical_decision: preserved
official_base_baseline: candidate_b
candidate_c_role: experimental_successor_candidate
candidate_c_replacement_status: false
candidate_c_execution_approval: separate_required
candidate_c_base_promotion_approval: separate_required
publication_approval: separate_required
```

- [제안] Candidate B는 Candidate C Evaluation과 별도 승격 결정이 끝날 때까지 current Base baseline을 유지합니다.
- [제안] Candidate C는 Candidate B를 자동 대체하는 모델이 아니라 제한된 EOS 가설을 검증하는 experimental successor
  candidate입니다.
- [제안] Candidate C 학습 실행 승인은 특정 immutable commit, Dataset·Tokenizer·resolved config fingerprint,
  Run ID와 output을 묶는 single-use 승인으로만 발급합니다.
- [제안] 학습 완료는 Candidate C의 성공, Candidate B 대체, Foundation Base 승격 또는 publication을 뜻하지 않습니다.
- [제안] Base 승격은 승인된 Full Evaluation과 Candidate Selection 기록을 검토한 뒤 별도 사용자 결정으로 수행합니다.

## Candidate C 목적

> 동일한 DohaLM-Tiny architecture·운영 Tokenizer·비교 identity를 유지하면서, 승인된 단일 EOS-focused intervention이
> Candidate B 대비 pure greedy 종료와 반복 loop에 미치는 인과 효과를 검증하는 experimental successor 실험입니다.

## 허용 변경과 금지 변경

- [제안] 한 실행에서 승인된 독립 변경 축은 하나만 사용합니다. 후보는 token budget, learning rate, warmup,
  EOS-aware loss weighting, boundary sampling, sequence construction, regularization 또는 seed입니다.
- [제안] Dataset을 변경하는 실험과 training objective를 변경하는 실험을 같은 Candidate C identity에 섞지 않습니다.
- [제안] architecture, vocabulary, Tokenizer, hidden size와 layer 수 변경은 Candidate C 범위에서 금지합니다.
- [제안] unrelated Dataset 교체, cross-candidate resume, 자동 retry·extension과 forced EOS 성공 간주는 금지합니다.
- [검증 필요] 실제 Candidate C에서 사용할 단일 intervention과 causal control을 승인해야 합니다.

## 승인 경계

이 ADR은 `draft`이므로 ADR-009의 승인 결정을 변경하지 않습니다. 사용자 승인 전 상태는 다음과 같습니다.

```text
candidate_c_contract_design: completed
candidate_c_execution_allowed: false
candidate_c_training: not_started
candidate_c_base_promotion: not_approved
```

ADR 승인도 Dataset·Tokenizer·Training Config freeze, GPU Smoke 또는 학습 실행 승인을 자동 부여하지 않습니다.

## Consequences

- Candidate B의 artifact, historical 계약 미통과 판정과 current baseline 지위를 보존합니다.
- Candidate C 실패 또는 평가 미완료 시 Candidate B가 계속 current Base baseline입니다.
- Candidate C는 `rejected`, `experimental_only`, `approved_as_successor_candidate`,
  `approved_as_base_baseline`, `evaluation_incomplete` 중 하나로 별도 판정됩니다.
- `approved_as_successor_candidate`는 연구 후속 자격이며 `approved_as_base_baseline`과 동일하지 않습니다.

## Revisit conditions

- Candidate C 단일 intervention과 C-1~C-4 계약이 승인됩니다.
- Dataset·Tokenizer·architecture 또는 evaluation identity 변경이 필요해집니다.
- Candidate C Full Evaluation에서 stability·privacy·lineage 또는 generation blocker가 발견됩니다.
- Candidate C의 Base 승격이나 publication이 제안됩니다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | ADR-009 historical 결정 보존, Candidate B current baseline 유지, Candidate C experimental successor와 실행·승격 승인 분리 제안 |
