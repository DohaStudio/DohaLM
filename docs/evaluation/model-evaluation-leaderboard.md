# DohaLM 모델 평가 리더보드

- 문서 상태: `review`
- 마지막 검토일: 2026-07-27
- 태그: `evaluation`, `leaderboard`, `quick`, `full`

첫 네 행은 동일한 Quick subset 비교군이다. Candidate A Final Full 행은 같은 internal evaluation identity의 전체 14,329 sequence 결과이며 Quick와 profile을 섞지 않는다.

공통 dataset fingerprint: `sha256:0265e2d4b2ab94cd4f3df3afba14e671a58cc76b8e11434ebd64db36506f8790`

| Artifact | Stage | Step | Consumed tokens | Epoch | Profile | Sequences | Dataset fingerprint | Loss | PPL | Top-1 | Top-5 | Top-10 | Packed Top-1 | Rebased Top-1 | Position gap | EOS gen. | Max length | Repetition | Distinct-1/2/3 | Eval time | Result fingerprint | Status |
|---|---|---:|---:|---:|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---|---|
| Initial seed 17 | initial | 0 | 0 | 0.000000 | quick | 128 | `sha256:0265e2d4...f8790` | 250.683483 | 7.4208e+108 | 1.0968% | 1.1121% | 1.1397% | 1.0968% | 1.0078% | -0.0890%p | 0% | 100% | 100.0000% | .0625/.0667/.0714 | 0.9320s | `sha256:6e621bfe...64e10` | `completed` |
| Pilot step 100 | pilot | 100 | 204,800 | 0.002872 | quick | 128 | `sha256:0265e2d4...f8790` | 27.605845 | 9.7514e+11 | 6.8260% | 15.0827% | 17.2335% | 6.8260% | 7.1535% | +0.3275%p | 0% | 100% | 88.0000% | .1750/.2067/.2214 | 0.8889s | `sha256:fcc92372...75a25` | `completed` |
| Candidate A step 2,442 | full-pretraining mid | 2,442 | 5,001,216 | 0.070135 | quick | 128 | `sha256:0265e2d4...f8790` | 6.559930 | 706.2223 | 15.9559% | 28.1373% | 34.1728% | 15.9559% | 16.6033% | +0.6475%p | 0% | 100% | 69.3333% | .2813/.3533/.4286 | 0.8569s | `sha256:423ec489...81837` | `completed` |
| Candidate A step 4,883 | full-pretraining final | 4,883 | 10,000,384 | 0.140242 | quick | 128 | `sha256:0265e2d4...f8790` | 6.282144 | 534.9342 | 18.2353% | 30.8915% | 37.0221% | 18.2353% | 19.2962% | +1.0609%p | 0% | 100% | 45.3333% | .3813/.4800/.5786 | 0.7849s | `sha256:21649cca...1ad2ab` | `completed` |
| Candidate A step 4,883 | full-pretraining final | 4,883 | 10,000,384 | 0.140242 | full | 14,329 | `sha256:0265e2d4...f8790` | 6.369027 | 583.4899 | 16.8417% | 29.2154% | 35.5767% | 16.8417% | 16.6767% | -0.1650%p | 0% | 100% | 45.3333% | .3813/.4800/.5786 | 135.8096s | `sha256:1ec526e2...2d78d` | `completed` |

Comparison ID는 `initial-pilot-candidate-a-quick-20260727-01`이며 상태는 `comparable`이다. Gate 7은 memorization-only 별도 그룹이므로 이 순위에 포함하지 않는다. 공개 승인이 없는 checkpoint, 원문, token 배열 및 생성 text는 연결하지 않는다.

[확정] Candidate A Final Quick은 동일 Full 대비 `approximately_representative`이며 `biased_optimistic` 특성을 가진다. 공식 baseline은 Full 행이다. 기존 행의 수치·fingerprint·`completed` 실행 상태는 변경하지 않으며 대표성 판정은 [승인 정책](./quick-full-representativeness-policy.md)에 둔다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | fingerprint-aware leaderboard 골격 작성 |
| 2026-07-27 | Candidate A Final 128-sequence Quick 결과 반영 |
| 2026-07-27 | Initial, Pilot, Candidate A Mid/Final 동일 Quick 비교군 반영 |
| 2026-07-27 | Candidate A Final 14,329-sequence Full Evaluation을 별도 profile 행으로 반영 |
| 2026-07-27 | Quick 대표성 잠정 판정과 기존 leaderboard 상태 유지 경계 기록 |
| 2026-07-27 | Candidate A Quick 대표성 승인과 Full 공식 baseline 반영 |
