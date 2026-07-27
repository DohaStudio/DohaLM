# Quick·Full 대표성 정책

- 문서 상태: `review`
- 승인 상태: `approved`
- 승인일: 2026-07-27
- 승인 범위: Quick 개발용·Full 공식 비교 역할, 대표성 등급과 임계값
- 대체 여부: `not_superseded`
- 마지막 검토일: 2026-07-27

## 관측 결과

Candidate A Final 동일 checkpoint에서 Quick 128개와 Full 14,329개를 비교했다.

| 지표 | Quick | Full | 차이 |
|---|---:|---:|---:|
| Loss | 6.282144 | 6.369027 | -0.086883 |
| Top-1 | 18.2353% | 16.8417% | +1.3936%p |
| EOS target 비율 | 0.153186% | 0.130880% | +0.022306%p |
| sequence Top-1 mean | 18.2353% | 16.8416% | +1.3937%p |
| sequence Top-1 KS | — | — | 0.108012 |

Position 분포 JS divergence는 `1.02e-10`, target length KS는 `0.0000698`로 구조적 position·길이 차이는 사실상 없었다. Token 범주 JS divergence는 `0.0001816`, PSI는 `0.001453`이었다. Quick은 Korean 비율이 1.3104%p 낮고 symbol이 0.7076%p, byte fallback이 0.4374%p 높다.

[확정] Quick은 이 checkpoint에서 성능을 낙관적으로 추정했다. 승인된 packed artifact에는 source archive/category lineage가 없고 과거 Quick에는 sequence별 loss가 없어 archive별 원인을 확정할 수 없다. 따라서 특정 archive를 원인으로 단정하지 않는다.

## 용도

[확정] Quick/Full 대표성 비교는 같은 artifact와 checkpoint에서만 수행한다. 다른 Candidate의 Quick를 Full
reference로 연결하지 않는다. Candidate 간 공식 성능 비교는 동일 Full profile 결과끼리 별도 수행한다.

[확정] Prompt fingerprint가 다르면 teacher-forced 지표의 비교 가능성과 synthetic generation의 비교 가능성을
분리한다. generation은 `incomparable_prompt_identity`로 표시할 수 있지만 Full teacher-forced 결과를
임의로 폐기하거나 성공으로 완화하지 않는다.

- [확정] Quick은 개발 중 회귀 탐지와 방향성 확인에 사용한다.
- [확정] milestone, 공식 baseline, 모델 간 최종 판정에는 Full을 사용한다.
- [확정] Quick 결과에는 `representativeness_status`와 가장 최근 동일 checkpoint Full 대비 bias를 함께 기록한다.
- [확정] 기존 Quick 결과 상태와 leaderboard 수치는 변경하지 않는다.

## 대표성 판정 임계값

동일 checkpoint·dataset·tokenizer·평가 계약의 Quick/Full 쌍에 대해 절대 차이를 적용한다.

| 상태 | Loss | Top-1 | Top-5 | Top-10 | Position gap |
|---|---:|---:|---:|---:|---:|
| `representative` | ≤ 0.05 | ≤ 0.5%p | ≤ 0.75%p | ≤ 1.0%p | ≤ 0.5%p |
| `approximately_representative` | ≤ 0.10 | ≤ 1.5%p | ≤ 2.0%p | ≤ 2.0%p | ≤ 1.5%p |
| 그 외 | `not_representative` |  |  |  |  |

[확정] Candidate A Final은 loss 0.0869, Top-1 1.3936%p 차이로 `approximately_representative`이며 `biased_optimistic` 특성을 병기한다. 공식 baseline은 Full이다. 이전 checkpoint는 동일 Full 쌍이 없으므로 `insufficient_evidence`를 유지한다.

`directionally_consistent`는 학습 단계별 loss와 핵심 Top-k 방향 및 checkpoint 순서가 Full에서도 유지되지만 위 절대 오차를 넘는 경우의 보조 등급으로 제안한다. Quick이 핵심 지표 둘 이상에서 일관되게 좋거나 나쁘고 허용 폭을 넘으면 각각 `biased_optimistic`, `biased_pessimistic`을 병기한다. Full 쌍이 없으면 `insufficient_evidence`다.

## Quick v2 개선 후보

| 후보 | 장점 | 한계 |
|---|---|---|
| archive·길이·범주·EOS·position 층화 128 | 현재 비용 유지, 알려진 구성 편향 통제 | 승인 artifact에 archive lineage가 없어 즉시 구현 불가 |
| 층화 256 | 표본 오차 감소 | 추론 비용이 현재 Quick의 약 2배 |
| deterministic 128 다중 shard | 분산과 방향 일관성 측정 | shard 수만큼 비용 증가, 단일 공식 수치가 복잡해짐 |
| high/low-loss 층화 | 성능 난이도 꼬리 반영 | Full 결과로 subset을 고르면 checkpoint 종속·선택 편향 발생 |

[확정] Quick v2 상태는 `planned_awaiting_separate_approval`이다. 권장안은 archive lineage를 비민감 metadata로 연결한 뒤 checkpoint 성능을 사용하지 않는 archive×target-length×token-category 층화 128과 고정 seed를 설계하는 것이다. EOS·position은 제약 조건으로 점검하고 256 또는 다중 shard는 평가 시간 실측 후 선택한다. 이번 승인으로 Quick v2를 생성하지 않는다.

## 재검토 조건

Evaluation identity가 바뀌거나, 두 개 이상의 후속 Quick/Full 쌍에서 승인 임계값이 방향·순위를 잘못 판정하거나, 공식 공개 요건이 달라지면 재검토한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | same-artifact Quick/Full reference와 prompt별 부분 comparability 경계 추가 |
| 2026-07-27 | Candidate A Final Quick/Full 분포 비교와 대표성 임계값 제안 작성 |
| 2026-07-27 | 사용자 승인으로 역할·등급·임계값과 Candidate A 판정을 `approved`로 변경 |
