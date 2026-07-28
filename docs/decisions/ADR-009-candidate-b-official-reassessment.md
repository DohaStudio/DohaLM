# ADR-009: Candidate B Official Reassessment under ADR-008

- 문서 상태: `approved`
- 결정일: 2026-07-28
- 승인일: 2026-07-28
- 대체 여부: `not_superseded`
- 관련 문서: [ADR-007](./ADR-007-evaluation-baseline-and-candidate-comparison.md), [ADR-008](./ADR-008-eos-generation-and-decoding-evaluation-policy.md), [Candidate A/B Full 비교](../evaluation/candidate-a-b-full-comparison.md), [EOS 진단 결과](../evaluation/eos-generation-decoding-diagnostic-result.md)

## Context

[확정] Candidate B Run `FULL-PRETRAIN-CANDIDATE-B-20260728-0002`는 12,208 step과 25,001,984 token을
정상 완료했고 동일 evaluation identity의 Full 결과를 확보했다. 기존 Candidate B 계약은 pure greedy EOS
개선을 필수 조건으로 사용해 `evaluated_contract_not_passed`로 판정했다. 이후 승인된 ADR-008은 Base의
pure greedy EOS를 필수 진단으로 유지하되 단독 실패 조건으로 사용하지 않도록 모델 단계별 계약을 분리했다.

## Historical contract

[확정] 다음 historical 상태와 artifact는 변경하지 않는다.

```text
historical_evaluation_contract: evaluated_contract_not_passed
historical_result_mutation: forbidden
```

Candidate A/B result fingerprint, checkpoint checksum과 EOS diagnostic fingerprint는 그대로 보존한다. 이
Decision은 과거 판정을 통과로 다시 쓰지 않고 현재 정책에 따른 별도 reassessment를 추가한다.

## Evidence

### Artifact identity

| 항목 | Candidate A | Candidate B |
|---|---|---|
| Run / training commit | `FULL-PRETRAIN-CANDIDATE-A-20260727-0001` / `c3b778df31b9888ca6539b1d2b3c09faca6ec0e9` | `FULL-PRETRAIN-CANDIDATE-B-20260728-0002` / `4c2eced3bf70551fbf7bc8ebde6666062584d92b` |
| Final checkpoint | `sha256:80f2aee72605ffcfeea13e158cbf7a132682591cf4295cd01c16f514686338f8` | `sha256:f3edc978db9d88e9de8e2e423a28291e9f35e2e163f0413c0e27e95facc55395` |
| Full result | `sha256:1ec526e2dc6b1792f2d071fc788cd384ad3a22a0c2750df7437158153ca2d78d` | `sha256:7b796f3abed0d6bd7a2426f9dff619f0609f59a4e1d04bf232545548d25d9df0` |
| Evaluation dataset | `sha256:0265e2d4b2ab94cd4f3df3afba14e671a58cc76b8e11434ebd64db36506f8790` | 동일 |
| Training lineage | `sha256:a0677dc18dbc98371d349aef0f83ea610ab4a984657412bd1518b883a66bd3c6` | 동일 |
| Split / packing | `sha256:dd71433c11a69345fed217620ba84b4ebc8b969b25400db07af9bc5ef0f4696f` / `sha256:e7ad635dafa3f18a77a243ec17b2bcb9d5f29c72e081ad161bd63b2218e0680b` | 동일 |
| Tokenizer / model | `sha256:9ce19a118a893fd69bad3124f94cea78f804d450a2ff6a9c4149b3064312f0ff` / `sha256:a7a4d109c6d9f385bc65f33a0c5b9a0e9af218764b2e0648ea0c81b317fed106` | 동일 |
| 동일 prompt EOS diagnostic | `sha256:db58082b055f36728d1abac1b9eeeb159daa08bd25b3fb870a7a66afc9a96026` | 동일 result |

[확정] 승인 문서·manifest 사이에서 위 identity가 일치한다. Candidate B 전용 historical EOS diagnostic
`sha256:f218e22db64f20ea7ac69ec5d00fffd352beb88c010bcfbf5d54d13cf5768040`도 변경하지 않는다.

### 성능 비교

| 지표 | Candidate A | Candidate B | 판단 |
|---|---:|---:|---|
| Full loss | 6.369027 | 5.591160 | B 개선 |
| PPL | 583.4899 | 268.0464 | B 개선 |
| Top-1/5/10 | 16.8417/29.2154/35.5767% | 21.8782/36.8569/43.9577% | B 모두 개선 |
| EOS Top-1/5/10 | 12.2334/86.3028/89.4814% | 28.0845/88.4358/90.8407% | B 모두 개선 |
| EOS mean loss | 3.165948 | 2.572150 | B 개선 |
| EOS median/p90 rank | 3/12 | 2/7 | B 개선 |
| Packed/rebased Top-1 | 16.8417/16.6767% | 21.8782/22.1533% | B 개선 |
| Pure greedy EOS / max | 0% / 100% | 0% / 100% | 동일 실패 진단 |
| 128-token adjacent repetition | 67.5591% | 44.7244% | B 개선 |
| 32+ token loop | 100% | 100% | 동일 blocker risk |

[확정] Candidate B는 모든 position bucket에서 Candidate A보다 Top-1이 높고, FP16/FP32 tolerance,
deterministic repeat, NaN/Inf, checkpoint integrity, dataset·split·tokenizer·model lineage 검증을 통과했다.
Special-token exposure는 0%다. 동일 prompt 진단에서 장기 loop는 두 모델 모두 100%이고 Candidate B의
반복률은 낮아, Candidate A보다 심각한 generation degeneration이 증가했다는 근거는 없다.

## Decision

```text
candidate_b_historical_status: evaluated_contract_not_passed
candidate_b_adr008_reassessment: approved_as_base_baseline
official_base_baseline: candidate_b
candidate_a_historical_base_baseline: true
candidate_b_derivative_parent_eligibility: approved_experimental
```

[확정] Candidate B를 현재 공식 DohaLM Base Tiny performance baseline으로 승격한다. Candidate A는 삭제·
deprecated 처리하지 않고 historical Base baseline과 회귀 비교 기준으로 보존한다. 공식 baseline은 하나만
유지하며 governance/performance dual baseline을 만들지 않는다.

## Derivative parent eligibility

[확정] Candidate B는 다음 연구 트랙의 `approved_experimental` Base parent다.

- DohaLM Instruct Tiny: 우선 experimental Base parent
- DohaLM Chat Tiny: 향후 승인된 Instruct lineage 또는 별도 direct-parent 결정의 Base 후보
- Code·SQL·Recruit·Game CPT: 우선 experimental Base parent
- EOS-aware SFT: 우선 research parent

이 결정은 Instruct·Chat·Domain CPT·SFT 데이터, 수치 계약 또는 학습 실행 승인이 아니다. 실제 파생 모델은
생성되지 않았으며 publication도 승인하지 않는다.

## Service decoding과 추가 학습

```text
service_decoding: deferred_to_instruct_chat_stage
service_decoding_implementation: not_approved
additional_base_pretraining: not_required
candidate_c: not_required
```

[확정] No-repeat bigram은 연구 후보로만 유지한다. Service decoding은 Instruct·Chat 응답 종료 계약과 함께
별도 승인하며 Base checkpoint 자체의 baseline 상태와 합치지 않는다. 현재 baseline 결정에 추가 Base
pretraining이나 Candidate C는 필요하지 않다. EOS-focused CPT·SFT도 별도 제안과 승인 없이는 실행하지 않는다.

## Publication status

- Model publication: `not_approved`
- Checkpoint publication: `not_approved`
- Dataset/tokenizer publication 변경: `not_approved`

## Consequences

- Candidate B가 향후 Base 비교의 현재 reference가 된다.
- Candidate A의 historical 수치·fingerprint·계약 판정은 불변이다.
- Candidate B의 pure greedy 종료 실패와 `decoding_assisted_termination_only` 진단은 알려진 제한으로 남는다.
- Instruct·Chat은 Base보다 엄격한 종료 계약을 별도로 충족해야 한다.

## Revisit conditions

- Dataset·split·tokenizer·packing·model 또는 Full evaluation identity가 변경된다.
- 실제 Instruct·Chat·Domain data contract와 parent 요구사항이 승인된다.
- 새로운 동일 조건 evidence에서 Candidate B의 심각한 stability·generation 회귀가 확인된다.
- Candidate C 또는 추가 Base pretraining proposal이 별도 승인된다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | ADR-008 기준 Candidate B 현재 Base baseline 승격과 experimental derivative parent 적격성 승인 |
