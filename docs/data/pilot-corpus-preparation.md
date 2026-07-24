# Pilot Corpus 준비 계약

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-24 |
| 선행 문서 | [데이터 전략](./data-strategy.md), [데이터 전처리](./preprocessing.md), [데이터 라이선스 정책](./data-license-policy.md) |
| 후속 문서 | [Pilot Pretraining](../training/pilot-pretraining.md) |
| 구현 전 필수 여부 | 예 |

## 2. 입력과 local-only 정책

- [확정] 사용자가 명시한 UTF-8 TXT 또는 JSONL `text_normalized`/명시 text field만 읽는다.
- [확정] metadata·source field 혼입, 빈 record, NUL, 비-NFC, 최소 record 미달을 fail-closed 처리한다.
- [확정] 원문 전체를 메모리에 적재하거나 token artifact·manifest·Git에 저장하지 않는다.
- [확정] source ID, license 상태, record·문자·byte 수와 경로를 제외한 corpus SHA-256을 기록한다.
- [확정] license가 pending이어도 `local_experiment_only=true`이고 공개·재배포·모델 공개가 모두 false인 로컬 학습만 허용한다. 이 예외는 license 또는 목적별 승인을 `approved`로 바꾸지 않는다.
- [제외] validation/test 용도 자료의 train 편입과 임의 데이터 경로 탐색은 허용하지 않는다.

## 3. Tokenizer와 tokenization

- [확정] 우선 사용자가 지정한 기존 tokenizer를 검사하고, 없을 때만 development corpus로 후보 학습을 명시적으로 요청할 수 있다.
- [확정] vocabulary 16,000, SentencePiece Unigram, identity normalization, hard vocab limit, special token ID 0~7을 강제한다.
- [확정] 16,000 vocabulary 생성이 불가능하면 자동 축소하지 않고 중단한다.
- [확정] tokenizer·corpus fingerprint, encode/decode smoke, token 수와 unknown ratio를 기록한다.
- [확정] record text 대신 token ID, label, attention mask만 JSONL에 저장하며 pad label은 `-100`이다.

## 4. Split과 packing

- [확정] text fingerprint와 고정 seed를 SHA-256으로 조합해 기본 train 95%/validation 5% split을 만든다.
- [확정] exact duplicate는 같은 fingerprint를 사용하므로 양 split에 동시에 들어갈 수 없다.
- [확정] train과 validation을 분리해 각각 packing하며 validation은 학습 loader에 전달하지 않는다.
- [확정] 기본 packing은 context 256, continuous, EOS separator, 마지막 remainder drop이다.
- [확정] record-boundary와 remainder padding도 지원하며 padding label은 `-100`이다.
- [검증 필요] 실제 corpus에서 packing 후 validation sequence가 최소 1개 이상인지 사전 보고 단계에서 확인한다.

## 5. 산출물

Git 제외 output에 `train.jsonl`, `validation.jsonl`, `corpus-manifest.json`, `split-manifest.json`, `tokenization-manifest.json`, `token-statistics.json`, `corpus-fingerprint.json`을 원자적으로 게시한다. [확정] 기존 output은 덮어쓰지 않으며 원본 corpus를 수정하지 않는다.
