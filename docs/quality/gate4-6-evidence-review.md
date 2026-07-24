# Gate 4·5·6 Evidence 검토

- 문서 상태: `review`
- 마지막 검토일: 2026-07-24
- 선행 문서: [모델 구성요소 테스트](./model-component-testing.md), [모델 통합 테스트](./model-integration-testing.md), [Tiny 학습 테스트](./tiny-training-testing.md), [Tiny 실규모 검증](../training/tiny-training-validation.md)
- 후속 문서: [개발 로드맵](./development-roadmap.md), [Pilot Pretraining 준비 검증](../training/pilot-pretraining-readiness.md)
- 구현 전 필수 여부: Gate 상태 사용자 검토 전 필수

## 1. 목적과 경계

- [확정] `src/training/gate_evidence.py`는 Git에서 제외된 Tiny validation·overfit·batch probe 산출물과 전체 테스트 결과를 읽어 Gate 4·5·6 검토 증거를 생성한다.
- [확정] 검증기는 artifact 존재, SHA-256 checkpoint 무결성, Tiny config, parameter count, device·dtype, finite metric, resume·sampler 연속성과 합성 source 경계를 함께 검사한다.
- [확정] 결과가 `eligible_for_user_approval`이어도 Gate 상태를 자동으로 변경하지 않는다.
- [제외] 이 문서는 실제 tokenizer·승인 corpus 학습, 한국어 생성 품질 또는 장시간 안정성을 증명하지 않는다.

## 2. 검토 입력

| 입력 | Run ID | 용도 |
|---|---|---|
| Tiny validation | `tiny-20260724T120703513334Z-da9eacf685` | CUDA FP16 10-step, checkpoint 5·10, bitwise resume, VRAM·처리량 |
| Tiny overfit | `tiny-20260724T120731577061Z-cdb24aef18` | 반복 합성 pattern 100-step loss 감소 |
| Batch probe | `probe-20260724T120643503137Z-a75fad7b2e` | 3개 micro-batch·accumulation 후보의 finite update와 OOM 0 |
| 전체 테스트 | 검증기 실행 시 재실행 | 514개 통과와 필수 test contract 존재 |

- [확정] 입력과 출력은 `tests/output/` 아래 Git 제외 경로에 있으며 절대 로컬 경로를 bundle에 기록하지 않는다.
- [확정] checkpoint의 `checksums.json`을 다시 계산하며 불일치 시 해당 Gate를 차단한다.

## 3. 검증 및 승인 결과

| Gate | 승인 전 상태 | 승인 결과 | 주요 근거 |
|---|---|---|---|
| Gate 4 | `planned` | `passed` | 구성요소 shape·causal mask·backward·dtype/device·tying·count·CPU/CUDA test와 사용자 승인 |
| Gate 5 | `planned` | `passed` | Tiny forward·shifted loss·greedy generation·state round-trip·16,889,856·finite CPU/CUDA와 사용자 승인 |
| Gate 6 | `planned` | `passed` | CUDA FP16 10-step·AMP·accumulation·clipping·checkpoint/resume·RNG/sampler·VRAM·처리량·overfit과 사용자 승인 |

Evidence bundle:

- Run ID: `gate-20260724-review-v3`
- Evidence fingerprint: `sha256:4260844cd4c48b385e60c8cd023504cbc6897a8914dfab9ec8dc0f7b746156be`
- Status proposal fingerprint: `sha256:f59573ffc791833247e560da283eb684c4c97246144fea115df16d363b3798c6`
- [확정] 위 proposal artifact의 `approved_by`와 `approved_at`은 제안 생성 시점의 불변 값 `null`이며, 실제 승인 기록은 아래 사용자 승인 metadata와 [개발 로드맵](./development-roadmap.md)에 별도로 보존한다.
- [확정] 승인자: `DDORINY`
- [확정] 승인일: 2026-07-24

## 4. Gate 6 요약 수치

| 항목 | 실측 |
|---|---:|
| Parameter count | 16,889,856 |
| Tiny validation loss | 254.352510 → 83.265637 |
| Overfit loss | 249.916672 → 1.7976e-7 |
| Peak allocated VRAM | 634,336,768 B |
| Peak reserved VRAM | 679,477,248 B |
| Warm-up 제외 처리량 | 9,144.53 tokens/s |
| Validation optimizer steps | 10 |
| Overfit optimizer steps | 100 |

- [확정] 위 수치는 해당 합성 run의 실측값이며 실제 corpus pilot의 자원·속도 예측값으로 확정하지 않는다.

## 5. Bundle 계약

`tests/output/gate-evidence/<run-id>/`에는 다음 파일을 생성한다.

- `gate4-evidence.json`
- `gate5-evidence.json`
- `gate6-evidence.json`
- `pilot-readiness.json`
- `evidence-checksums.json`
- `status-proposal.json`
- `review-checklist.md`

- [확정] `status-proposal.json`은 현재 상태, 제안 상태, eligibility, evidence fingerprint, 차단 사유와 사용자 승인 metadata를 분리한다.
- [확정] `evidence-checksums.json`은 proposal을 포함한 bundle 파일의 SHA-256을 기록한다.

## 6. 실행

```powershell
python -m scripts.training.validate_gate_evidence `
  --tiny-validation tests/output/tiny-validation/<run-id> `
  --tiny-overfit tests/output/tiny-overfit/<run-id> `
  --batch-probe tests/output/tiny-batch-probe/<run-id> `
  --output tests/output/gate-evidence `
  --json

python -m scripts.training.inspect_gate_proposal `
  --proposal tests/output/gate-evidence/<run-id>/status-proposal.json `
  --json
```

## 7. 사용자 승인 결과와 남은 검토

- [확정] Gate 4·5·6은 2026-07-24 사용자 승인으로 `passed` 처리했다.
- [검증 필요] 합성 evidence의 적용 범위와 남은 실제 데이터 검증 경계 확인
- [검증 필요] Gate 7 정책과 Pilot 진입 Gate 정의 확정
- [확정] Gate 3·7은 `planned`, tokenizer·corpus·license·PII 승인은 `pending`이다.

## 8. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-24 | [확정] `DDORINY` 승인과 지정 fingerprint·514개 테스트를 근거로 Gate 4·5·6 `passed`를 기록함 |
