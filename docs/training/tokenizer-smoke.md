# Phase 2 Tokenizer Smoke Pipeline

## 문서 정보

- 문서 상태: `review`
- 마지막 검토일: 2026-07-24
- 선행 문서: [Phase 2 토크나이저 계약](./phase2-tokenizer-contract.md), [ADR-003](../decisions/ADR-003-tokenizer-method.md), [ADR-004](../decisions/ADR-004-data-governance.md)
- 후속 작업: 승인된 development corpus 확보 후 운영 후보 비교
- 구현 전 필수 여부: Smoke 재실행 전 예

## 범위와 상태

- [확정] 이 pipeline은 `tests/fixtures/tokenizer/`의 직접 작성한 synthetic UTF-8 TXT만 허용한다.
- [확정] AI Hub, Phase 1 실제 artifact, `train.jsonl`, `records.jsonl`, preview와 private review 파일은 사용하지 않는다.
- [확정] SentencePiece Unigram trainer, vocabulary·special token 검사, encode/decode, fingerprint, manifest, 통계와 호환성 smoke를 구현했다.
- [확정] Smoke 성공은 tokenizer 승인, 운영 artifact 완성 또는 Gate 3 통과가 아니다.

## 의존성과 결정론

- SentencePiece: `0.2.2`
- Model type: `unigram`
- Smoke vocab: `128`, `256`, `512`만 허용
- 기준 실행: vocab `256`, `character_coverage=1.0`, `hard_vocab_limit=true`
- 입력 순서: fixture 순서 고정
- Shuffle: `false`
- Threads: `1`
- Normalization: `identity`
- Byte fallback: `false`

Trainer는 corpus 문장을 memory iterator로 전달하고 model을 memory writer로 받아 output·temporary 절대경로가 binary model에 들어가지 않게 한다. 같은 입력·설정·SentencePiece version에서 model checksum과 fingerprint가 같은지 회귀 검사한다.

## Synthetic corpus 경계

CLI는 저장소의 `tests/fixtures/tokenizer/` 아래 `.txt`만 허용한다. 경계 밖 파일, 비 TXT, 빈 corpus, 잘못된 UTF-8과 NUL을 거부한다. 실제 데이터 내용의 자동 판별을 주장하지 않으며 경로 정책과 개발 절차를 함께 적용한다.

## 실행

```powershell
python -m scripts.tokenizer.train_tokenizer `
  --corpus tests/fixtures/tokenizer/corpus.txt `
  --output tests/output/tokenizer `
  --vocab-size 256

python -m scripts.tokenizer.inspect_tokenizer `
  --model tests/output/tokenizer/tokenizer.model

python -m scripts.tokenizer.validate_tokenizer `
  --model tests/output/tokenizer/tokenizer.model
```

`tests/output/`은 Git에서 제외하며 기존 output을 덮어쓰지 않는다.

## 검증 결과

신규 tokenizer 회귀 22개와 기존 회귀를 합친 전체 215개 테스트가 통과했다.

| 항목 | 결과 |
|---|---:|
| Synthetic record | 40 |
| 요청/실제 piece | 256 / 256 |
| Special token | ADR-003 ID 0~7 일치 |
| 전체 token | 585 |
| 평균 token/record | 14.625 |
| 평균 character/token | 1.776068376068376 |
| UNK | 0 |
| Vocab 사용 | 190 / 256 (0.7421875) |
| Fingerprint | `sha256:230151dffc2544bbb1c31d202babe68976e6f3e17c22339458e94cca75f79abe` |

- [가정] 위 통계는 작은 synthetic fixture의 smoke 결과일 뿐 한국어 corpus 품질을 대표하지 않는다.
- [검증 필요] 실제 승인 corpus의 coverage, byte fallback, UNK, whitespace와 16,000 vocabulary는 별도 후보 검증이 필요하다.

## Gate와 승인

- Candidate: `registered`
- License review: `pending_terms_review`
- Tokenizer/pretraining/SFT/evaluation: `pending`
- Gate 3: `planned`

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-24 | [확정] Synthetic corpus 전용 TOK-001~012 smoke 구현과 256-piece 실행 결과를 기록함 |
