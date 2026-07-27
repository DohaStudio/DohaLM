# Full Pretraining 공개·재배포 경계

- 문서 상태: `approved`
- 마지막 검토일: 2026-07-27
- 관련 문서: [데이터 라이선스 정책](../data/data-license-policy.md), [ADR-004](../decisions/ADR-004-data-governance.md)

## 권리와 공개 상태

- [확정] License는 `approved_student_noncommercial`이다.
- [확정] Commercial use, 원본·파생 Dataset 재배포는 `not_approved`이다.
- [확정] Model checkpoint, tokenizer, raw log, generated sample, PII 상세 공개는 `not_approved`이다.
- [확정] Full 실행 승인은 어떤 공개·배포 승인도 포함하지 않는다.
- [확정] aggregate metrics, config, Dataset fingerprint, training curve와 비공개 run summary는 실행 후 별도 검토 대상이다.

명시적 추가 승인 전에는 어떤 artifact도 Git, 공개 저장소 또는 외부 서비스로 복사·업로드하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | [확정] Candidate A 실행 정책과 공개·재배포 승인을 분리해 유지 |
