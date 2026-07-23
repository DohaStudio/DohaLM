# AIHUB-86 구조 분석

## 문서 상태

- 문서 상태: `review`

## 분석 기준

- [확정] 2026-07-23 quick inventory와 ZIP 중앙 디렉터리만 조회했다. 원문·음성은 읽지 않았다.

## 데이터셋 개요

- Dataset ID: `AIHUB-86`
- [검증 필요] 음성·텍스트·감정 label·대화 turn의 실제 schema를 확인해야 한다.

## 외부 상대 경로

- `external_root: configured_locally`
- `dataset_relative_root: extracted/AIHUB-86`

## 분석 시점

- 2026-07-23

## 파일·용량 요약

| 폴더 | 파일 | 총 용량 | 최대 파일 | 평균 파일 |
|---:|---:|---:|---:|---:|
| 6 | 4 | 20.35 MiB | 10.25 MiB | 5.09 MiB |

## 최상위 디렉터리

- `Training_221115_add`, `Validation_221115_add`

## 경로 구조

- 최대 깊이 3, 최대 상대경로 길이 58, 한글·특수문자 경로 있음, 공백 경로 미탐지

## 확장자 분포

- 외부 root: ZIP 4개
- ZIP 내부: JSON 2개, XLSX 2개

## 압축파일 현황

- 정상 4개, 암호화 0개, 내부 파일 4개, 압축 해제 0건

## Training·Validation 구조

- [확정] `Training_221115_add`와 `Validation_221115_add` 후보가 분리돼 있다.

## 원천·라벨 구조

- [확정] 원천·라벨 후보가 탐지됐다.
- [검증 필요] 텍스트·음성 연결, 감정 label과 대화 turn schema는 미확인이다.

## JSON schema signature

- [검증 필요] ZIP 내부 JSON을 읽지 않아 signature 0건이다.

## JSONL 구조

- 직접 접근 가능한 JSONL 표본 0건

## TXT 구조

- 직접 접근 가능한 TXT 표본 0건

## Text field 후보

- `manual_review_required`: 상담 발화 field 미확인

## Label·metadata field 후보

- `manual_review_required`: 감정 label, speaker, turn과 음성 metadata를 분리해야 한다.

## PII 가능 field 경고

- [검증 필요] 상담·감정 데이터의 민감정보와 재식별 위험을 우선 검토한다.

## Tokenizer 적합성

- `manual_review_required`: 승인된 텍스트 발화만 분리 가능한지 확인한다.

## Pretraining 적합성

- `manual_review_required`: 상담·민감정보와 label 혼입 위험 때문에 자동 사용하지 않는다.

## SFT·Preference 적합성

- `manual_review_required`: 대화 turn과 역할은 schema 확인 후 판단한다.

## Evaluation 제외 후보

- Validation과 감정 평가 label은 학습 후보에서 분리한다.

## 수동 검토 필요 항목

- 민감정보·상담 내용, text/audio 연결, turn/감정 label, 이용조건

## 현재 승인 상태

- `candidate_status: registered`, `license_review_status: pending_terms_review`, 목적별 승인 모두 `pending`

## 다음 작업

- 공식 조건과 민감정보 검토 전 corpus 생성에 사용하지 않는다.

