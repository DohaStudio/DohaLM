# 비공개 최소 record preview 계약

## 문서 정보

- 문서 상태: `review`
- 마지막 검토일: 2026-07-24
- 선행 문서: [층화 record review 계약](./stratified-record-review.md)
- 후속 작업: 사용자 승인 후 별도 비공개 preview 실행과 수동 검토
- 구현 전 필수 여부: 비공개 원문 preview 생성 전 예

## 목적과 기본 차단

- [확정] field 이름만으로 판단할 수 없는 PII·민감정보·한국어 품질을 사람이 검토할 때만 최소 `text` 조각을 외부 비공개 경로에 생성한다.
- [확정] 기본 정책은 `pending_user_review`이며 이 상태에서는 content를 읽지 않는 dry-run만 허용한다.
- [확정] preview 검토는 라이선스, tokenizer, pretraining, SFT 또는 evaluation 승인을 뜻하지 않는다.
- [제외] 전체 record JSON, metadata, source와 다른 field 값은 저장하지 않는다.

## 승인 계약

실제 생성에는 `approval.status: approved`, 승인자·승인 시각·만료 시각, reviewer가 모두 필요하다. 목적은 `manual_pii_and_quality_review`, 출력 token은 `external_private_review_root`, `allow_unredacted`는 반드시 `false`다.

| 제한 | 기본 | 최대 |
|---|---:|---:|
| Record | 5 | 10 |
| Record당 Unicode code point | 300 | 500 |
| 보존 일수 | 3 | 7 |
| 허용 field | `text` | `text` |

보존 만료는 승인 만료와 `created_at + retention_days` 중 이른 시각이다. 만료 후 review 완료를 차단하며 자동 삭제는 하지 않는다.

## 선택과 비노출

- [확정] 기존 승인 mapping과 층화 candidate를 재사용하고 archive·entry마다 최대 1개 record만 선택한다.
- [확정] Dataset ID, 익명 archive·entry hash, record index, strata, schema signature와 고정 seed를 SHA-256에 반영한다.
- [확정] preview 파일에는 익명 식별자와 redacted `text` 일부만 기록한다. Manifest에는 원문과 로컬 절대경로를 기록하지 않는다.
- [확정] 외부 `analysis/private-review/<Dataset ID>/<run-id>/` 밖, 원본 root, 저장소 내부 출력은 거부한다.

## Redaction과 문자 제한

표준 라이브러리 정규식으로 이메일, 한국 전화번호, 주민등록번호 형태, 카드번호 형태, 유효 IPv4, URL query, 긴 숫자 식별자 후보를 치환한다. 문자 제한에는 `[TRUNCATED]` 표시도 포함된다.

- [검증 필요] 자동 redaction은 모든 PII 제거를 보장하지 않는다.
- [확정] 모든 preview 상태는 `manual_review_required`이며 사람 검토 전 `clear`로 간주하지 않는다.
- [확정] reviewer note에는 원문이나 preview 문장을 복사하지 않는다.

## 산출물과 삭제

실제 승인 실행은 `preview-*.txt`, `preview-manifest.json`, `review-checklist.json`, `deletion-manifest.json`, `run-summary.json`을 만든다. Dry-run은 네 JSON manifest만 만들고 preview text는 0건이다. 기존 run 덮어쓰기는 금지한다.

`deletion-manifest.json`은 기대 파일, 만료 시각, 삭제 필요 여부와 수동 삭제 검증 상태를 기록한다. 사용자 명시 명령 없이 자동 삭제하지 않는다.

## 실행

```powershell
python -m scripts.datasets.generate_private_record_previews --config configs/local-datasets.yaml --dataset AIHUB-71748 --manual-mapping configs/aihub-71748-path-mapping.yaml --preview-policy configs/aihub-71748-private-preview.yaml --dry-run --json
python -m scripts.datasets.review_private_previews --review-dir "<외부 비공개 run 경로>" --check-expiration --json
```

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-24 | [확정] 승인·최소 선택·redaction·보존·수동 review·외부 출력 계약을 최초 작성함 |
