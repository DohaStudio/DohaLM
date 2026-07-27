# Candidate B 실행 Backend

- 문서 상태: `review`
- 마지막 검토일: 2026-07-28
- 실행 허용: `false`
- 관련 문서: [Candidate B 설계](./candidate-b-design.md), [실행 승인 계약](./candidate-b-execution-approval.md), [Checkpoint 정책](./candidate-b-checkpoint-policy.md), [최종 Readiness](./candidate-b-final-readiness.md)

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

Checkpoint 이름은 canonical 양의 정수로 파싱하고 숫자로 정렬한다. Directory listing 순서는 무시하며 invalid name, missing, duplicate, unexpected, final missing과 directory/metadata step 불일치를 별도 fail-closed code로 진단한다. 각 bundle의 checksum과 내부 metadata 검증을 모두 통과한 뒤에만 성공 output을 atomic publish한다.

Checkpoint evidence 생성 뒤 validator 또는 publish 직전 실패가 발생하면 staging을 삭제하지 않고 외부 `analysis/training/candidate-b/quarantine/<run-id>`로 격리한다. Quarantine에는 validation·failure·policy·checksum evidence를 남기며 resume·evaluation·publication·approval reuse를 모두 차단한다. 첫 checkpoint 이전 빈 staging만 안전하게 정리한다.

## 현재 상태

첫 단일 실행은 immutable commit `bdcf85d4...86b1b`에서 12,208 step까지 도달했지만 문자열 checkpoint 정렬 버그로 실패했고 기존 cleanup이 staging을 제거했다. 해당 Run과 소비된 Approval은 재사용할 수 없다. Numeric validator와 향후 실패 quarantine 정책은 구현됐지만 새 실행은 승인되지 않아 `execution_allowed: false`다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | Checkpoint numeric ordering·세부 진단과 post-checkpoint quarantine 보존 정책 구현 |
| 2026-07-28 | Candidate B 전용 resolver·scope·Git·approval·probe·monitor·runner orchestration 구현 |
