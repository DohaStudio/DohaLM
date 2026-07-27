# Candidate B 실행 Backend

- 문서 상태: `review`
- 마지막 검토일: 2026-07-28
- 실행 허용: `false`
- 관련 문서: [Candidate B 설계](./candidate-b-design.md), [실행 승인 계약](./candidate-b-execution-approval.md), [최종 Readiness](./candidate-b-final-readiness.md)

## 구조

- [확정] `src/training/candidate_b.py`는 scope·resolver·Git/upstream·approval·output probe·checkpoint metadata·readiness를 검증한다.
- [확정] `src/training/candidate_b_backend.py`는 CPU smoke, runtime monitor, single-use approval consumer와 향후 승인 후 Trainer orchestration을 제공한다.
- [확정] `scripts/training/run_candidate_b.py`는 `inspect`를 기본 모드로 하고 `resolve-config`, `validate`, `cpu-smoke`, `preflight`, `execute`를 분리한다.
- [확정] 기존 `Trainer`, `TrainingConfig`, `TokenizedJsonlDataset`, `CheckpointManager`, collator·dataloader, Candidate A atomic JSON/checksum 유틸리티를 재사용한다.
- [확정] Candidate A 실행 함수와 4,883-step 상수는 수정하지 않았다.

## Scope validation

Candidate ID `candidate-b`, stage `full_pretraining_candidate`, fresh seed 17, 25M requested token, 25,001,984 scheduled token, 12,208 step, micro batch 2·accumulation 4·context 256만 허용한다. Candidate A checkpoint/state, Resume, retry, extension, publication, Dataset·split·packing·tokenizer·model·evaluation 변경을 차단한다.

## Runner와 execute 경계

기본 `inspect`는 model·dataset·optimizer를 만들지 않는다. `execute`는 mode와 `--execute`가 모두 필요하며 resolved fingerprint, clean immutable Git/upstream, 실제 approved single-use manifest, output probe와 물리 preflight 중 하나라도 없으면 `CANDIDATE_B_EXECUTION_BLOCKED`로 종료한다.

승인 후 실행 경로도 Full Evaluation을 자동 실행하지 않고 예약 hook만 기록한다. Quick은 start/4,883/final, Full은 training 종료 후 별도 evaluation-only 단계다.

## Runtime·Checkpoint

Runtime monitor는 step/token, 5,400초 hard stop, 2GiB output, 10GiB/5GiB disk, 7GiB VRAM, 4GiB CPU RSS, NaN/Inf, AMP skip, loss·gradient spike를 차단한다. Checkpoint는 4,883/9,766/12,208만 허용하며 schema에는 model·optimizer·scheduler·scaler·step/token·sampler·RNG·fingerprint·Git·approval·run·checksum을 요구한다. `resume_allowed`는 false다.

## 현재 상태

Backend와 CPU 검증은 완료됐지만 실제 commit/upstream·물리 preflight·실행 승인이 없어 `execution_allowed: false`다. 이번 작업에서 `execute` 경로는 fail-closed 확인만 했고 Trainer 실행은 0건이다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | Candidate B 전용 resolver·scope·Git·approval·probe·monitor·runner orchestration 구현 |
