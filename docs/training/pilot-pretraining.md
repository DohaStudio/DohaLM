# DohaLM 학생용 Pilot Pretraining

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-24 |
| 선행 문서 | [사전학습 계획](./pretraining-plan.md), [Pilot 준비 검증](./pilot-pretraining-readiness.md), [체크포인트와 재개](./checkpoint-and-resume.md) |
| 후속 문서 | 실제 Pilot 실행 기록, Gate 7 검토 |
| 구현 전 필수 여부 | 예 |

## 2. 범위와 상태

- [확정] 이 기능은 학생용·학습용 로컬 Pilot이며 최종 사전학습이나 공개 모델 제작이 아니다.
- [확정] `DohaLM-Tiny`와 기존 `Trainer`, `CheckpointManager`를 연결하고 optimizer step은 최대 100으로 제한한다.
- [확정] Stage A의 코퍼스·tokenization·packing·validation·checkpoint/resume·greedy generation 코드와 합성 회귀 테스트를 구현했다.
- [검증 필요] 사용자 지정 한국어 development corpus를 사용하는 Stage B 실제 Pilot은 실행 전 입력·권리·출력 경로 사전 보고와 사용자 확인이 필요하다.
- [확정] 데이터 재배포와 모델 공개는 허용되지 않았고 Gate 3·7 상태를 자동 변경하지 않는다.

## 3. 실행 흐름

`명시적 corpus → 엄격한 UTF-8/NFC 검사 → SentencePiece 16,000 호환성 검사 → SHA-256 split → tokenization → 256-token packing → train/validation DataLoader → DohaLM-Tiny → checkpoint/resume → 검증·생성`

기본 후보값은 micro-batch 2, gradient accumulation 4, effective batch 8, FP16 AMP, cosine scheduler, validation 10-step, checkpoint 25-step, 최대 100-step이다. [가정] 이 값은 Candidate B 시작 후보이며 운영 확정값이 아니다.

## 4. Validation과 지표

- [확정] validation은 별도 DataLoader, `model.eval()`, `torch.no_grad()`를 사용하며 optimizer·scaler·train sampler를 변경하지 않는다.
- [확정] loss, overflow-safe perplexity, target token, sequence, 평가 시간과 step을 기록한다.
- [확정] 학습 metric은 loss, learning rate, gradient norm, token 수, tokens/sec, step time, CUDA peak allocated/reserved를 포함한다.
- [검증 필요] 실제 RTX 3060 Ti 8GB Pilot의 처리량·VRAM·열·총 실행 시간은 Stage B에서 측정한다.

## 5. Checkpoint와 재개

- [확정] 기존 원자적 checkpoint bundle을 사용한다.
- [확정] train/validation token artifact, corpus manifest, split·packing manifest, tokenizer model의 SHA-256을 결합한 계보 fingerprint가 다르면 resume를 차단한다.
- [확정] `local_experiment_only=true`, `publish_allowed=false`, `redistribution_allowed=false`, `model_release_allowed=false`를 checkpoint metadata에 기록한다.
- [검증 필요] 실제 100-step Pilot에서는 25·50·75·100 checkpoint와 50-step 재개 연속성을 확인한다. 시간이 과도하면 50-step에서 중단하고 이유를 기록한다.

## 6. CLI

```powershell
python -m scripts.training.prepare_pilot_corpus --help
python -m scripts.training.run_pilot_pretraining --config configs/pilot-pretrain.yaml --steps 100 --device cuda --use-amp --json
python -m scripts.training.evaluate_pilot_checkpoint --checkpoint "<저장소 상대 checkpoint>" --json
python -m scripts.training.generate_from_checkpoint --checkpoint "<저장소 상대 checkpoint>" --prompt "안녕하세요" --max-new-tokens 32 --json
```

- [확정] 실제 설정 `configs/pilot-pretrain.yaml`, tokenized corpus, experiment, checkpoint와 생성 결과는 Git 제외 경로에만 둔다.
- [확정] 생성 품질은 자동 성공 판정하지 않는다.
- [제외] SFT, RLHF, 분산·멀티 GPU, API, Frontend, 장시간 학습과 공개 배포는 이 단계 범위가 아니다.
