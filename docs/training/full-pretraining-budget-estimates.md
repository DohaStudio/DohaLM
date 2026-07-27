# Full Pretraining Candidate A 예산

- 문서 상태: `approved`
- 마지막 검토일: 2026-07-27
- 기준 evidence: [canonical pilot-v2 100-step 결과](./pilot-pretraining-100-v2-result.md)
- 관련 문서: [실행 계획](./full-pretraining-execution-plan.md)

## 계산 기준

- Train token: 71,307,940
- Packed sequence: 278,547
- Context 256, effective batch 8, optimizer step당 scheduled token 2,048
- Step: `ceil(10,000,000 / 2,048) = 4,883`
- Scheduled token: `4,883 × 2,048 = 10,000,384`
- Equivalent epoch: `10,000,384 / 71,307,940 = 0.14024222267534303`
- 마지막 고정 batch의 허용 overshoot: 최대 2,047 token capacity

## 승인 예산

| 항목 | 값 |
|---|---:|
| Planned wall-clock | 1,800초 |
| Hard stop | 2,700초 |
| Checkpoint | 2개 |
| 예상 output | 약 0.58GiB |
| Run output hard limit | 2GiB |
| 시작 free disk | 최소 10GiB |
| 실행 중 free disk | 최소 5GiB |
| VRAM / CPU hard limit | 7GiB / 4GiB |

Candidate A 완료 후 자동 연장하거나 더 큰 budget으로 전환하지 않는다. 예상치는 보장값이 아니며 hard limit가 우선한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | [확정] Candidate A token·step·epoch·disk·wall-clock 예산 승인 |
