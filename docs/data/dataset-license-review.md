# DohaLM 데이터셋 라이선스 검토

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-26 |
| 선행 문서 | [데이터셋 후보 등록부](./dataset-candidate-registry.md), [데이터 라이선스 정책](./data-license-policy.md), [ADR-004](../decisions/ADR-004-data-governance.md) |
| 후속 문서·작업 | [데이터셋 승인 로그](./dataset-approval-log.md), 공식 문의, 취득 계보 확인, 용도별 승인 |
| 구현 전 필수 여부 | 실제 데이터 사용·학습·artifact 공개 전 예 |

- [확정] 이 문서는 법적·정책적 검토만 관리하며 기술적 품질 평가는 후보 등록부가 담당한다.
- [확정] 아래 내용은 2026-07-23 공개 상태의 [AI Hub 이용정책](https://www.aihub.or.kr/intrcn/guid/usagepolicy.do)과 각 공식 상세페이지를 요약한 것이며 법률 자문을 대신하지 않는다.
- [확정] `AIHUB-71748`은 사용자 결정에 따라 학생·비상업적 연구 및 개인 학습 범위에서 `approved_student_noncommercial`이다. 나머지 후보는 `pending_terms_review`다.
- [확정] `AIHUB-71748`의 상업적 이용과 원본·파생 데이터 재배포는 `not_approved`이며 이 결정은 tokenizer·Adapter·학습 승인을 부여하지 않는다.

## 2. AI Hub 일반 이용정책 확인 결과

| 항목 | 공식 정책에서 확인한 내용 | DohaLM 적용 |
|---|---|---|
| 권리 주체 | 구축 수행·참여기관과 한국지능정보사회진흥원에 권리가 있다고 설명 | NIA를 모든 원문의 단일 권리자로 간주하지 않음 |
| 연구·개발 | 영리·비영리 연구·개발 목적으로 활용 가능 | 개별 데이터 조건·목적 승인까지 확인 |
| 출처 표시 | NIA 사업 결과임을 밝히고 2차적 저작물에도 동일 표시 | artifact·모델 카드 표시 방식 공식 확인 필요 |
| 목적 제한 | AI 학습모델 학습용으로만 사용할 수 있다고 명시 | tokenizer·pretraining·SFT 목적별 승인 분리 |
| 제3자 제공 | 승인 없는 열람·제공·양도·대여·판매 금지 | 원본·가공 text 외부 공유 금지 |
| 국외 이용·반출 | 수행기관 등과 NIA의 별도 합의 필요 | 해외 cloud·server·외국 사용자 공개 보류 |
| 데이터셋 판매 | 판매 등 상업적 이용은 수행기관과 별도 협의 | 상업 서비스와 별도로 공식 문의 |
| 개인정보 | 발견 즉시 신고하고 다운로드 데이터셋 삭제 | 격리·계보 추적·사용 중단 |
| 재식별 | 비식별 정보로 개인을 재식별하는 행위 금지 | 재식별 시도 금지 |
| 다운로드 | 본인 확인, 정보 제공과 사용 목적 제출 필요 | 사용자 명시 승인 전 신청하지 않음 |
| 제3자 권리 데이터 | NIA 비권리 데이터는 해당 기관 정책·절차 적용 | source별 권리·CCL 보존 |

- [확정] 일반 정책에는 연구·개발 활용 문구와 학습용 목적 제한이 함께 있으므로 상업 서비스·공개 배포 범위를 임의로 확대 해석하지 않는다.

## 3. 공통 미확인 항목

다음은 일반 정책만으로 허용을 확정하지 않는다. `AIHUB-71748`은 학생·비상업 범위와 명시된 금지 상태를 적용하고, 그 밖의 후보는 `pending_official_confirmation`으로 둔다.

- 모델 가중치·GitHub Release·Hugging Face 공개
- `tokenizer.model`, `tokenizer.vocab` 공개
- 원본에서 추출한 가공·정제 text 재배포
- 해외 cloud 학습·해외 server 저장
- 상업 서비스 제공
- 생성 결과의 원문 유사 재현 처리
- 공개 artifact가 국외 사용자의 다운로드 대상이 되는 경우의 국외 반출 판단

### 3.1 후보별 개별 조건·다운로드 상태

| Dataset ID | 개별 이용조건 | 다운로드 승인 조건 | 다운로드 상태 | 검토 상태 |
|---|---|---|---|---|
| `AIHUB-71748` | 학생·비상업 연구·개인 학습, 상업·재배포 불가 | 취득 증빙은 별도 계보 검토 | `downloaded_restricted` | `approved_student_noncommercial` |
| `AIHUB-110` | `pending_official_confirmation` | 본인 확인·목적 제출 후 실제 심사 결과 확인 | `not_requested` | `pending_terms_review` |
| `AIHUB-86` | `pending_official_confirmation` | 본인 확인·목적 제출 후 실제 심사 결과 확인 | `not_requested` | `pending_terms_review` |
| `AIHUB-71477` | `pending_official_confirmation` | 본인 확인·목적 제출 후 실제 심사 결과 확인 | `not_requested` | `pending_terms_review` |
| `AIHUB-653` | `pending_official_confirmation` | 본인 확인·목적 제출 후 실제 심사 결과 확인 | `not_requested` | `pending_terms_review` |

- [확정] `AIHUB-71748`의 학생·비상업 라이선스 범위는 승인됐지만 다운로드 신청·승인 증빙과 취득 당시 조건 snapshot은 계보 미확정으로 남는다. package는 `downloaded_restricted`, registry는 `reviewing`을 유지한다.

## 4. AIHUB-71748 검토표

공식 근거: [상세페이지](https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=71748), [일반 이용정책](https://www.aihub.or.kr/intrcn/guid/usagepolicy.do).

| 항목 | 상태 | 공식 근거 | 추가 확인 |
|---|---|---|---|
| 학생·비상업 연구·개인 학습 | `approved_student_noncommercial` | 사용자 결정 | 목적·보관 범위 준수 |
| tokenizer development | `approved_tokenizer_development` | 사용자 명시 승인 | Training `data_info[].contents`만, Validation·benchmark·RLHF·SFT·metadata 제외 |
| 상업 서비스 | `not_approved` | 사용자 결정 | 별도 결정 전 금지 |
| 원본 재배포 | `not_approved` | 사용자 결정·제3자 제공 제한 | 금지 유지 |
| 가공·파생 데이터 재배포 | `not_approved` | 사용자 결정 | 금지 유지 |
| tokenizer.model 공개 | `not_approved` | 파생 artifact 재배포 미승인 | 별도 공개 승인 필요 |
| tokenizer.vocab 공개 | `not_approved` | 파생 artifact 재배포 미승인 | 별도 공개 승인 필요 |
| 모델 가중치 공개 | `pending_official_confirmation` | 불명확 | 공식 문의 |
| Hugging Face 공개 | `pending_official_confirmation` | 불명확 | 국외 이용·제3자 제공 문의 |
| 국외 반출 | `restricted_pending_agreement` | 별도 합의 필요 | 수행기관·NIA 합의 |
| 해외 cloud 처리 | `pending_official_confirmation` | 직접 명시 없음 | 저장·처리 위치 문의 |
| 출처 표시 | `required` | 일반 이용정책 | subset별 표시 형식 |
| 데이터셋 판매 | 별도 협의 | 일반 이용정책 | 적용 주체 확인 |

- [검증 필요] 상세페이지가 복수 source·CCL 유형을 제시하므로 source별 권리 조건과 artifact 공개 영향을 따로 확인한다.
- [확정] tokenizer development는 학생·비상업 범위에서 승인됐다. 이는 tokenizer 전용 최소 corpus와 16k 후보 학습에만 적용하며 PII가 없다는 판정, 모델 학습 승인 또는 artifact 재배포 승인이 아니다.

## 5. AIHUB-110 검토표

공식 근거: [상세페이지](https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=110), [일반 이용정책](https://www.aihub.or.kr/intrcn/guid/usagepolicy.do).

| 항목 | 상태 | 공식 근거 | 추가 확인 |
|---|---|---|---|
| 영리 연구·개발 | 일반 정책 근거 확인 | 일반 이용정책 | 개별 약관·source 목적 |
| 상업 서비스 | `pending_official_confirmation` | 불명확 | 공식 문의 |
| 원본 재배포 | `restricted` | 무승인 제3자 제공 금지 | 법령·판례·특허·논문별 조건 |
| 가공 text 재배포 | `pending_official_confirmation` | 불명확 | source별 문의 |
| tokenizer.model 공개 | `pending_official_confirmation` | 불명확 | 공식 문의 |
| tokenizer.vocab 공개 | `pending_official_confirmation` | 불명확 | 공식 문의 |
| 모델 가중치 공개 | `pending_official_confirmation` | 불명확 | 공식 문의 |
| Hugging Face 공개 | `pending_official_confirmation` | 불명확 | 국외·제3자 제공 문의 |
| 국외 반출 | `restricted_pending_agreement` | 별도 합의 필요 | 수행기관·NIA 합의 |
| 해외 cloud 처리 | `pending_official_confirmation` | 직접 명시 없음 | 공식 문의 |
| 출처 표시 | `required` | 일반 이용정책 | source별 표시 형식 |
| 데이터셋 판매 | 별도 협의 | 일반 이용정책 | 적용 주체 확인 |

- [검증 필요] 구매 특허 자료, 크롤링 논문 초록, 법령·판례 등 source별 원천 권리와 이용조건을 분리한다.

## 6. AIHUB-86 검토표

공식 근거: [상세페이지](https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=86), [일반 이용정책](https://www.aihub.or.kr/intrcn/guid/usagepolicy.do).

| 항목 | 상태 | 공식 근거 | 추가 확인 |
|---|---|---|---|
| 영리 연구·개발 | 일반 정책 근거 확인 | 일반 이용정책 | 대화·음성 개별 조건 |
| 상업 서비스 | `pending_official_confirmation` | 불명확 | 민감 상담 활용 포함 문의 |
| 원본 재배포 | `restricted` | 무승인 제3자 제공 금지 | 개별 조건 |
| 가공 text 재배포 | `pending_official_confirmation` | 불명확 | 비식별 파생 text 문의 |
| tokenizer.model 공개 | `pending_official_confirmation` | 불명확 | 공식 문의 |
| tokenizer.vocab 공개 | `pending_official_confirmation` | 불명확 | 공식 문의 |
| 모델 가중치 공개 | `pending_official_confirmation` | 불명확 | 공식 문의 |
| Hugging Face 공개 | `pending_official_confirmation` | 불명확 | 국외·민감정보 위험 문의 |
| 국외 반출 | `restricted_pending_agreement` | 별도 합의 필요 | 수행기관·NIA 합의 |
| 해외 cloud 처리 | `pending_official_confirmation` | 직접 명시 없음 | 공식 문의 |
| 출처 표시 | `required` | 일반 이용정책 | 표시 형식 |
| 데이터셋 판매 | 별도 협의 | 일반 이용정책 | 해당 여부 확인 |

## 7. AIHUB-71477 검토표

공식 근거: [상세페이지](https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=71477), [일반 이용정책](https://www.aihub.or.kr/intrcn/guid/usagepolicy.do).

| 항목 | 상태 | 공식 근거 | 추가 확인 |
|---|---|---|---|
| 영리 연구·개발 | 일반 정책 근거 확인 | 일반 이용정책 | 개별 약관·평가 목적 |
| 상업 서비스 | `pending_official_confirmation` | 불명확 | 공식 문의 |
| 원본 재배포 | `restricted` | 무승인 제3자 제공 금지 | 개별 조건 |
| 가공 text 재배포 | `pending_official_confirmation` | 불명확 | 교정 pair 공개 문의 |
| tokenizer.model 공개 | `pending_official_confirmation` | 불명확 | 공식 문의 |
| tokenizer.vocab 공개 | `pending_official_confirmation` | 불명확 | 공식 문의 |
| 모델 가중치 공개 | `pending_official_confirmation` | 불명확 | correction model 포함 문의 |
| Hugging Face 공개 | `pending_official_confirmation` | 불명확 | 국외·제3자 제공 문의 |
| 국외 반출 | `restricted_pending_agreement` | 별도 합의 필요 | 수행기관·NIA 합의 |
| 해외 cloud 처리 | `pending_official_confirmation` | 직접 명시 없음 | 공식 문의 |
| 출처 표시 | `required` | 일반 이용정책 | 표시 형식 |
| 데이터셋 판매 | 별도 협의 | 일반 이용정책 | 해당 여부 확인 |

## 8. AIHUB-653 검토표

공식 근거: [상세페이지](https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=653), [일반 이용정책](https://www.aihub.or.kr/intrcn/guid/usagepolicy.do).

| 항목 | 상태 | 공식 근거 | 추가 확인 |
|---|---|---|---|
| 영리 연구·개발 | 일반 정책 근거 확인 | 일반 이용정책 | 구매도서 개별 조건 |
| 상업 서비스 | `pending_official_confirmation` | 불명확 | 공식 문의 |
| 원본 재배포 | `restricted` | 무승인 제3자 제공 금지 | 구매·출판 계약 확인 |
| 가공 text 재배포 | `pending_official_confirmation` | 불명확 | 발췌·정제 범위 문의 |
| tokenizer.model 공개 | `pending_official_confirmation` | 불명확 | memorization·파생성 문의 |
| tokenizer.vocab 공개 | `pending_official_confirmation` | 불명확 | 원문 phrase 포함 가능성 문의 |
| 모델 가중치 공개 | `pending_official_confirmation` | 불명확 | 구매도서 학습 weight 문의 |
| Hugging Face 공개 | `pending_official_confirmation` | 불명확 | 국외·제3자 제공 문의 |
| 국외 반출 | `restricted_pending_agreement` | 별도 합의 필요 | 수행기관·NIA 합의 |
| 해외 cloud 처리 | `pending_official_confirmation` | 직접 명시 없음 | 공식 문의 |
| 출처 표시 | `required` | 일반 이용정책 | 도서·사업 표시 형식 |
| 데이터셋 판매 | 별도 협의 | 일반 이용정책 | 해당 여부 확인 |

- [검증 필요] 원문 재현·암기 완화 책임과 공개 모델에 필요한 추가 조치를 공식 문의한다.

## 9. 공식 문의 목록

문의 상태는 모두 `pending_official_inquiry`다.

1. AI Hub 데이터로 학습한 모델 가중치를 공개할 수 있는가?
2. Hugging Face 또는 GitHub Release에 모델을 배포할 수 있는가?
3. SentencePiece `tokenizer.model`과 `tokenizer.vocab`을 공개할 수 있는가?
4. 학습된 모델을 상업 서비스에 사용할 수 있는가?
5. 해외 cloud 또는 외국계 서비스에서 데이터를 처리할 수 있는가?
6. AI Hub 데이터에서 추출·정제한 text를 재배포할 수 있는가?
7. 모델 출력이 원문과 유사하게 재현되는 경우 필요한 조치는 무엇인가?
8. 각 데이터셋별 별도 이용 제한이 있는가?
9. subset별 CCL·권리 조건이 다를 때 적용 기준은 무엇인가?
10. 공개 모델이 국외 사용자의 다운로드 대상이면 국외 반출로 보는가?

## 10. 다운로드 전 승인 단계

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

| 단계 | 의미 |
|---|---|
| `registered` | 공식 후보와 metadata만 등록 |
| `pending_terms_review` | 일반·개별 조건 검토 중 |
| `pending_download_approval` | 사용자 승인 뒤 공식 신청 대기·진행 |
| `downloaded_restricted` | 다운로드됐으나 격리·사용 미승인 |
| `pending_sample_inspection` | schema·PII·권리 metadata·품질 점검 중 |
| `approved_tokenizer_development` | 개발 후보 실험에만 허용 |
| `approved_tokenizer_candidate` | 운영 tokenizer 후보에 허용 |
| `approved_pretraining` / `approved_sft` | 해당 학습 목적에 별도 허용 |

## 11. 다운로드 후 보관 원칙

- 원본은 `data/raw/` 또는 승인된 저장소 외 경로에 두고 Git에서 제외한다.
- 원본 변경을 금지하고 checksum, dataset ID·version, 약관 확인일, 다운로드 사용자·목적을 기록한다.
- 국외 동기화·해외 cloud 처리는 별도 승인 전 금지하고 자동 backup 위치를 확인한다.
- AI Hub 원본을 GitHub, Google Drive, Dropbox, Hugging Face Dataset에 업로드하지 않는다.
- 개인정보 발견 시 사용을 중단하고 공식 정책에 따라 신고·삭제하며 영향 계보를 기록한다.

## 12. 미결정 사항

- [검증 필요] 개별 약관의 최종 법적 해석과 source별 CCL
- [검증 필요] weight·tokenizer·가공 text 공개, 상업 서비스, 해외 cloud 가능 여부
- [검증 필요] 공식 문의 담당자·회신·유효기간과 재검토 주기

## 13. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-26 | [확정] AIHUB-71748을 학생·비상업 연구·개인 학습 `approved_student_noncommercial`로 반영하고 상업·원본·파생 재배포를 `not_approved`로 고정함 |
| 2026-07-26 | [확정] AIHUB-71748 tokenizer development 허용 여부를 공식 확인 항목으로 추가하고 `under_review`가 사용 승인이 아님을 명시함 |
| 2026-07-26 | [확정] AIHUB-71748 로컬 package 보유 사실을 `downloaded_restricted`로 반영하고 취득 증빙·공식 조건·목적별 승인 미확정 경계를 유지함 |
| 2026-07-23 | [확정] AI Hub 일반 정책과 5개 공식 상세페이지를 기준으로 미승인 라이선스 검토 및 공식 문의 항목을 등록함 |
