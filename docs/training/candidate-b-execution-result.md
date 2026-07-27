# Candidate B Run 0002 실행 결과

- 문서 상태: `review`
- 마지막 검토일: 2026-07-28
- Run ID: `FULL-PRETRAIN-CANDIDATE-B-20260728-0002`
- Approval ID: `CANDIDATE-B-APPROVAL-20260728-0002`
- Immutable training commit: `4c2eced3bf70551fbf7bc8ebde6666062584d92b`

## Training 결과

| 항목 | 결과 |
|---|---:|
| Optimizer steps | 12,208 |
| Scheduled tokens | 25,001,984 |
| Runtime | 2,793.842초 |
| Final loss | 5.420430 |
| Minimum loss | 4.164067 |
| Retry / resume / extension | 0 / 0 / 0 |
| Approval consumed | `true` |
| 원문 저장 | `false` |

Run 0002는 fresh seed 17에서 정상 종료됐다. 기존 실패 Run 0001의 retry 또는 resume가 아니며 Approval은
single-use로 소비돼 재사용할 수 없다.

## Checkpoint

| Step | `checksums.json` SHA-256 |
|---:|---|
| 4,883 | `sha256:d4ba67bf4cac0b13306f717f13a3d4330a4d807c614e3ee7e68d15ea7fc62ff6` |
| 9,766 | `sha256:87b90abf33426db425bd6d6366bfed7d1b260771f782c875ee09940721e2f7b8` |
| 12,208 | `sha256:f3edc978db9d88e9de8e2e423a28291e9f35e2e163f0413c0e27e95facc55395` |

세 checkpoint는 numeric ordering·schedule·metadata·checksum 검증을 통과했다. Final Full과 EOS diagnostic
전후에도 step 12,208 checksum은 동일했다.

## Evaluation 상태

- Final Quick: `completed`
- 기존 Full failure `-01`/`-02`: 영구 보존
- Final Full `candidate-b-final-full-20260728-03`: `completed`
- EOS diagnostic `eos-candidate-b-final-20260728-01`: `completed`
- 공식 판정: `evaluated_contract_not_passed`

세부 지표와 비교는 [Candidate B Full 결과](../evaluation/candidate-b-final-full-result.md)와
[Candidate A/B Full 비교](../evaluation/candidate-a-b-full-comparison.md)를 따른다. 추가 training, retry, resume,
extension, publication은 승인되지 않았다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | Run 0002 training·checkpoint·Quick·Full·EOS diagnostic 결과와 승인 경계 기록 |
