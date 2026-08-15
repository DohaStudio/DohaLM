# C1 PostgreSQL 16.15 evidence cleanup policy

- 문서 상태: `proposed`
- 마지막 검토일: 2026-08-14
- 실행 권한: 없음

[확정] evidence 실행은 `dohalm.c1.evidence=postgres-16.15` 또는
`dohalm.c1.preflight=postgres-16.15-proposed` task label과 correlation ID로 생성 자원을 제한한다.

[확정] 각 probe 종료 시 task container, volume과 private network를 제거한다. 전체 evidence 수집이 끝나면 이 작업이 새로
pull한 exact PostgreSQL image, Go analysis image, scanner executable/archive, extracted gosu/source와 임시 scan directory를
제거한다. 기존 사용자 Docker 자원은 이름·label·사전 inventory가 일치하지 않으면 변경하지 않는다.

[확정] cleanup failure, 잔존 수 불명확, public port, 실제 credential/data 또는 기존 자원 변경은 fail closed다. 정리 결과는
실행 뒤에만 `cleanup-evidence.json`으로 기록하며 성공 placeholder를 만들지 않는다.
