# DohaLM-Tiny 실규모 합성 학습 검증

- 문서 상태: `review`
- 마지막 검토일: 2026-07-24

## 1. 목적과 범위

- [확정] ADR-002의 실제 `DohaLM-Tiny` 16,889,856 파라미터를 단일 `RTX 3060 Ti 8GB`에서 합성 token으로 제한 검증했다.
- [확정] vocabulary 16,000, context 256, layer 6, hidden 384, head 6, FFN 1,536과 weight tying을 사용했다.
- [제외] 실제 tokenizer artifact, AI Hub 데이터, 승인 corpus, 장시간 사전학습과 한국어 품질 평가는 사용하거나 수행하지 않았다.
- [확정] Gate 3~7은 사용자 승인 전까지 `planned`다.

## 2. 구현 계약

`src/training/tiny_validation.py`는 `repeated_pattern`과 `deterministic_random` 합성 stream, stateful DataLoader, cosine scheduler 후보, 제한 학습, checkpoint/resume 비교와 검증 산출물을 연결한다.

- [확정] token ID는 `0..15,999`, PAD 0, BOS 2, EOS 3 계약을 유지한다.
- [확정] labels는 input IDs와 같고 shifted loss는 모델 내부에서 한 번만 적용한다.
- [확정] 원문 문자열과 실제 tokenizer는 존재하지 않는다.
- [가정] bounded 검증 후보는 LR `3e-4`, warmup 1 step, cosine minimum ratio `0.1`이다. 운영 확정값이 아니다.

## 3. Batch 후보 실측

실행 산출물: Git 제외 `tests/output/tiny-batch-probe/probe-20260724T120643503137Z-a75fad7b2e/`

| 후보 | S | micro | accumulation | effective | 상태 | peak allocated | peak reserved | tokens/sec |
|---|---:|---:|---:|---:|---|---:|---:|---:|
| A | 256 | 1 | 8 | 8 | `passed` | 368,237,568 B | 434,110,464 B | 2,922.26 |
| B | 256 | 2 | 4 | 8 | `passed` | 389,331,968 B | 455,081,984 B | 12,072.47 |
| C | 128 | 4 | 2 | 8 | `passed` | 379,710,464 B | 463,470,592 B | 11,409.73 |

- [확정] 세 후보 모두 OOM 0건, finite loss·gradient와 optimizer step을 확인했다.
- [검증 필요] 1-step 처리량은 warm-up·반복 측정이 부족하므로 운영 batch 선택의 단독 근거로 사용하지 않는다.

## 4. 10-step CUDA FP16 smoke

실행 산출물: Git 제외 `tests/output/tiny-validation/tiny-20260724T120703513334Z-da9eacf685/`

| 항목 | 결과 |
|---|---:|
| 초기 loss | 254.352510 |
| step 5 loss | 163.670940 |
| step 10 loss | 83.265637 |
| warmup 제외 tokens/sec | 9,144.53 |
| 평균 optimizer step time | 0.223959초 |
| p50 / p95 step time | 0.222373초 / 0.236385초 |
| peak allocated / reserved | 634,336,768 B / 679,477,248 B |
| step 후 allocated / reserved | 429,252,608 B / 679,477,248 B |
| model parameter bytes | 67,559,424 B |
| optimizer state bytes | 135,119,152 B |

- [확정] step 5 checkpoint checksum 검증 후 새 Trainer에서 step 10까지 재개했다.
- [확정] 중단 없는 10-step 기준과 model parameter checksum, logits, final loss가 bitwise 동일했다.
- [확정] sampler 다음 batch fingerprint, scheduler step, scaler state와 weight tying이 유지됐다.

## 5. 제한 overfit

실행 산출물: Git 제외 `tests/output/tiny-overfit/tiny-20260724T120731577061Z-cdb24aef18/`

- [확정] `repeated_pattern`, sequence 64, micro-batch 1, 100 optimizer step을 실행했다.
- [확정] loss는 `249.916672 → 1.6888e-5(step 50) → 1.7976e-7(step 100)`로 감소했다.
- [확정] step 50 checkpoint에서 재개해 step 100까지 finite 상태와 sampler 연속성을 유지했다.
- [제외] 이 결과는 한국어 생성 품질, 일반화, 실제 corpus 학습 성공 또는 Gate 7 통과를 의미하지 않는다.

## 6. 산출물

각 validation run은 `run-summary.json`, `batch-probe.json`, `throughput.json`, `memory.json`, `training-metrics.jsonl`, `resume-validation.json`, `sampler-state.json`, `validation-manifest.json`과 `checkpoint-*`를 생성한다. 절대 로컬 경로와 원문은 기록하지 않는다.

## 7. 실행 명령

```powershell
python -m scripts.training.probe_tiny_batch_sizes --device cuda --dtype float16 --output tests/output/tiny-batch-probe --json
python -m scripts.training.run_tiny_validation --device cuda --dtype float16 --use-amp --steps 10 --save-step 5 --output tests/output/tiny-validation --json
python -m scripts.training.run_tiny_validation --mode overfit --device cuda --dtype float16 --use-amp --steps 100 --save-step 50 --output tests/output/tiny-overfit --json
python -m scripts.training.inspect_tiny_validation --run-dir tests/output/tiny-validation/<run-id> --json
```

## 8. 남은 검증

- [검증 필요] 실제 tokenizer·승인 corpus 연결
- [검증 필요] 운영 LR·warmup·cosine minimum ratio·batch 확정
- [검증 필요] 여러 반복 실행의 처리량 분산과 장시간 열·전력 안정성
- [검증 필요] 사용자 Gate 6·7 승인
