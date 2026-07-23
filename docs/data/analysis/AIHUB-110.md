# AIHUB-110 구조 분석

## 문서 상태

- 문서 상태: `review`

## 분석 기준

- [확정] 2026-07-23 quick inventory와 ZIP 중앙 디렉터리만 조회했다. 원문은 읽지 않았다.

## 데이터셋 개요

- Dataset ID: `AIHUB-110`
- [확정] 외부 파일명에서 법령·판례·특허·논문 구분 후보가 탐지됐다.

## 외부 상대 경로

- `external_root: configured_locally`
- `dataset_relative_root: extracted/AIHUB-110`

## 분석 시점

- 2026-07-23

## 파일·용량 요약

| 폴더 | 파일 | 총 용량 | 최대 파일 | 평균 파일 |
|---:|---:|---:|---:|---:|
| 2 | 20 | 13.63 GiB | 10.68 GiB | 698.07 MiB |

## 최상위 디렉터리

- `Training`, `Validation`

## 경로 구조

- 최대 깊이 2, 최대 상대경로 길이 39, 한글·특수문자 경로 있음, 공백 경로 미탐지

## 확장자 분포

- 외부 root: ZIP 20개
- ZIP 내부: JSON 665개, TXT 2개

## 압축파일 현황

- 정상 20개, 암호화 0개, 내부 파일 667개, 압축 해제 0건

## Training·Validation 구조

- [확정] 최상위에 Training·Validation 후보가 분리돼 있다.

## 원천·라벨 구조

- [확정] 원천·라벨 후보가 탐지됐다.
- [검증 필요] 법률·특허·논문 원문과 개체명 annotation을 분리해야 한다.

## JSON schema signature

- [검증 필요] ZIP 내부 JSON을 읽지 않아 signature 0건이다.

## JSONL 구조

- 직접 접근 가능한 JSONL 표본 0건

## TXT 구조

- ZIP 내부 TXT 2개는 미열람

## Text field 후보

- `manual_review_required`: 법령·판례·특허·논문별 text field 미확인

## Label·metadata field 후보

- `manual_review_required`: NER label과 문서 metadata를 본문에서 분리해야 한다.

## PII 가능 field 경고

- field 이름 미확인. 판례 등에서 비식별·민감정보를 별도 검토한다.

## Tokenizer 적합성

- `manual_review_required`: 원문만 추출 가능한지와 분야 편향을 확인한다.

## Pretraining 적합성

- `manual_review_required`: 원문 권리와 NER annotation 혼입을 확인한다.

## SFT·Preference 적합성

- `manual_review_required`: 구조 분석만으로 대화·선호 데이터라고 판단하지 않는다.

## Evaluation 제외 후보

- Validation과 향후 법률 benchmark 중복 후보를 분리한다.

## 수동 검토 필요 항목

- 분야별 schema, 원문/NER label mapping, 개인정보·권리, 평가 누수

## 현재 승인 상태

- `candidate_status: registered`, `license_review_status: pending_terms_review`, 목적별 승인 모두 `pending`

## 다음 작업

- 공식 조건 확인 후 분야별 최소 schema mapping을 사용자 승인 절차로 검토한다.

