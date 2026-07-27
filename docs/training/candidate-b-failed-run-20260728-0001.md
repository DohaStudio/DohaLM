# Candidate B 실패 Run — 20260728-0001

- 문서 상태: `review`
- 기록일: 2026-07-28
- Run ID: `FULL-PRETRAIN-CANDIDATE-B-20260728-0001`
- Approval ID: `CANDIDATE-B-APPROVAL-20260728-0001`
- Immutable commit: `bdcf85d4fd60aefb15178ec4041735737bb86b1b`
- 상태: `failed`

## 실행 사실

승인된 단일 실행은 optimizer step 1 직전에 single-use Approval을 atomic consume한 뒤 정확히 한 번 진행됐다. 12,208 optimizer step과 25,001,984 scheduled token에 도달했으며 관찰된 NaN, OOM과 AMP skip은 없고 runtime hard stop도 발동하지 않았다.

Checkpoint write는 step 4,883과 9,766에서 관찰됐고 final step 12,208 저장 코드까지 진입했다. 이후 schedule validator가 이름을 문자열 순서 `12,208 → 4,883 → 9,766`으로 정렬해 정상 schedule을 불일치로 판정했다. 기존 failure handler가 staging 전체를 제거했으므로 checkpoint와 runtime 원본은 현재 보존되지 않았다.

## 영구 상태

```text
status: failed
retry_allowed: false
resume_allowed: false
approval_consumed: true
superseded: false
checkpoint_preserved: false
quick_evaluation: not_run
full_evaluation: not_run
official_candidate_b_result: unavailable
```

Failure Manifest와 approval consumption record는 외부 제한 경로의 read-only 증거로 유지한다. 원본은 수정·삭제·이름 변경하지 않는다.

- Failure evidence SHA-256: `81569b41b05ccd42f17b1b3e9d71164ddfc4f198dd3bae1c561ddc5616d84d57`
- Approval consumption SHA-256: `b56605b1922781cdcece4f2ac86053728b4a1f6779ca72c23b73f5d299a653bf`

이 Run은 성공 결과, resume source, evaluation source 또는 publication artifact로 사용할 수 없다. 기존 Approval도 재사용할 수 없다. 향후 실행은 retry/resume가 아니라 새 immutable commit, 새 Run ID, 새 single-use Approval과 fresh seed 17 step 0 시작을 요구하며 현재 상태는 `awaiting_separate_approval`이다.

## 영향

- Candidate A Full 공식 internal baseline: 불변
- Candidate B Quick/Full Evaluation: 미실행
- Candidate B 공식 결과: 없음
- Dataset·split·tokenizer·packing·model·budget·evaluation 계약: 불변
- Gate 상태와 Foundation Model Roadmap: 불변

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | 첫 Candidate B 단일 실행의 실패 원인·소비 승인·미보존 결과를 영구 기록 |
