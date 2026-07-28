# AI Hub Instruction Dataset 후보 Read-only 검토

- 문서 상태: `review`
- 최종 검토일: 2026-07-28
- 작업 유형: `data`, `documentation`
- 결정 상태: `dataset:not_selected`, `execution_allowed:false`
- 관련 결정: [ADR-004](../decisions/ADR-004-data-governance.md), [ADR-010](../decisions/ADR-010-dohalm-instruct-strategy.md)

## 1. 범위

이 문서는 `${DOHALM_DATASET_ROOT}/extracted` 아래의 AI Hub 패키지 5개를 DohaLM Instruct 후보로
read-only 검토한 결과다. 다운로드, 압축 해제, 원본 변경, corpus·token array·학습 산출물 생성과 SFT 실행은
범위에 포함하지 않았다. 검토 결과는 후보 선정을 위한 근거일 뿐 사용 승인이나 학습 승인이 아니다.

## 2. Read-only 정책과 조사 한계

- ZIP central directory, 파일명, 확장자, 크기와 제한된 JSON/CSV/TSV schema만 읽었다.
- 대표 archive의 JSON은 component당 최대 1개, record는 최대 3개만 구조적으로 확인했다.
- 큰 JSON은 최대 8 MiB prefix만 사용했고, record 수 확인이 필요한 선택된 배열만 저장 없이 streaming했다.
- 실제 문자열, 대화, 개인정보, URL, 학습 가능한 텍스트는 문서에 기록하지 않았다.
- 중복·근접 중복·train/validation overlap·benchmark contamination은 전체 검사를 하지 않았다.
- AIHUB-653 TSV의 header 유무를 확인하는 과정에서 첫 행의 원문 일부가 터미널 표준 출력에 일시 노출되는
  조사 경계 위반이 1회 있었다. 파일이나 문서에는 저장하지 않았고 원본은 변경하지 않았으며, 즉시 값 출력
  방식을 중단했다. 따라서 본 검토를 개인정보·저작권 안전 판정으로 사용할 수 없다.

## 3. Dataset inventory 요약

| Dataset ID | 논리 경로 | ZIP | ZIP bytes | central directory 구성 | 로컬 상태 |
|---|---|---:|---:|---|---|
| AIHUB-71748 | `${DOHALM_DATASET_ROOT}/extracted/AIHUB-71748` | 55 | 17,256,335,769 | JSON 1,609, TXT 1 | `downloaded_restricted` |
| AIHUB-71477 | `${DOHALM_DATASET_ROOT}/extracted/AIHUB-71477` | 48 | 120,566,390,709 | JSON 2,231,613, CSV 1,220,009, WAV 1,011,604 | `local_unapproved` |
| AIHUB-86 | `${DOHALM_DATASET_ROOT}/extracted/AIHUB-86` | 4 | 21,339,737 | JSON 2, XLSX 2 | `local_unapproved` |
| AIHUB-110 | `${DOHALM_DATASET_ROOT}/extracted/AIHUB-110` | 20 | 14,639,655,155 | JSON 665, TXT 2 | `local_unapproved` |
| AIHUB-653 | `${DOHALM_DATASET_ROOT}/extracted/AIHUB-653` | 158 | 18,103,513,163 | JSON 5,974, TSV 151 | `local_unapproved` |
| 합계 | 외부 dataset root | 285 | 170,587,234,533 | ZIP central directory 기준 | Git 외부, 원본 미변경 |

5개 package root에는 별도 이용조건, 다운로드 승인 증빙, checksum manifest가 발견되지 않았다. ZIP은 모두
central directory를 읽을 수 있었고 encrypted entry는 관찰되지 않았다. 이는 payload 전체 무결성 검증이나
사용권 확인을 대신하지 않는다.

## 4. Dataset identity

| Dataset ID | 저장소의 공식 dataset 명칭 | identity 근거 | 현재 판단 |
|---|---|---|---|
| AIHUB-71748 | 대규모 구매도서 기반 한국어 말뭉치 데이터 | ID, 경로, archive 구성, 기존 registry | 식별됨; 공식 페이지 제목의 정확한 문구는 이번 자동 확인에서 재확정하지 못함 |
| AIHUB-71477 | 한국어 맞춤법 교정 데이터 | ID, 경로, correction/ASR/overcorrection 구성 | 식별됨 |
| AIHUB-86 | 감성 대화 말뭉치 | ID, 경로, dialogue/profile 구조 | 식별됨 |
| AIHUB-110 | 전문분야 말뭉치 | ID, 경로, 법률·논문·특허 domain 구성 | 식별됨 |
| AIHUB-653 | 도서자료 요약 데이터 | ID, 경로, source TSV/label JSON 구성 | 식별됨 |

공식 참조는 [AI Hub 이용정책](https://www.aihub.or.kr/aihubdata/guide.do?pageIndex=1&currMenu=115&topMenu=100)과
각 dataset 상세 페이지([71748](https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=71748),
[71477](https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=71477),
[86](https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=86),
[110](https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=110),
[653](https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=653))다.

## 5. 목적별 적합성 요약

| Dataset/component | SFT mapping score (0~4) | 가능한 목적 | 현재 결론 |
|---|---:|---|---|
| AIHUB-71748 `SFTdata` + `SFTlabel` | 4 | 일반 instruction/answer schema 후보 | `recommended_for_schema_review` |
| AIHUB-71748 `RMdata`, `PPOdata`, 일반 corpus | 0~2 | Preference/RLHF 또는 Base/CPT | Instruct SFT에서 제외 |
| AIHUB-71477 correction, ASR correction | 3 | 고정 지시문 기반 보조 교정 SFT | `recommended_for_schema_review` |
| AIHUB-71477 overcorrection | 2 | 교정 robustness 평가 | `evaluation_only_candidate` |
| AIHUB-86 text dialogue | 2 | 제한된 상담형 Chat | `conditional_safety_review` |
| AIHUB-110 | 1 | Base/CPT, retrieval, domain evaluation | `base_only_candidate` |
| AIHUB-653 | 1 | Base/CPT 또는 요약 원천 후보 | `base_only_candidate` |

점수는 구조의 instruction-input-output 직접성만 뜻한다. 라이선스, 안전성, 품질 또는 학습 승인을 뜻하지 않는다.

## 6. Local availability와 split

- AIHUB-71748에는 Training/Validation의 PPO·SFT·RM source와 SFT·RM label이 있다.
- AIHUB-71477에는 Training/Validation과 correction·ASR correction·overcorrection component가 있다.
- AIHUB-86에는 Training 51,628개, Validation 6,640개의 JSON dialogue record가 관찰됐다.
- AIHUB-110에는 Training/Validation과 논문·법령·의안·자치법규·특허·판례·행정규칙 domain이 있다.
- AIHUB-653에는 Training source/label 58쌍과 Validation source/label 21쌍이 있다.
- 모든 Validation은 학습 후보에서 제외한다. Evaluation/benchmark 전용 subset도 학습에 포함하지 않는다.

## 7. Schema mapping

### AIHUB-71748

- SFT source 후보: `question`; label 후보: `answer.contents`; join 후보: `data_id`.
- Training 구조 수: PPO 25,443, SFT source/label 각 10,580, RM source/label 각 26,408.
- Validation 구조 수: PPO 3,180, SFT source/label 각 1,322, RM source/label 각 3,301.
- `question_type`, category와 ID는 비학습 metadata로 유지한다.
- RM의 다중 answer/ranking과 PPO는 별도 Preference/RLHF 승인 없이는 사용하지 않는다.

### AIHUB-71477

- correction/ASR 후보 mapping: `ko` → `corrected`; 지시문은 고정되고 versioned되어야 한다.
- overcorrection에는 `autoproof`, `excess`가 있어 방향과 평가 계약을 먼저 확정해야 한다.
- local Training JSON 수는 correction 1,000,005, ASR 1,001,604, overcorrection 200,004로 총
  2,201,613이다. 기존 문서의 공식 공개 합계 2,201,601보다 12개 많아 계보 확인 전 사용하지 않는다.
- ASR source WAV는 이번 Instruct text 후보에서 제외한다.

### AIHUB-86

- record는 `profile`, `talk.id`, `talk.content`를 가지며 content에는 HS/SS 계열 turn slot이 있다.
- HS/SS의 정확한 화자 의미를 공식 schema로 재확인해야 한다. 일부 선택 record에서 선택적 turn이 비어 있었다.
- persona, emotion, situation과 ID는 prompt text와 분리된 민감 metadata로 취급한다.

### AIHUB-110

- source 후보 구조에는 `title`, `author`, `text`, `NE`와 domain identifier가 있다.
- label은 domain별 metadata와 `rows[].text`, `rows[].NE` 형태가 관찰됐다.
- 법령제개정·자치법규 조례·판례의 선택 entry는 현재 Python runtime이 compression method 9를 지원하지 않아
  payload schema를 확인하지 못했다. 우회 압축 해제 없이 `format_unresolved`로 유지한다.
- 직접 instruction/output pair가 없어 Instruct SFT mapping 대상으로 삼지 않는다.

### AIHUB-653

- label JSON은 `id`, `info`, 집계 `statistics`만 관찰됐다.
- source TSV는 header가 없는 6개 열 구조로 의미가 확정되지 않았다.
- instruction/output mapping과 source-label join을 확정할 근거가 부족하다.

## 8. PII 위험

| Dataset | 제한 표본 관찰 | 잔여 위험과 필요한 조치 |
|---|---|---|
| 71748 | SFT 3건에서 표준 email·phone·resident ID·URL 패턴 미관찰 | 의료 민감어 신호가 있어 전체 field-aware PII·민감정보 검토 필요 |
| 71477 | component별 1건에서 표준 PII 미관찰; ID류 false-positive 가능 | 음성의 화자 개인정보, 파일명·ID와 text 분리, text/audio 별도 승인 필요 |
| 86 | 3건에서 표준 구조 PII 패턴 미관찰 | persona·감정·상황·상담 내용은 고위험 준식별·정신건강 정보로 취급 |
| 110 | 3건에서 표준 PII 패턴 미관찰 | author·사건·등록번호·개체명과 법률/의료/금융 domain 위험 검토 필요 |
| 653 | TSV 3행에서 표준 PII 패턴 미관찰 | 열 의미 미확정, 저작물 원문·저자 식별·암기 위험 검토 필요 |

제한 표본의 미관찰은 PII 부재 증명이 아니다. 전체 스캔은 별도 승인된 비원문 보고 방식, quarantine,
false-positive review와 deletion/retention 정책을 갖춘 뒤 실행한다.

## 9. Safety 위험

- 71748: 의료·전문 domain 답변을 일반 조언으로 학습할 위험과 답변 품질 편차가 있다.
- 71477: 교정 결과가 사실성 보증으로 오인될 수 있고 음성 component에는 consent·speaker privacy 위험이 있다.
- 86: 정신건강·감정 상담 답변의 위해, 과도한 의존, 위기 대응 실패 위험이 높다.
- 110: 법률·의료·금융 고위험 지식의 시점성, 관할권, 권위 오인 위험이 있다.
- 653: 장문 저작물 암기·재현과 출처 없는 요약을 사실로 제시할 위험이 있다.

고위험 domain은 별도 safety rubric, refusal/escalation 계약과 evaluation set 승인 전 학습하지 않는다.

## 10. Quality 위험

- 전체 중복, 근접 중복, template leakage, benchmark contamination은 미검증이다.
- AIHUB-71477은 local Training JSON과 기존 공식 집계가 12개 불일치한다.
- AIHUB-86은 화자 의미와 빈 선택 turn 처리 정책이 미확정이다.
- AIHUB-110은 일부 compression method가 현재 inspector에서 지원되지 않는다.
- AIHUB-653은 TSV header와 6개 열 의미가 미확정이고 logical row count를 산출하지 않았다.
- Source/label join key uniqueness, orphan, one-to-many 관계는 전체 검증하지 않았다.

## 11. License 상태

| Dataset | 현재 license 상태 | Instruct 목적 승인 |
|---|---|---|
| AIHUB-71748 | `approved_student_noncommercial`; commercial/raw/derived redistribution `not_approved` | SFT `not_approved` |
| AIHUB-71477 | `pending_terms_review` | 모든 목적 `pending` |
| AIHUB-86 | `pending_terms_review` | 모든 목적 `pending` |
| AIHUB-110 | `pending_terms_review` | 모든 목적 `pending` |
| AIHUB-653 | `pending_terms_review` | 모든 목적 `pending` |

AI Hub 공식 정책과 dataset별 이용조건, 다운로드 당시 동의 내용, 제3자 권리, 개인정보와 파생물 조건을
법률·데이터 책임자가 확인해야 한다. AIHUB-71748의 기존 학생·비상업 상태는 되돌리지 않지만 Tokenizer
Development 승인을 SFT 승인으로 확장하지 않는다. 다른 4개 dataset은 로컬 존재만으로 취득·처리 승인을
간주하지 않는다.

## 12. 권장 역할

- Core schema 후보: AIHUB-71748의 SFT source/label만.
- Auxiliary 후보: AIHUB-71477 correction/ASR correction. 고정 지시문과 mixture cap이 필요하다.
- Evaluation-only 후보: AIHUB-71477 overcorrection. 별도 평가 dataset 승인과 격리가 필요하다.
- Conditional Chat 후보: AIHUB-86 text dialogue. 고위험 safety·PII 승인 후에만 재검토한다.
- Base/CPT-only 후보: AIHUB-110, AIHUB-653. 현재 Instruct SFT에서 제외한다.

## 13. Shortlist

1. `AIHUB-71748/SFT`: 가장 직접적인 schema 후보이나 아직 선택·SFT 승인되지 않았다.
2. `AIHUB-71477/correction`: 보조 교정 과제로 유효할 수 있으나 count·license·mixture 정책이 blocker다.
3. `AIHUB-86/text-dialogue`: Chat 다양성 후보이나 안전성과 화자 mapping 위험으로 조건부다.

Shortlist는 우선 검토 순서이며 dataset 선택이 아니다.

## 14. Blocker

- 5개 dataset의 Instruct 목적별 license·PII·저작권·파생물·보존 정책 승인 부재.
- AIHUB-71748 SFT의 join integrity, 전체 PII, 중복·누수와 answer quality 미검증.
- AIHUB-71477 local/official count 12개 불일치와 overcorrection 방향 미확정.
- AIHUB-86 화자 mapping, 정신건강 safety와 빈 turn 직렬화 정책 미확정.
- AIHUB-110 일부 archive format 미해결, 직접 SFT mapping 부재.
- AIHUB-653 TSV 열 의미·join·저작권 위험 미해결.
- train/validation/benchmark 격리 manifest와 immutable fingerprint 미생성.
- SFT backend, resolved config, budget, evaluation thresholds와 single-use execution approval 부재.

## 15. 필요한 승인

1. 공식 이용조건과 다운로드 계보에 대한 dataset별 법률·데이터 책임자 승인.
2. 원문 비출력형 전체 PII·중복·누수·join 검증 계획 승인.
3. Shortlist에서 사용할 component와 field mapping의 schema review 승인.
4. Validation·evaluation·benchmark 격리 및 contamination 검사 계약 승인.
5. dataset 선택과 immutable source manifest 생성에 대한 별도 승인.
6. SFT backend 구현·CPU fail-closed 검증 승인.
7. 학습 config·budget·output·checkpoint·evaluation 계약과 단일 실행 승인.

각 승인은 앞 단계의 완료를 자동 승인하지 않으며 Fail Closed로 소비한다.

## 16. 최종 상태

```yaml
dataset: not_selected
dataset_acquisition: not_approved
dataset_processing: not_approved
sft_backend: not_started
sft_training: not_approved
execution_allowed: false
```

현재 추천은 AIHUB-71748 SFT를 첫 schema review 대상으로 유지하고 AIHUB-71477 correction을 보조 후보로
검토하는 것이다. 어떤 dataset도 Instruct 학습에 선택되거나 승인되지 않았으며, 다운로드·변환·학습 실행은
계속 금지한다.
