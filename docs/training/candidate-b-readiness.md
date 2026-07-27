# Candidate B Readiness

- 문서 상태: `review`
- 마지막 검토일: 2026-07-28
- Readiness 상태: `backend_implemented_execution_blocked`
- 실행 허용: `false`
- 관련 문서: [Candidate B 설계](./candidate-b-design.md), [설계 manifest](./candidate-b-readiness.manifest.yaml), [Candidate B 평가 계약](../evaluation/candidate-b-evaluation-contract.md)

## 1. 현재 판정

- [확정] Candidate A Final Full baseline과 Candidate B 평가 계약은 승인돼 있다.
- [확정] Candidate B 25M config·identity·budget·checkpoint·resume·평가·자원·승인 소비 설계가 작성됐다.
- [확정] Candidate B execution backend와 CPU fail-closed validation은 구현됐지만 training은 `not_approved`이므로 실제 실행은 불가능하다.
- [확정] 현재 `execution_allowed: false`, `training_started: false`다.

## 2. Readiness checklist

| ID | 조건 | 현재 상태 | 증거·후속 조치 |
|---|---|---|---|
| B-RDY-01 | Candidate A 공식 Full baseline | `passed` | `candidate-a-final-full-20260727-01` |
| B-RDY-02 | Candidate B Quick·Full 계약 | `passed` | 승인된 Candidate B 평가 계약 |
| B-RDY-03 | Dataset·split·PII·tokenizer·model identity 고정 | `passed` | 설계 manifest identity |
| B-RDY-04 | 25M token·12,208 step 예산 계산 | `passed` | Candidate B example과 manifest |
| B-RDY-05 | Fresh seed-17 초기화와 no warm-start | `passed` | Candidate B 설계 8절 |
| B-RDY-06 | 3-checkpoint·same-run-only Resume 정책 | `passed` | Candidate B 설계 8절 |
| B-RDY-07 | EOS·일반 품질 성공 조건 | `partial` | 승인 계약 적용; “심각한 회귀” 추가 수치 임계값은 미확정 |
| B-RDY-08 | GPU·시간·Disk 설계 예산 | `projection_and_probe_passed` | Candidate A 실측 외삽·외부 output probe 통과; runtime 학습 미검증 |
| B-RDY-09 | Candidate B execution backend | `passed` | resolver·scope·approval·Git·probe·monitor·runner CPU 검증 |
| B-RDY-10 | Resolved config·Run ID·output 고정 | `passed` | Run ID와 fingerprint 고정; 절대경로 미포함 |
| B-RDY-11 | Immutable Git commit | `blocked` | backend commit `a6464be`는 upstream에 존재하나 현재 문서 변경이 미커밋이므로 실행 identity 재고정 필요 |
| B-RDY-12 | Output probe·free disk | `passed` | write·fsync·rename·checksum·delete·10GiB 기준 통과 |
| B-RDY-13 | 물리적·시스템 preflight | `blocked` | 전원·냉각·환기·절전·CUDA·GPU 점유 확인 필요 |
| B-RDY-14 | Single-use Candidate B 실행 승인 | `blocked` | 별도 사용자 승인 필요 |

## 3. Fail Closed blocker

현재 문서 worktree 기준 blocker는 다음 3개다. 버전 관리된 YAML의 `backend_ready_awaiting_commit_preflight_and_approval`은 backend commit 전 snapshot이며 이번 문서 정합화 범위에서 변경하지 않는다.

1. `CANDIDATE_B_IMMUTABLE_GIT_COMMIT_PENDING`
2. `CANDIDATE_B_PHYSICAL_PREFLIGHT_MISSING`
3. `CANDIDATE_B_EXECUTION_APPROVAL_MISSING`

어느 하나라도 남으면 `execution_allowed`를 `true`로 바꾸지 않는다. 문서 작성이나 Git commit만으로 실행 승인이 생기지 않는다.

## 4. 별도 승인 패키지 요구사항

실행 승인 요청 시 다음 항목을 새 manifest revision에 모두 고정한다.

- immutable Git commit과 clean worktree
- 실제 Run ID, 충돌 없는 외부 output 경로와 resolved config fingerprint
- Candidate B 25M 예산과 training/checkpoint/resume/evaluation/resource 정책의 승인 상태
- Dataset·split·PII·tokenizer·model·config fingerprint 재검증
- Candidate B 전용 backend의 inspection/dry-run·mismatch·재실행 차단 테스트
- output probe와 disk budget 결과
- Python·Torch·CUDA·driver·GPU 환경
- 전원·냉각·환기·절전·재시작 예약·다른 장시간 GPU 작업 부재 확인
- 승인자·승인시각·승인 commit·승인 config/manifest fingerprint

승인은 optimizer step 1에서 한 번만 소비하며 자동 retry, 자동 Resume, 예산 연장과 Candidate C 전환에는 재사용하지 않는다.

## 5. 이번 단계에서 실행하지 않은 작업

Candidate B backend·CPU validation·output probe는 완료했다. Quick/Full 평가, optimizer, backward, checkpoint 생성과 모델 학습은 실행하지 않았다. 이는 현재 `execution_allowed: false`를 유지하기 위한 의도된 경계다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | Backend commit 이후 현재 문서 변경을 반영해 clean immutable Git 재확정 경계를 명시함 |
| 2026-07-28 | Candidate B 설계 완료와 실행 차단 blocker·별도 승인 패키지 요구사항 기록 |
| 2026-07-28 | Backend·resolved config·CPU validation·output probe 완료와 blocker 3개로 축소 |
