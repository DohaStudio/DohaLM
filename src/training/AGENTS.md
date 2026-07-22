# 학습 영역 작업 규칙

루트 `AGENTS.md`, [사전학습 계획](../../docs/training/pretraining-plan.md), [GPU 메모리 전략](../../docs/training/gpu-memory-strategy.md), [실험 관리](../../docs/training/experiment-management.md)를 함께 적용한다.

- 단일 `RTX 3060 Ti 8GB` 환경을 기준으로 설계하고 검증한다.
- 긴 학습 전에 최소 step smoke test를 수행한다.
- 단일 배치 overfit과 극소량 데이터 overfit을 본 학습보다 먼저 검증한다.
- FP16 autocast와 GradScaler 순서, skipped step과 수치 안정성을 검증한다.
- Gradient Accumulation의 loss normalization과 optimizer update 주기를 검증한다.
- Gradient clipping은 AMP unscale 이후 의도된 시점에 적용하고 실제 norm을 기록한다.
- NaN·Inf를 loss, gradient와 주요 상태에서 감지하고 실패를 숨기지 않는다.
- checkpoint의 모델·optimizer·scheduler·AMP scaler·step·RNG·sampler 등 필수 상태를 저장하고 복원한다.
- 중단 없는 기준 실행과 resume 실행의 연속성을 검증한다.
- peak allocated/reserved VRAM, tokens/sec와 step time을 기록한다.
- 실패 실험과 로그를 삭제하지 않고 실패 원인·환경·설정·마지막 정상 checkpoint를 보존한다.
- 실험 ID를 Git SHA, branch와 working tree 상태에 연결한다.
- 실제 적용된 resolved config를 저장한다.
- 데이터·전처리·split·토크나이저 fingerprint를 실험과 checkpoint에 연결한다.
- 사용자의 명시적 승인 없이 장시간 학습을 자동 시작하지 않는다.
- OOM 발생 시 [GPU 메모리 전략](../../docs/training/gpu-memory-strategy.md)의 순서대로 한 번에 하나의 변수를 조정하고 전후 값을 기록한다.
- loss가 한 번 감소했다는 사실만으로 학습 성공이나 완료를 판단하지 않는다.
