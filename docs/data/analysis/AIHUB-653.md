# AIHUB-653 구조 분석

## 문서 상태

- 문서 상태: `review`

## 분석 기준

- [확정] 2026-07-23 quick inventory와 ZIP 중앙 디렉터리만 조회했다. 원문은 읽지 않았다.

## 데이터셋 개요

- Dataset ID: `AIHUB-653`
- [검증 필요] 도서 분야·문장·문단·도서 metadata의 정확한 schema와 사용 범위를 확인해야 한다.

## 외부 상대 경로

- `external_root: configured_locally`
- `dataset_relative_root: extracted/AIHUB-653`

## 분석 시점

- 2026-07-23

## 파일·용량 요약

| 폴더 | 파일 | 총 용량 | 최대 파일 | 평균 파일 |
|---:|---:|---:|---:|---:|
| 7 | 158 | 16.86 GiB | 3.21 GiB | 109.27 MiB |

## 최상위 디렉터리

- `01.데이터`

## 경로 구조

- 최대 깊이 4, 최대 상대경로 길이 44, 한글 경로 있음, 공백·특수문자 경로 미탐지

## 확장자 분포

- 외부 root: ZIP 158개
- ZIP 내부: JSON 5,974개, TSV 151개

## 압축파일 현황

- 정상 158개, 암호화 0개, 내부 파일 6,125개, 압축 해제 0건

## Training·Validation 구조

- [확정] 경로명 기준 Training·Validation 후보가 모두 탐지됐다.

## 원천·라벨 구조

- [확정] 원천데이터·라벨링데이터 후보가 모두 탐지됐다.
- [검증 필요] 원문 text와 도서·문단 metadata 및 label을 분리해야 한다.

## JSON schema signature

- [검증 필요] ZIP 내부 JSON을 읽지 않아 signature 0건이다.

## JSONL 구조

- 직접 접근 가능한 JSONL 표본 0건

## TXT 구조

- 직접 접근 가능한 TXT 표본 0건; ZIP 내부 TSV는 미열람

## Text field 후보

- `manual_review_required`: 문장·문단 후보 field 미확인

## Label·metadata field 후보

- `manual_review_required`: 도서 분야와 서지 metadata를 본문에서 분리해야 한다.

## PII 가능 field 경고

- field 이름 미확인. 미탐지는 PII 부재를 의미하지 않는다.

## Tokenizer 적합성

- `manual_review_required`: 본문 field와 권리 범위를 확인해야 한다.

## Pretraining 적합성

- `manual_review_required`: 저작권·암기 위험과 재배포·파생 모델 조건을 우선 검토한다.

## SFT·Preference 적합성

- `manual_review_required`: 구조 분석만으로 Q&A·대화 데이터라고 판단하지 않는다.

## Evaluation 제외 후보

- Validation과 고정 평가 subset은 학습에서 분리한다.

## 수동 검토 필요 항목

- 도서 분야별 권리, text/metadata schema, 중복·암기 위험, 공식 이용조건

## 현재 승인 상태

- `candidate_status: registered`, `license_review_status: pending_terms_review`, 목적별 승인 모두 `pending`

## 다음 작업

- 공식 조건 확인 후 도서 원문과 metadata의 최소 schema mapping을 승인 절차로 검토한다.

