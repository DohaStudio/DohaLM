# DohaLM v0.3 의미 보존형 Short-Answer Dataset

## 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-08-02 |
| Dataset ID | `DOHALM-V0.3-SHORT-ANSWER-DATASET-20260802-0001` |
| 선행 Dataset | [v0.2 Sidecar·Sampling Dataset](./dohalm-v0.2-sidecar-sampling.md) |

## 목적과 범위

[확정] v0.1·v0.2 평가에서 확인된 낮은 EOS와 높은 반복·불완결 문제를 장문 학습 답변의 길이 분포 문제로 보고, 원문 의미를 보존한 별도 short/medium variant를 Train에 추가한다. Source Train 10,374행과 Validation 1,287행은 수정·삭제·이동하지 않는다.

[제외] Tokenization, QLoRA, optimizer step, checkpoint 생성과 기존 adapter 재학습은 수행하지 않는다.

## 생성 정책

[확정] 우선 경로는 extractive-first다. 질문 용어와 겹치는 문장, 결론 문장, 수치·고유명사를 포함한 문장을 우선하되 원문 문장과 순서를 보존한다. 문장 중간 truncation과 새 사실 추가는 허용하지 않는다.

- Short: 80~180 Qwen tokenizer token
- Medium: 181~320 token
- 원본당 short/medium variant 각각 최대 1개
- Constrained abstractive: `review_only`; 자동 합격 금지
- Validation: Source bytes 그대로 유지

생성 Prompt와 정책은 [설정](../../configs/data/dohalm-v0.3-short-answer.yaml)에서 버전 관리한다. 자동 생성은 `do_sample=false`, seed 42이며 실제 생성 payload는 deterministic extractive 결과다.

## 의미·품질 검증

[확정] 고정 로컬 `Qwen/Qwen2.5-1.5B-Instruct` revision `989aa7980e4cf806f80c7fef2b1adb7bc71aa306`의 last-hidden mean cosine을 의미 유사도 경로로 사용한다. Model·tokenizer SHA-256과 방법을 Manifest에 기록하고 threshold 0.85를 적용한다.

자동 합격은 다음을 모두 만족해야 한다.

- token 길이 범위와 `completion_score=1.0`
- strong repetition 없음
- semantic similarity 0.85 이상
- candidate 수치·고유명사가 원문 집합에 포함
- contradiction 및 새 사실 위험 없음
- review 사유 없음

4/5-gram excess는 참고 통계로 기록하며 한국어 조사·상용 표현만으로 자동 탈락시키지 않는다. 불확실한 후보와 abstractive 후보는 원문 없는 Review Queue로 분리한다.

## Dry Run과 Fail Closed

전체 생성 전 category별 20건, 10개 category, 총 200건을 평가한다.

```yaml
semantic_pass_rate: ">= 0.90"
completion_pass_rate: ">= 0.95"
strong_repetition_rate: "<= 0.02"
numeric_mismatch_rate: 0
entity_mismatch_rate: 0
```

기준 미달, Source checksum 변경, model snapshot 누락, cross-split duplicate, lineage 누락, checksum·reload 실패 또는 output identity 충돌 시 게시하지 않는다.

## Schema와 Artifact

학습 JSONL은 `instruction/input/output/system`을 유지한다. 품질·lineage는 별도 sidecar에 저장하며 질문·답변·token sequence를 포함하지 않는다.

최종 외부 package:

- `train.jsonl`, `validation.jsonl`
- `quality-sidecar.jsonl`, `lineage.jsonl`, `review-queue.jsonl`
- `generation-policy.yaml`, `manifest.yaml`, `statistics.json`
- `checksums.sha256`

final과 명시적 `.staging`·`.failed` identity가 존재하면 덮어쓰지 않는다. 같은 부모의 exclusive staging에서 fsync, checksum, reload 후 atomic no-replace로 한 번만 게시한다. Dataset은 Git에 추가하지 않는다.

## 현재 상태

```yaml
policy: implemented_pending_validation
dry_run: not_started
v03_dataset: not_created
tokenization_started: false
training_started: false
optimizer_steps: 0
```

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-02 | v0.3 의미 보존형 short-answer 생성·품질·writer 계약 초안 작성 |
