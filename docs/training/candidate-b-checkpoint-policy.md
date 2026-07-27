# Candidate B Checkpoint 검증·격리 정책

- 문서 상태: `review`
- 마지막 검토일: 2026-07-28
- 실행 허용: `false`
- 관련 문서: [Candidate B Backend](./candidate-b-backend.md), [실패 Run 기록](./candidate-b-failed-run-20260728-0001.md), [Checkpoint/Resume](./checkpoint-and-resume.md)

## 이름과 step 계약

Candidate B checkpoint 이름은 `checkpoint-<step>` 형식의 canonical 양의 10진 정수만 허용한다. `0`, 음수, 소수, 공백, suffix, leading zero와 최대 step `12,208` 초과 값은 fail-closed 처리한다. 디렉터리 이름과 checksum 검증을 통과한 내부 `global_step`은 정확히 일치해야 한다.

검증기는 filesystem 나열 순서를 신뢰하지 않고 정수 step으로 변환한 뒤 숫자로 정렬한다. 예상 schedule은 `[4,883, 9,766, 12,208]`이며 invalid name, duplicate, metadata mismatch, unexpected, final missing, 일반 missing을 별도 상태와 오류 코드로 기록한다.

## 검증 순서

1. Checkpoint atomic write와 내부 checksum 생성
2. 각 bundle의 필수 파일·checksum·manifest·training state 검증
3. 이름 step과 metadata step 일치 확인
4. 실제 step의 numeric sort와 예상 schedule 비교
5. 최종 run validation
6. 성공 output으로 atomic publish

검증 완료 전 staging을 공식 성공 output으로 publish하지 않는다.

## 실패 보존과 quarantine

Checkpoint manifest 또는 checksum evidence가 하나라도 생성된 뒤 실패하면 staging을 무조건 삭제하지 않는다. 다음 logical path로 atomic 격리한다.

```text
analysis/training/candidate-b/quarantine/<run-id>/
```

격리 bundle에는 checkpoint, validation report, failure manifest, quarantine policy와 checksum manifest를 둔다. 상태는 `quarantined`이며 `not_for_resume`, `not_for_evaluation`, `not_for_publication`, `manual_review_required`와 `approval_reuse_allowed: false`를 강제한다. `CheckpointManager`는 상위 경로에 `quarantine-policy.json`이 있으면 inspect와 load를 모두 `CHECKPOINT_QUARANTINED`로 차단한다.

첫 checkpoint evidence 이전의 빈 staging과 불완전한 임시 조각은 안전한 경로 검증 후 정리할 수 있다. Quarantine 충돌 또는 보존 실패 시 staging을 삭제하지 않고 수동 검토 상태로 남긴다. Quarantine은 공식 Candidate B 결과가 아니며 사람이 별도 승인하기 전 자동 발견·resume·evaluation·publication 대상이 아니다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | Numeric ordering, 진단별 fail-closed와 post-checkpoint quarantine 정책 명시 |
