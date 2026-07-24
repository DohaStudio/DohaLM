# DohaLM-Tiny 모델 구성요소 테스트

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-24 |
| 선행 문서 | [모델 구성요소](../architecture/model-components.md), [모델 아키텍처](../architecture/model-architecture.md), [테스트 전략](./test-strategy.md), ADR-002 |
| 후속 문서·작업 | Gate 4 사용자 검토, Phase 4 통합 모델 테스트 |
| 구현 전 필수 여부 | Phase 4 통합 전 예 |

## 2. 검증 범위

`tests/test_model_components.py`는 Config, token/position embedding, LayerNorm, causal attention, padding mask, FFN, Pre-LN block, LM Head, weight alias와 parameter count를 검증한다. 전체 모델, loss, generation, trainer, checkpoint와 학습은 범위 밖이다.

## 3. 필수 검증 결과

| 범주 | 검증 | 결과 |
|---|---|---|
| Config | Tiny 값·round-trip·invalid matrix | `pass` |
| Embedding | `[B,S,H]`, ID·rank·dtype·context·position | `pass` |
| LayerNorm | shape·affine·mean·finite backward | `pass` |
| Attention | QKV·head·output shape와 parameter | `pass` |
| Causal | 미래 입력 변경 시 이전 출력 불변 | `pass` |
| Padding | `[B,S]` bool, key 차단·query branch 0 | `pass` |
| FFN·Block | GELU·Pre-LN·residual·finite backward·eval 결정론 | `pass` |
| LM Head | logits shape·bias 없음·shape mismatch | `pass` |
| Weight tying | 동일 Parameter 객체와 `data_ptr` | `pass` |
| Parameter count | tied 중복 제외 `16,889,856` | `pass` |
| CUDA FP16 | component forward/backward·finite gradient | `pass` |

## 4. 실행 결과

```powershell
python -m pytest tests/test_model_components.py
python -m pytest
python -m src.cli.main environment --cuda-smoke
```

- [확정] 신규 구성요소 테스트 55개와 기존 회귀 245개를 합친 전체 300개가 통과했다.
- [확정] 단일 `RTX 3060 Ti 8GB`에서 small config FP16 forward/backward와 finite gradient가 통과했다.
- [확정] 환경 CLI의 CPU·CUDA tensor smoke도 성공했다. CUDA toolkit compiler(`nvcc`) 미확인은 기존 Gate 1과 같이 표준 PyTorch 구성요소 구현의 차단 사항이 아니다.

## 5. Gate 경계

- [확정] Gate 4는 `planned`이며 사용자 검토 없이 `passed`로 변경하지 않는다.
- [검증 필요] Phase 4 통합 모델에서 final LayerNorm 위치, 실제 logits causal 불변성, 전체 parameter count와 tied alias를 다시 검사한다.
- [제외] 이번 결과는 loss 감소, 생성 품질, checkpoint 복원 또는 학습 가능성을 승인하지 않는다.

## 6. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-24 | [확정] 55개 구성요소 테스트와 CPU·CUDA 검증 계약을 기록함 |
