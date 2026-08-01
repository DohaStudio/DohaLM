# DohaLM v0.1 Decoding 최적화 평가

- 문서 상태: `review`
- 마지막 검토일: 2026-08-01
- 관련 정책: [ADR-008](../decisions/ADR-008-eos-generation-and-decoding-evaluation-policy.md), [DohaLM v0.1 독립 평가](./dohalm-v0.1-qlora-evaluation.md)

## 목적과 범위

[확정] 이 평가는 완료된 `checkpoint-1750`과 `final-adapter`의 weight를 변경하지 않고 greedy decoding 설정만 비교한다. 추가 학습, backward, optimizer step, checkpoint 변경, adapter merge 및 dataset·tokenization 변경은 허용하지 않는다.

[확정] Base 모델 수치는 `DOHALM-V0.1-EVAL-20260801-0001`의 immutable 결과를 기준선으로 재사용한다. 고정 prompt 80개와 선택 순서, reference, category, length bucket 및 prompt fingerprint도 변경하지 않는다.

## 공통 생성 계약

```yaml
do_sample: false
num_beams: 1
temperature: null
top_p: null
top_k: null
pad_token_id: 151643
eos_token_id: 151645
use_cache: true
```

[확정] tokenizer, model config, generation config와 명시적 override의 EOS ID가 일치하지 않으면 평가를 시작하지 않는다. EOS가 생성됐는데도 생성이 계속되는 경우 구현 오류로 처리한다.

## 단계적 Grid

1. Phase A: `repetition_penalty=1.05`, `no_repeat_ngram_size=0`에서 `max_new_tokens` 64/96/128/192/256 비교
2. Phase B: Phase A 상위 길이 2개에서 `repetition_penalty` 1.00/1.05/1.10/1.15/1.20 비교
3. Phase C: checkpoint 다양성을 보존한 Phase B 상위 3개 설정에서 `no_repeat_ngram_size` 0/3/4/5 비교
4. Phase D: 상위 3개 preset을 전체 80 prompt에서 두 번 실행하고 generated-token, metric, termination-reason fingerprint 일치를 검증

[확정] Character F1·ROUGE-L이 Base 이하이거나 empty output, special token 노출, repetition 또는 max-length 비율이 80%를 넘는 설정은 다음 단계로 진행하지 않는다. 최종 선택에서는 repetition 50% 초과를 hard blocker로 적용한다.

## 종료·반복·불완전 판정

- 종료 원인: `eos_token`, `max_new_tokens`, `other_stopping_criteria`, `generation_error`, `empty_output`
- 기존 비교 지표: 4-gram이 3회 이상 반복되는 legacy `repetition`
- 추가 지표: 문자·단어·문장·3-gram·4-gram·연속 구문·long loop
- 자동 incomplete: empty, max-length truncation 또는 문장 종결 부호 부재
- 의미적 incomplete와 factual error: 승인된 judge가 없으므로 자동 판정하지 않고 `not_assessed`로 기록

[확정] reference mismatch는 incomplete로 간주하지 않는다. 원문 prompt, reference, 생성문 및 token ID는 기본 artifact에 저장하지 않으며 stable hash만 기록한다.

## 선택과 배포 판정

최종 preset은 품질 점수만으로 선택하지 않는다. Base 이하 품질, 빈 출력, special token 노출 또는 repetition 50% 초과는 점수와 관계없이 선택할 수 없다.

```text
quality_score
= 0.45 × Character F1
+ 0.25 × ROUGE-L
+ 0.15 × EOS termination rate
- 0.10 × repetition rate
- 0.05 × incomplete rate
```

- `PASS`: Base 이상 품질, EOS ≥80%, repetition ≤15%, max hit ≤10%, incomplete ≤15%, deterministic
- `CONDITIONAL_PASS`: Base 이상 품질, EOS ≥70%, repetition ≤30%, max hit ≤20%, incomplete ≤25%, deterministic
- `NEEDS_MODEL_IMPROVEMENT`: decoding만으로 위 조건을 충족하지 못함
- `FAIL`: Base 이하 품질, 비결정성, adapter 활성화·EOS·artifact 무결성 실패

모든 목표를 충족하지 못하면 `deployment_ready=false`를 유지한다. 평가 결과가 나쁘다는 이유로 추가 학습을 자동 시작하지 않는다.

## 실행과 Artifact

공개 설정에는 로컬 절대경로를 기록하지 않는다. 실제 경로는 CLI 인자로만 전달한다.

```powershell
python -m scripts.evaluation.evaluate_dohalm_v01_decoding --help
```

외부 output에는 다음 파일을 atomic no-replace 방식으로 게시한다.

- `decoding-config.yaml`
- `grid-summary.json`
- `phase-a-results.json`
- `phase-b-results.json`
- `phase-c-results.json`
- `final-comparison.json`
- `inference-preset.yaml`
- `failure-analysis.json`
- `environment.json`
- `checksums.sha256`

평가 ID가 이미 존재하면 overwrite하거나 다음 번호를 자동 발급하지 않고 Fail Closed한다.

## 변경 이력

| 날짜 | 내용 |
|---|---|
| 2026-08-01 | DohaLM v0.1 decoding-only 단계적 grid, 종료·반복·불완전 판정과 배포 후보 선택 계약 작성 |
