# Candidate A Final Quick Evaluation 결과

- 문서 상태: `review`
- 마지막 검토일: 2026-07-27
- 태그: `evaluation`, `candidate-a`, `quick`, `gpu`
- 관련 문서: [평가 계획](./evaluation-plan.md), [평가 지표](./evaluation-metrics.md), [리더보드](./model-evaluation-leaderboard.md)

## 실행 identity

- canonical evaluation ID: `candidate-a-final-quick-20260727-02`
- artifact: `candidate-a-final`, checkpoint step 4,883
- profile: Quick, deterministic 128 packed sequence
- subset fingerprint: `sha256:0bc66ac5061fa0a5c0415cd78ef4fa663265e6ed8bfb054652874addb375b254`
- evaluation config fingerprint: `sha256:a5b12cceaa07c2ce59d303f74f7569d4a6bc37e3a515e4f9a6f7a60d67b36c5c`
- result fingerprint: `sha256:21649cca219f8254937deb6af7d9402171a68e4589630194aa4d18c2ca1ad2ab`

## 집계 결과

| 지표 | 값 |
|---|---:|
| target token | 32,640 |
| loss / perplexity | 6.282144 / 534.9342 |
| Top-1 / Top-5 / Top-10 | 18.2353% / 30.8915% / 37.0221% |
| packed / rebased Top-1 | 18.2353% / 19.2962% |
| position gap | +1.0609%p |
| generation EOS / maximum length | 0% / 100% |
| generation adjacent repetition | 45.3333% |
| distinct-1 / 2 / 3 | 0.3813 / 0.4800 / 0.5786 |
| continuation exact | 0 / 16 |
| FP16/FP32 loss gap | 0.000123, 허용치 이내 |
| teacher-forced 시간 / 처리량 | 1.031초 / 31,668 token/s |
| peak allocated / reserved VRAM | 592,825,856 / 933,232,640 bytes |
| CPU working set | 892,436,480 bytes |

## 안전성과 해석

evaluation dataset checksum, checkpoint checksum과 in-memory model state fingerprint는 실행 전후 동일했다. optimizer, scheduler, backward와 gradient 생성은 0건이다. raw text, decoded generation, prefix·continuation과 전체 token ID는 저장하지 않았다. 최초 성공 run `-01`과 최종 검증 run `-02`의 deterministic result fingerprint도 동일했다.

Quick 결과는 Candidate A가 기존 전체 평가의 loss 6.3690과 같은 규모의 손실을 보인다는 개발 검증이다. 16-token synthetic generation이 모두 길이 제한에 도달하고 EOS가 없으며 반복률이 높으므로 생성 품질 한계를 나타낸다. Quick subset은 Full 평가나 일반화 benchmark를 대신하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | Candidate A Final Quick evaluation 집계와 안전 검증 기록 |
