# Candidate B 최종 실행 Readiness

- 문서 상태: `review`
- 마지막 검토일: 2026-07-28
- 상태: `first_execution_failed_fix_validated_awaiting_separate_approval`
- 실행 허용: `false`
- 학습 승인: `not_approved`
- 결과 manifest: [Final readiness manifest](./candidate-b-final-readiness.manifest.yaml)

## 첫 실행 결과와 보완 상태

- 첫 single-use Approval은 optimizer step 1 직전에 소비됐고 실행은 12,208 step에 도달했다.
- Checkpoint 이름의 문자열 정렬 때문에 정상 schedule이 실패로 판정됐고 기존 staging cleanup으로 checkpoint가 보존되지 않았다.
- Numeric parser·schedule diagnostics와 post-checkpoint quarantine 정책을 구현하고 CPU fixture 회귀 테스트를 추가했다.
- 기존 실패 Run은 `failed`, Approval은 `consumed`, Quick/Full은 `not_run`, 공식 Candidate B 결과는 `unavailable`로 유지한다.
- Dataset·split·tokenizer·packing·model·budget·평가 계약과 Candidate A baseline은 변경하지 않았다.

## 현재 blocker

1. `CANDIDATE_B_IMMUTABLE_GIT_COMMIT_PENDING`: 이번 수정이 develop에 병합된 새 immutable commit을 별도로 선택해야 한다.
2. `CANDIDATE_B_NEW_RUN_ID_REQUIRED`: 실패 Run ID는 재사용하지 않는다.
3. `CANDIDATE_B_PHYSICAL_PREFLIGHT_MISSING`: 새 실행 직전에 다시 확인해야 한다.
4. `CANDIDATE_B_EXECUTION_APPROVAL_MISSING`: 새 Run/commit을 묶은 single-use 승인이 없다.

모든 조건이 해소돼도 실행 전 backend가 clean tree, upstream HEAD 일치, remote HEAD 존재, output 충돌·disk와 approval 미소비를 다시 검사한다. 승인·preflight는 자동 생성하거나 추정하지 않는다.

## 현재 경계

`execution_allowed: false`, Candidate B training `not_approved`, rerun `awaiting_separate_approval`이다. 이번 보완 작업에서는 optimizer·backward·GPU 학습·checkpoint·Approval 생성/소비·Quick/Full Evaluation을 0건 수행했다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | 첫 실행 실패와 numeric validator·quarantine 보완 후 별도 재실행 승인 대기 상태 반영 |
| 2026-07-28 | Backend commit 존재와 versioned manifest의 pre-commit snapshot 경계를 정합화함 |
| 2026-07-28 | Backend·CPU·output probe 완료와 commit·physical·approval 잔여 blocker 확정 |
