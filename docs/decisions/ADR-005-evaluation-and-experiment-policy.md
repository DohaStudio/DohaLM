# ADR-005: 평가 및 실험 관리 정책

- 문서 상태: `approved`
- 결정일: 2026-07-23
- 구현 상태: [검증 필요] 미구현
- 관련 문서: [평가 계획](../10-evaluation-plan.md), [실험 관리](../15-experiment-management.md), [Benchmark 정책](../27-benchmark-policy.md), [생성 평가](../28-generation-evaluation.md), [재현성 정책](../29-reproducibility-policy.md), [실험 템플릿](../30-experiment-template.md)

## 결정 배경

DohaLM은 제한된 `RTX 3060 Ti 8GB`에서 모델 구현, 사전학습, SFT와 생성 품질을 단계적으로 검증한다. 지표·데이터·생성 설정·실행 환경이 고정되지 않으면 checkpoint와 실험 간 차이를 해석할 수 없고, 좋은 결과만 선택하거나 실패·누수를 놓칠 위험이 있다.

- [확정] 현재 평가 코드·실험 schema·실행 결과는 없으며 구현 전에 공통 비교 계약을 정한다.
- [확정] 정량 합격선과 외부 Benchmark는 실측·공식 조건 없이 확정하지 않는다.

## 구현 전 정의하는 이유

- [확정] 학습 코드가 기록해야 할 metric·환경·계보 필드를 처음부터 일관되게 설계할 수 있다.
- [확정] 동일 조건이 아닌 checkpoint 결과를 잘못 비교하는 것을 방지한다.
- [확정] SFT 전후와 메모리 전략 전후의 변경 변수를 분리한다.
- [확정] 실패 실험과 평가 누수를 성공 결과와 같은 계보에서 추적한다.

## 고려한 대안

| 대안 | 장점 | 위험 | 결정 |
|---|---|---|---|
| 실행 후 필요한 정보만 수기 기록 | 시작이 빠름 | 누락·선택 보고·재현 불가 | [제외] |
| 최신 checkpoint와 최고 점수만 보존 | 저장공간 절약 | 실패·회귀·선택 근거 유실 | [제외] |
| 고정 평가 계약과 experiment metadata 채택 | 비교·감사·재현 가능 | 초기 문서·저장 비용 | [확정] 채택 |

## 결정 사항

### 동일 validation split

- [확정] checkpoint와 SFT 전후 비교는 동일 dataset·preprocessing·split version을 사용한다.
- [확정] validation 데이터가 변경되면 같은 시계열로 직접 연결하지 않고 새 evaluation version으로 구분한다.

### 동일 tokenizer 조건의 Perplexity

- [확정] perplexity는 동일 tokenizer·vocabulary·special token, context·packing, 문서 경계와 loss mask 조건에서 비교한다.
- [확정] 전체 유효 target NLL 합을 전체 유효 target 수로 나눈 mean loss를 지수화한다.
- [확정] tokenizer 또는 vocabulary가 다른 모델의 token-level perplexity를 직접 우열 지표로 사용하지 않는다.

### 고정 생성 프롬프트

- [확정] versioned prompt set과 생성 설정을 checkpoint 비교에 사용한다.
- [확정] prompt fingerprint를 학습·SFT 데이터 누수 검사와 연결한다.
- [확정] 좋은 샘플뿐 아니라 전체 상태 분포와 실패 사례를 보존한다.

### 실험 ID와 메타데이터

- [가정] 실험 ID 권장 형식은 `EXP-NNNN-purpose`다.
- [확정] 각 실험은 코드, 모델 설정, tokenizer, 데이터·split·전처리, 학습 설정, seed와 환경 조합으로 정의한다.
- [확정] metadata에는 resolved config, 상태, 지표, artifact 참조와 실패 이유를 포함한다.

### Git commit과 데이터 version 연결

- [확정] 모든 실험은 Git commit SHA, branch와 working tree clean 여부를 기록한다.
- [확정] dataset·preprocessing·split version, tokenizer ID·fingerprint, model config와 checkpoint hash를 experiment ID에 연결한다.
- [검증 필요] dirty working tree의 patch 보존 방식은 구현 전에 결정한다.

### 실패 실험 보존

- [확정] OOM, NaN/Inf, loss 미감소, 데이터 손상, checkpoint 실패, 시간 초과, 사용자 중단, 환경·설정 오류와 누수 발견을 기록한다.
- [확정] 실패 결과를 삭제하거나 성공 실험으로 덮어쓰지 않고 새 attempt와 parent 관계를 남긴다.
- [확정] 비교에 사용할 수 없는 결과는 `invalid`로 명시한다.

### 외부 Benchmark 누수 방지

- [확정] Benchmark 문제·정답을 학습·SFT 데이터에 수동 추가하지 않는다.
- [확정] 문제·정답·해설과 표현 변경 후보를 데이터 누수 정책에 따라 검사한다.
- [확정] 외부 Benchmark의 라이선스·version·prompt·평가 코드·공식 규정을 적용 시점에 다시 확인한다.
- [제외] 비공개 평가 데이터 복원·추정을 금지한다.

## 장점

- [확정] checkpoint·SFT·메모리·hyperparameter 결과를 같은 기준으로 비교할 수 있다.
- [확정] Git·config·data·tokenizer·checkpoint의 계보와 평가 결과를 연결한다.
- [확정] 실패·누수·회귀를 숨기지 않고 후속 결정의 근거로 사용할 수 있다.
- [확정] `RTX 3060 Ti 8GB`에서 품질과 자원 비용을 함께 평가한다.

## 단점

- [확정] metadata·환경·metric·sample 보존에 구현·저장 비용이 든다.
- [확정] 완전한 결정론과 사람 평가 일관성은 보장하기 어렵다.
- [확정] 고정 평가에 반복 적응하면 validation·prompt overfitting이 생길 수 있다.
- [검증 필요] 개인 프로젝트 범위에 맞는 반복 seed·사람 평가·보존 수준을 조정해야 한다.

## 구현 영향

- [확정] trainer와 evaluator는 유효 token 기반 loss, 처리 token, 처리량, 시간, peak VRAM과 환경을 기록해야 한다.
- [확정] evaluation은 tokenizer·split·context·mask·prompt·generation config 호환성을 검사해야 한다.
- [확정] experiment registry는 상태 전이, resolved config, Git·데이터 계보와 artifact 참조를 지원해야 한다.
- [확정] checkpoint에는 experiment ID와 평가·데이터·tokenizer 식별자를 연결해야 한다.
- [확정] 자동 테스트는 metric 집계, seed·복원, 누수·invalid 처리와 metadata 필수 field를 검증해야 한다.

## 재검토 조건

- [검증 필요] 실제 평가가 현재 metric·상태로 표현되지 않는다.
- [검증 필요] metadata 비용이 실험 반복을 지속적으로 방해한다.
- [검증 필요] 비결정성으로 기준선 비교가 불가능하거나 허용 범위를 정할 수 없다.
- [검증 필요] 외부 Benchmark·Leaderboard가 다른 평가·보고 계약을 요구한다.
- [검증 필요] 데이터·tokenizer 변경으로 기존 perplexity·prompt 비교가 무효가 된다.
- [확정] 실패 삭제, validation 교체 후 직접 비교 또는 누수 기준 완화는 후속 ADR 없이 적용하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] 고정 validation·tokenizer·prompt, experiment metadata, 실패 보존과 Benchmark 누수 방지 원칙 채택 |
