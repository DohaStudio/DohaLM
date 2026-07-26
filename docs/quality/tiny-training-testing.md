# DohaLM-Tiny 실규모 학습 테스트

- 문서 상태: `review`
- 마지막 검토일: 2026-07-24

## 1. 테스트 범위

[확정] synthetic token만 사용해 sampler state, cosine scheduler 후보, batch probe, throughput, CUDA memory, 실제 Tiny checkpoint/resume와 제한 overfit을 검증했다. 실제 tokenizer·corpus·사전학습 품질은 대상이 아니다.

## 2. 자동 테스트

- 신규 테스트 파일: `test_sampler_state.py`, `test_tiny_training_validation.py`, `test_training_memory_probe.py`, `test_training_throughput.py`, `test_training_resume_continuity.py`
- [확정] 신규 테스트 38개가 통과했다.
- [확정] 기존 464개를 포함해 전체 `502 passed in 24.84s`를 확인했다.
- [확정] mocked OOM 뒤 다음 후보 계속, dataset/seed/permutation mismatch, warmup/cosine/min LR, 0분모, CUDA reset/synchronize 호출을 포함한다.

## 3. 실제 GPU 검증

| 검증 | 결과 |
|---|---|
| Candidate A/B/C 1-step | 모두 `passed`, OOM 0 |
| Tiny 10-step FP16 AMP | finite, step 5→10 resume 성공 |
| checkpoint inspection | 5·10 및 50·100 step bundle checksum 통과 |
| sampler continuity | state·다음 batch fingerprint 일치 |
| uninterrupted 비교 | model checksum·logits·loss bitwise 동일 |
| repeated-pattern overfit | 100-step loss 명확히 감소, NaN/Inf 0 |

## 4. 해석 제한

- [확정] VRAM·처리량은 Windows 11, PyTorch 2.7.1+cu118, RTX 3060 Ti 8GB의 현재 짧은 실행 실측이다.
- [검증 필요] 긴 실행, 다른 driver·PyTorch 조합, 실제 corpus I/O에서는 결과가 달라질 수 있다.
- [확정] cosine scheduler, LR, warmup, min LR와 batch는 후보이며 운영 승인값이 아니다.
- [확정] Gate 6은 2026-07-24 사용자 승인으로 `passed`다. 이 합성 검증과 별개인 실제 64문서 Tiny Overfit 증거를 사용자 승인해 2026-07-27 Gate 7도 `passed`다.
