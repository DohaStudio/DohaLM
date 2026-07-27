# Candidate A 10M Token Full Pretraining 결과

- 문서 상태: `review`
- 마지막 검토일: 2026-07-27
- 관련 문서: [실행 계획](./full-pretraining-execution-plan.md), [승인 manifest](./full-pretraining-approval.manifest.yaml), [Readiness](./full-pretraining-readiness.md)

## 실행 판정

- [확정] Run ID: `FULL-PRETRAIN-CANDIDATE-A-20260727-0001`
- [확정] 상태: `completed`
- [확정] optimizer step 4,883, scheduled/target token 10,000,384, equivalent epoch 0.14024222267534303
- [확정] 전체 실행 시간: 1,310.184초
- [확정] 승인 소비: optimizer step 1, `2026-07-27T19:38:29+09:00`
- [확정] 자동 연장·Resume·재시작·Candidate B/C 전환: 0건

## Identity

| 항목 | Fingerprint |
|---|---|
| Training lineage | `sha256:a0677dc18dbc98371d349aef0f83ea610ab4a984657412bd1518b883a66bd3c6` |
| Tokenizer | `sha256:9ce19a118a893fd69bad3124f94cea78f804d450a2ff6a9c4149b3064312f0ff` |
| Model | `sha256:a7a4d109c6d9f385bc65f33a0c5b9a0e9af218764b2e0648ea0c81b317fed106` |
| Initialization | `sha256:c580d1786efc2aa85ebb4c9ada4cf28ac280b3367beeee69cd263dc25b7a3356` |
| Candidate config | `sha256:b1c6979fe681f6c69dec124f0dcce457ea1e26d511f285ee16eab1c185cea4f5` |
| Evaluation | `sha256:0265e2d4b2ab94cd4f3df3afba14e671a58cc76b8e11434ebd64db36506f8790` |

## 학습과 Evaluation

| 항목 | 결과 |
|---|---:|
| 첫 / 마지막 train loss | 249.1661 / 6.0697 |
| Train loss 최소 / 최대 | 5.0584 / 250.5206 |
| LR 최대 / 마지막 | 0.0003 / 0.00003 |
| 평균 처리량 | 10,053.21 token/s |
| 평균 optimizer step | 0.20635초 |
| 시작 evaluation loss / perplexity | 251.0258 / 1.0450e109 |
| 종료 evaluation loss / perplexity | 6.3690 / 583.4888 |
| 평가 sequence / target token | 각 14,329 / 3,653,719 |

Train loss 구간 평균은 step 1~1,000에서 14.8103, 1,001~2,442에서 6.8698, 2,443~4,000에서 6.4778, 4,001~4,883에서 6.3746이다.

## 안전성과 자원

- [확정] NaN/Inf/OOM/AMP skip: 0건
- [확정] 반복 loss·gradient 안전장치 발동: 0건
- [확정] Peak allocated/reserved VRAM: 524,190,208 / 593,494,016 bytes
- [확정] Peak CPU working set: 1,027,362,816 bytes
- [확정] 실행 중 최소 free disk: 991,952,576,512 bytes
- [확정] 전체 output: 408,985,121 bytes, 파일 27개
- [확정] 원문·prompt·continuation·전체 token ID 저장: 0건

## Checkpoint

| Checkpoint | Step | Token | Bundle bytes | Checksum manifest SHA-256 |
|---|---:|---:|---:|---|
| `checkpoint-2442` | 2,442 | 5,001,216 | 202,790,078 | `sha256:99519a1dcb3dd2ac667229184735dd54b08db874fe4a6f3e6cf45010b0744d7e` |
| `checkpoint-4883` | 4,883 | 10,000,384 | 202,790,081 | `sha256:80f2aee72605ffcfeea13e158cbf7a132682591cf4295cd01c16f514686338f8` |

두 checkpoint 모두 필수 파일, 개별 checksum, global/micro step, scheduler, sampler와 identity 검증을 통과했다. Staging 잔존은 0개이다.

## 승인과 후속 경계

- [확정] single-use 실행 승인은 소비됐고 `execution_allowed: false`이다.
- [확정] 동일 Run ID/output 재사용은 차단한다.
- [확정] Resume, 추가 학습, Candidate B/C, SFT, RLHF, Preference Training과 공개·재배포는 별도 사용자 승인 전까지 `not_approved`이다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | [확정] Candidate A 10M 단일 실행과 checksum·runtime 검증 결과 기록 |
