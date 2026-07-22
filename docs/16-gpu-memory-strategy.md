# DohaLM GPU 메모리 전략

## 1. 목적과 원칙

- [확정] 모든 학습·추론 설계는 단일 `RTX 3060 Ti 8GB`를 기준으로 한다.
- [확정] A100, H100, 멀티 GPU 및 대규모 분산 학습을 해결책으로 전제하지 않는다.
- [확정] 아래 계산은 메모리 구성요소를 이해하기 위한 이론값이며 실제 VRAM 사용량 확정값이 아니다.
- [확정] 실제 사용량은 동일한 PyTorch, CUDA, driver, batch, sequence 및 기능 설정에서 측정한다.

## 2. 파라미터 기반 이론값

### 2.1 DohaLM-Tiny

[모델 아키텍처](./04-model-architecture.md)의 예상 파라미터는 `16,889,856`개다.

| 항목 | 산식 | 이론값 |
|---|---:|---:|
| FP16 parameter payload | `P × 2 byte` | 33,779,712 byte, 약 32.22 MiB |
| FP32 parameter payload | `P × 4 byte` | 67,559,424 byte, 약 64.43 MiB |
| FP32 parameter + gradient + AdamW moments | `P × (4+4+8) byte` | 270,237,696 byte, 약 257.72 MiB |

- [확정] PyTorch AMP autocast는 보통 모델 parameter를 FP32로 유지하면서 일부 연산을 FP16으로 수행할 수 있으므로 첫 행만으로 학습 메모리를 계산하면 안 된다.
- [확정] 위 표에는 activation, 임시 attention tensor, autocast cache, allocator reservation, CUDA context, kernel workspace, dataloader 및 평가 출력이 포함되지 않는다.

### 2.2 DohaLM-Small 검토안

- [가정] `04-model-architecture.md`의 비구속 검토안은 `59,804,160`개다.
- [가정] 같은 단순 `16 byte/parameter` 산식을 적용하면 parameter, gradient 및 AdamW moments payload는 약 912.54 MiB다.
- [확정] 이 수치는 Small 사양 또는 실제 총 VRAM 사용량을 확정하지 않는다.
- [검증 필요] Tiny 실측 전 Small의 상세 구조와 optimizer memory 정책을 고정하지 않는다.

## 3. 주요 메모리 구성요소

| 구성요소 | 주요 영향 변수 | 특성 |
|---|---|---|
| Model parameters | parameter 수, dtype | 대체로 고정 |
| Gradients | trainable parameter 수, dtype | backward 시 유지 |
| Optimizer states | optimizer, state dtype | AdamW는 moment 2개 사용 |
| Activations | `B`, `T`, `D`, `F`, `L`, dtype | 학습 시 큰 가변 항목 |
| Attention scores/probabilities | `B`, `H`, `T²`, dtype, 구현 | context 증가에 제곱 영향 |
| Logits | `B`, `T`, `V`, dtype | vocab 16,000의 영향 |
| Temporary buffers | 연산, kernel, allocator | 실행 환경에 따라 변동 |
| CUDA context/framework | driver, CUDA, PyTorch | 모델 외 고정 오버헤드 존재 |
| KV cache | `B`, `L`, `H`, cached length, `Dh`, dtype | 추론 길이에 선형 증가 |

## 4. Attention score 예시

score tensor 하나의 단순 payload는 `B × H × T × T × element_size`다.

| 모델/가정 | `B` | `H` | `T` | FP16 score tensor 1개 |
|---|---:|---:|---:|---:|
| Tiny | 1 | 6 | 256 | 786,432 byte, 0.75 MiB |
| Small 검토안 | 1 | 10 | 512 | 5,242,880 byte, 5.00 MiB |

- [확정] 실제 attention은 layer별 score뿐 아니라 probability, Q/K/V, backward 저장값과 임시 buffer를 사용할 수 있으므로 위 값을 layer 수만 곱해 총 VRAM으로 간주하지 않는다.
- [확정] `T`가 두 배가 되면 score 원소 수는 네 배가 된다.
- [검증 필요] 직접 구현 attention의 실제 peak memory를 profiler로 측정한다.

## 5. FP16 계획

- [확정] Tiny forward/backward 계산은 PyTorch autocast 기반 FP16 mixed precision을 사용한다.
- [확정] GradScaler로 underflow를 완화하고 NaN/Inf 및 skipped optimizer step을 기록한다.
- [확정] 수치 민감 연산이 어떤 dtype으로 실행되는지 구현·환경별로 확인한다.
- [검증 필요] model parameter, gradient, optimizer state, logits 및 loss의 실제 dtype을 첫 실행에서 기록한다.
- [확정] 단순히 모든 parameter를 FP16으로 강제 변환해 메모리를 줄이는 방식은 수치 안정성 검증 없이 사용하지 않는다.

## 6. Gradient Accumulation 계획

- [확정] VRAM에 직접 영향을 주는 micro-batch와 수렴에 영향을 주는 유효 batch를 분리한다.
- [확정] micro-batch를 줄인 후 accumulation step을 늘려 유효 sequence/token 수를 보완한다.
- [확정] accumulation은 여러 micro-step activation을 동시에 보관하지 않으므로 micro-batch보다 peak activation을 낮게 유지할 수 있다.
- [확정] 누적 중 gradient는 유지되지만 매 micro-step activation은 backward 후 해제되어야 한다.
- [검증 필요] logging tensor나 loss graph를 Python collection에 붙잡아 의도치 않게 activation을 보존하지 않는지 확인한다.

## 7. Gradient Checkpointing 계획

- [확정] Transformer block 단위로 activation checkpointing을 선택 적용한다.
- [확정] forward activation 일부를 저장하지 않고 backward 때 재계산해 VRAM을 줄이는 대신 처리량이 감소한다.
- [가정] Tiny는 off 기준선부터 측정하고 필요할 때 on으로 전환한다.
- [가정] Small은 on을 우선 검토하되 Tiny 실측 근거 없이 확정하지 않는다.
- [검증 필요] on/off에서 loss, gradient, RNG, peak memory 및 tokens/sec를 비교한다.

## 8. OOM 가능 지점

### 8.1 학습

1. [검증 필요] 첫 model/CUDA context 로드 시 다른 process 또는 baseline 점유로 인한 OOM
2. [검증 필요] 긴 sequence와 큰 micro-batch의 QKV 및 `[B,H,T,T]` attention score 생성
3. [검증 필요] `[B,T,F]` FFN activation과 `[B,T,V]` logits 생성
4. [검증 필요] backward에서 saved activation, gradient 및 임시 buffer가 겹치는 peak
5. [검증 필요] 첫 AdamW step에서 optimizer state가 생성되는 순간
6. [검증 필요] validation 중 logits·loss·생성 결과를 GPU tensor로 누적하는 경우
7. [검증 필요] checkpoint 저장·복원 중 state를 GPU에 중복 materialize하는 경우
8. [검증 필요] shape 오류로 mask나 broadcast tensor가 예상보다 크게 생성되는 경우

### 8.2 추론

1. [검증 필요] 긴 prompt와 generation을 합쳐 context 상한에 접근할 때
2. [검증 필요] batch 생성 또는 beam 계열 탐색으로 sequence가 복제될 때
3. [검증 필요] KV cache가 layer 및 cached token에 따라 증가할 때
4. [검증 필요] KV cache 없이 매 step 전체 prefix의 attention matrix를 재계산할 때
5. [검증 필요] 여러 모델 또는 checkpoint를 GPU에 동시에 로드할 때

## 9. OOM 대응 우선순위

확정 모델값은 조용히 변경하지 않는다. 아래 순서대로 한 번에 하나의 변수를 조정하고 전후 측정값을 기록한다.

1. **환경과 누수 확인** [확정]
   - 다른 GPU process, 이전 model 참조, 누적된 output tensor 및 예상치 못한 shape를 확인한다.
   - `memory_allocated`, `memory_reserved`, `max_memory_allocated`와 실행 설정을 기록한다.
2. **Micro-batch 축소** [확정]
   - 학습 micro-batch를 우선 1까지 낮춘다.
   - 평가·추론 batch도 별도로 낮춘다.
3. **Gradient accumulation 증가** [확정]
   - micro-batch 축소로 줄어든 유효 batch/token을 accumulation으로 보완한다.
4. **Gradient checkpointing 활성화** [확정]
   - block 단위로 적용하고 처리량 손실과 memory 감소를 측정한다.
5. **불필요한 GPU 보존 제거** [확정]
   - logging에는 detached scalar를 사용하고 validation output은 즉시 CPU 이동 또는 집계한다.
   - optimizer gradient를 적절히 비우고 checkpoint 직렬화 중 중복 GPU copy를 피한다.
6. **Sequence 운영값 조정** [확정]
   - Small은 확정 상한 512 이하에서 실제 training sequence length를 낮춰 측정할 수 있다.
   - Tiny의 Context Length 256 변경은 진단용 실험과 모델 사양 변경을 구분한다.
7. **Optimizer 또는 연산 메모리 전략 재검토** [검증 필요]
   - state dtype, optimizer 선택 또는 직접 구현 attention의 메모리 개선은 수치·직접 구현 범위·재현성 검토 후 결정한다.
8. **확정 모델 사양 변경** [최후순위]
   - Tiny의 Layer, Hidden, Head, Context 또는 Vocabulary를 변경해야 하면 기존 값을 임의 수정하지 않고 ADR을 작성한다.
   - Small은 Tiny 실측에 따라 상세 사양을 확정한다.

- [확정] FP16은 기준 설정이므로 OOM 후 처음 켜는 임시 조치가 아니다.
- [제외] 해결책으로 멀티 GPU 또는 대형 GPU를 전제하지 않는다.

## 10. 메모리 측정 절차

1. [확정] GPU 이름, 총 VRAM, driver, CUDA, PyTorch 및 실행 process를 기록한다.
2. [확정] 동일 seed와 batch에서 warm-up 후 측정한다.
3. [확정] step 전 peak 통계를 초기화하고 forward, backward, optimizer step을 모두 포함한다.
4. [확정] allocated, reserved, peak allocated, batch, `T`, dtype, checkpointing 및 accumulation 설정을 함께 기록한다.
5. [확정] 첫 optimizer step과 안정화 이후 step을 구분한다.
6. [확정] tokens/sec 및 step time을 함께 기록해 memory 절감의 계산 비용을 비교한다.
7. [검증 필요] profiler 자체의 memory 영향과 측정 오차를 기록한다.

## 11. 학습·추론 기준선 표

실측 전에는 값을 채우지 않는다.

| 모델 | 모드 | B | T | FP16 | Accum | Checkpointing | Peak allocated | Peak reserved | tokens/sec | 상태 |
|---|---|---:|---:|---|---:|---|---:|---:|---:|---|
| DohaLM-Tiny | train | 미정 | 256 | on | 미정 | off 기준선 | 미측정 | 미측정 | 미측정 | [검증 필요] |
| DohaLM-Tiny | train | 미정 | 256 | on | 미정 | on 비교 | 미측정 | 미측정 | 미측정 | [검증 필요] |
| DohaLM-Tiny | inference | 미정 | ≤256 | on | 해당 없음 | off | 미측정 | 미측정 | 미측정 | [검증 필요] |
| DohaLM-Small | train | 미정 | ≤512 | 미정 | 미정 | 미정 | 미측정 | 미측정 | 미측정 | [후순위] |

## 12. 중단 및 재검토 조건

- [확정] memory leak, 잘못된 shape, 불필요 tensor 보존을 먼저 배제한다.
- [확정] Tiny가 micro-batch 1, accumulation 및 checkpointing 검토 후에도 8GB에서 안정적으로 실행되지 않으면 원인과 실측을 기록하고 ADR을 작성한다.
- [확정] Small이 현실적인 처리량을 내지 못하면 Small을 중단할 수 있으며 Tiny 완료와 분리한다.
- [검증 필요] 현실적인 처리량과 허용 학습 시간의 정량 기준은 Tiny pilot 후 확정한다.

## 13. 검토 필요 사항

- [검증 필요] 실제 parameter/gradient/optimizer dtype과 AMP cache 동작
- [검증 필요] Tiny의 최대 micro-batch, accumulation, checkpointing 조합
- [검증 필요] attention, FFN, logits 및 optimizer step별 peak memory
- [검증 필요] Small 상세 사양과 최대 512 context의 실효성
- [검증 필요] 처리량·학습 시간 기준 및 profiler 측정 방법
