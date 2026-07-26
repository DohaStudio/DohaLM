# DohaLM 데이터셋 승인 로그

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-26 |
| 선행 문서 | [데이터셋 후보 등록부](./dataset-candidate-registry.md), [데이터셋 라이선스 검토](./dataset-license-review.md), [데이터 전략](./data-strategy.md) |
| 후속 문서·작업 | 공식 조건·취득 계보 검토, 목적별 승인 기록 |
| 구현 전 필수 여부 | 실제 데이터 처리·학습 전 예 |

- [확정] 후보 등록과 데이터 사용 승인은 서로 다른 사건이다.
- [확정] 현재 로그는 공식 metadata 검토와 로컬 보유 사실의 제한 상태 기록만 포함하며 데이터 처리·학습·공개를 승인하지 않는다.

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

## 3.1 로컬 보유 상태 정합화 이벤트

| 검토일 | Dataset ID | 용도 | 이전 상태 | 새 상태 | 결정자 | 근거 | 허용 범위 | 금지 범위 | 재검토 조건 | 관련 문서 |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-07-26 | `AIHUB-71748` | 로컬 보유 상태 metadata 정합화 | `download_status: not_requested` | `download_status: downloaded_restricted` | 사용자 정합화 지시 | 로컬 상대경로 `extracted/AIHUB-71748` 아래 ZIP 55개·17,256,335,769 bytes 존재와 기존 읽기 전용 inventory 확인 | 파일·크기·ZIP 중앙 디렉터리·소형 inventory metadata 기록 | record 본문 열람, 추출, corpus 생성, tokenizer·학습, Adapter 활성화, artifact 공개 | 취득 증빙·제공자 version·ZIP별 내용 SHA-256·공식 이용조건·PII·목적별 승인 | [package manifest](./aihub-71748-local-package.manifest.yaml), [registry snapshot](./dataset-registry.md#5-aihub-71748-로컬-제한-package-snapshot), [구조 분석](./analysis/AIHUB-71748.md), [라이선스](./dataset-license-review.md#4-aihub-71748-검토표) |

- [확정] 이 이벤트는 누락된 로컬 보유 사실을 바로잡는 비승인 상태 기록이다. `candidate_status`, 라이선스 검토와 모든 목적별 승인 상태는 변경하지 않는다.

## 3.2 Checksum·tokenizer development 검토 이벤트

| 검토일 | Dataset ID | 용도 | 이전 상태 | 새 상태 | 결정자 | 근거 | 허용 범위 | 금지 범위 | 재검토 조건 | 관련 문서 |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-07-26 | `AIHUB-71748` | tokenizer development 검토 | `tokenizer: pending` | `tokenizer: under_review` | 사용자 | 원본 ZIP 55개 개별 SHA-256과 검토 계획 작성 승인 | 원본 ZIP byte checksum, 소형 checksum inventory, 공식 조건·PII·누수·field·표본·저장 계획 정리 | Record 본문 열람, 표본·PII 검사, Adapter, corpus·tokenization·tokenizer/모델 학습, Gate 변경 | 공식 이용조건·취득 증빙·tokenizer 허용 여부·PII·누수·text field·제한 표본 범위의 별도 승인 | [checksum inventory](./aihub-71748-zip-checksums.manifest.yaml), [검토 계획](./aihub-71748-tokenizer-development-review-plan.md), [라이선스](./dataset-license-review.md#4-aihub-71748-검토표) |

- [확정] `under_review`는 검토 개시 상태이며 실제 목적별 승인이 아니다. `approved` 상태는 여전히 0개다.

## 3.2.1 운영 16k tokenizer development 승인 이벤트

| 검토일 | Dataset ID | 용도 | 이전 상태 | 새 상태 | 결정자 | 근거 | 허용 범위 | 금지 범위 | 재검토 조건 | 관련 문서 |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-07-26 | `AIHUB-71748` | 운영 16k tokenizer development | `tokenizer: under_review` | `tokenizer: approved_tokenizer_development` | 사용자 | Training의 `data_info[].contents`만으로 최소 corpus와 Unigram/BPE 16k 후보 2개를 만들고 비교하도록 명시 승인 | Training 일반 원천데이터, tokenizer 전용 Adapter, corpus manifest·fingerprint·통계, SentencePiece 후보 학습·비교 | Validation, evaluation/benchmark, RLHF, SFT, instruction/answer/label/role/metadata, Pretraining, 모델·GPU 학습, Gate 7, 재배포 | 범위 변경, source checksum 불일치, 후보 공개·모델 연결·Gate 3 상태 전환 | [검토 계획](./aihub-71748-tokenizer-development-review-plan.md), [package manifest](./aihub-71748-local-package.manifest.yaml), [평가 제외 목록](./evaluation-exclusion-list.md) |
| 2026-07-26 | `AIHUB-71748` | 16k 후보 evidence | `Gate 3: planned` | `Gate 3: planned` | Codex 조사, 사용자 판정 대기 | 제한 corpus 437 MiB, Unigram/BPE 각 16,000 pieces·fingerprint·비교 완료 | checksum·aggregate 품질·속도·한국어/숫자/영어/특수문자 probe 검토 | 후보 모델의 Pretraining 연결, 공개·재배포, Gate 3 통과 처리 | 실제 표본 UNK 0.20%·UNK line 26.17%·round-trip 72.35% 보완과 사용자 승인 | [corpus manifest](./aihub-71748-tokenizer-corpus.manifest.yaml), [후보 평가](../training/aihub-71748-operating-tokenizer-evaluation.md) |
| 2026-07-26 | `AIHUB-71748` | 16k v2 보완 후보 evidence | `Gate 3: planned` | `Gate 3: planned` | 사용자 보완 작업 승인, 최종 판정 대기 | 기존 corpus와 v1을 보존하고 byte fallback·whitespace 보존 Unigram/BPE v2를 별도 생성 | 동일 Training 표본 10,000건 UNK 0%·exact/ID round-trip 100%, 19개 synthetic probe 실패 0, bundle checksum·fingerprint 검증 | Pretraining·Overfit·모델 연결, 공개·재배포, Gate 3 통과 처리 | 별도 경로 재학습의 vocab·encode ID는 같으나 출력별 metadata로 binary fingerprint가 다른 판정, v2 Unigram 최종 선택과 Gate 3 상태 전환의 사용자 승인 | [v2 요약](./aihub-71748-operating-tokenizer-v2.manifest.yaml), [후보 평가](../training/aihub-71748-operating-tokenizer-evaluation.md) |

## 3.3 학생·비상업 라이선스와 최소 schema 검토 이벤트

| 검토일 | Dataset ID | 용도 | 이전 상태 | 새 상태 | 결정자 | 근거 | 허용 범위 | 금지 범위 | 재검토 조건 | 관련 문서 |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-07-26 | `AIHUB-71748` | 라이선스 범위 | `pending_terms_review` | `approved_student_noncommercial` | 사용자 | 학생·비상업적 연구 및 개인 학습 목적 결정 | 해당 범위의 최소 기술 검토 | 상업적 이용, 원본·파생 데이터 재배포 | 목적 변경 시 재승인 | [라이선스](./dataset-license-review.md#4-aihub-71748-검토표), [package manifest](./aihub-71748-local-package.manifest.yaml) |
| 2026-07-26 | `AIHUB-71748` | tokenizer 최소 schema 검토 | `tokenizer: under_review` | `tokenizer: under_review` | 사용자 | Training·Validation 각 1 ZIP·1 JSON·3 Record, 문자열 값 출력 0 상한 승인 | key·type·null·길이·배열·field 후보 확인 | 추가 Record, 원문 출력, PII 검사, Adapter·corpus·tokenizer 학습 | PII·권리·누수·추가 schema·Adapter의 별도 승인 | [최소 schema 결과](./analysis/AIHUB-71748-tokenizer-schema-review.md), [검토 계획](./aihub-71748-tokenizer-development-review-plan.md) |

- [확정] 라이선스 범위 승인과 tokenizer 목적 승인은 별개다. 목적별 `approved`는 여전히 0개다.

## 4. 용도별 승인 snapshot

모든 값은 2026-07-26 기준이다. `AIHUB-71748`의 tokenizer 목적만 `approved_tokenizer_development`이며 다른 목적별 승인값은 변경하지 않는다.

| Dataset ID | tokenizer | pretraining | SFT | preference | evaluation | tokenizer artifact 공개 | model weight 공개 | 상업 서비스 | 해외 cloud |
|---|---|---|---|---|---|---|---|---|---|
| `AIHUB-71748` | `approved_tokenizer_development` | `pending` | `pending` | `pending` | `pending` | `not_approved` | `pending` | `not_approved` | `pending` |
| `AIHUB-110` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` |
| `AIHUB-86` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` |
| `AIHUB-71477` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` |
| `AIHUB-653` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `pending` |

- [확정] tokenizer development 승인 1건은 Pretraining·SFT·Preference·평가·artifact 공개·상업 서비스 승인이 아니다.
- [확정] `AIHUB-71748`은 `downloaded_restricted`이며, 나머지 4개 후보의 문서상 `download_status`는 `not_requested`다.
- [확정] `downloaded_restricted`는 존재 확인일 뿐 처리·sample 검사·학습 허가가 아니다.

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
| 2026-07-26 | [확정] AIHUB-71748 학생·비상업 라이선스 승인과 6 Record 값 비노출 schema 검토를 기록하고 tokenizer `under_review`를 유지함 |
| 2026-07-26 | [확정] AIHUB-71748 ZIP 55개 checksum inventory와 별도 검토 계획에 근거해 tokenizer 목적을 비승인 `under_review`로 기록함 |
| 2026-07-26 | [확정] AIHUB-71748 로컬 ZIP package 존재를 `downloaded_restricted` 비승인 보유 상태로 기록하고 목적별 `pending` 상태를 유지함 |
| 2026-07-23 | [확정] 5개 AI Hub 후보의 `unregistered → registered` metadata 등록 사건과 전 용도 `pending` snapshot을 기록함 |
