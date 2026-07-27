# Full Pretraining Checkpoint·Retention 정책

- 문서 상태: `approved`
- 마지막 검토일: 2026-07-27
- 관련 문서: [Checkpoint와 재개](./checkpoint-and-resume.md), [실행 계획](./full-pretraining-execution-plan.md)

## Checkpoint

| 구분 | Step | Scheduled token |
|---|---:|---:|
| Mid | 2,442 | 5,001,216 |
| Final | 4,883 | 10,000,384 |

- [확정] 위 두 checkpoint만 생성하고 최대 2개를 보존한다.
- [확정] atomic publish, 파일별 SHA-256, checksum inventory와 bundle byte 집계를 필수로 한다.
- [확정] 불완전하거나 checksum-invalid인 checkpoint는 사용하지 않는다.
- [확정] 실행 중·종료 후 자동 삭제를 하지 않는다. 축소·삭제는 별도 사용자 승인이 필요하다.

## Retention

Mid/Final checkpoint, JSONL log, aggregate metrics, resolved config, environment manifest, checksum manifest와 failure report를 보존한다. 성공한 staging과 임시 파일만 제거할 수 있다. 원문·prompt·continuation·전체 token ID는 저장하지 않으며 Git 또는 외부에 게시하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | [확정] 2,442/4,883 checkpoint와 2개 보존 정책 승인 |
