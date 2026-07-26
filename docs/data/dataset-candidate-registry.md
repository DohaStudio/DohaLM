# DohaLM 데이터셋 후보 등록부

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-26 |
| 선행 문서 | [데이터 전략](./data-strategy.md), [데이터 라이선스 정책](./data-license-policy.md), [ADR-004](../decisions/ADR-004-data-governance.md) |
| 후속 문서·작업 | [구조 분석 요약](./analysis/dataset-analysis-summary.md), [데이터셋 라이선스 검토](./dataset-license-review.md), [데이터셋 승인 로그](./dataset-approval-log.md), [평가 제외 목록](./evaluation-exclusion-list.md), 실제 취득 계보 검토 |
| 구현 전 필수 여부 | 실제 데이터 사용·Phase 2 corpus 승인 전 예 |

- [확정] 이 문서는 후보의 공식 사실·기술적 적합성과 실제 사용 전 로컬 보유 상태를 관리한다.
- [확정] 실제 승인·다운로드·처리 version은 [데이터셋 레지스트리](./dataset-registry.md)가 관리한다.
- [확정] 아래 적합성은 DohaLM 관점의 정성 후보 평가이며 품질·이용 승인이 아니다.
- [확정] 현재 승인된 tokenizer·pretraining·SFT·preference·evaluation corpus는 0개다.
- [확정] 2026-07-23 로컬 제한 package 5종의 파일·ZIP 구조를 읽기 전용으로 분석했다. 이 관찰은 공식 다운로드 계보 확인이나 목적별 승인이 아니며, 2026-07-26에는 `AIHUB-71748`의 로컬 보유 사실만 `downloaded_restricted`로 정합화했다.
- [확정] AIHUB-71748의 [안전 표본 dry-run](./analysis/AIHUB-71748-sampling.md)은 absolute entry 1,610개를 거부하고 추출 0건으로 종료했다. 이 결과도 승인 상태를 변경하지 않는다.

## 2. 공식 근거와 제공기관 필드

공식 사실은 다음 AI Hub 상세페이지와 [AI Hub 이용정책](https://www.aihub.or.kr/intrcn/guid/usagepolicy.do)만 사용했다.

| Dataset ID | 공식 상세페이지 |
|---|---|
| `AIHUB-71748` | [한국어 성능이 개선된 초거대AI 언어모델 개발 및 데이터](https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=71748) |
| `AIHUB-110` | [전문분야 말뭉치](https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=110) |
| `AIHUB-86` | [감성 대화 말뭉치](https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=86) |
| `AIHUB-71477` | [자연어 분석 후처리용 과교정 검증 데이터](https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=71477) |
| `AIHUB-653` | [대규모 구매도서 기반 한국어 말뭉치 데이터](https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=653) |

모든 후보는 `provider` 하나로 합치지 않고 다음 필드를 사용한다.

| 필드 | 값·원칙 |
|---|---|
| `platform` | [확정] AI Hub |
| `platform_operator` | [확정] 한국지능정보사회진흥원 |
| `dataset_builder` | 공식 상세페이지의 주관 수행기관; 참여기관 전체 범위는 필요 시 공식 설명서 재확인 |
| `source_rights_holders` | [검증 필요] source별 확인 필요 |

- [확정] AI Hub 또는 한국지능정보사회진흥원을 모든 원문 데이터의 단일 저작권자로 표현하지 않는다.

## 3. 상태와 목적별 승인 계약

후보 상태는 다음 값만 사용한다.

`registered`, `pending_terms_review`, `pending_download_approval`, `pending_sample_inspection`, `approved_tokenizer_development`, `approved_tokenizer_candidate`, `approved_pretraining`, `approved_sft`, `approved_preference`, `approved_evaluation`, `restricted_internal_only`, `rejected`, `revoked`.

각 후보의 현재 상태는 다음과 같다.

| Dataset ID | `candidate_status` | `license_review_status` | `download_status` |
|---|---|---|---|
| `AIHUB-71748` | `registered` | `approved_student_noncommercial` | `downloaded_restricted` |
| `AIHUB-110` | `registered` | `pending_terms_review` | `not_requested` |
| `AIHUB-86` | `registered` | `pending_terms_review` | `not_requested` |
| `AIHUB-71477` | `registered` | `pending_terms_review` | `not_requested` |
| `AIHUB-653` | `registered` | `pending_terms_review` | `not_requested` |

용도별 승인은 `pending`, `under_review`, `approved_tokenizer_development`, `approved`, `restricted`, `rejected`, `not_applicable`만 사용한다. `AIHUB-71748`의 tokenizer 목적만 [검토 계획](./aihub-71748-tokenizer-development-review-plan.md)에 따라 `approved_tokenizer_development`이며, Adapter는 이 목적에 한해서만 허용된다. 나머지 목적·후보는 모두 `pending`이다.

- [확정] `AIHUB-71748`의 `downloaded_restricted`는 로컬 ZIP package 존재를 반영한 보유 상태다. 취득 승인·이용 승인·schema/PII 검토·학습 승인을 뜻하지 않는다.
- [확정] 라이선스는 학생·비상업 연구·개인 학습에 한해 승인됐고 상업적 이용과 원본·파생 데이터 재배포는 승인되지 않았다.
- [확정] 원본 ZIP 55개의 개별 SHA-256은 [checksum inventory](./aihub-71748-zip-checksums.manifest.yaml)에 기록됐다. 미확정 취득 계보 때문에 일반 source manifest 사용은 차단하되, 사용자 승인에 따라 검증된 Training 원천 ZIP을 tokenizer development에만 제한 사용한다.
- [검증 필요] 실제 취득일, 제공자 package version과 다운로드 신청·승인 증빙은 확인되지 않았다.

## 4. 후보 공통 등록 표

| Dataset ID | 공식 데이터셋명 | Tokenizer | Pretraining | SFT | Preference | Evaluation | 최초 상태 |
|---|---|---|---|---|---|---|---|
| `AIHUB-71748` | 한국어 성능이 개선된 초거대AI 언어모델 개발 및 데이터 | 핵심 후보 | 핵심 후보 | 핵심 후보 | 핵심 후보 | 기본 제외 후 검토 | `registered` |
| `AIHUB-110` | 전문분야 말뭉치 | 핵심 후보 | 핵심 후보 | 제한적 | 해당 없음 또는 제한적 | 일부 가능 | `registered` |
| `AIHUB-86` | 감성 대화 말뭉치 | 보조 후보 | 제한적 후보 | 후보 | 제한적 | 감정 task용 분리 | `registered` |
| `AIHUB-71477` | 자연어 분석 후처리용 과교정 검증 데이터 | 제한적 후보 | 기본 제외 | 교정 SFT 후보 | 해당 없음 | 핵심 평가 후보 | `registered` |
| `AIHUB-653` | 대규모 구매도서 기반 한국어 말뭉치 데이터 | 핵심 후보 | 핵심 후보 | 비주력 | 해당 없음 | 일반 평가 비권장 | `registered` |

## 5. AIHUB-71748

| 필드 | 등록 내용 |
|---|---|
| Dataset ID | `AIHUB-71748` |
| 공식 데이터셋명 | 한국어 성능이 개선된 초거대AI 언어모델 개발 및 데이터 |
| 공식 URL | [AI Hub 상세페이지](https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=71748) |
| 플랫폼 / 운영기관 | AI Hub / 한국지능정보사회진흥원 |
| 구축 수행기관 | 대구경북과학기술원(주관); 참여기관 전체 범위는 공식 설명서 재확인 |
| 원천 권리자 | [검증 필요] source별 권리·CCL 확인 |
| 언어 | 한국어 |
| 데이터 구성 | 일반 말뭉치, SFT, RM, PPO |
| 공식 공개 규모 | 일반 말뭉치 20억 어절·310만 건, RLHF 7만7천 건(SFT 1.3만, RM 3.3만, PPO 3.1만) |
| 형식 / 구축 연도 | JSON / 2023 |
| 적합성 | tokenizer·pretraining·SFT·preference 핵심 후보; evaluation 기본 제외 후 검토 |
| PII / 저작권 위험 | `medium` / `high` |
| 평가 누수 / 암기 위험 | `high` / `high` |
| 추가 위험 | license complexity·source mix `high` |
| 우선순위 / 상태 | `critical` / `registered` |

공식 상세페이지는 공유·공공 데이터, 저작권 만료 고전, Creative Commons 표기 영상 등 복수 출처를 제시한다. 따라서 source별 `data_ccl`과 권리 정보를 record 또는 source 단위로 보존해야 한다.

| 목적 | 허용 후보 subset | 제외 subset |
|---|---|---|
| Tokenizer | 일반 `corpus` | SFT, RM, PPO |
| Pretraining | 일반 `corpus` | SFT, RM, PPO |
| SFT | SFT | corpus, RM, PPO |
| Preference | RM 후보, PPO schema 검토 후 후보 | corpus, SFT |
| Evaluation | contamination 검토 전 전체 기본 제외 | 공식 평가·공개 QA/instruction 중복 가능 subset |

권장 논리 분리:

```text
AIHUB-71748/
├─ corpus/
├─ sft/
├─ reward-model/
├─ preference-or-ppo/
└─ excluded/
```

- [검증 필요] 공개 instruction·QA 데이터와 중복 검사가 필요하다.
- [검증 필요] 특정 외부 데이터셋과 실제 중복된다는 주장은 검사 전 확정하지 않는다.

## 6. AIHUB-110

| 필드 | 등록 내용 |
|---|---|
| Dataset ID / 공식명 | `AIHUB-110` / 전문분야 말뭉치 |
| 공식 URL | [AI Hub 상세페이지](https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=110) |
| 플랫폼 / 운영기관 | AI Hub / 한국지능정보사회진흥원 |
| 구축 수행기관 | 포티투마루(주관); 참여기관 전체 범위는 공식 설명서 재확인 |
| 원천 권리자 | [검증 필요] 법령·판례·특허·논문 source별 확인 |
| 언어 / 유형 | 한국어 / 전문 말뭉치·개체명 annotation |
| 공식 공개 규모 | 150만 건; 법령 217,592, 판례 445,308, 특허 780,580, 논문 131,179 말뭉치 건수 표기 |
| 형식 / 구축 연도 | JSON / 2020 |
| 적합성 | tokenizer·pretraining 핵심 후보, SFT·evaluation 제한적, preference 비주력 |
| PII / 저작권 위험 | source별 `low`~`medium_to_high` / `high` |
| 평가 누수 / 암기 위험 | `medium` / `medium_to_high` 후보 |
| 추가 위험 | 법령 개정·특허 청구항 반복 `high` |
| 우선순위 / 상태 | `high` / `registered` |

| Source | PII 위험 | 필수 확인 |
|---|---|---|
| 법령 | `low` 후보 | 개정 전후 중복·시점 |
| 특허 | `low` 후보 | 청구항 반복·권리·메타데이터 |
| 학술 초록 | `low` 후보 | 출처·저작권·HTML/XML 잔여물 |
| 판례 | `medium_to_high` | 비식별 상태·사건정보·개인 식별 가능성 |

- [확정] tokenizer·pretraining에는 원문 text를 사용 후보로 두고 개체명 label은 별도 보존한다.
- [확정] label과 원문을 하나의 일반 text로 혼합하지 않으며 분야별 기여 비율을 기록한다.

## 7. AIHUB-86

| 필드 | 등록 내용 |
|---|---|
| Dataset ID / 공식명 | `AIHUB-86` / 감성 대화 말뭉치 |
| 공식 URL | [AI Hub 상세페이지](https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=86) |
| 플랫폼 / 운영기관 | AI Hub / 한국지능정보사회진흥원 |
| 구축 수행기관 | 미디어젠(주관) |
| 원천 권리자 | [검증 필요] 공식 설명서 확인 필요 |
| 언어 / 유형 | 한국어 / 대화·감정 label·상담형 내용 |
| 공식 공개 규모 | 코퍼스 27만 문장; 음성은 소개 15,700문장과 구축량 표 약 10,000문장이 병기돼 공식 확인 필요 |
| 형식 / 구축 연도 | [검증 필요] 공개 상세 구조 재확인 / 2020 |
| 적합성 | tokenizer 보조, pretraining 제한적, SFT 후보, preference 제한적, 감정 task 평가 전용 후보 |
| PII / 저작권 위험 | `medium_to_high` / `medium` 후보 |
| 평가 누수 / 암기 위험 | `medium` / `medium` 후보 |
| 추가 위험 | style bias·민감 상담·위기 내용 `high` |
| 우선순위 / 상태 | `medium` / `registered` |

처리 순서는 `PII 검사 → turn 구조 → 감정 label 분리 → 상담·위기 발화 격리 → tokenizer 표본 판단 → SFT 안전성 검토`다.

| 용도 | 실험 weight 후보 | 상태 |
|---|---|---|
| Tokenizer | `0.05`, `0.10` | [가정] 실험 후보, 승인값 아님 |
| Pretraining | `0.03`, `0.05`, `0.08` | [가정] 실험 후보, 승인값 아님 |
| 최종 | `null` | [검증 필요] |

## 8. AIHUB-71477

| 필드 | 등록 내용 |
|---|---|
| Dataset ID / 공식명 | `AIHUB-71477` / 자연어 분석 후처리용 과교정 검증 데이터 |
| 공식 URL | [AI Hub 상세페이지](https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=71477) |
| 플랫폼 / 운영기관 | AI Hub / 한국지능정보사회진흥원 |
| 구축 수행기관 | 한국외국어대학교(주관); 참여기관 전체 범위는 공식 설명서 재확인 |
| 원천 권리자 | [검증 필요] 신규 제작 참여자·계약 범위 확인 |
| 언어 / 유형 | 한국어 / 철자·문법, 음성인식 후처리 병렬, 과교정 검증 |
| 공식 공개 규모 | 총 2,201,601건: 철자·문법 1,000,001, 음성인식 후처리 1,001,600, 과교정 검증 200,000 |
| 형식 / 구축 연도 | JSON / 2022 |
| 적합성 | tokenizer 제한, pretraining 기본 제외, 교정 SFT·평가 후보, preference 해당 없음 |
| PII / 저작권 위험 | `low_to_medium` / `medium` 후보 |
| 평가 누수 / 암기 위험 | `high` / `medium` 후보 |
| 추가 위험 | correction task bias `high` |
| 우선순위 / 상태 | `low_for_tokenizer` / `registered` |

- [확정] `source_error_text`, `corrected_text`, `overcorrection_text`, `label`을 논리적으로 분리한다.
- [제외] 오류문·정답문 무구분 혼합, 과교정 문장의 정상 text 처리, 평가 subset의 학습 포함, corrected text 전체 자동 사전학습 승인을 금지한다.

## 9. AIHUB-653

| 필드 | 등록 내용 |
|---|---|
| Dataset ID / 공식명 | `AIHUB-653` / 대규모 구매도서 기반 한국어 말뭉치 데이터 |
| 공식 URL | [AI Hub 상세페이지](https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=653) |
| 플랫폼 / 운영기관 | AI Hub / 한국지능정보사회진흥원 |
| 구축 수행기관 | ㈜웅진북센(주관); 참여기관 전체 범위는 공식 설명서 재확인 |
| 원천 권리자 | [검증 필요] 개별 도서·출판 권리자와 구매 계약 범위 확인 |
| 언어 / 유형 | 한국어 / 출판 도서 장문 말뭉치 |
| 공식 공개 규모 | 10억 어절 |
| 형식 / 구축 연도 | 원천 TXT, labeling JSON / 2021 |
| 적합성 | tokenizer·pretraining 핵심 후보, SFT 비주력, preference 해당 없음, 일반 평가 비권장 |
| PII / 저작권 위험 | `low` 후보 / `high` |
| 평가 누수 / 암기 위험 | `medium` 후보 / `high` |
| 추가 위험 | verbatim 재현 `high`, model release `pending_review` |
| 우선순위 / 상태 | `critical` / `registered` |

- [검증 필요] 내부 학습, model weight·tokenizer artifact 공개, 출력 인용 범위와 상업 서비스 가능 여부를 공식 확인한다.
- [확정] 원문 재배포는 승인 근거가 생기기 전 금지한다.
- [가정] tokenizer에는 전체 원문 대신 record ID 기반 결정론적 대표 표본을 사용하는 후보를 검토한다.

## 10. 검토 우선순위

1. `AIHUB-71748`
2. `AIHUB-653`
3. `AIHUB-110`
4. `AIHUB-86`
5. `AIHUB-71477`

- [확정] 1~3은 이용조건 검토·다운로드 신청 후보, 4는 보조 검토, 5는 교정·평가 중심 검토 순서다.
- [확정] 이는 데이터 품질 확정 순위가 아니라 DohaLM 목적 기준의 검토 우선순위다.

## 11. Tokenizer 용도 행렬

| Dataset | 일반 한국어 | 문어체 | 전문용어 | 대화체 | 오류문 | 장문 | 특수문자·영문 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 71748 | 높음 | 높음 | 중간 | 중간 | 낮음 | 중간 | 중간 |
| 653 | 높음 | 매우 높음 | 중간 | 낮음 | 낮음 | 매우 높음 | 중간 |
| 110 | 중간 | 높음 | 매우 높음 | 낮음 | 낮음 | 중간 | 높음 |
| 86 | 중간 | 낮음 | 낮음 | 매우 높음 | 중간 | 낮음 | 중간 |
| 71477 | 낮음 | 중간 | 낮음 | 중간 | 매우 높음 | 낮음 | 낮음 |

- [가정] 이 행렬은 기술적 정성 후보 평가이며 실제 승인 corpus 통계로 재검증해야 한다.

## 12. Pretraining·SFT·Preference 용도 행렬

| 용도 | 핵심 후보 | 보조·제한 후보 | 기본 제외·비주력 |
|---|---|---|---|
| Pretraining | 71748 일반 corpus, 653 도서 corpus, 110 전문 corpus | 86 대화 corpus | 71477 오류·과교정; corrected text도 별도 검토 |
| SFT | 71748 SFT subset | 86, 71477 correction subset | 110·653 비주력 |
| Preference | 71748 RM·PPO 관련 subset | 86 제한적 | 110·653·71477 비주력 또는 해당 없음 |

- [확정] 사전학습 corpus와 SFT·preference 데이터를 같은 pipeline 입력으로 혼합하지 않는다.

## 13. 미결정 사항

- [검증 필요] 다운로드·승인 결과와 개별 약관의 최종 해석
- [검증 필요] 실제 source별 CCL·원천 권리자·schema·용량
- [검증 필요] 실제 PII·quality·contamination 검사 결과
- [검증 필요] 최종 corpus 구성·혼합 비율과 artifact·weight 공개 범위

## 14. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-26 | [확정] AIHUB-71748 라이선스를 `approved_student_noncommercial`로 반영하고 상업·재배포 금지와 tokenizer `under_review` 경계를 유지함 |
| 2026-07-26 | [확정] AIHUB-71748 로컬 ZIP 55개 존재를 반영해 다운로드 상태를 `not_requested`에서 `downloaded_restricted`로 정합화하고 목적별 승인은 `pending`으로 유지함 |
| 2026-07-23 | [확정] AI Hub 공식 상세페이지에 근거해 5개 데이터셋을 모두 미승인 `registered` 후보로 등록함 |
