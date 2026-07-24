# DohaLM-Tiny 모델 통합 테스트

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-24 |
| 선행 문서 | [모델 통합](../architecture/model-integration.md), [모델 구성요소 테스트](./model-component-testing.md), [테스트 전략](./test-strategy.md) |
| 후속 문서·작업 | Gate 5 승인 기록, Phase 5 학습·checkpoint 테스트 |
| 구현 전 필수 여부 | Gate 5 검토 전 예 |

## 2. 검증 범위

Phase 4 신규 테스트 65개는 전체 forward, shifted loss, hidden states, causal/padding mask, 실제 tying과 파라미터 집계, greedy generation, state dict round-trip, CPU·CUDA 및 CLI를 검증한다. 실제 tokenizer·corpus, optimizer update, checkpoint 파일과 생성 품질은 범위 밖이다.

| 범주 | 핵심 검증 | 결과 |
|---|---|---|
| 통합 forward | 기본·small config, logits shape, mask, hidden off/on, eval 결정론 | `pass` |
| Causal | 미래 token 변경 시 이전 통합 logits 불변 | `pass` |
| Loss | shift 수동 계산, labels=input, ignore, 오류, finite backward | `pass` |
| Tying·count | 동일 Parameter·storage, 고유 `16,889,856`, module breakdown | `pass` |
| Generation | greedy 결정론, prefix, batch EOS, context, mode, no-grad | `pass` |
| State dict | config·strict key, logits round-trip, re-tying, CPU→CUDA | `pass` |
| CPU | small config forward/loss/backward/generation | `pass` |
| CUDA | FP32·FP16/autocast forward/backward, generation, finite gradient | `pass` |
| CLI | inspect, CPU/CUDA smoke, generation, 간결한 오류 | `pass` |

## 3. 실행 결과

```powershell
python -m pytest
python -m scripts.model.inspect_model
python -m scripts.model.run_model_smoke --device cpu --dtype float32
python -m scripts.model.run_model_smoke --device cuda --dtype float16
python -m scripts.model.generate_smoke
```

- [확정] 기존 300개와 Phase 4 신규 65개를 합친 전체 365개 테스트가 통과했다.
- [확정] 테스트는 실제 데이터 대신 고정 seed의 합성 token ID와 bounded small config를 사용한다.
- [확정] RTX 3060 Ti 8GB에서 small config CUDA FP16 loss·backward와 finite gradient를 통과했다.
- [확정] small config, batch 2, sequence 8, CUDA FP16 smoke에서 peak allocated `16.373 MiB`, peak reserved `22.0 MiB`를 관측했다.
- [검증 필요] 이 값은 단일 smoke 조건의 관측값이며 Tiny 학습 VRAM 추정으로 확대하지 않는다.

## 4. 오류·품질 경계

잘못된 입력은 안정적인 오류 code로 실패하고 CLI는 traceback 없이 종료 코드 2를 반환한다. Generation은 context를 자동 절단하지 않으며 loss는 all-ignored target을 NaN으로 통과시키지 않는다.

- [제외] 생성 문장의 자연스러움, 반복, 한국어 품질은 무작위 초기 모델의 합격 조건이 아니다.
- [제외] 단일 optimizer step, loss 감소, checkpoint 파일 round-trip과 resume는 Phase 5 이후 검증 대상이다.
- [확정] Gate 4·5는 2026-07-24 사용자 승인으로 `passed`이며 Gate 3은 `planned`다.

## 5. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-24 | [확정] Phase 4 신규 65개와 전체 365개 CPU·CUDA 회귀 결과를 기록함 |
