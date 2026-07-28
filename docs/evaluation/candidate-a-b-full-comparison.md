# Candidate A/B Full 비교

- 문서 상태: `review`
- 마지막 검토일: 2026-07-28
- 비교 범위: 동일 Full internal evaluation의 teacher-forced·EOS·position·stability·resource
- 종합 점수: 사용하지 않음

## 비교 identity

Candidate A `candidate-a-final-full-20260727-01`과 Candidate B
`candidate-b-final-full-20260728-03`은 dataset, split, tokenizer, model architecture와 Full profile이 같다.
Candidate A historical prompt snapshot은 검증되지 않았고 Candidate B는 현재 prompt를 사용했으므로 generation
간 비교만 `incomparable_prompt_identity`다. teacher-forced 지표는 `comparable`이다.

## 핵심 Full 비교

| 지표 | Candidate A | Candidate B | B−A |
|---|---:|---:|---:|
| Loss | 6.369027 | 5.591160 | -0.777867 |
| PPL | 583.4899 | 268.0464 | ratio 0.459385 |
| Top-1 | 16.8417% | 21.8782% | +5.0365%p |
| Top-5 | 29.2154% | 36.8569% | +7.6414%p |
| Top-10 | 35.5767% | 43.9577% | +8.3809%p |
| Korean Top-1 | 4.1705% | 9.4773% | +5.3068%p |
| English Top-1 | 44.2860% | 48.1499% | +3.8639%p |
| Number Top-1 | 28.9916% | 30.9522% | +1.9606%p |
| Symbol Top-1 | 52.0377% | 59.9325% | +7.8949%p |

## EOS 계약 비교

| 지표 | Candidate A | Candidate B | 판정 |
|---|---:|---:|---|
| EOS Top-1 | 12.2334% | 28.0845% | 개선 |
| EOS Top-5 | 86.3028% | 88.4358% | 개선 |
| EOS Top-10 | 89.4814% | 90.8407% | 개선 |
| EOS mean loss | 3.165948 | 2.572150 | 개선 |
| EOS rank median | 3 | 2 | 개선 |
| EOS rank p90 | 12 | 7 | 개선 |
| Greedy EOS rate | 0% | 0% | 필수 개선 없음 |
| Greedy maximum-length | 100% | 100% | 필수 감소 없음 |

Candidate B의 teacher-forced EOS는 모든 고정 기준에서 개선됐다. 그러나 Candidate B 자체의 현재 prompt greedy
결과가 EOS 0%, maximum-length 100%이므로 절대 성공 조건을 통과하지 못했다. Candidate A/B generation의
직접 수치 비교는 prompt identity 불일치 때문에 공식 비교로 사용하지 않는다.

## Position, stability와 비용

| 지표 | Candidate A | Candidate B | B−A |
|---|---:|---:|---:|
| Packed Top-1 | 16.8417% | 21.8782% | +5.0365%p |
| Rebased Top-1 | 16.6767% | 22.1533% | +5.4766%p |
| Position gap | -0.1650%p | +0.2751%p | +0.4401%p |
| Evaluation time | 135.810s | 123.432s | -12.378s |
| Target token/s | 26,903 | 29,601 | +2,698 |
| Peak reserved VRAM | 3,032,481,792 B | 3,032,481,792 B | 0 B |
| CPU working set | 879,890,432 B | 896,049,152 B | +16,158,720 B |

모든 position bucket의 Candidate B Top-1은 Candidate A보다 4.4629–5.2107%p 높았다. 두 결과 모두
FP16/FP32 tolerance, deterministic repeat, NaN/Inf, checkpoint·model 불변성 검증을 통과했다.

## 결론

Candidate B는 teacher-forced 품질과 EOS rank를 개선했지만 승인된 generation 종료 조건을 충족하지 못했다.
따라서 `training: completed`, `full_evaluation: completed`,
`official_candidate_b_result: evaluated_contract_not_passed`로 분리하며 Candidate A를 공식 baseline으로 유지한다.

[확정] 2026-07-28 승인된 ADR-008과 모델 단계별 EOS 계약은 이 historical 비교와 공식 baseline을 소급
변경하지 않는다. Candidate B 재평가와 derivative parent 선정은 별도 승인 대상이다.
후속 decoding·EOS 정책 변경이나 추가 학습은 별도 사용자 승인과 ADR 영향 검토가 필요하다.

[동일 조건 신규 진단](./eos-generation-decoding-diagnostic-result.md)은 historical prompt identity 문제를
해소했다. 두 모델 모두 128-token pure greedy EOS 0%였고 Candidate B는 assisted profile에서만 종료했다.
이 근거는 기존 Full 수치나 Candidate A baseline을 변경하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | Candidate A/B 동일 Full teacher-forced 비교와 generation comparability·계약 판정 기록 |
