# 생성 평가 정책

- 문서 상태: `review`
- 마지막 검토일: 2026-07-27
- 태그: `evaluation`, `generation`, `privacy`

## Prompt set

저장소에는 AI Hub 문장을 복사하지 않은 synthetic prompt만 둔다. 한국어 이어쓰기·설명, 한영 혼합, 숫자·날짜, 특수문자, 줄바꿈, code shape, `.invalid` URL/email shape와 반복 probe를 포함한다. 정답 benchmark가 아니라 생성 안정성 probe이다.

## 실행과 지표

현재 기본 전략은 deterministic greedy이며 sampling adapter는 후속 승인 전 비활성화한다. EOS 도달, 길이 제한 도달, empty, UNK/byte fallback/special token 비율, adjacent 및 repeated 4-gram, unique ratio, distinct-1/2/3, degenerate loop를 집계한다.

[확정] Candidate A Final 제한 진단에서는 sampling 6종이 반복·loop를 낮췄지만 모든 profile이 16-token 제한에서 EOS 0%였다. 이 결과는 기본 greedy 또는 decoding 정책을 변경하지 않으며 [진단 문서](./eos-incomplete-block-diagnostic.md)와 승인된 [Candidate B 계약](./candidate-b-evaluation-contract.md)의 근거로만 사용한다.

[확정] EOS success policy는 2026-07-27 승인됐으며 Candidate A Full을 기준선으로 한다. Candidate B training과 기본 decoding 변경은 승인하지 않는다.

결과에는 prompt ID hash, category, 입력 token 길이, 생성 token hash와 집계값만 저장한다. prompt text, decoded generation, 전체 token ID 배열은 저장하지 않는다. 실제 text 저장이 필요한 경우 별도 사용자 승인 없이는 fail-closed한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | synthetic prompt와 text-free generation statistics 구현 계약 반영 |
| 2026-07-27 | FP32 제한 decoding 비교와 정책 비변경 경계 기록 |
| 2026-07-27 | EOS success 및 Candidate B 생성 평가 계약 승인 반영 |
