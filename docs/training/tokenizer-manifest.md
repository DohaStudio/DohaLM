# Tokenizer Smoke Manifest와 호환성 계약

## 문서 정보

- 문서 상태: `review`
- 마지막 검토일: 2026-07-24
- 선행 문서: [Tokenizer smoke](./tokenizer-smoke.md), [Phase 2 계약](./phase2-tokenizer-contract.md)
- 후속 작업: 운영 tokenizer 8개 artifact schema와 version 정책 확정
- 구현 전 필수 여부: Smoke bundle 소비 전 예

## Smoke artifact

Smoke bundle은 다음 5개 파일을 atomic staging 후 게시한다.

1. `tokenizer.model`
2. `tokenizer.vocab`
3. `manifest.json`
4. `fingerprint.json`
5. `statistics.json`

- [확정] 이는 운영 후보에 요구되는 8개 artifact를 대체하지 않는다.
- [확정] 기존 output은 덮어쓰지 않고 실패한 staging은 게시하지 않는다.

## Manifest

`manifest.json`은 다음을 기록한다.

- Schema와 `synthetic_tokenizer_smoke` artifact 종류
- `smoke_only_not_approved` 상태
- 요청 vocabulary와 실제 piece 수
- 명시적 trainer config
- SentencePiece version
- ADR-003 special token mapping
- Synthetic corpus fingerprint·record·문자·byte 수
- Model·vocab checksum
- Tokenizer fingerprint
- 승인 및 Gate 3 영향 `none`

절대경로, 사용자명, 머신명과 원문 record는 기록하지 않는다.

## Fingerprint

Fingerprint는 canonical JSON과 SHA-256을 사용한다. 입력은 다음과 같다.

- `tokenizer.model` SHA-256
- Trainer config
- Special token 문자열과 ID
- SentencePiece version

`created_at`, output 경로, staging 경로와 사용자 환경 식별자는 제외한다. 형식은 `sha256:<64 lowercase hex>`다.

## Statistics

Synthetic corpus를 완성 model로 다시 encode해 record·문자·token 수, 평균 token 수, 평균 문자/token, UNK 수·비율, configured character coverage, byte fallback과 vocabulary 사용률을 기록한다. 원문 예시는 저장하지 않는다.

## Compatibility

| 상태 | 조건 |
|---|---|
| `compatible` | Fingerprint가 동일함 |
| `warning` | Fingerprint는 다르지만 model type, piece 수, special mapping, normalization과 fallback이 같음 |
| `incompatible` | 위 구조 호환 필드 중 하나 이상이 다름 |

- [확정] Smoke compatibility 결과는 model checkpoint 호환 승인이 아니다.
- [검증 필요] 운영 tokenizer version·migration과 checkpoint 적용 정책은 Gate 3 전에 확정해야 한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-24 | [확정] 5개 smoke artifact, fingerprint, 통계와 compatibility 상태 계약을 작성함 |
