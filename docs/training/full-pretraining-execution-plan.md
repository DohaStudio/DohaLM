# DohaLM-Tiny Full Pretraining Candidate A 실행 계획

- 문서 상태: `approved`
- 마지막 검토일: 2026-07-27
- 관련 문서: [사전학습 계획](./pretraining-plan.md), [Readiness](./full-pretraining-readiness.md), [승인 manifest](./full-pretraining-approval.manifest.yaml), [ADR-004](../decisions/ADR-004-data-governance.md), [ADR-005](../decisions/ADR-005-evaluation-and-experiment-policy.md)
- 공개용 config: [Candidate A example](../../configs/full-pretraining.example.yaml)

## 범위와 identity

Candidate A는 학생·비상업 연구용 로컬 실험이다. `AIHUB-71748/pilot-v2` Training 내부 train 92,948 records와 internal evaluation 4,799 records, `operating-16k-v2/unigram-16k`, DohaLM-Tiny만 사용한다. AI Hub 원래 Validation, benchmark, SFT, RLHF, Preference, label과 metadata는 사용하지 않는다.

## 승인된 Candidate A

| 항목 | 값 |
|---|---:|
| 목표 token | 10,000,000 |
| Scheduled 상한 | 10,000,384 |
| Optimizer step 상한 | 4,883 |
| Context / effective batch | 256 / 8 |
| Step당 scheduled token | 2,048 |
| Equivalent epoch | 약 0.140242223 |
| Planned / hard wall-clock | 1,800초 / 2,700초 |

어느 상한이든 먼저 도달하면 종료하며 자동 연장, Candidate B/C 전환, 추가 학습은 허용하지 않는다.

## Training config

DohaLM-Tiny를 seed 17로 새로 초기화한다. AdamW, learning rate `3e-4`, weight decay `0.1`, cosine scheduler, min LR ratio `0.1`, warmup 10, micro batch 2, accumulation 4, FP16 AMP, gradient clipping `1.0`, step별 JSONL logging을 사용한다. Config fingerprint는 `sha256:b1c6979fe681f6c69dec124f0dcce457ea1e26d511f285ee16eab1c185cea4f5`이다.

## Evaluation과 checkpoint

- Full internal evaluation은 시작과 종료에만 실행한다.
- Mid checkpoint는 2,442 step, Final checkpoint는 4,883 step이다.
- 최대 2개를 보존하고 자동 삭제하지 않는다.
- Final evaluation 결과가 final checkpoint를 가리키는 논리 best reference가 된다.

세부 정책은 [Evaluation](./full-pretraining-evaluation-policy.md), [Checkpoint·Retention](./full-pretraining-checkpoint-retention-policy.md), [초기화·Resume](./full-pretraining-initialization-resume-policy.md)를 따른다.

## Disk와 system safety

- Run output 최대 2GiB, 시작 free disk 최소 10GiB, 실행 중 최소 5GiB
- Peak reserved VRAM 최대 7GiB, CPU working set 최대 4GiB
- Windows 절전 방지, 재시작·업데이트 예약 없음, 전원 연결, 냉각·환기, NVIDIA/CUDA와 다른 GPU 작업 부재를 실행 직전에 확인
- GPU 온도 API가 없으면 `unavailable` 사유와 수동 확인을 기록

NaN/Inf, OOM, 모든 identity/fingerprint 불일치, 미승인 split, checkpoint/checksum/atomic/log/evaluation 실패, disk·output·wall-clock·VRAM·CPU 상한 위반은 즉시 중단한다. AMP skip 3회 연속, 이전 정상값 최대 100 step의 rolling 평균 대비 loss 또는 pre-clip gradient 4배 이상이 10 step 연속이면 중단한다. 자동 설정 변경·retry는 금지한다.

## Backend와 CLI

기본 동작은 inspection-only이며 `--dry-run`은 model·optimizer를 만들지 않는다. 실행 경로는 명시적 `--execute`와 최종 승인 모두를 요구한다. 실행 시작 시 외부 run 디렉터리에 single-use approval consumption을 atomic 기록하며 기존 Run ID/output 재사용을 차단한다. Pilot checkpoint는 거부하고, Full 내부 Resume는 별도 사용자 승인 없이는 거부한다.

이번 정책 확정 단계에서는 `--execute`를 호출하지 않았고 optimizer step과 GPU 학습은 0건이다.

## 성공·실패와 공개 경계

성공은 정확한 step/token 범위, start/final evaluation, 두 checkpoint, checksum과 필수 보고 산출물이 모두 충족된 경우에만 기록한다. 중단·실패 시 failure report를 남기고 자동 재시작하지 않는다. 공개와 재배포는 [공개 경계](./full-pretraining-publication-boundary.md)에 따라 계속 미승인이다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | [확정] Candidate A 정책과 fail-closed 실행 backend 계약 승인 |
