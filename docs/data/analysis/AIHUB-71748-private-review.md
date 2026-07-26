# AIHUB-71748 비공개 preview 준비 상태

## 문서 정보

- 문서 상태: `review`
- 마지막 검토일: 2026-07-26
- 선행 문서: [비공개 최소 preview 계약](./private-record-preview.md), [AIHUB-71748 schema review](./AIHUB-71748-schema-review.md)
- 후속 작업: 사용자의 기간 제한 승인 후 별도 실제 실행
- 구현 전 필수 여부: 실제 AIHUB-71748 preview 생성 전 예

## 현재 상태

- [확정] 로컬 정책은 `pending_user_review`다.
- [확정] 실제 preview 생성과 원문 파일 저장은 수행하지 않았다.
- [확정] 승인 없는 dry-run만 수행하며 ZIP entry content read는 0 byte로 유지한다.
- [확정] Candidate는 `registered`, 라이선스는 `approved_student_noncommercial`, tokenizer는 `approved_tokenizer_development`, pretraining·SFT·evaluation 승인은 `pending`, Gate 3는 `planned`다.

## Pending dry-run 결과

| 항목 | 결과 |
|---|---|
| Run ID | `private-preview-dry-242db566da4d6d37` |
| 상태 | `dry_run_blocked_pending_approval` |
| 대용량 mapping 후보 | 571개 |
| 선택 entry 계획 | 1개 |
| 검사 entry | 0개 |
| Content read | 0 byte |
| Preview text | 0건 |
| 원본 변경 | 없음 |

- [확정] Dry-run 산출물은 JSON manifest 4개뿐이며 원문 preview 파일은 없다.
- [검증 필요] 실제 `text` 값의 PII·민감정보·품질은 사용자 승인 후 별도 실행과 사람 검토 전에는 판단할 수 없다.

## 승인 전 금지

- [제외] 전체 record 또는 전체 `text` 저장
- [제외] 저장소, 원본 root, 일반 분석 문서 경로에 preview 생성
- [제외] corpus 생성, tokenizer 학습, 모델 학습
- [제외] 자동 redaction 결과를 PII clear 또는 데이터 사용 승인으로 해석

## 실제 실행 선행 조건

사용자는 추적되지 않는 로컬 정책에서 승인자·승인 시각·만료 시각·reviewer를 명시해야 한다. 실행 전 공식 이용조건, 검토 목적, 최대 record·문자·보존 기간과 삭제 책임을 다시 확인한다. 실행 후에는 checklist 수동 검토와 보존 만료 삭제 검증이 필요하다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-26 | [확정] 현재 학생·비상업 라이선스와 tokenizer `under_review` 상태를 동기화함 |
| 2026-07-24 | [확정] pending 정책과 실제 preview 0건 원칙을 기록함 |
