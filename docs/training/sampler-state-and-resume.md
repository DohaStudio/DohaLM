# Sampler State와 학습 재개

- 문서 상태: `review`
- 마지막 검토일: 2026-07-24

## 1. 목적

[확정] Phase 5의 DataLoader fast-forward 후보를 보완해 다음 batch 위치를 명시적으로 저장·복원하는 `StatefulBatchSampler`를 구현했다. 합성 Tiny 검증 범위이며 실제 corpus sampler 확정은 아니다.

## 2. 상태 계약

| 필드 | 의미 |
|---|---|
| `epoch` | 현재 permutation epoch |
| `sample_offset` | 다음 record의 permutation offset |
| `permutation_seed` | epoch permutation 기준 seed |
| `permutation_fingerprint` | dataset·epoch·seed·index 순서 SHA-256 |
| `batches_yielded` | 누적 batch 수 |
| `records_yielded` | 누적 record 수 |
| `dataset_fingerprint` | 입력 dataset identity |

- [확정] `num_workers=0`을 Windows 우선 검증값으로 사용했다.
- [확정] dataset fingerprint, seed, permutation fingerprint, offset 범위가 다르면 resume를 차단한다.
- [확정] checkpoint의 `training-state.json` 안에 sampler state를 포함하며 별도 `sampler-state.json`은 검증 run 요약 사본이다.

## 3. 재개 순서

1. checkpoint 8-file checksum과 config·dataset·synthetic tokenizer fingerprint를 검증한다.
2. model, optimizer, scheduler, GradScaler와 Python·PyTorch CPU/CUDA RNG를 복원한다.
3. sampler state를 새 DataLoader의 batch sampler에 적용한다.
4. 다음 batch fingerprint를 중단 직전 예상값과 비교한다.
5. optimizer/global/scheduler step과 weight tying을 확인하고 학습을 재개한다.

## 4. 실제 연속성 결과

- [확정] Tiny 5→10 step resume에서 sampler state와 다음 batch fingerprint가 일치했다.
- [확정] resumed/uninterrupted 실행의 최종 model checksum, logits와 loss가 bitwise 동일했다.
- [확정] 50→100 step repeated-pattern overfit에서도 sampler 다음 batch 연속성을 확인했다.
- [검증 필요] `num_workers>0`, 실제 streaming dataset, distributed sampler는 현재 범위 밖이다.

## 5. 실패 조건

dataset·seed·permutation fingerprint 불일치, 유효하지 않은 offset/count, sampler 없는 DataLoader에 state 적용, checkpoint checksum·config 불일치는 traceback 없는 명시적 오류로 종료한다. 자동 seed 변경이나 위치 추정 fallback은 하지 않는다.

## 6. Gate 경계

- [확정] 명시적 sampler state 구현은 Gate 6 승인과 실제 데이터 재현성 승인을 자동으로 의미하지 않는다.
- [확정] Gate 3~7은 `planned`를 유지한다.
