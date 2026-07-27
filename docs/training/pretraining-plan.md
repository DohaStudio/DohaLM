# DohaLM 사전학습 계획

- 문서 상태: `draft`
- 마지막 검토일: 2026-07-28

## 1. 목적과 전제

- [확정] 첫 사전학습 대상은 랜덤 초기화한 `DohaLM-Tiny`다.
- [확정] 기준 장비는 단일 `RTX 3060 Ti 8GB`다.
- [확정] 모델은 [모델 아키텍처](../architecture/model-architecture.md), 토큰 방식은 [토크나이저 설계](./tokenizer-design.md), Phase 2 입력·산출물·호환성은 [토크나이저 상세 계약](./phase2-tokenizer-contract.md)을 따른다.
- [확정] 합성 token 전용 [Trainer Foundation](./trainer-foundation.md)과 [checkpoint/resume](./checkpoint-and-resume.md)는 구현·검증됐다. 승인된 실제 학습 데이터·운영 tokenizer·사전학습 checkpoint는 존재하지 않으며, 이 문서의 실제 사전학습 절차는 실행 계획이다.
- [확정] 100-step 이하 로컬 검증의 구현 계약은 [학생용 Pilot Pretraining](./pilot-pretraining.md)을 따른다. Canonical Pilot과 [Candidate A 10M 단일 실행](./full-pretraining-candidate-a-result.md)은 완료됐고 자동 연장·추가 학습은 미승인이다.
- [확정] 사전학습 후보와 목적별 승인은 [데이터셋 후보 등록부](../data/dataset-candidate-registry.md), [라이선스 검토](../data/dataset-license-review.md), [승인 로그](../data/dataset-approval-log.md)에서 분리해 관리한다.
- [후순위] `DohaLM-Small` 사전학습은 Tiny의 정확성·메모리·처리량 측정 후 진행한다.

## 2. 학습 목표

- [확정] objective는 다음 token 예측을 위한 causal language modeling이다.
- [확정] 모델은 `[B, T]` 입력에서 logits `[B, T, V]`를 출력한다.
- [확정] `input_ids=tokens[:, :-1]`, `labels=tokens[:, 1:]`로 한 token shift한다.
- [확정] loss는 유효 target에 대한 Cross-Entropy 평균이다.
- [확정] padding과 학습 제외 위치는 `ignore_index`로 loss에서 제외한다.

## 3. 학습 전 게이트

다음 항목이 통과되기 전 장시간 사전학습을 시작하지 않는다.

1. [검증 필요] 데이터 출처·라이선스 검토와 `approved_pretraining` 승인, 정제 및 train/validation 분할 기록 완료
2. [검증 필요] Phase 2 계약의 SentencePiece 16,000 vocabulary, ADR-003 special token ID 0~7, artifact checksum과 tokenizer fingerprint 테스트 통과
3. [확정] 합성 통합 모델에서 파라미터 수 `16,889,856` 일치; [검증 필요] 운영 config 재확인
4. [확정] 합성 입력의 shape, causal mask, loss shift 및 weight tying 단위 테스트 통과; [검증 필요] 운영 tokenizer 연결
5. [확정] 합성 작은 batch의 CPU·CUDA FP16 forward/backward에서 finite gradient 확인; [검증 필요] 실제 batch 검증
6. [확정] 반복 합성 batch의 50-step loss 감소 확인; [검증 필요] 승인 데이터 기반 의도적 과적합과 Gate 7 승인
7. [확정] 합성 checkpoint 저장·복원 및 결정론적 재개 테스트 통과; [검증 필요] NumPy·명시적 sampler state와 운영 checkpoint 검증
8. [검증 필요] `RTX 3060 Ti 8GB` 메모리 기준선 측정 완료

## 4. 데이터 흐름

### 4.1 사전 처리

`라이선스 승인 원문 → 정제 → 중복 제거 → train/validation 분할 → tokenizer encode → 문서 경계 추가 → context block 구성`

- [확정] train/validation 분할은 중복 제거 후 수행하고 문서 단위 누수를 점검한다.
- [확정] 각 문서는 `<bos>`와 `<eos>` 경계를 갖는다.
- [검증 필요] 서로 다른 문서를 고정 길이 block으로 packing하는 정확한 방식은 데이터 전처리 문서에서 확정한다.

### 4.2 Batch와 모델

| 단계 | 입력 shape | 출력 shape |
|---|---|---|
| token block | - | `[B, T+1]` |
| input/label split | `[B, T+1]` | 각각 `[B, T]` |
| model forward | `[B, T]` | `[B, T, 16,000]` |
| flatten | logits, labels | `[B×T, 16,000]`, `[B×T]` |
| Cross-Entropy | flatten 결과 | scalar loss |
| loss scaling/backward | scalar loss | parameter gradient |

- [확정] Tiny에서 `T <= 256`이다.
- [확정] causal mask는 attention score `[B, H, T, T]`에 softmax 직전 적용한다.
- [확정] 사전학습은 모든 유효 위치의 다음 token을 loss 대상으로 사용한다.

## 5. Optimizer와 learning-rate 계획

| 항목 | 계획 | 상태 |
|---|---|---|
| Optimizer | AdamW | [확정] |
| Scheduler | warmup 후 cosine decay | [확정] |
| Base learning rate | 미정 | [검증 필요] 짧은 탐색 후 확정 |
| Warmup step/비율 | 미정 | [검증 필요] 전체 token budget과 함께 결정 |
| Weight decay | 미정 | [검증 필요] |
| Gradient clipping | 적용 후보 | [가정] threshold 검증 필요 |
| 총 학습 token/step | 미정 | [검증 필요] 데이터 규모·처리량 측정 필요 |

- [확정] 정확한 hyperparameter를 corpus와 처리량 근거 없이 임의로 확정하지 않는다.
- [확정] optimizer parameter group에서 bias와 LayerNorm parameter의 weight decay 적용 여부를 명시적으로 기록한다.
- [확정] Phase 5 Trainer Foundation smoke는 구현 계약에 따라 linear warmup 후 linear decay만 사용한다. 이는 위 운영 사전학습 cosine 계획을 변경하거나 승인한 결과가 아니다.
- [확정] [Tiny 실규모 합성 검증](./tiny-training-validation.md)에서 warmup+cosine과 minimum LR 후보의 step·resume 연속성을 확인했다. 실제 corpus pilot 전 운영값 승인이 필요하다.

## 6. FP16 mixed precision 계획

- [확정] Tiny의 기준 학습 계산 정밀도는 FP16 mixed precision이다.
- [확정] PyTorch autocast를 사용해 지원 연산을 FP16으로 실행한다.
- [확정] PyTorch AMP `GradScaler`로 scaled backward, unscale, gradient 검사, optimizer step, scaler update 순서를 따른다.
- [확정] gradient clipping을 사용할 경우 unscale 이후, optimizer step 이전에 수행한다.
- [확정] 모델 parameter 및 AdamW state의 실제 dtype은 구현과 checkpoint에서 기록한다. autocast 사용만으로 모든 tensor가 FP16이라고 간주하지 않는다.
- [검증 필요] loss scale 감소 반복, skipped step, NaN/Inf 빈도를 로그로 확인한다.
- [검증 필요] FP16이 지속적으로 불안정하면 원인과 실측값을 기록하고 정밀도 정책 변경을 ADR로 검토한다.

## 7. Gradient Accumulation 계획

- [확정] micro-batch를 먼저 VRAM에 맞추고 여러 micro-step의 gradient를 누적해 optimizer update를 수행한다.
- [확정] 누적 중 각 micro-step loss를 `accumulation_steps`로 나눈 뒤 backward한다.
- [확정] optimizer, scheduler 및 GradScaler의 update는 누적 주기가 끝날 때 한 번 수행한다.
- [확정] 유효 sequence 수는 `micro_batch × accumulation_steps`이며 유효 token 수는 padding을 제외해 별도 기록한다.
- [확정] 마지막 불완전 누적 구간의 처리 정책을 명시하고 scheduler step과 optimizer step을 일치시킨다.
- [검증 필요] 목표 유효 batch/token 수와 accumulation step은 메모리·수렴 실험 후 확정한다.

## 8. Gradient Checkpointing 계획

- [확정] 모델 구현은 Transformer block 단위 activation checkpointing을 켜고 끌 수 있어야 한다.
- [가정] Tiny의 첫 메모리 기준선은 checkpointing을 끈 상태로 측정한다.
- [확정] micro-batch를 줄인 뒤에도 OOM이 발생하거나 유효 batch 확보가 어려우면 checkpointing을 활성화한다.
- [가정] Small 검토 시 checkpointing 활성화를 기본 후보로 둔다.
- [확정] 활성화 전후 최대 VRAM, tokens/sec 및 loss 일치 범위를 비교한다.
- [검증 필요] RNG와 dropout을 함께 사용할 때 재계산 구간의 재현성을 테스트한다.

세부 조정 순서는 [GPU 메모리 전략](./gpu-memory-strategy.md)을 따른다.

## 9. 단계별 실행 계획

### 단계 A: CPU 및 짧은 GPU 검증

- [확정] 합성 단일 batch forward와 loss shift 확인
- [확정] causal mask 불변성 테스트
- [확정] 합성 CPU·CUDA FP16의 1~수 step backward와 parameter update 확인

### 단계 B: 작은 데이터 과적합

- [확정] 반복 합성 batch 50-step에서 loss 감소 확인; [검증 필요] 실제 승인 표본 검증
- [검증 필요] 생성 결과와 target token alignment 확인
- [확정] 합성 checkpoint round-trip·resume 연속성·weight tying 확인

### 단계 C: 메모리·처리량 기준선

- [검증 필요] micro-batch 1에서 시작해 OOM 없이 가능한 범위를 측정
- [검증 필요] FP16, accumulation 및 checkpointing 조합별 최대 allocated/reserved VRAM과 tokens/sec 기록
- [확정] 측정 전 다른 GPU process와 캐시 상태를 기록한다.

### 단계 D: 제한된 pilot pretraining

- [검증 필요] validation loss, perplexity, gradient norm, scaler 상태 및 고정 prompt 생성 기록
- [검증 필요] 데이터·학습 파이프라인 이상이 없을 때만 더 긴 학습으로 확대

### 단계 E: 본 사전학습

- [검증 필요] 확정 config와 데이터 fingerprint로 실행
- [검증 필요] 주기적 평가, checkpoint 및 생성 sample 저장
- [확정] 실패 실험도 원인과 마지막 정상 checkpoint를 기록한다.

## 10. 평가와 로깅

- [확정] optimizer step, micro-step, processed token, train/validation loss, learning rate를 기록한다.
- [확정] gradient norm, GradScaler scale/skipped step, 경과 시간, tokens/sec 및 GPU 최대 메모리를 기록한다.
- [확정] 고정 validation set과 고정 prompt를 사용한다.
- [검증 필요] 평가 주기, checkpoint 주기 및 정량 합격선은 데이터 규모와 pilot 결과 후 확정한다.
- [확정] perplexity는 validation mean loss의 지수로 계산하되 overflow와 averaging 방식을 명시한다.

## 11. 체크포인트 저장 항목

### 11.1 학습 재개 필수 항목

Phase 5 합성 bundle의 구현 범위와 운영 계약의 남은 차이는 [체크포인트·재개](./checkpoint-and-resume.md)를 따른다.

- [확정] checkpoint format version
- [확정] model `state_dict` 및 전체 model config
- [확정] optimizer `state_dict`
- [확정] scheduler `state_dict`
- [확정] AMP GradScaler `state_dict`
- [확정] global optimizer step, micro-step, epoch 또는 sampler 위치, processed token 수
- [확정] Python, NumPy, PyTorch CPU 및 CUDA RNG state
- [확정] gradient accumulation 진행 상태 또는 저장 시 누적 경계임을 보장하는 규칙

### 11.2 재현성과 계보 항목

- [확정] 최종 적용 학습·모델·데이터 config snapshot
- [확정] tokenizer model 식별자와 hash, vocabulary size 및 special-token mapping
- [확정] tokenizer manifest·fingerprint와 corpus manifest·fingerprint, compatibility 결과
- [확정] train/validation dataset fingerprint와 split version
- [확정] code revision, Python/PyTorch/CUDA 환경 정보
- [확정] best metric, 마지막 평가 결과 및 parent checkpoint
- [확정] 생성 일시와 실험 ID

### 11.3 저장 규칙

- [확정] 임시 파일에 쓴 뒤 검증된 경로로 교체해 불완전 checkpoint 노출을 방지한다.
- [확정] `latest`, 주기 checkpoint 및 검증 기준 best checkpoint를 구분한다.
- [확정] 저장 직후 load 및 핵심 key 검증을 수행한다.
- [확정] checkpoint 저장 중 GPU 메모리 복제를 피하고 필요한 직렬화 작업은 CPU 메모리 영향을 함께 측정한다.
- [검증 필요] 보존 개수와 대용량 산출물 저장 위치는 실험 관리 문서에서 확정한다.

## 12. 중단 및 복구 기준

- [확정] 반복적인 NaN/Inf, 손실 급증, 데이터 손상, checkpoint 복원 실패 또는 해결되지 않는 OOM이 발생하면 장시간 학습을 중단한다.
- [확정] 마지막 정상 checkpoint, config, log 및 오류 정보를 보존한다.
- [확정] 사양 변경이 필요하면 기존 확정값을 조용히 바꾸지 않고 ADR로 재검토한다.

## 13. 검토 필요 사항

- [검증 필요] Candidate A 10M은 완료됐다. [Candidate B 최종 Readiness](./candidate-b-final-readiness.md)의 B 25M backend·CPU·output probe는 완료됐지만 immutable commit·물리 preflight·실행 승인이 없으므로 training은 금지한다. C 1 epoch는 미설계·미승인이다.
- [검증 필요] learning rate, warmup, weight decay 및 gradient clipping threshold
- [검증 필요] micro-batch, accumulation step, checkpointing 활성화 여부
- [검증 필요] 평가·저장 주기와 정량 중단 기준

## 14. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | [확정] Candidate B backend·CPU validation·output probe 완료와 실행 승인 전 fail-closed 경계 연결 |
| 2026-07-28 | [확정] Candidate B 25M readiness package와 `execution_allowed: false` 경계를 연결함 |
| 2026-07-27 | [확정] canonical 100-step Pilot 실측 기반 Full Pretraining budget·evaluation·checkpoint·초기화·안전·승인 패키지를 연결하고 실행 미승인을 유지함 |
| 2026-07-27 | [확정] Candidate A 10M single-use 실행을 4,883 step에서 완료하고 추가 학습 미승인을 유지함 |
| 2026-07-24 | [확정] [Pilot Pretraining 준비 검증](./pilot-pretraining-readiness.md)을 연결하고 Gate·tokenizer·corpus·split·평가 제외·config·storage가 명시 승인되기 전 실제 pilot을 차단함 |
| 2026-07-24 | [확정] 실제 Tiny 합성 batch·cosine·sampler resume·VRAM/처리량·100-step overfit 후보 결과를 연결하고 실제 사전학습과 구분함 |
| 2026-07-24 | [확정] 합성 Trainer Foundation·CPU/CUDA FP16·checkpoint/resume·50-step loss 감소 결과를 실제 사전학습과 구분해 반영함 |
| 2026-07-23 | [확정] Phase 2 토크나이저 상세 계약의 artifact·fingerprint·호환성 요구를 사전학습 진입 조건과 checkpoint 계보에 연결함 |
| 2026-07-23 | [확정] 후보·라이선스·승인 로그를 사전학습 데이터 선행 조건에 연결하고 `approved_pretraining` 목적 승인을 요구함 |
