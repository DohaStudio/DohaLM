# DohaLM Checkpoint와 Resume 계약

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-24 |
| 선행 문서 | [Trainer Foundation](./trainer-foundation.md), [산출물 정책](../governance/artifact-and-configuration-policy.md), [실험 관리](./experiment-management.md) |
| 후속 문서·작업 | [Sampler와 재개](./sampler-state-and-resume.md), [Tiny 실규모 검증](./tiny-training-validation.md), Gate 6 검토, 운영 checkpoint schema·retention 결정 |
| 구현 전 필수 여부 | Resume 소비 전 예 |

## 2. Checkpoint 구조

```text
checkpoint-<step>/
├── model.pt
├── optimizer.pt
├── scheduler.pt
├── scaler.pt
├── training-state.json
├── config.json
├── manifest.json
└── checksums.json
```

- [확정] sibling staging 디렉터리에 전체 파일을 쓴 후 `os.replace`로 한 번에 게시한다.
- [확정] 같은 step 경로가 존재하면 `CHECKPOINT_ALREADY_EXISTS`로 실패하며 덮어쓰지 않는다.
- [확정] publish 실패 시 staging을 제거하고 final checkpoint를 노출하지 않는다.
- [확정] checkpoint 파일과 대용량 tensor는 Git에 추적하지 않는다.

## 3. 저장 상태

| 파일 | 내용 |
|---|---|
| `model.pt` | strict model state dict |
| `optimizer.pt` | AdamW parameter group·moment·step |
| `scheduler.pt` | 현재 optimizer step, warmup·max step, base LR |
| `scaler.pt` | AMP GradScaler state; CPU에서는 비활성 empty state |
| `training-state.json` | 진행·sampler state와 Python·torch CPU·가능 시 CUDA RNG |
| `config.json` | model·training snapshot, resume fingerprint, synthetic dataset descriptor |
| `manifest.json` | format `1.0`, step와 계보 fingerprint, 논리 파일명 |
| `checksums.json` | 위 7개 content file의 SHA-256 |

RNG는 JSON-safe 구조와 base64 tensor bytes로 저장해 별도 unsafe pickle payload를 만들지 않는다. 절대경로와 token 원문은 metadata에 기록하지 않는다.

## 4. Resume 검증

Resume는 state materialize 전에 모든 필수 파일과 checksum을 확인하고 다음 불일치를 fail-closed 처리한다.

| 조건 | 오류 |
|---|---|
| vocabulary, hidden, layer 등 model config 변경 | `CHECKPOINT_CONFIG_MISMATCH` |
| optimizer type 또는 핵심 training config 변경 | `CHECKPOINT_CONFIG_MISMATCH` |
| tokenizer fingerprint 변경 | `CHECKPOINT_TOKENIZER_MISMATCH` |
| dataset fingerprint 변경 | `CHECKPOINT_DATASET_MISMATCH` |
| checksum 변경 | `CHECKPOINT_CHECKSUM_MISMATCH` |
| key·state·step·RNG·tying 불일치 | `RESUME_STATE_MISMATCH` |

Accumulation 정책은 optimizer update 의미를 바꾸므로 incompatible이다. `log_every`, `save_every`, `output_dir`, worker·pin-memory 정책은 모델 update 의미를 직접 바꾸지 않는 warning 후보로 resume fingerprint에서 제외한다.

## 5. 복원 순서와 연속성

1. checksum·format·fingerprint 검증
2. model strict state load
3. optimizer, scheduler, scaler state load
4. global·optimizer·scheduler step 일치 검사
5. embedding–LM Head alias 검사
6. RNG 복원
7. sampler state가 있으면 새 DataLoader에 epoch·offset·permutation identity를 복원하고, 구형 synthetic state는 `micro_step` fast-forward
8. 다음 완전한 accumulation boundary부터 계속

- [확정] 중단 없는 2-step 실행과 checkpoint-1에서 resume한 실행의 parameter가 동일함을 검증했다.
- [확정] CPU와 CUDA FP16에서 checkpoint-5→10의 global step, LR, scaler와 fingerprint 연속성을 검증했다.
- [확정] 실제 Tiny 5→10 step에서 명시적 sampler state와 다음 batch fingerprint를 복원했고 uninterrupted 실행과 bitwise 동일했다.
- [검증 필요] 실제 corpus·streaming dataset과 `num_workers>0` sampler는 별도 검증한다.

## 6. 범위 경계

- [확정] 현재 format은 synthetic Trainer Foundation의 구현 schema다.
- [검증 필요] 운영 checkpoint version migration, retention, best/latest alias, 저장 공간과 cross-platform 장기 호환성은 미결정이다.
- [제외] 이 구현은 실제 tokenizer·dataset 또는 사전학습 checkpoint 승인을 뜻하지 않는다.
- [확정] Gate 6은 checkpoint/resume 통합 evidence와 2026-07-24 사용자 승인으로 `passed`다. 실제 tokenizer·dataset 또는 사전학습 checkpoint 승인은 별도다.

## 7. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-24 | [확정] 명시적 sampler state와 실제 Tiny 5→10·50→100 resume 연속성 검증을 반영함 |
| 2026-07-24 | [확정] atomic 8-file checkpoint, checksum·fingerprint·RNG와 strict resume 계약을 기록함 |
