# Candidate B Full Evaluation 계약 수정

- 문서 상태: `implemented`
- 마지막 검토일: 2026-07-28
- 작업 범위: Evaluation Framework 계약 수정과 기존 checkpoint evaluation-only 재평가
- 학습 작업: `forbidden`

## 확인된 사실

Candidate B Run `FULL-PRETRAIN-CANDIDATE-B-20260728-0002`는 immutable training commit
`4c2eced3bf70551fbf7bc8ebde6666062584d92b`에서 정확히 한 번 실행됐다. 12,208 optimizer step과
25,001,984 scheduled token을 완료했고 checkpoint 4,883, 9,766, 12,208의 checksum 검증이 통과했다.
Candidate B Final Quick `candidate-b-final-quick-20260728-01`도 완료됐다. 이번 수정은 학습, optimizer,
backward, gradient, checkpoint 갱신 또는 Approval 재사용을 포함하지 않는다.

## 보존하는 실패 evidence

| Evaluation ID | Failure | 처리 |
|---|---|---|
| `candidate-b-final-full-20260728-01` | `QUICK_REFERENCE_INVALID` | 영구 보존 |
| `candidate-b-final-full-20260728-02` | `QUICK_REFERENCE_INCOMPARABLE` | 영구 보존 |

실패 artifact를 삭제하거나 성공으로 덮어쓰지 않는다. 수정 병합 후에는 새 ID
`candidate-b-final-full-20260728-03`을 사용한다.

## Root cause

기존 Full validator는 Candidate A Final Quick artifact ID를 하드코딩했다. 동시에 현재 Full target과
같은 평가 identity를 요구해 Candidate B same-artifact Quick를 직접 참조할 수 없었다. Candidate A 공식
결과에 기록된 historical prompt fingerprint는 현재 Git prompt fingerprint와 다르며, historical prompt
본문 snapshot은 확인되지 않았다.

## 수정 계약

Full의 Quick reference는 Full target과 같은 `artifact_id`, artifact identity, checkpoint step, model,
tokenizer, dataset lineage와 유효한 Quick result fingerprint를 가져야 한다. Candidate A Quick는 Candidate B
Full의 직접 Quick reference가 될 수 없다. Candidate A와 Candidate B의 공식 비교는 각각 완료된 Full 결과
사이에서 별도로 수행한다.

Prompt identity는 teacher-forced와 generation을 분리한다. Loss, perplexity, Top-k, category, EOS target,
position과 stability는 prompt mismatch만으로 폐기하지 않는다. Synthetic generation 비교만
`GENERATION_PROMPT_INCOMPARABLE`로 표시하며 전체 상태는
`completed_with_incomparable_generation_reference`가 될 수 있다.

## Fail-closed 코드

- `QUICK_REFERENCE_MISSING`
- `QUICK_REFERENCE_ARTIFACT_MISMATCH`
- `QUICK_REFERENCE_CHECKPOINT_MISMATCH`
- `QUICK_REFERENCE_MODEL_MISMATCH`
- `QUICK_REFERENCE_TOKENIZER_MISMATCH`
- `QUICK_REFERENCE_DATASET_MISMATCH`
- `QUICK_REFERENCE_PROFILE_INVALID`
- `QUICK_REFERENCE_RESULT_FINGERPRINT_INVALID`
- `GENERATION_PROMPT_INCOMPARABLE`
- `BASELINE_REFERENCE_INVALID`

## Historical prompt 상태

- Candidate A historical prompt: `historical_prompt_unverified`
- 현재 repository prompt: `current_prompt_only`
- Candidate B Final Quick: 현재 repository prompt와 일치
- Candidate B Full generation: 같은 현재 prompt로 실행 완료

Historical snapshot을 추정하거나 재구성하지 않는다. Candidate A 기존 result fingerprint는 변경하지 않는다.

## 완료 결과

수정 PR #33은 develop commit `79a88b00ae02325119fd7b04f9d1a90f4abaa27d`로 squash merge됐다.
Evaluation ID `candidate-b-final-full-20260728-03`은 same-artifact Quick reference 검증을 통과해 완료됐고
기존 failure `-01`/`-02`는 보존됐다. 결과는 [Candidate B Full](./candidate-b-final-full-result.md)을 따른다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | Candidate B same-artifact Quick, Full baseline 분리와 prompt comparability 계약 작성 |
| 2026-07-28 | PR #33 병합, Candidate B Full evaluation-only 완료와 기존 failure 보존 확인 |
