# 체크포인트 비교 정책

- 문서 상태: `review`
- 마지막 검토일: 2026-07-27
- 태그: `evaluation`, `checkpoint`, `comparison`

## 비교 그룹

주 비교 그룹은 initial seed 17, Pilot step 100, Candidate A step 2,442와 step 4,883이다. Gate 7 Tiny Overfit은 memorization-only 별도 그룹이며 일반화 성능 순위에 섞지 않는다.

Artifact registry는 ID, stage, run, step/token/epoch, dataset/split/tokenizer/model/config fingerprint, checksum manifest SHA-256, 논리 외부 경로, 승인·평가·공개 상태를 기록한다. 실제 checkpoint가 없거나 checksum/fingerprint/승인이 맞지 않으면 fail-closed한다.

## 비교 가능성

- 동일 dataset identity와 evaluation config: `comparable`
- dataset identity 불일치: `incomparable_dataset`
- config fingerprint 불일치: `incomparable_config`
- 미완료: `incomplete`
- 실행 실패: `failed`

임의 종합 점수나 가중치 순위를 만들지 않고 원 지표를 그대로 나열한다.

[확정] 2026-07-27 승인된 [ADR-007](../decisions/ADR-007-evaluation-baseline-and-candidate-comparison.md)에 따라 Quick은 개발 회귀·방향성 전용이고 Candidate 공식 baseline과 최종 비교에는 Full을 사용한다. Candidate A Final Quick은 `approximately_representative`이면서 `biased_optimistic`이며, 공식 baseline은 Candidate A Final Full이다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | artifact 그룹과 fingerprint 비교 차단 규칙 작성 |
| 2026-07-27 | Candidate A Full baseline과 Quick 대표성 승인 반영 |
