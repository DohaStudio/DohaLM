# Candidate B 평가 계약

- 문서 상태: `review`
- 승인 상태: `approved`
- 승인일: 2026-07-27
- 승인 범위: Candidate B 완료 후 필수 Evaluation Framework 검증
- 대체 여부: `not_superseded`
- 추가 학습 승인: `not_approved` (Run 0002 승인 소비·실행 완료)
- 마지막 검토일: 2026-07-28

## Historical 적용 상태

[확정] 이 계약은 2026-07-27 승인 당시 Candidate B에 적용된 historical 계약이다. Candidate B는 이 계약의
synthetic greedy EOS 기준을 통과하지 못해 공식 상태 `evaluated_contract_not_passed`를 유지한다.
[ADR-008](../decisions/ADR-008-eos-generation-and-decoding-evaluation-policy.md)과 향후
[EOS Success Policy](./eos-success-policy.md)는 모델 단계별 계약을 정의하지만 이 판정을 소급 변경하지 않는다.
이 문서 작성 당시 공식 baseline 변경 또는 재평가는 `awaiting_separate_approval`이었다. 이후 별도
[ADR-009](../decisions/ADR-009-candidate-b-official-reassessment.md)가 historical 판정을 보존한 채 current
reassessment를 `approved_as_base_baseline`으로 결정했다.

## 고정 비교 조건

[확정] Candidate B Final Full의 직접 Quick reference는 동일 Candidate B Final artifact여야 한다. artifact ID,
run/checkpoint identity, model, tokenizer, dataset lineage와 Quick result fingerprint가 모두 일치해야 한다.
Candidate A Quick는 Candidate B Full의 직접 reference가 아니며 Candidate A/B 공식 비교는 Full 결과끼리
별도로 수행한다. 세부 구현 경계는 [Full 계약 수정](./candidate-b-full-evaluation-contract-fix.md)을 따른다.

[확정] Synthetic prompt fingerprint 불일치는 teacher-forced Full 지표를 무효화하지 않는다. generation
지표만 `incomparable_prompt_identity`로 분리하며 historical prompt가 없으면 추정하지 않는다.

[확정] Candidate B를 별도 승인할 경우 Candidate A와 동일한 dataset/split/tokenizer/model/context/packing/masking 평가 identity를 사용한다. 먼저 Quick으로 개발 회귀를 확인하고, 최종 판정은 Full로 한다. 변경된 identity는 같은 leaderboard 비교군에 넣지 않는다.

## 필수 지표와 합격 제안

- [확정] Full loss, PPL, Top-1/5/10, Korean·English·number·symbol·byte fallback과 position gap을 Candidate A Final Full과 비교한다.
- [확정] EOS Top-1/5/10은 각각 Candidate A의 12.2334% / 86.3028% / 89.4814%보다 낮아지지 않아야 한다.
- [확정] EOS mean loss, median rank 3과 p90 rank 12가 악화되지 않는 것을 판단 기준으로 사용한다.
- [확정] EOS rank distribution, probability와 Top-1 margin을 같은 position/context bucket으로 보고한다.
- [확정] synthetic greedy EOS rate는 0%보다 개선하고 maximum-length rate는 100%보다 낮아야 한다.
- [확정] 반복률 45.3333%, loop rate 80%, special-token exposure 0%와 일반 Top-k가 심각하게 악화되면 EOS 개선만으로 통과시키지 않는다.
- [확정] Quick 대표성은 [승인 정책](./quick-full-representativeness-policy.md)에 따라 Full 쌍으로 재판정한다.

Teacher-forced EOS 필수 보고값은 target count·ratio, mean loss, Top-1/5/10, median/p90 rank다. 생성 필수 보고값은 greedy와 승인된 sampling profile의 EOS rate, maximum-length rate, mean termination length, loop, 반복, distinct-n과 special-token exposure다. 안정성·평가 시간·peak VRAM은 필수 보고하되 성능 합격선과 분리한다. 임의 종합 점수는 만들지 않는다.

필수 실행은 동일 Quick, 동일 Full internal, 동일 synthetic generation, 동일 EOS rank, position-aware와 token-category 평가다. Candidate A Final Full·Quick 및 Initial/Pilot/Mid/Final Quick comparison을 기준선으로 고정한다.

## Fail Closed

[확정] 이 문서는 평가 계약만 승인하며 Candidate B 생성·추가 학습·데이터 변경을 승인하지 않는다. Run 0002
학습 승인은 소비됐고 재사용할 수 없다. 별도 사용자 승인 전에는 optimizer, backward, 장시간 GPU 학습과
Candidate B/C를 실행하지 않는다. EOS 삽입, loss weighting, packing 또는 decoding 변경도 각각 별도 승인과
ADR 영향 검토가 필요하다.

## 재검토 조건

Evaluation identity 또는 Candidate A baseline이 바뀌거나, 승인된 EOS 기준이 일반 정확도·반복·자원 성능과 충돌하거나, privacy·lineage 요건이 강화되면 재검토한다.

[확정] 동일 synthetic prompt와 16/32/64/128-token horizon으로 Candidate A/B를 비교하는
[EOS Generation·Decoding 진단](./eos-generation-decoding-policy.md)은 재검토 근거만 제공한다. 결과가
나와도 이 approved 계약과 Candidate B 공식 상태는 사용자 승인 없이 변경하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | ADR-008 승인 후에도 당시 계약 판정과 공식 상태를 소급 변경하지 않는 historical 경계 명시 |
| 2026-07-28 | proposed 다중 길이 EOS·decoding 진단을 계약 재검토 근거로만 연결 |
| 2026-07-28 | Run 0002 완료 후 추가 training 미승인·승인 재사용 금지 경계 명시 |
| 2026-07-28 | Candidate B same-artifact Quick reference, Full baseline 분리와 prompt comparability 계약 명시 |
| 2026-07-27 | Candidate A 진단을 기준으로 Candidate B 평가·EOS 성공 조건 제안 작성 |
| 2026-07-27 | 사용자 승인으로 Candidate B Evaluation Contract를 `approved`로 변경하고 training `not_approved` 유지 |
