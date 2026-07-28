# EOS Generation·Decoding 진단 결과

- 문서 상태: `review`
- 실행 당시 정책 상태: `proposed`
- 현재 정책 상태: `approved` (2026-07-28, 결과 fingerprint 불변)
- 실행일: 2026-07-28
- Diagnostic ID: `eos-generation-decoding-20260728-01`
- 실행 commit: `2419608c7147da3e773ad96a63d0a313c7fce0d1`
- Result fingerprint: `sha256:db58082b055f36728d1abac1b9eeeb159daa08bd25b3fb870a7a66afc9a96026`
- 관련 정책: [EOS Generation·Decoding 정책](./eos-generation-decoding-policy.md), [ADR-008](../decisions/ADR-008-eos-generation-and-decoding-evaluation-policy.md)

## 실행 범위와 불변성

Candidate A/B Final을 동일한 신규 synthetic prompt fingerprint
`sha256:2cd1fee275601b82d34da9c7fd0f0398abd7dfb15b6a35afbcdbdb96164b37fa`, seed 17,
15개 category와 11개 decoding profile에서 비교했다. 최대 128-token trajectory를 생성하고
16/32/64/128-token prefix를 각각 집계했다. historical prompt 결과와 섞지 않았다.

실행은 RTX 3060 Ti에서 341.208초 걸렸다. optimizer·scheduler·backward·gradient는 0건이며 decoded
text와 raw token sequence를 저장하지 않았다. Candidate A checksum
`sha256:80f2aee72605ffcfeea13e158cbf7a132682591cf4295cd01c16f514686338f8`과 Candidate B checksum
`sha256:f3edc978db9d88e9de8e2e423a28291e9f35e2e163f0413c0e27e95facc55395`은 전후 동일했다.
13개 output file checksum과 model state digest도 모두 일치했다.

## 길이별 EOS 결과

### Pure greedy

| Model | 16 EOS / max | 32 EOS / max | 64 EOS / max | 128 EOS / max |
|---|---:|---:|---:|---:|
| Candidate A | 0% / 100% | 0% / 100% | 0% / 100% | 0% / 100% |
| Candidate B | 0% / 100% | 0% / 100% | 0% / 100% | 0% / 100% |

128-token greedy에서 Candidate B의 mean EOS rank/probability는 5,958.04/0.016789%로 Candidate A의
7,437.89/0.012416%보다 나았지만 EOS는 선택되지 않았다. mean Top-1−EOS logit margin은 B 13.4421,
A 14.2341이었다. Candidate B의 greedy adjacent repetition은 A 67.5591%보다 낮은 44.7244%였으나
두 모델 모두 32 token 이후 degenerate loop 100%였다.

### Decoding-assisted

| Model/Profile | 16 EOS | 32 EOS | 64 EOS | 128 EOS | 128 max-length | 128 loop |
|---|---:|---:|---:|---:|---:|---:|
| A, temperature 1.0 | 0% | 0% | 0% | 20.00% | 80.00% | 0% |
| B, temperature 1.0 | 0% | 0% | 0% | 13.33% | 86.67% | 6.67% |
| A, top-p 0.9 | 0% | 6.67% | 13.33% | 13.33% | 86.67% | 0% |
| B, top-p 0.9 | 6.67% | 6.67% | 6.67% | 13.33% | 86.67% | 26.67% |
| A, top-p 0.95 | 0% | 6.67% | 13.33% | 13.33% | 86.67% | 0% |
| B, top-p 0.95 | 0% | 0% | 6.67% | 20.00% | 80.00% | 6.67% |
| A, repetition 1.10 | 0% | 0% | 0% | 0% | 100% | 100% |
| B, repetition 1.10 | 0% | 0% | 6.67% | 6.67% | 93.33% | 93.33% |
| A, no-repeat bigram | 0% | 0% | 0% | 0% | 100% | 0% |
| B, no-repeat bigram | 0% | 0% | 0% | 33.33% | 66.67% | 0% |

temperature 0.7과 top-k 20/50은 두 모델 모두 모든 길이에서 EOS 0%였다. Candidate B no-repeat
bigram은 EOS 5/15개, mean/median step 88.8/90을 기록하고 bigram·trigram distinct를 100%로 유지했다.
이는 순수 모델 성공이 아니라 반복 억제에 의한 decoding-assisted termination이다.

## Prompt category와 step-level 관찰

Candidate B의 128-token assisted EOS는 완결형 전체 9.09%, 미완결형 4.55%, domain-like 18.18%, 일반
6.29%였다. 개별 profile까지 포함한 성공은 완결 직전, 줄바꿈 문단, code·SQL 종료, 장문 context,
짧은 설명과 대화 category에서 관찰됐다. 반면 greedy에서는 마침표·질문·명시적 종료를 포함한 15개
category 모두 EOS 0%였으므로 punctuation 또는 완결형 자체가 pure greedy 종료를 만들었다고 결론낼 수 없다.

Candidate B는 loop 전 step에서 mean EOS rank 3,685.44, probability 0.066351%였고 loop 시작 후에는
5,198.29, 0.019839%로 악화됐다. Candidate A도 3,498.59/0.085661%에서
7,139.65/0.011445%로 악화됐다. EOS가 Top-5 안에 있으나 선택되지 않은 step은 B 202건, A 161건이었다.
긴 생성에서 assisted EOS가 생기지만 128-token greedy에서도 나오지 않아 short-horizon만의 문제는 아니다.

## 해석과 상태 제안

- Pure model behavior: Candidate B는 Candidate A보다 greedy EOS rank·probability와 반복이 일부 개선됐지만
  128 token까지 EOS 선택 0%로 승인 계약을 통과하지 못한다.
- Decoding-assisted behavior: sampling과 특히 no-repeat bigram에서 종료가 나타나 모델이 EOS를 완전히
  배제한 것은 아니지만, 보조 정책이 없으면 종료하지 않는다.
- 상태 제안: `decoding_assisted_termination_only`.
- 공식 상태: historical `evaluated_contract_not_passed` 유지.
- 실행 당시 Candidate A: 공식 Full baseline 유지.
- 정책·ADR-008: 진단 후 2026-07-28 `approved`; 이 결과의 historical 판정은 비소급.

Base Model의 EOS 기준을 바꾸거나 no-repeat bigram을 서비스 기본값으로 채택하거나 추가 학습을 수행하는
결정은 이 결과에 포함되지 않는다.

[확정] 후속 [ADR-009](../decisions/ADR-009-candidate-b-official-reassessment.md)는 result fingerprint를
변경하지 않고 Candidate B를 current Base baseline으로 승인했다. 이 진단의 historical 상태는 그대로다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | ADR-008 승인과 historical 결과 비소급 상태를 메타데이터에 반영; 결과 fingerprint 불변 |
| 2026-07-28 | 동일 A/B 다중 길이·decoding profile 진단과 상태 제안 기록 |
