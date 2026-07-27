# EOS Generation·Decoding 진단 정책

- 문서 상태: `review`
- 정책 상태: `proposed`
- 마지막 검토일: 2026-07-28
- 태그: `evaluation`, `generation`, `eos`, `decoding`, `privacy`
- 관련 ADR: [ADR-008](../decisions/ADR-008-eos-generation-and-decoding-evaluation-policy.md)

## 목적과 적용 경계

이 제안은 Base Model의 순수 EOS 생성 능력과 decoding 보조 효과를 분리해 측정한다. 승인된
[Candidate B 평가 계약](./candidate-b-evaluation-contract.md)과 Candidate A 공식 Full baseline을
자동 변경하지 않는다. 서비스 decoding, Chat/Instruct 종료 규칙과 강제 종료는 별도 승인 대상이다.

평가는 Candidate A/B Final checkpoint의 `model.eval()`·`torch.inference_mode()` 추론만 허용한다.
optimizer, scheduler, backward, gradient, 학습, checkpoint 수정은 금지한다.

## 동일 조건 계약

- 같은 synthetic·PII-free prompt set, prompt fingerprint와 category를 사용한다.
- 같은 dataset/split/tokenizer/model Full evaluation identity를 검증한다.
- `max_new_tokens` 16/32/64/128을 같은 생성 trajectory의 고정 prefix로 비교한다.
- sampling seed는 artifact와 무관하게 prompt ID와 profile에서 결정해 Candidate A/B에 같은 난수열을 준다.
- 기존 historical prompt identity가 다르면 신규 진단 결과와 섞지 않는다.
- 결과는 immutable external output에 atomic publish하며 기존 artifact를 덮어쓰지 않는다.

## Pure model baseline과 보조 진단

Pure model behavior는 logit bias·forced EOS·최소 길이·반복 보정이 없는 greedy다. 이 결과를 모델
종료 능력의 기준선으로 유지한다.

Decoding-assisted behavior는 temperature 0.7/1.0, top-k 20/50, top-p 0.9/0.95,
repetition penalty 1.05/1.10과 no-repeat bigram/trigram이다. 보조 profile의 EOS 성공을 greedy
모델 점수와 합치거나 기본 정책 채택으로 해석하지 않는다.

## Prompt와 지표

실제 dataset 문장 대신 15개 synthetic category를 사용한다. 미완결·완결 직전·마침표·줄바꿈,
짧고 긴 설명, 질문·대화·목록, code·SQL 종료, 명시적 종료, 최소 prompt, 장문 context와 반복 probe를
각각 한 번 포함한다.

각 step에서 EOS logit/probability/rank, Top-1 logit/probability, 두 margin, EOS Top-5/10,
position, loop 상태와 종료 이유를 기록한다. profile·길이·category별 EOS rate/step, maximum-length,
생성 길이, special/UNK/byte fallback, 반복, distinct-n, loop와 unique-token ratio를 집계한다.

## 개인정보와 산출물

공개 config 외 결과에는 prompt ID와 비민감 category만 기록한다. decoded text, prompt text, raw token
sequence와 전체 token ID는 저장하지 않는다. EOS ID는 공개 special-token 계약의 단일 상수로 manifest에만
기록한다. checkpoint, weight, dataset, 원본 runtime log는 Git에 포함하지 않는다.

## 성공 기준 재검토 후보

현재 승인 계약의 greedy EOS `>0%`, maximum-length `<100%`는 그대로 유지한다. 진단 후 다음 항목을
별도 승인으로 검토할 수 있다.

- 16-token 단일 horizon 대신 64/128-token 결과 병기
- completion shape와 prompt category별 최소 기준
- greedy와 sampling 결과의 별도 판정
- Base Model과 Chat/Instruct Model 종료 계약 분리
- teacher-forced EOS 개선을 generation 통과와 분리한 부분 상태

forced EOS, EOS logit bias, 길이 기반 강제 stop과 외부 문장 분리기는 이번 진단에 적용하지 않으며
서비스 정책 후보로도 별도 승인 없이는 채택하지 않는다.

## 현재 승인 상태

- Candidate A 공식 baseline: 유지
- Candidate B 공식 상태: `evaluated_contract_not_passed` 유지
- 이 정책과 ADR-008: `proposed`
- 기본 decoding 변경: `not_approved`
- 추가 학습: `not_approved`

## 재검토 조건

동일 조건 진단 결과가 확보되고 사용자에게 정책 변경안이 승인되거나, Base/Chat 목적이 확정되거나,
evaluation identity·prompt taxonomy·privacy 계약이 변경될 때 재검토한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | Candidate A/B 동일 조건의 다중 길이·decoding profile 진단 정책 초안 작성 |
