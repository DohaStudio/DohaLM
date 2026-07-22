# DohaLM 평가 계획

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-23 |
| 선행 문서 | [모델 아키텍처](../architecture/model-architecture.md), [토크나이저 설계](../training/tokenizer-design.md), [사전학습 계획](../training/pretraining-plan.md), [SFT 계획](../training/sft-plan.md), [데이터 분할 및 누수 방지](../data/data-split-and-leakage-policy.md), [ADR-005](../decisions/ADR-005-evaluation-and-experiment-policy.md) |
| 후속 문서 | [실험 관리](../training/experiment-management.md), [Benchmark 정책](./benchmark-policy.md), [생성 평가](./generation-evaluation.md), [재현성 정책](../quality/reproducibility-policy.md), [개발 로드맵](../quality/development-roadmap.md), `11-inference-design.md`, `20-leaderboard-strategy.md` 작성 예정 |
| 구현 전 필수 여부 | 학습 전 예 |

- [확정] 현재 평가 코드, 평가 데이터, 실행 결과와 합격 기준 실측값은 없다.
- [확정] 이 문서는 평가 조건과 기록 계약을 정의하며 근거 없는 수치 합격선을 정하지 않는다.

## 2. 평가 목적

| 목적 | 확인 질문 | 주요 근거 |
|---|---|---|
| 모델 구현 정상성 | shape·mask·loss·weight tying·복원이 설계대로 동작하는가 | 정적 검증, 단위·과적합 결과 |
| 사전학습 진행 상태 | 같은 validation 조건에서 loss와 perplexity가 어떻게 변하는가 | step/token별 validation 결과 |
| 체크포인트 비교 | 성능 변화가 checkpoint 진행과 일치하는가 | 같은 평가 snapshot의 지표·샘플 |
| SFT 전후 비교 | 대화 관련성과 지시 준수가 개선되고 기반 품질이 붕괴하지 않았는가 | 동일 prompt·설정의 전후 결과 |
| 생성 품질 비교 | 한국어 완결성·반복·일관성·종료가 어떤가 | 고정 prompt와 상태형 판정 |
| 자원 효율 비교 | 품질 대비 시간·처리량·VRAM 비용이 어떤가 | tokens/sec, step time, latency, peak VRAM |
| 회귀 여부 확인 | 이전 승인 기준선보다 핵심 동작이 나빠졌는가 | versioned baseline과 동일 조건 비교 |
| Leaderboard 가능성 검토 | 당시 공식 형식·라이선스·오염 정책에 맞는가 | [후순위] 최신 공식 규정 검토 |

## 3. 평가 단계

| 평가 단계 | 목적 | 입력 | 평가 지표 | 비교 대상 | 통과 기준 상태 | 결과 저장 위치 | 현재 상태 |
|---|---|---|---|---|---|---|---|
| 1. 모델 구현 전 정적 설계 검증 | 사양·산식·shape 계약 확인 | 설계 문서·ADR | parameter 산식, shape, mask 위치, 설정 일치 | 기준 문서 간 | 필수 불일치가 없으면 `pass` 후보 | 문서 검토 기록 | [검증 필요] 코드 미구현 |
| 2. 단일 배치 overfitting 평가 | forward·loss·backward 연결 확인 | 고정 단일 batch | training loss 추세, token alignment, NaN/Inf | 초기화 직후 | 합격 수치는 pilot 후 확정 | 실험 결과·metrics | [검증 필요] 미실행 |
| 3. 극소량 데이터 overfitting 평가 | loader·shuffle·checkpoint·생성 연결 확인 | 고정 극소량 train/validation | train/validation loss, perplexity, 생성, 복원 | 단일 배치·재개 전후 | [검증 필요] 기준선 후 결정 | 실험 결과·샘플 | [검증 필요] 미실행 |
| 4. 사전학습 중간 checkpoint 평가 | 진행·붕괴·회귀 감시 | 중간 checkpoint, 고정 validation·prompt | validation loss, perplexity, 생성 상태, 자원 | 이전 checkpoint·초기화 | 동일 조건에서 추세와 오류 검토 | experiment ID 하위 결과 | [검증 필요] 미실행 |
| 5. 사전학습 완료 평가 | Tiny 사전학습 결과 확정 | 최종·best checkpoint | 정량·정성·복원·자원 지표 | 초기화·중간 checkpoint | pilot 후 승인 기준 적용 | 평가 요약·선별 샘플 | [검증 필요] 미실행 |
| 6. SFT 전 평가 | SFT 기준선 고정 | parent pretraining checkpoint | validation loss, 고정 대화 prompt, 생성 상태 | 최종 사전학습 모델 | 전후 비교 입력 완전성 확인 | SFT experiment baseline | [검증 필요] 미실행 |
| 7. SFT 후 평가 | 대화 품질 변화·회귀 확인 | SFT checkpoint | SFT validation loss, 관련성, 지시 준수, 반복·종료 | 정확한 parent checkpoint | 같은 split·prompt·설정 비교 | SFT 결과·failure sample | [검증 필요] 미실행 |
| 8. 추론 성능 평가 | 사용자 관점 지연·메모리 측정 | checkpoint, tokenizer, prompt set | first-token latency, total latency, tokens/sec, peak VRAM | 생성 설정·환경별 기준선 | 실측 후 허용 범위 결정 | performance result | [검증 필요] 미실행 |
| 9. 회귀 평가 | 코드·설정 변경의 악화 탐지 | 승인 baseline과 후보 | 핵심 loss·생성·복원·latency 차이 | 직전 승인 baseline | 허용 오차 [검증 필요] | 회귀 보고서 | [검증 필요] 미실행 |
| 10. 외부 Benchmark 검토 | 외부 비교 가능성 판단 | 후보 benchmark·공식 규정 | benchmark별 공식 지표 | 공개·로컬 결과 구분 | 채택 전 라이선스·누수 검토 | benchmark 결과 후보 | [후순위] 후보 미정 |

## 4. 정량 평가

| 지표 | 계산 목적 | 계산 시점 | 단위 | 데이터 범위 | 비교 방법 | 해석상 주의점 |
|---|---|---|---|---|---|---|
| Training loss | optimizer가 train objective를 낮추는지 확인 | micro-step 집계·optimizer step | 유효 target당 mean CE | train batch, padding/loss 제외 | step·처리 token 축으로 추세 비교 | validation 일반화를 뜻하지 않음; accumulation 평균 규칙 고정 |
| Validation loss | 미학습 split의 causal LM/SFT 손실 확인 | 고정 평가 주기·checkpoint | 유효 target당 mean CE | 고정 validation split | 동일 tokenizer·mask·context에서 비교 | sample 평균이 아닌 유효 token 가중 평균 원칙 |
| Perplexity | validation CE를 해석 가능한 지수로 표현 | validation loss 집계 후 | `exp(mean loss)` | 고정 validation 유효 target | 동일 평가 계약에서만 비교 | overflow, vocabulary·tokenizer 차이, SFT mask 차이 주의 |
| Token accuracy | 다음 token top-1 일치율의 보조 진단 | validation 시 후보 | 유효 target 비율 | loss와 같은 target | 같은 tokenizer·mask에서 보조 비교 | 자연어에 다수의 타당한 다음 token이 있어 핵심 품질 지표로 단독 사용하지 않음 |
| 처리 token 수 | 학습·평가 진행량 정규화 | 실행 중 누적 | 유효 token | padding 제외 기준 명시 | step 대신 token 축 비교 | raw sequence token과 loss target token을 구분 |
| Token throughput | 학습·평가 자원 효율 | warm-up 후 안정 구간 | tokens/sec | 처리 token 정의와 구간 고정 | 동일 환경·모드·batch·context 비교 | I/O, 평가, accumulation 포함 범위 명시 |
| Step time | update 비용 측정 | warm-up 후 optimizer step | 초/optimizer step | forward+backward+update 범위 | 반복 분포와 대표값 비교 | micro-step 수가 다르면 직접 비교 주의 |
| Peak VRAM | 8GB 적합성 확인 | train/eval/inference 구간별 | byte 또는 MiB | allocated/reserved 각각 기록 | 동일 환경·warm-up·기능 조건 | CUDA context·allocator·profiler 영향 포함 여부 명시 |
| Checkpoint 크기 | 저장·복원·보존 비용 판단 | checkpoint 저장 후 | byte 또는 MiB | 파일 전체와 구성별 | 동일 format·state 범위 비교 | optimizer 포함 여부에 따라 크게 달라짐 |
| 생성 latency | 요청의 생성 속도 확인 | 고정 prompt 생성 | 초/요청, ms/token 후보 | prompt·output 길이 기록 | 같은 hardware·checkpoint·설정 | warm-up, 동기화, token 수 차이 주의 |
| 첫 token latency | 응답 시작 지연 확인 | 생성 시작~첫 token | ms | 고정 prompt 범주 | 같은 prompt 길이·환경 | model load·tokenize 포함 여부 분리 |
| 전체 생성 시간 | 종료까지 총 비용 확인 | 요청 시작~종료 | 초 | 입력·생성 token 수 기록 | 동일 종료 조건·최대 길이 | EOS 조기 종료와 max token 도달 구분 |

- [확정] training loss와 validation loss는 데이터 범위·모드를 분리해 기록한다.
- [검증 필요] 각 지표의 합격 수치, 집계 구간, warm-up 횟수와 허용 회귀 폭은 기준 실험 후 확정한다.

## 5. Perplexity 정책

1. [확정] 비교 checkpoint는 동일 tokenizer model·version·special-token mapping을 사용한다.
2. [확정] 동일 validation split을 사용하며 dataset ID, preprocessing version, split version과 평가 순서를 고정한다.
3. [확정] context length, chunk·packing, 긴 문서와 마지막 잔여 조각 처리를 동일하게 유지한다.
4. [확정] padding target과 사전학습에서 제외할 위치는 `ignore_index`로 제외한다.
5. [확정] SFT perplexity를 계산하면 assistant loss mask 정책을 고정하고 일반 causal LM perplexity와 별도 명칭으로 보고한다.
6. [확정] 문서 경계의 `<bos>`·`<eos>` 및 문서 간 `<eos><bos>` 처리 정책을 동일하게 유지한다.
7. [확정] batch별 loss를 단순 평균하지 않고 전체 유효 target의 negative log-likelihood 합을 전체 유효 target 수로 나눈 뒤 지수화한다.
8. [확정] checkpoint 간 model evaluation mode, dtype·autocast, batch, deterministic 설정을 기록한다.
9. [확정] vocabulary 또는 tokenizer가 다른 모델의 perplexity는 token 단위가 달라 직접 우열 비교하지 않는다.
10. [검증 필요] FP16 평가와 FP32 기준 평가의 차이를 측정해 기준 dtype을 확정한다.

## 6. 정성 평가

상태값은 `pass`, `warning`, `fail`, `not_checked`를 기본으로 사용한다. 합격 임계와 예외는 기준 prompt 결과를 본 뒤 승인한다.

| 범주 | 확인 내용 | 주요 실패 신호 | 기본 기록 |
|---|---|---|---|
| 문장 완결성 | 문장이 자연스럽게 마무리되는가 | 중도 절단·끝없는 접속 | 상태·근거 구간 |
| 한국어 문법 | 조사·어미·띄어쓰기·구문이 이해 가능한가 | 구조 붕괴·무의미 조합 | 상태·오류 유형 |
| 반복 생성 | token·구문·문단이 과도하게 반복되는가 | loop·동일 문장 연속 | 반복 통계·샘플 |
| 의미 일관성 | 응답 내부 주제·전제가 유지되는가 | 자기모순·급격한 주제 전환 | 상태·근거 |
| 질문 관련성 | 사용자 요구에 직접 응답하는가 | 무관 답변·입력 복사 | 상태·근거 |
| 사실성 | 검증 가능한 주장에 명백한 오류가 있는가 | 허위 단정·근거 조작 | 사실 오류와 미확인을 구분 |
| 지시 준수 | 요청 형식·제약을 따르는가 | 금지 형식·누락 | 상태·위반 항목 |
| 부적절한 내용 | 유해·차별·민감한 출력 위험이 있는가 | 안전성 범주 위반 | 범주·심각도 후보 |
| 특수문자·영문·숫자 처리 | 혼합 입력을 보존·이해하는가 | 문자 붕괴·숫자 변경 | 입력·출력 diff |
| 긴 문맥 처리 | 앞부분 정보와 요구를 유지하는가 | 맥락 망각·role 혼동 | prompt token 길이 |
| EOS 종료 여부 | `<|end|>`·`<eos>` 또는 제한에서 정상 종료하는가 | 미종료·즉시 빈 종료 | stop reason·token 수 |

- [확정] 점수를 도입하기 전 상태형 판정과 근거를 먼저 사용한다.
- [검증 필요] 수치 점수를 도입하면 평가 기준표, 예시 anchor, 평가자 교육, 동일 샘플 중복 평가와 일치도 보고 방식을 함께 확정한다.
- [확정] 사실 오류와 주관적 선호를 같은 점수로 합치지 않는다.

## 7. 평가 비교 단위

| 비교 단위 | 고정할 조건 | 변경 대상 | 해석 목적 |
|---|---|---|---|
| 초기화 직후 모델 | seed·구조·validation | 학습 전 상태 | loss·생성 기준선 |
| 단일 배치 overfit 모델 | batch·seed·step·구조 | 학습 적용 | 연결 정확성 |
| 사전학습 checkpoint | tokenizer·validation·평가 설정 | checkpoint step | 진행 추세 |
| 최종 사전학습 모델 | 평가 snapshot·환경 | 최종/best 선택 | 완료 판단 |
| SFT 전·후 모델 | parent·tokenizer·prompt·생성 설정·평가 split | SFT 적용 여부 | 대화 개선·기반 회귀 |
| 서로 다른 hyperparameter | 코드·데이터·seed 또는 반복 seed 정책 | 한 번에 명시 변수 | 인과 해석 가능성 |
| Gradient Checkpointing 전후 | model·batch·seed·데이터 순서 | checkpointing flag | VRAM·처리량·수치 차이 |
| Context length 전후 | tokenizer·데이터 source·비교 subset | context 운영값 | 품질·비용 변화; 처리 데이터 차이 주의 |

- [확정] 한 비교에서 여러 변수가 바뀌면 단일 변수 효과로 결론 내리지 않는다.
- [확정] SFT 후 모델은 정확한 parent checkpoint ID와 hash를 기록한다.

## 8. 결과 보존

- [확정] evaluation ID를 experiment ID, checkpoint ID·hash, tokenizer ID, dataset·split version과 연결한다.
- [확정] 지표 원본, 집계 방식, 생성 설정, 고정 prompt version, sample 전체와 실패 사례를 보존한다.
- [확정] 선택된 좋은 샘플만 보고하지 않는다.
- [확정] 대용량 결과 본체와 Git 추적 가능한 요약을 구분한다.
- [검증 필요] 실제 결과 schema·디렉터리·보존 기간은 [실험 관리](../training/experiment-management.md)에서 구체화한다.

## 9. 미결정 사항

- [검증 필요] 모든 정량 합격선과 허용 회귀 폭
- [검증 필요] 평가·checkpoint 주기
- [검증 필요] validation/test 데이터와 split 비율
- [검증 필요] token accuracy 채택 여부와 보조 지표 범위
- [검증 필요] 평가 기준 dtype, batch와 성능 측정 warm-up
- [검증 필요] 사람 평가자 수·일치도 방법·수치 점수 도입 여부
- [검증 필요] 외부 Benchmark 후보와 Leaderboard 최신 규정

## 10. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] 평가 목적·10단계·정량·정성·perplexity·비교 조건의 구현 전 정책 정의 |
