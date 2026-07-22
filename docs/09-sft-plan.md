# DohaLM SFT 계획

## 1. 목적과 전제

- [확정] 질문·답변 데이터로 사전학습 모델을 supervised fine-tuning한다.
- [확정] SFT는 검증된 `DohaLM-Tiny` 사전학습 checkpoint부터 시작한다.
- [후순위] `DohaLM-Small` SFT는 Small 사전학습과 자원 검증 후 수행한다.
- [확정] tokenizer와 vocabulary를 SFT에서 임의 변경하지 않는다.
- [확정] 현재 SFT 데이터, 학습 코드 및 checkpoint는 존재하지 않는다.

## 2. 데이터 요구사항

- [확정] 각 데이터셋의 출처, 버전, 취득일, 라이선스, 학습·수정·재배포 허용 범위를 기록한다.
- [확정] system, user, assistant role을 구조적으로 구분한다.
- [확정] 빈 답변, 손상된 role 순서, 개인정보, 중복 및 라이선스 불명 데이터를 제외한다.
- [확정] train/validation/test 분할 간 질문 또는 답변 중복을 점검한다.
- [검증 필요] 데이터 규모, 품질 점수, 최대 turn 수 및 길이 분포는 데이터 확보 후 결정한다.

권장 중간 표현은 다음과 같다.

```json
{
  "id": "dataset-specific-id",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "source": "...",
  "license": "..."
}
```

- [확정] 위 JSON은 데이터 계약 예시이며 실제 데이터가 존재한다는 의미가 아니다.
- [확정] 원본 ID와 출처를 정제 결과까지 추적할 수 있어야 한다.

## 3. 대화 템플릿

### 3.1 단일 turn

```text
<bos><|system|>{system}<|end|><|user|>{user}<|end|><|assistant|>{assistant}<|end|><eos>
```

### 3.2 다중 turn

```text
<bos><|system|>{system}<|end|>
<|user|>{user_1}<|end|><|assistant|>{assistant_1}<|end|>
<|user|>{user_2}<|end|><|assistant|>{assistant_2}<|end|><eos>
```

### 3.3 추론 prompt

```text
<bos><|system|>{system}<|end|><|user|>{user}<|end|><|assistant|>
```

- [확정] special token 문자열과 ID는 [토크나이저 설계](./05-tokenizer-design.md)를 따른다.
- [확정] 학습과 추론에서 하나의 chat serialization 함수를 공유한다.
- [확정] assistant marker 다음부터 생성하고 `<|end|>` 또는 `<eos>`에서 종료한다.
- [검증 필요] 기본 system message와 직렬화 줄바꿈 규칙은 데이터셋 구성 전에 확정한다.

## 4. SFT 학습 텐서와 loss mask

| 항목 | shape | 설명 |
|---|---|---|
| serialized token IDs | `[B, T+1]` | padding 포함 가능 |
| input IDs | `[B, T]` | 마지막 token 제외 |
| shifted labels | `[B, T]` | 첫 token 제외 |
| attention/key padding mask | `[B, T]` | 유효 token 표시 |
| loss mask | `[B, T]` | assistant target 여부 |
| logits | `[B, T, V]` | `V=16,000` |
| flattened logits/labels | `[B×T, V]`, `[B×T]` | Cross-Entropy 입력 |
| loss | scalar | assistant target 평균 |

- [확정] system, user, role marker 및 `<pad>` target은 `ignore_index`로 설정한다.
- [확정] assistant 본문, assistant `<|end|>` 및 마지막 `<eos>` target은 loss에 포함한다.
- [확정] 기본안은 다중 turn의 모든 assistant 답변을 loss에 포함한다.
- [확정] causal mask는 attention score에, key padding mask는 padding key에, loss mask는 Cross-Entropy target에 각각 적용한다.
- [확정] label shift 전후 mask 정렬을 fixture로 테스트한다.

## 5. 길이 제한과 truncation

- [확정] `DohaLM-Tiny`의 serialized sequence는 256 token 이하여야 한다.
- [확정] special token이나 assistant 답변을 임의의 중간 위치에서 잘라 잘못된 role 구조를 만들지 않는다.
- [확정] 단일 turn이 context를 초과하면 해당 표본을 제외하거나 명시적 전처리 규칙을 적용하고 수량을 기록한다.
- [가정] 다중 turn 초과 시 가장 오래된 완결 turn부터 제거하고 현재 user 질문과 assistant 답변을 우선 보존한다.
- [검증 필요] truncation 정책은 실제 길이 분포를 확인한 뒤 확정한다.
- [제외] 서로 무관한 SFT 대화를 한 context에 단순 연결해 서로 attention하게 만들지 않는다.

## 6. 학습 데이터 흐름

1. 라이선스와 품질 검사를 통과한 role 구조 데이터를 읽는다.
2. 공통 chat template으로 문자열 또는 token sequence를 직렬화한다.
3. special token 단일-ID 여부와 role 순서를 검증한다.
4. context 제한에 따라 표본을 유지·제외·truncation한다.
5. `input_ids`, shifted `labels`, key padding mask와 loss mask를 생성한다.
6. 사전학습 checkpoint를 로드하고 logits `[B, T, V]`를 계산한다.
7. assistant target만 Cross-Entropy에 포함한다.
8. FP16 mixed precision과 gradient accumulation으로 update한다.
9. validation과 고정 대화 prompt를 평가하고 checkpoint를 저장한다.

## 7. 추론 데이터 흐름

1. system message, 대화 history 및 새 user message를 동일 템플릿으로 직렬화한다.
2. 마지막에 `<|assistant|>`를 붙이고 tokenize한다.
3. context 상한을 넘으면 확정된 history truncation 규칙을 적용한다.
4. 모델의 마지막 위치 logits에서 다음 token을 선택해 자기회귀 생성한다.
5. `<|end|>`, `<eos>` 또는 최대 생성 길이에 도달하면 중단한다.
6. role token을 사용자 표시 문자열에서 제거하고 assistant 본문만 반환한다.

- [확정] 학습은 정답 assistant token이 있는 teacher forcing이고 추론은 생성 token을 다음 입력으로 사용하는 자기회귀 방식이다.
- [검증 필요] sampling parameter와 최대 생성 길이는 추론 설계 문서에서 확정한다.

## 8. FP16, accumulation 및 checkpointing

- [확정] 사전학습과 동일하게 PyTorch autocast FP16과 GradScaler를 사용한다.
- [확정] micro-batch는 `RTX 3060 Ti 8GB` 실측으로 정하고 유효 batch는 gradient accumulation으로 확보한다.
- [확정] accumulation 중 loss normalization, optimizer/scheduler step 및 scaler update 규칙은 사전학습과 동일하게 유지한다.
- [확정] block 단위 gradient checkpointing을 지원한다.
- [가정] Tiny SFT는 checkpointing off 기준선을 먼저 측정하고 OOM 또는 유효 batch 제약이 있으면 활성화한다.
- [검증 필요] SFT sequence 길이 분포에 따른 padding 낭비와 length bucketing 효과를 측정한다.

## 9. Hyperparameter 원칙

| 항목 | 계획 | 상태 |
|---|---|---|
| 초기 weight | 검증된 사전학습 checkpoint | [확정] |
| Optimizer | AdamW | [확정] |
| Learning rate | 사전학습보다 낮은 후보 탐색 | [가정] 정확한 값 검증 필요 |
| Scheduler | warmup 포함 | [확정] 세부 형태 검증 필요 |
| Epoch/token budget | 미정 | [검증 필요] 데이터 규모 기준 |
| Weight decay | 미정 | [검증 필요] |
| Gradient clipping | 적용 후보 | [가정] threshold 검증 필요 |

- [확정] 정확한 수치를 데이터 규모와 pilot 결과 없이 확정하지 않는다.
- [확정] 사전학습 checkpoint와 SFT checkpoint를 별도 계보로 관리한다.

## 10. 평가 계획

- [검증 필요] SFT 전후에 동일한 validation loss와 고정 prompt를 사용한다.
- [검증 필요] 질문 관련성, 한국어 자연스러움, 반복, 빈 응답, role token 누출 및 종료 동작을 점검한다.
- [검증 필요] 학습 답안 암기와 train/test 중복을 별도로 점검한다.
- [확정] 선택된 좋은 예시만 보고하지 않고 고정 evaluation set 전체 결과와 실패 사례를 보존한다.
- [검증 필요] 자동·사람 평가의 정량 합격선은 `10-evaluation-plan.md`에서 확정한다.

## 11. SFT 체크포인트 추가 항목

[사전학습 계획](./08-pretraining-plan.md)의 공통 checkpoint 항목에 다음을 추가한다.

- [확정] parent pretraining checkpoint ID와 hash
- [확정] SFT dataset fingerprint, split 및 filtering version
- [확정] chat-template version과 special-token mapping
- [확정] loss-mask 정책과 truncation 정책
- [확정] SFT config snapshot과 평가 결과
- [확정] template 또는 tokenizer 변경 여부 검증 결과

## 12. 중단 기준

- [확정] role token이 분할되거나 template과 loss mask가 어긋나면 학습을 시작하지 않는다.
- [확정] 데이터 라이선스 또는 분할 누수 문제가 발견되면 해당 데이터 실험을 중단한다.
- [확정] 반복적인 NaN/Inf, 해결되지 않는 OOM, checkpoint 복원 실패 또는 SFT 후 명백한 품질 붕괴가 있으면 원인을 분석하기 전 확대 학습을 중단한다.
- [검증 필요] 수치 기반 조기 종료 기준은 pilot 결과 후 확정한다.

## 13. 검토 필요 사항

- [검증 필요] SFT 데이터셋, 규모, 품질 기준 및 라이선스
- [검증 필요] 기본 system message와 줄바꿈 직렬화
- [검증 필요] 다중 turn truncation 및 assistant loss 범위
- [검증 필요] learning rate, token budget, batch와 평가 합격선
