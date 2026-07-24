# DohaLM Trainer Foundation 테스트

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-24 |
| 선행 문서 | [Trainer Foundation](../training/trainer-foundation.md), [Checkpoint·Resume](../training/checkpoint-and-resume.md), [테스트 전략](./test-strategy.md) |
| 후속 문서·작업 | Gate 6 승인 기록, Gate 7 사용자 검토, 운영 데이터·Tiny overfit 검증 |
| 구현 전 필수 여부 | Gate 6 검토 전 예 |

## 2. 자동 테스트 결과

| 범주 | 검증 | 결과 |
|---|---|---|
| Config | batch·effective batch·AMP·경로·fingerprint·invalid matrix | `pass` |
| Dataset·Collator | 결정론·BOS/EOS·반복 pattern·padding·mask·ignore·context | `pass` |
| DataLoader | 고정 seed first batch, empty 차단 | `pass` |
| Optimizer | decay/no-decay, tying 중복 제외, frozen·empty | `pass` |
| Scheduler | step 0, warmup, decay, max, resume LR | `pass` |
| Trainer | update, train mode, finite, metric, state rollback | `pass` |
| Accumulation | 1·2 step, update 수, loss scaling, 큰 batch 근사 | `pass` |
| Clipping | unscale 후 clipping, 전·후 norm, non-finite 차단 | `pass` |
| Checkpoint | 8 files, atomic publish, overwrite, checksum, 비노출 | `pass` |
| Resume | model·training·dataset·tokenizer mismatch, RNG, tying, 연속성 | `pass` |
| AMP | CPU 차단, CUDA FP16 update·scaler checkpoint/resume | `pass` |
| Overfit | 고정 반복 batch loss 감소와 seed 결정론 | `pass` |
| CLI | training, inspection, resume JSON와 concise error | `pass` |

- [확정] Phase 5 신규 99개와 기존 365개를 합친 전체 464개 테스트가 통과했다.
- [확정] 실제 데이터와 tokenizer artifact는 테스트에 사용하지 않았다.

## 3. 실제 Smoke 결과

| 환경 | 실행 | 결과 |
|---|---|---|
| CPU FP32 | batch 2, sequence 8, checkpoint-5→10 | step·LR·checksum·RNG·tying resume 통과 |
| CUDA FP16 AMP | batch 2, sequence 16, checkpoint-5→10 | finite loss·gradient·scaler resume 통과 |
| CPU overfit 준비 | 반복 batch, 50 optimizer step | 초기 loss > 최종 loss |

CUDA resume 구간 최대 관측값은 allocated `18,574,336 bytes`(`17.714 MiB`), reserved `23,068,672 bytes`(`22.0 MiB`)다. 이는 small synthetic config의 smoke 관측값이며 DohaLM-Tiny 운영 학습 VRAM으로 확대하지 않는다.

## 4. 제한과 Gate

- [가정] accumulation 큰 batch 비교 허용 오차는 float32 reduction 순서 차이를 고려해 `atol=3e-4`, `rtol=1e-4`다.
- [제외] 실제 corpus 수렴, validation loss, 생성 품질, 장시간 안정성과 OOM 경계는 검증하지 않았다.
- [확정] Gate 6은 통합 evidence와 2026-07-24 사용자 승인으로 `passed`다. Synthetic overfit은 Gate 7 통과 근거가 아니며 Gate 3·7은 `planned`다.

## 5. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-24 | [확정] 신규 99개·전체 464개와 CPU·CUDA·overfit smoke 결과를 기록함 |
