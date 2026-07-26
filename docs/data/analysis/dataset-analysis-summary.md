# AI Hub 데이터셋 구조 분석 요약

## 문서 정보

- 문서 상태: `review`
- 분석일: 2026-07-23
- 마지막 검토일: 2026-07-26
- 분석 방식: quick inventory와 ZIP 중앙 디렉터리 조회 후 제한 quick profile

## 비교 결과

| Dataset ID | 파일 수 | 용량 | 주요 형식 | ZIP | Text 후보 | Tokenizer | Pretraining | SFT | 평가 제외 | 수동 검토 |
|---|---:|---:|---|---:|---|---|---|---|---|---|
| [AIHUB-71748](./AIHUB-71748.md) | 55 | 16.07 GiB | ZIP 내부 JSON·TXT | 55 | 안전 표본 0 | 검토 필요 | 검토 필요 | general/SFT/RM/PPO 구분 필요 | 평가 subset 분리 필요 | [dry-run 결과](./AIHUB-71748-sampling.md) 필수 |
| [AIHUB-653](./AIHUB-653.md) | 158 | 16.86 GiB | ZIP 내부 JSON·TSV | 158 | 미확인 | 검토 필요 | 저작권·암기 위험 검토 | schema 확인 필요 | Validation 분리 필요 | 필수 |
| [AIHUB-110](./AIHUB-110.md) | 20 | 13.63 GiB | ZIP 내부 JSON·TXT | 20 | 미확인 | 검토 필요 | 원문/NER label 분리 필요 | 검토 필요 | Validation 분리 필요 | 필수 |
| [AIHUB-86](./AIHUB-86.md) | 4 | 20.35 MiB | ZIP 내부 JSON·XLSX | 4 | 미확인 | 검토 필요 | 상담·민감정보 검토 | turn/감정 label 분리 필요 | Validation 분리 필요 | 필수 |
| [AIHUB-71477](./AIHUB-71477.md) | 48 | 112.29 GiB | ZIP 내부 CSV·JSON·WAV | 48 | 미확인 | 검토 필요 | 원문/오류문/교정문 분리 필요 | 검토 필요 | 평가·교정 정답 분리 필요 | 필수 |

## 공통 해석

- [확정] 외부 root에서 직접 확인된 파일은 모두 ZIP이며 285개, 약 158.87 GiB다.
- [확정] 285개 ZIP의 중앙 디렉터리는 모두 정상 조회됐고 암호화 ZIP은 탐지되지 않았다.
- [확정] ZIP 내부 파일은 총 4,471,632개로 집계됐지만 entry 내용은 읽지 않았다.
- [검증 필요] 직접 접근 가능한 JSON·JSONL·TXT가 없어 schema signature, text field, label field와 PII field는 미확인이다.
- [확정] 자동 구조 분석 자체는 승인 결과가 아니다. 후속 사용자 결정으로 `AIHUB-71748` tokenizer만 `approved_tokenizer_development`, 그 밖의 목적별 승인은 `pending`이며 Gate 3은 `planned`다.
- [검증 필요] 일부 ZIP 내부 entry가 절대·상위 이동 형태로 분류돼 경로를 보고서에서 마스킹했다. 압축 해제가 필요해질 경우 별도 경로 안전성 검토가 선행돼야 한다.
- [확정] AIHUB-71748 dry-run에서 55개 archive의 1,610개 entry가 모두 absolute path로 거부돼 실제 추출과 schema 검토를 수행하지 않았다.

## 다음 결정

1. 공식 이용조건과 다운로드 계보를 확인한다.
2. 사용자가 승인한 격리 절차로 ZIP 내부 schema의 최소 수동 표본 검토 여부를 결정한다.
3. 목적별 corpus와 evaluation 제외 목록을 승인 로그에 기록한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-26 | [확정] AIHUB-71748 tokenizer `under_review`와 Gate 3 `planned`의 현재 경계를 동기화함 |
