# DohaLM 데이터셋 승인 로그

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-23 |
| 선행 문서 | [데이터셋 후보 등록부](./dataset-candidate-registry.md), [데이터셋 라이선스 검토](./dataset-license-review.md), [데이터 전략](./data-strategy.md) |
| 후속 문서·작업 | 공식 조건 검토, 다운로드 승인 요청 여부 결정, 목적별 승인 기록 |
| 구현 전 필수 여부 | 실제 다운로드·처리·학습 전 예 |

- [확정] 후보 등록과 데이터 사용 승인은 서로 다른 사건이다.
- [확정] 현재 로그는 공식 metadata 검토를 위한 등록만 허용하며 데이터 다운로드·처리·학습·공개를 승인하지 않는다.

## 2. 기록 schema

| 필드 | 계약 |
|---|---|
| 검토일 | ISO 날짜 |
| Dataset ID | 후보 또는 실제 version 식별자 |
| 용도 | tokenizer, pretraining, SFT, preference, evaluation, release 등 |
| 이전 상태 / 새 상태 | 허용된 상태 enum |
| 결정자 | 실제 결정 주체 |
| 근거 | 공식 문서·검사·사용자 결정 |
| 허용 범위 / 금지 범위 | 행위 경계 |
| 재검토 조건 | 다음 전이에 필요한 증거 |
| 관련 문서 | 상대 링크 또는 공식 URL |

## 3. 최초 등록 이벤트

| 검토일 | Dataset ID | 용도 | 이전 상태 | 새 상태 | 결정자 | 근거 | 허용 범위 | 금지 범위 | 재검토 조건 | 관련 문서 |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-07-23 | `AIHUB-71748` | tokenizer·pretraining·SFT·preference 후보 metadata | `unregistered` | `registered` | 사용자 | DohaLM 후보 등록 요청과 AI Hub 공식 상세페이지 확인 | 공식 자료 검토·metadata 등록 | 다운로드, 학습, artifact 공개, 상업 사용 | 공식 약관·subset 구조·문의 결과 | [후보](./dataset-candidate-registry.md#5-aihub-71748), [라이선스](./dataset-license-review.md#4-aihub-71748-검토표) |
| 2026-07-23 | `AIHUB-110` | tokenizer·pretraining 후보 metadata | `unregistered` | `registered` | 사용자 | DohaLM 후보 등록 요청과 AI Hub 공식 상세페이지 확인 | 공식 자료 검토·metadata 등록 | 다운로드, 학습, artifact 공개, 상업 사용 | 공식 약관·source 구조·문의 결과 | [후보](./dataset-candidate-registry.md#6-aihub-110), [라이선스](./dataset-license-review.md#5-aihub-110-검토표) |
| 2026-07-23 | `AIHUB-86` | tokenizer·SFT 보조 후보 metadata | `unregistered` | `registered` | 사용자 | DohaLM 후보 등록 요청과 AI Hub 공식 상세페이지 확인 | 공식 자료 검토·metadata 등록 | 다운로드, 학습, artifact 공개, 상업 사용 | 공식 약관·PII·대화 구조·문의 결과 | [후보](./dataset-candidate-registry.md#7-aihub-86), [라이선스](./dataset-license-review.md#6-aihub-86-검토표) |
| 2026-07-23 | `AIHUB-71477` | 교정 SFT·평가 후보 metadata | `unregistered` | `registered` | 사용자 | DohaLM 후보 등록 요청과 AI Hub 공식 상세페이지 확인 | 공식 자료 검토·metadata 등록 | 다운로드, 학습, artifact 공개, 상업 사용 | 공식 약관·평가 subset·문의 결과 | [후보](./dataset-candidate-registry.md#8-aihub-71477), [라이선스](./dataset-license-review.md#7-aihub-71477-검토표) |
| 2026-07-23 | `AIHUB-653` | tokenizer·pretraining 후보 metadata | `unregistered` | `registered` | 사용자 | DohaLM 후보 등록 요청과 AI Hub 공식 상세페이지 확인 | 공식 자료 검토·metadata 등록 | 다운로드, 학습, artifact 공개, 상업 사용 | 공식 약관·도서 권리·문의 결과 | [후보](./dataset-candidate-registry.md#9-aihub-653), [라이선스](./dataset-license-review.md#8-aihub-653-검토표) |

## 4. 용도별 승인 snapshot

모든 값은 2026-07-23 기준이다.

| Dataset ID | tokenizer | pretraining | SFT | preference | evaluation | tokenizer artifact 공개 | model weight 공개 | 상업 서비스 | 해외 cloud |
|---|---|---|---|---|---|---|---|---|---|
| `AIHUB-71748` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` |
| `AIHUB-110` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` |
| `AIHUB-86` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` |
| `AIHUB-71477` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` |
| `AIHUB-653` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` |

- [확정] `approved` 상태는 0개다.
- [확정] `download_status=not_requested`인 후보는 다운로드·sample 검사를 수행한 것으로 간주하지 않는다.

## 5. 상태 전이 규칙

```text
registered
→ pending_terms_review
→ pending_download_approval
→ downloaded_restricted
→ pending_sample_inspection
→ approved_tokenizer_development
→ approved_tokenizer_candidate
→ approved_pretraining 또는 approved_sft
```

- [확정] 단계는 자동 승격하지 않으며 근거·결정자·허용·금지 범위를 새 로그 행으로 남긴다.
- [확정] tokenizer 승인으로 pretraining·SFT·artifact 공개 승인을 대체하지 않는다.
- [확정] 조건 변경·철회·PII·누수 발견 시 `restricted`, `rejected`, `revoked` 전이를 기록한다.

## 6. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] 5개 AI Hub 후보의 `unregistered → registered` metadata 등록 사건과 전 용도 `pending` snapshot을 기록함 |
